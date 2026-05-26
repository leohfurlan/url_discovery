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

from domain.entities.form import ExecutionResult, FormField, FormPage, FormSession, FormStatus
from domain.services.classifier_port import ClassifierPort
from domain.services.generator import DataGenerator
from infrastructure.browser.crawler import DOMCrawler
from infrastructure.browser.filler import FormFiller

logger = structlog.get_logger(__name__)

# Seletores que representam submissão FINAL do formulário.
# Quando ALLOW_FORM_SUBMIT=false, estes seletores são ignorados
# e o agente para antes de enviar dados ao portal.
_FINAL_SUBMIT_SELECTORS = frozenset({
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Submit")',
    'button:has-text("Enviar")',
    'button:has-text("Submeter")',
})

# Seletores comuns para botões de avanço — ordem de prioridade.
# Os seletores de submissão final ficam no início para serem encontrados
# primeiro, mas são filtrados por _FINAL_SUBMIT_SELECTORS quando necessário.
_NEXT_BUTTON_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    # Cover/intro page — formulários que iniciam com uma página de apresentação
    'button:has-text("Iniciar")',
    'button:has-text("Iniciar agora")',
    'button:has-text("Começar")',
    'button:has-text("Start now")',
    'button:has-text("Start")',
    'button:has-text("Begin")',
    # Submissão final (ex: Microsoft Forms)
    'button:has-text("Submit")',
    'button:has-text("Enviar")',
    'button:has-text("Submeter")',
    # Progressão multi-página
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
    SUBMIT_BLOCKED = auto()   # ALLOW_FORM_SUBMIT=false — campos preenchidos, Submit não clicado
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
        allow_submit: bool = False,
        on_page_done: Callable[[StepReport], Awaitable[None]] | None = None,
    ) -> None:
        self._page = page
        self._classifier = classifier
        self._generator = generator
        self._iframe_selector = iframe_selector
        self._max_pages = max_pages
        self._screenshot_dir = screenshot_dir
        self._slow_fill = slow_fill
        self._allow_submit = allow_submit
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
                    # Só considera sucesso se já preenchemos pelo menos uma página —
                    # evita falso positivo na cover page (que pode ter "obrigado"
                    # ou "confirmação" na descrição do formulário)
                    if report.steps and await self._is_success_page():
                        session.status = FormStatus.COMPLETED
                        logger.info("success_page_detected", page=page_num)
                        break
                    # Pode ser cover/intro page — tenta clicar em "Iniciar", "Próximo", etc.
                    advanced = await self._click_next(page_num, portal_name)
                    if not advanced:
                        report.result = NavigationResult.NEXT_BUTTON_NOT_FOUND
                        break
                    # Aguarda SPA renderizar os campos após o clique
                    await self._wait_for_stable_dom()
                    continue

                form_page = FormPage(page_number=page_num, fields=raw_fields)

                # 2–4. Classifica, gera e preenche em loop até estabilizar.
                #       Cobre campos condicionais que surgem após cada resposta
                #       (ex: Jaguar Mining — Questionário de Integridade, pág. 3).
                fl = self._page.frame_locator(self._iframe_selector) if self._iframe_selector else None
                filler = FormFiller(self._page, frame_locator=fl, slow_fill=self._slow_fill)
                classified_fields, failures = await self._fill_until_stable(
                    initial_fields=raw_fields,
                    page_num=page_num,
                    session=session,
                    filler=filler,
                )
                form_page.fields = classified_fields

                # 5. Screenshot
                screenshot_path = await filler.take_screenshot(
                    f"{portal_name}_page_{page_num}"
                )

                step = StepReport(
                    page_number=page_num,
                    fields_found=len(classified_fields),
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

                # 6. Avança / verifica estado pós-preenchimento
                #
                # Ordem importa:
                #   a) Se allow_submit=False e o próximo botão é submissão final,
                #      para ANTES de checar success — botão de Submit visível
                #      prova que não estamos numa página de confirmação real.
                #   b) Só então verifica se a página de sucesso já apareceu
                #      (formulário submetido via outro mecanismo, ex: Enter).
                if not self._allow_submit and await self._next_is_final_submit():
                    logger.warning(
                        "submit_blocked",
                        page=page_num,
                        portal=portal_name,
                        reason="ALLOW_FORM_SUBMIT=false",
                    )
                    report.result = NavigationResult.SUBMIT_BLOCKED
                    break

                if await self._is_success_page():
                    session.status = FormStatus.COMPLETED
                    logger.info("success_after_fill", page=page_num)
                    break

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
        Itera por TODOS os matches de cada seletor — evita pegar o primeiro
        elemento invisível quando há duplicatas no DOM (ex: Microsoft Forms
        renderiza dois botões "Start now", o primeiro fora da viewport).
        Retorna True se conseguiu clicar.
        """
        fl = self._page.frame_locator(self._iframe_selector) if self._iframe_selector else None

        for selector in _NEXT_BUTTON_SELECTORS:
            locator = fl.locator(selector) if fl else self._page.locator(selector)
            try:
                count = await locator.count()
                for i in range(count):
                    btn = locator.nth(i)
                    is_visible = await btn.is_visible()
                    is_enabled = await btn.is_enabled()
                    if is_visible and is_enabled:
                        await btn.click()
                        logger.info("next_button_clicked", selector=selector, index=i, page=page_num)
                        return True
            except Exception:
                continue

        logger.warning("next_button_not_found", page=page_num, portal=portal_name)
        return False

    async def _next_is_final_submit(self) -> bool:
        """Verifica se o próximo botão visível e habilitado é um botão de submissão final."""
        fl = self._page.frame_locator(self._iframe_selector) if self._iframe_selector else None
        for selector in _FINAL_SUBMIT_SELECTORS:
            locator = fl.locator(selector) if fl else self._page.locator(selector)
            try:
                count = await locator.count()
                for i in range(count):
                    btn = locator.nth(i)
                    if await btn.is_visible() and await btn.is_enabled():
                        return True
            except Exception:
                continue
        return False

    async def _is_success_page(self) -> bool:
        """Verifica se a página atual contém indicadores de conclusão.
        Usa innerText (texto visível) em vez do HTML completo para evitar
        falsos positivos com palavras de sucesso embutidas em bundles JS/CSS.
        """
        try:
            text = await self._page.evaluate("document.body.innerText")
            content = text.lower()
            return any(ind in content for ind in _SUCCESS_INDICATORS)
        except Exception:
            return False

    async def _fill_until_stable(
        self,
        initial_fields: list[FormField],
        page_num: int,
        session: FormSession,
        filler: FormFiller,
        max_rounds: int = 20,
    ) -> tuple[list[FormField], list[str]]:
        """
        Preenche campos em loop até o DOM parar de revelar novos campos.

        A cada rodada:
          1. Filtra apenas campos com seletor ainda não visto
          2. Classifica, gera valor e preenche
          3. Espera o DOM estabilizar (campos condicionais renderizarem)
          4. Re-crawla — se surgiram novos campos, repete

        Garante que formulários com campos encadeados (cada resposta revela
        a próxima pergunta) sejam completamente preenchidos antes de avançar.
        """
        seen_selectors: set[str] = set()
        all_classified: list[FormField] = []
        all_failures: list[str] = []
        crawler = DOMCrawler(self._page, iframe_selector=self._iframe_selector)

        current_fields = initial_fields

        for round_num in range(max_rounds):
            new_fields = [f for f in current_fields if f.selector not in seen_selectors]

            if not new_fields:
                logger.debug("conditional_fields_stable", page=page_num, rounds=round_num)
                break

            for f in new_fields:
                seen_selectors.add(f.selector)

            classified = await self._classifier.classify(new_fields)
            all_classified.extend(classified)

            for f in classified:
                if f.semantic_type and f.selector not in session.filled_values:
                    session.filled_values[f.selector] = self._generator.generate(f.semantic_type)

            form_page_round = FormPage(page_number=page_num, fields=classified)
            round_failures = await filler.fill_page(form_page_round, session)
            all_failures.extend(round_failures)

            if round_failures:
                logger.warning(
                    "conditional_round_failures",
                    page=page_num,
                    round=round_num,
                    count=len(round_failures),
                )

            await self._wait_for_conditional_dom()
            current_fields = await crawler.extract_fields()
        else:
            logger.warning("conditional_max_rounds_reached", page=page_num, limit=max_rounds)

        return all_classified, all_failures

    async def _wait_for_conditional_dom(self) -> None:
        """Espera breve para campos condicionais renderizarem após um preenchimento."""
        await asyncio.sleep(0.4)

    async def _wait_for_stable_dom(self) -> None:
        """
        Aguarda o DOM estabilizar após navegação ou clique.
        Primeiro tenta detectar campos no DOM (bom para SPAs como Microsoft Forms);
        cai para sleep fixo se nenhum campo aparecer no timeout.
        Usa state="visible" para garantir que o React/SPA populou os atributos
        (id, name, aria-*) antes do crawler tentar extraí-los.
        """
        await asyncio.sleep(0.15)  # margem mínima antes de checar
        root = (
            self._page.frame_locator(self._iframe_selector)
            if self._iframe_selector
            else self._page
        )
        field_sel = (
            "input:not([type='hidden']):not([type='submit']):not([type='button']),"
            "select,textarea"
        )
        try:
            await root.locator(field_sel).first.wait_for(state="visible", timeout=8_000)
        except Exception:
            await asyncio.sleep(0.8)


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