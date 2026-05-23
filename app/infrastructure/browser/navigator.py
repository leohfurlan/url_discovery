"""
infrastructure/browser/navigator.py

NavigationOrchestrator — coordena o fluxo multi-page do formulário:
    1. Crawla a página atual via DOMCrawler
    2. Classifica campos via ClassifierPort
    3. Gera valores via DataGenerator
    4. Preenche via FormFiller
    5. Detecta e clica no botão "próximo" / "continuar"
    6. Repete até fim ou até FormSession estar encerrada

Mantém FormSession atualizado a cada etapa.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import auto, Enum
from typing import Callable, Awaitable

import structlog
from playwright.async_api import Page

from domain.entities.form import ExecutionResult, FormPage, FormSession, FormStatus
from domain.services.classifier_port import ClassifierPort
from domain.services.generator import DataGenerator
from infrastructure.browser.crawler import DOMCrawler
from infrastructure.browser.filler import FormFiller

logger = structlog.get_logger(__name__)

# Seletores comuns para botões de avanço — ordem de prioridade
_NEXT_BUTTON_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Próximo")',
    'button:has-text("Continuar")',
    'button:has-text("Avançar")',
    'button:has-text("Next")',
    'button:has-text("Continue")',
    'a:has-text("Próximo")',
    'a:has-text("Next")',
    '[data-testid*="next"]',
    '[data-testid*="submit"]',
    '[class*="next"]',
    '[class*="submit"]',
]

# Indicadores de sucesso/conclusão na página
_SUCCESS_INDICATORS = [
    "sucesso",
    "success",
    "obrigado",
    "thank you",
    "concluído",
    "completed",
    "enviado",
    "submitted",
    "confirmação",
    "confirmation",
]


class NavigationResult(Enum):
    SUCCESS = auto()
    MAX_PAGES_REACHED = auto()
    NEXT_BUTTON_NOT_FOUND = auto()
    FILL_ERRORS = auto()
    EXCEPTION = auto()


@dataclass
class StepReport:
    page_number: int
    fields_found: int
    fields_filled: int
    failures: list[str]
    screenshot: str | None = None


@dataclass
class RunReport:
    result: NavigationResult
    steps: list[StepReport] = field(default_factory=list)
    final_url: str = ""
    session: FormSession | None = None
    error: str | None = None


class NavigationOrchestrator:
    """
    Orquestra o fluxo completo de preenchimento multi-página.

    Parâmetros:
        page            — instância Playwright já navegada até a URL do formulário
        classifier      — implementação de ClassifierPort (ex: GemmaClassifier)
        generator       — DataGenerator instanciado
        iframe_selector — seletor CSS do iframe, se houver (ex: "#form-frame")
        max_pages       — limite de segurança para evitar loops infinitos
        screenshot_dir  — diretório onde salvar screenshots (None = /tmp)
        slow_fill       — delay extra entre campos (portais sensíveis a timing)
        on_page_done    — callback opcional chamado após cada página preenchida
    """

    def __init__(
        self,
        page: Page,
        classifier: ClassifierPort,
        generator: DataGenerator,
        iframe_selector: str | None = None,
        max_pages: int = 15,
        screenshot_dir: str | None = None,
        slow_fill: bool = False,
        on_page_done: Callable[[StepReport], Awaitable[None]] | None = None,
    ) -> None:
        self._page = page
        self._classifier = classifier
        self._generator = generator
        self._iframe_selector = iframe_selector
        self._max_pages = max_pages
        self._screenshot_dir = screenshot_dir
        self._slow_fill = slow_fill
        self._on_page_done = on_page_done

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    async def run(self, portal_name: str = "portal") -> RunReport:
        """
        Executa o fluxo completo.
        Retorna RunReport com resultado e histórico de cada etapa.
        """
        session = FormSession(current_page=1)
        report = RunReport(result=NavigationResult.SUCCESS, session=session)

        try:
            for page_num in range(1, self._max_pages + 1):
                session.current_page = page_num
                logger.info("navigating_page", page=page_num, url=self._page.url)

                # 1. Crawl
                crawler = DOMCrawler(self._page, iframe_selector=self._iframe_selector)
                raw_fields = await crawler.extract_fields()

                if not raw_fields:
                    logger.warning("no_fields_found", page=page_num)
                    # Pode ser página de confirmação — verifica indicadores
                    if await self._is_success_page():
                        session.status = FormStatus.COMPLETED
                        logger.info("success_page_detected", page=page_num)
                        break
                    # Tenta clicar em próximo mesmo assim (pode ser step sem campos)
                    advanced = await self._click_next(page_num, portal_name)
                    if not advanced:
                        report.result = NavigationResult.NEXT_BUTTON_NOT_FOUND
                        break
                    continue

                form_page = FormPage(page_number=page_num, fields=raw_fields)

                # 2. Classifica
                classified_fields = await self._classifier.classify(raw_fields)
                form_page.fields = classified_fields

                # 3. Gera valores
                for f in classified_fields:
                    if f.semantic_type and f.selector not in session.filled_values:
                        value = self._generator.generate(f.semantic_type)
                        session.filled_values[f.selector] = value

                # 4. Preenche
                fl = self._page.frame_locator(self._iframe_selector) if self._iframe_selector else None
                filler = FormFiller(self._page, frame_locator=fl, slow_fill=self._slow_fill)
                failures = await filler.fill_page(form_page, session)

                # 5. Screenshot
                screenshot_path = await filler.take_screenshot(
                    f"{portal_name}_page_{page_num}"
                )

                step = StepReport(
                    page_number=page_num,
                    fields_found=len(raw_fields),
                    fields_filled=len(classified_fields) - len(failures),
                    failures=failures,
                    screenshot=str(screenshot_path),
                )
                report.steps.append(step)
                session.screenshots.append(str(screenshot_path))

                if self._on_page_done:
                    await self._on_page_done(step)

                if failures:
                    logger.warning("fill_failures", page=page_num, count=len(failures))

                # 6. Verifica sucesso antes de tentar avançar
                if await self._is_success_page():
                    session.status = FormStatus.COMPLETED
                    logger.info("success_after_fill", page=page_num)
                    break

                # 7. Avança para próxima página
                advanced = await self._click_next(page_num, portal_name)
                if not advanced:
                    # Sem botão next pode significar formulário concluído
                    if await self._is_success_page():
                        session.status = FormStatus.COMPLETED
                    else:
                        report.result = NavigationResult.NEXT_BUTTON_NOT_FOUND
                    break

                # Aguarda navegação/renderização
                await self._wait_for_stable_dom()

            else:
                report.result = NavigationResult.MAX_PAGES_REACHED
                logger.warning("max_pages_reached", limit=self._max_pages)

        except Exception as exc:
            logger.exception("orchestrator_error", error=str(exc))
            session.status = FormStatus.ERROR
            report.result = NavigationResult.EXCEPTION
            report.error = str(exc)

        report.final_url = self._page.url
        report.session = session
        return report

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _click_next(self, page_num: int, portal_name: str) -> bool:
        """
        Tenta clicar no botão de avanço usando lista priorizada de seletores.
        Retorna True se conseguiu clicar.
        """
        fl = self._page.frame_locator(self._iframe_selector) if self._iframe_selector else None

        for selector in _NEXT_BUTTON_SELECTORS:
            locator = fl.locator(selector) if fl else self._page.locator(selector)
            try:
                count = await locator.count()
                if count > 0:
                    btn = locator.first
                    is_visible = await btn.is_visible()
                    is_enabled = await btn.is_enabled()
                    if is_visible and is_enabled:
                        await btn.click()
                        logger.info("next_button_clicked", selector=selector, page=page_num)
                        return True
            except Exception:
                continue

        logger.warning("next_button_not_found", page=page_num, portal=portal_name)
        return False

    async def _is_success_page(self) -> bool:
        """Verifica se a página atual contém indicadores de conclusão."""
        try:
            content = (await self._page.content()).lower()
            return any(ind in content for ind in _SUCCESS_INDICATORS)
        except Exception:
            return False

    @staticmethod
    async def _wait_for_stable_dom(timeout_ms: int = 3_000) -> None:
        """
        Aguarda o DOM estabilizar após navegação.
        Usa networkidle como proxy de "página carregada".
        """
        await asyncio.sleep(0.5)  # margem mínima


# ------------------------------------------------------------------
# Função de conveniência para uso direto via CLI / testes
# ------------------------------------------------------------------

async def run_portal(
    page: Page,
    portal_name: str,
    classifier: ClassifierPort,
    generator: DataGenerator,
    iframe_selector: str | None = None,
    slow_fill: bool = False,
) -> RunReport:
    """Atalho para criar e executar NavigationOrchestrator em uma linha."""
    orchestrator = NavigationOrchestrator(
        page=page,
        classifier=classifier,
        generator=generator,
        iframe_selector=iframe_selector,
        slow_fill=slow_fill,
    )
    return await orchestrator.run(portal_name=portal_name)