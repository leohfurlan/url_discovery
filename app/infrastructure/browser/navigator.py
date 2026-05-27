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
import re
from dataclasses import dataclass, field
from enum import auto, Enum
from typing import Callable, Awaitable

import structlog
from playwright.async_api import Page

from domain.entities.company_profile import CompanyProfile
from domain.entities.form import (
    ExecutionResult, FieldType, FormField, FormPage, FormSession, FormStatus, SemanticType,
)
from domain.services.classifier_port import ClassifierPort
from domain.services.generator import DataGenerator
from infrastructure.audit.audit_session import AuditSession
from infrastructure.browser.crawler import DOMCrawler
from infrastructure.browser.filler import FormFiller, _UF_TO_NAME
from infrastructure.llm.heuristic import _is_binary_yes_no

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

# Grupos de checkbox com 2+ opções ("selecione todas que se aplicam": documentos,
# categorias, serviços) deixam de ser classificados item a item — o que marcava
# tudo com o mesmo semantic OU não marcava nada (deixando obrigatórios vazios e
# travando o form) — e passam a uma seleção única via LLM com base no perfil.
# Checkbox isolado (grupo de 1, ex.: "Concordo com os termos") segue no caminho
# normal de aceite.
_CHECKBOX_GROUP_MIN = 2

# Extrai o texto da opção do seletor de checkbox: ...[value="OPÇÃO"]
_CHECKBOX_VALUE_RE = re.compile(r'\[value="(.*)"\]\s*$')


def _tag(field: FormField, source: str, confidence: str) -> None:
    """Anota origem e confiança da decisão de preenchimento (Ajuste 4)."""
    field.classification_source = source
    field.confidence = confidence


# Semantics cujo valor é booleano/afirmativo (true/false), normalizado pelo filler
# para Sim/Não — não é um texto de opção a casar, então ficam fora do rematch.
_OPTION_VALUE_SEMANTICS: set[SemanticType] = {
    SemanticType.ACEITE_TERMOS,
    SemanticType.DOCUMENTO_PDF,
}


def _value_matches_option(value: str, options: list[str]) -> bool:
    """True se o valor gerado corresponde a alguma opção do campo de escolha.

    Espelha (de forma conservadora) o casamento do filler: igualdade ou substring,
    case-insensitive, com expansão de UF (ex.: "MG" casa com "Minas Gerais").
    Usado para decidir se confiamos no valor gerado ou pedimos ao LLM uma opção.
    """
    v = (value or "").strip().lower()
    if not v:
        return False
    candidates = [v]
    expanded = _UF_TO_NAME.get((value or "").strip().upper())
    if expanded:
        candidates.append(expanded.lower())
    for opt in options:
        o = opt.strip().lower()
        if not o:
            continue
        for c in candidates:
            if c == o or c in o or o in c:
                return True
    return False

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
    STUCK_PAGE = auto()       # cliquei "Avançar" mas a mesma página reapareceu (obrigatório não satisfeito)
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
    # Campos que o agente não soube preencher com segurança (Ajuste 1):
    # radio/select sem classificação onde nem o fallback do LLM decidiu.
    requires_human_review: list[FormField] = field(default_factory=list)


class NavigationOrchestrator:
    """
    Orquestra o fluxo completo de preenchimento multi-página.

    Parâmetros:
        page            — instância Playwright já navegada até a URL do formulário
        classifier      — implementação de ClassifierPort (ex: GemmaClassifier)
        generator       — DataGenerator instanciado
        iframe_selector — seletor CSS do iframe, se houver (ex: "#form-frame")
        max_pages       — limite de segurança para evitar loops infinitos
        audit           — AuditSession para salvar logs+screenshots (None = só /tmp)
        per_question_shots — quando True, gera 1 screenshot por pergunta preenchida
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
        audit: AuditSession | None = None,
        per_question_shots: bool = True,
        slow_fill: bool = False,
        allow_submit: bool = False,
        profile: CompanyProfile | None = None,
        on_page_done: Callable[[StepReport], Awaitable[None]] | None = None,
    ) -> None:
        self._page = page
        self._classifier = classifier
        self._generator = generator
        self._iframe_selector = iframe_selector
        self._max_pages = max_pages
        self._audit = audit
        self._per_question_shots = per_question_shots
        self._slow_fill = slow_fill
        self._allow_submit = allow_submit
        self._profile = profile
        self._profile_summary = profile.summary() if profile else ""
        self._on_page_done = on_page_done
        # Campos sem preenchimento seguro, acumulados ao longo da execução.
        self._review_queue: list[FormField] = []
        # Todos os campos classificados, para o sumário de confiança (Ajuste 4).
        self._all_classified: list[FormField] = []

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
        # Assinatura (conjunto de seletores) da última página processada — usada
        # para detectar que clicamos "Avançar" mas a mesma página reapareceu.
        previous_signature: frozenset[str] | None = None

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

                # Guard anti-loop: se reabrimos a MESMA página depois de clicar
                # "Avançar" (conjunto idêntico de campos), o portal recusou o
                # avanço — tipicamente um campo obrigatório não satisfeito. Falha
                # rápido e avisa, em vez de re-preencher a mesma página até max_pages.
                signature = frozenset(f.selector for f in raw_fields)
                if signature == previous_signature:
                    logger.error(
                        "page_not_advancing",
                        page=page_num,
                        fields=len(raw_fields),
                        review_pending=len(self._review_queue),
                        reason="portal recusou avançar — provável campo obrigatório não preenchido",
                    )
                    report.result = NavigationResult.STUCK_PAGE
                    break
                previous_signature = signature

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
                self._all_classified.extend(classified_fields)

                # 5. Screenshots de auditoria — visão geral da página + 1 por
                #    pergunta preenchida (cobertura de 100% das questões).
                screenshot_path = await self._capture_page_audit(
                    page_num, portal_name, classified_fields, failures, session, filler
                )

                step = StepReport(
                    page_number=page_num,
                    fields_found=len(classified_fields),
                    fields_filled=len(classified_fields) - len(failures),
                    failures=failures,
                    screenshot=str(screenshot_path),
                )
                report.steps.append(step)

                if self._on_page_done:
                    await self._on_page_done(step)

                if failures:
                    logger.warning("fill_failures", page=page_num, count=len(failures))

                # 6. Avança / verifica estado pós-preenchimento
                #
                # Ordem importa:
                #   a) Se allow_submit=False e o próximo botão é submissão final,
                #      para ANTES de avançar.
                #   b) Tenta clicar "Próximo"/"Next". Se não existe botão de avanço,
                #      só então verifica se é página de sucesso — evita falso positivo
                #      com formulários que têm "Thank you" no texto introdutório
                #      (ex: Jaguar Mining) e ainda têm mais páginas a preencher.
                if not self._allow_submit and await self._next_is_final_submit():
                    logger.warning(
                        "submit_blocked",
                        page=page_num,
                        portal=portal_name,
                        reason="ALLOW_FORM_SUBMIT=false",
                    )
                    report.result = NavigationResult.SUBMIT_BLOCKED
                    break

                advanced = await self._click_next(page_num, portal_name)
                if not advanced:
                    # Sem botão next pode significar formulário concluído
                    if await self._is_success_page():
                        session.status = FormStatus.COMPLETED
                        logger.info("success_after_fill", page=page_num)
                    else:
                        report.result = NavigationResult.NEXT_BUTTON_NOT_FOUND
                    break

                # Verifica e corrige erros de validação antes de prosseguir
                await self._advance_past_validation(
                    page_num, portal_name, classified_fields, session, filler
                )

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
        report.requires_human_review = list(self._review_queue)
        self._log_confidence_summary()

        # Consolida o índice de evidências (manifest.json + README.md) na pasta
        # de auditoria do portal — junto dos screenshots e do log da sessão.
        if self._audit is not None:
            try:
                self._audit.write_manifest(
                    result=report.result.name, final_url=report.final_url
                )
            except Exception as exc:
                logger.warning("audit_manifest_error", error=str(exc))

        return report

    async def _capture_page_audit(
        self,
        page_num: int,
        portal_name: str,
        fields: list[FormField],
        failures: list[str],
        session: FormSession,
        filler: FormFiller,
    ) -> str:
        """Captura as evidências visuais de uma página já preenchida.

        Sempre tira a visão geral (full page). Quando há AuditSession e
        per_question_shots está ligado, tira também 1 screenshot por pergunta
        preenchida, garantindo cobertura total das questões respondidas.

        Retorna o caminho do screenshot de visão geral (para o StepReport).
        """
        # ── Visão geral da página ───────────────────────────────────────────
        if self._audit is not None:
            overview = self._audit.overview_path(page_num)
            await filler.take_screenshot(dest=overview)
            self._audit.record_page(page_num, overview, url=self._page.url)
        else:
            overview = await filler.take_screenshot(f"{portal_name}_page_{page_num}")
        session.screenshots.append(str(overview))

        if self._audit is None or not self._per_question_shots:
            return str(overview)

        # ── Um screenshot por pergunta preenchida ───────────────────────────
        failed = set(failures)
        seen_groups: set[str] = set()
        q_index = 0
        for f in fields:
            # Só registra perguntas que de fato receberam valor e não falharam.
            if f.selector not in session.filled_values or f.selector in failed:
                continue
            # Grupos de radio/checkbox compartilham `name` — uma evidência por
            # grupo (senão um grupo de 183 checkboxes geraria 183 prints).
            if f.field_type in (FieldType.RADIO, FieldType.CHECKBOX) and f.name:
                group_key = f"{f.field_type}:{f.name}"
            else:
                group_key = f.selector
            if group_key in seen_groups:
                continue
            seen_groups.add(group_key)

            q_index += 1
            qpath = self._audit.question_path(page_num, q_index, self._audit.slug_for(f))
            ok = await filler.screenshot_field(f, qpath)
            self._audit.record_question(
                page_num, q_index, f, session.filled_values.get(f.selector), qpath, ok
            )
            if ok:
                session.screenshots.append(str(qpath))

        logger.info("page_audit_captured", page=page_num, questions=q_index)
        return str(overview)

    def _log_confidence_summary(self) -> None:
        """Emite o sumário de auditoria ao final da execução (Ajuste 4):
        total de campos, distribuição de confiança/origem e campos que precisam
        de revisão humana."""
        from collections import Counter

        fields = self._all_classified
        confidence = Counter((f.confidence or "untagged") for f in fields)
        sources = Counter((f.classification_source or "untagged") for f in fields)

        logger.info(
            "run_summary",
            total_fields=len(fields),
            confidence=dict(confidence),
            sources=dict(sources),
            requires_human_review=len(self._review_queue),
        )
        for f in self._review_queue:
            logger.info(
                "review_item",
                selector=f.selector,
                label=(f.label or "")[:80] or None,
            )

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

    @staticmethod
    def _checkbox_option_text(field: FormField) -> str:
        """Texto da opção de um checkbox de grupo (vem no value do seletor;
        cai no label como fallback)."""
        m = _CHECKBOX_VALUE_RE.search(field.selector)
        if m:
            return m.group(1).replace('\\"', '"').strip()
        label = field.label or ""
        return label.split(" — ", 1)[1].strip() if " — " in label else label.strip()

    async def _resolve_large_checkbox_groups(
        self, fields: list[FormField], session: FormSession
    ) -> None:
        """Trata grupos de checkbox (2+ opções) com uma única seleção via LLM.

        Sem isso, cada opção era classificada isoladamente — ou marcava tudo com o
        mesmo CNAE (a empresa fornecia "tudo"), ou não marcava nada (deixando um
        obrigatório vazio e travando o form). Aqui o LLM escolhe no máximo 3 opções
        aplicáveis ao perfil; as demais são explicitamente desmarcadas. Pré-preenche
        session.filled_values para que o loop campo a campo não reprocesse o grupo.
        """
        groups: dict[str, list[FormField]] = {}
        for f in fields:
            if f.field_type == FieldType.CHECKBOX and f.name:
                groups.setdefault(f.name, []).append(f)

        for name, group in groups.items():
            if len(group) < _CHECKBOX_GROUP_MIN:
                continue  # checkbox isolado → caminho normal (aceite/disponibilidade)

            options = [self._checkbox_option_text(f) for f in group]
            group_label = group[0].label or ""
            chosen = await self._classifier.choose_options(
                group_label, options, self._profile_summary, max_select=3,
            )
            chosen_set = {i for i in chosen if 0 <= i < len(group)}

            for i, f in enumerate(group):
                if i in chosen_set:
                    _tag(f, "llm_fallback", "medium")
                elif chosen_set:
                    _tag(f, "checkbox_unselected", "high")
                else:
                    _tag(f, "no_matching_options", "low")
                if f.selector not in session.filled_values:
                    session.filled_values[f.selector] = "true" if i in chosen_set else "false"

            if chosen_set:
                logger.info(
                    "checkbox_group_resolved",
                    group=group_label[:60] or None,
                    marked=len(chosen_set),
                    total=len(group),
                )
            else:
                logger.warning(
                    "no_matching_options",
                    group=group_label[:60] or None,
                    total=len(group),
                )

    async def _resolve_value(self, field: FormField) -> str | None:
        """Decide o valor de um campo, com fallback inteligente para o caso unknown.

        Fluxo (Ajuste 1):
          - radio/select NÃO binário com >2 opções e sem classificação → pede ao
            LLM a melhor opção dado o perfil (em vez de chutar "Não" cegamente).
            Sem resposta segura → registra para revisão humana e não preenche.
          - radio binário Sim/Não unknown → mantém o default conservador "Não"
            (delegado ao DataGenerator).
          - demais casos → geração normal (perfil + fake).
        """
        st = field.semantic_type
        is_unknown = st in (SemanticType.UNKNOWN, SemanticType.DESCONHECIDO)
        is_choice = field.field_type in (FieldType.RADIO, FieldType.SELECT, FieldType.COMBOBOX)

        if is_unknown and is_choice and len(field.options) > 2 and not _is_binary_yes_no(field):
            choice = await self._classifier.choose_option(field, self._profile_summary)
            if choice:
                _tag(field, "llm_fallback", "medium")
                logger.info(
                    "llm_fallback_resolved",
                    selector=field.selector,
                    label=(field.label or "")[:60] or None,
                    choice=str(choice)[:60],
                )
                return choice
            _tag(field, "human_review_needed", "low")
            self._review_queue.append(field)
            logger.warning(
                "human_review_needed",
                selector=field.selector,
                label=(field.label or "")[:80] or None,
                reason="unknown_multi_option",
                options=len(field.options),
            )
            return None

        if is_unknown and field.field_type == FieldType.RADIO and _is_binary_yes_no(field):
            _tag(field, "default_no", "low")
            logger.info(
                "field_default_no",
                selector=field.selector,
                label=(field.label or "")[:60] or None,
            )
            return self._generator.generate(st, field=field)

        # Caminho normal: distingue dado real do perfil de dado gerado/fake.
        value = self._generator.generate(st, field=field)

        # Campo de escolha classificado como DADO, mas o valor gerado não casa com
        # nenhuma opção (ex.: Q44 "Classificação de Fornecedor" recebeu o CNAE em
        # vez de Materiais/Serviços/Ambos). Em vez de deixar o filler marcar uma
        # opção arbitrária, o LLM escolhe uma opção real com base no perfil
        # (inclui supplier_kind/description). Estado/UF e afins, que casam com
        # uma opção, seguem pelo valor gerado.
        if (
            not is_unknown
            and field.field_type in (FieldType.RADIO, FieldType.SELECT)
            and len(field.options) >= 2
            and not _is_binary_yes_no(field)
            and st not in _OPTION_VALUE_SEMANTICS
            and not _value_matches_option(value, field.options)
        ):
            choice = await self._classifier.choose_option(field, self._profile_summary)
            if choice:
                _tag(field, "llm_fallback", "medium")
                logger.info(
                    "llm_option_rematch",
                    selector=field.selector,
                    label=(field.label or "")[:60] or None,
                    semantic=st.value if st else None,
                    generated=str(value)[:40],
                    choice=str(choice)[:60],
                )
                return choice
            _tag(field, "human_review_needed", "low")
            self._review_queue.append(field)
            logger.warning(
                "human_review_needed",
                selector=field.selector,
                label=(field.label or "")[:80] or None,
                reason="classified_value_no_option_match",
            )
            return value

        if self._profile is not None and self._profile.get(st):
            _tag(field, "profile_match", "high")
        elif is_unknown:
            _tag(field, "generated_fallback", "low")
        else:
            _tag(field, "classified", "high")
        return value

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

            # Grupos grandes de checkbox: uma única decisão antes do loop campo a campo.
            await self._resolve_large_checkbox_groups(classified, session)

            for f in classified:
                if f.semantic_type and f.selector not in session.filled_values:
                    value = await self._resolve_value(f)
                    if value is not None:
                        session.filled_values[f.selector] = value

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

            current_fields = await self._wait_for_conditional_dom(crawler, seen_selectors)
        else:
            logger.warning("conditional_max_rounds_reached", page=page_num, limit=max_rounds)

        return all_classified, all_failures

    async def _wait_for_conditional_dom(
        self,
        crawler: DOMCrawler,
        seen_selectors: set[str],
    ) -> list[FormField]:
        """Espera breve por campos condicionais e retorna a próxima crawl.

        Em vez de dormir 0.4s fixos, faz polling com early-exit:
        - se nenhum campo novo apareceu em duas amostragens seguidas, sai
          imediatamente (DOM estabilizou ou não havia campos condicionais).
        - caso contrário, espera até ~1.2s total para o React/SPA terminar
          de renderizar os campos dependentes.

        Em páginas sem condicionais (rounds=1) o custo cai de ~0.4s para
        ~0.15s; em páginas pesadas (Jaguar Mining pág. 3, rounds=13) o
        ganho composto é significativo.
        """
        previous_new: frozenset[str] = frozenset()
        latest_fields: list[FormField] = []
        for _ in range(8):  # máx ~1.2s
            await asyncio.sleep(0.15)
            latest_fields = await crawler.extract_fields()
            new_selectors = frozenset(
                f.selector for f in latest_fields if f.selector not in seen_selectors
            )
            if not new_selectors:
                return latest_fields
            if new_selectors == previous_new:
                return latest_fields
            previous_new = new_selectors
        return latest_fields

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

    async def _find_invalid_field_selectors(self, known_fields: list[FormField]) -> list[str]:
        """
        Retorna seletores (dentre os campos conhecidos) marcados com aria-invalid='true'.

        Quando o MS Forms rejeita uma página, marca os campos problemáticos com
        aria-invalid='true'. Se o atributo existe no DOM mas nenhum seletor coincide
        (ex: erros em containers de radio group), retorna todos os campos como
        fallback defensivo para garantir que o re-fill seja tentado.
        """
        fl = self._page.frame_locator(self._iframe_selector) if self._iframe_selector else None
        root = fl if fl else self._page

        # Pré-check: ainda estamos na mesma página? Se nenhum seletor conhecido
        # estiver presente, o clique em Avançar funcionou e estamos em outra página.
        # Sem esse check, o fallback defensivo abaixo tenta re-preencher campos
        # antigos na página nova e gera timeouts em cascata.
        sample = known_fields[: min(5, len(known_fields))]
        on_same_page = False
        for f in sample:
            try:
                if await root.locator(f.selector).count() > 0:
                    on_same_page = True
                    break
            except Exception:
                continue
        if not on_same_page:
            return []

        try:
            total_invalid = await root.locator("[aria-invalid='true']").count()
            if total_invalid == 0:
                return []
        except Exception:
            return []

        invalid: list[str] = []
        for field in known_fields:
            try:
                if await root.locator(f"{field.selector}[aria-invalid='true']").count() > 0:
                    invalid.append(field.selector)
            except Exception:
                continue

        # Se há aria-invalid no DOM mas nenhum seletor coincidiu (ex: container de radio),
        # re-preenche todos os campos da página como fallback defensivo.
        if not invalid:
            invalid = [f.selector for f in known_fields]

        return invalid

    async def _advance_past_validation(
        self,
        page_num: int,
        portal_name: str,
        classified_fields: list[FormField],
        session: FormSession,
        filler: FormFiller,
        max_retries: int = 3,
    ) -> None:
        """
        Verifica se o clique em Avançar gerou erros de validação (aria-invalid='true').
        Se sim, re-preenche os campos problemáticos e tenta avançar novamente,
        até max_retries tentativas.
        """
        for attempt in range(1, max_retries + 1):
            await asyncio.sleep(0.5)

            invalid_selectors = await self._find_invalid_field_selectors(classified_fields)
            if not invalid_selectors:
                return  # sem erros — a página avançou normalmente

            logger.warning(
                "validation_error_detected",
                page=page_num,
                attempt=attempt,
                invalid_count=len(invalid_selectors),
                selectors=invalid_selectors[:10],
            )

            error_fields = [f for f in classified_fields if f.selector in invalid_selectors]
            if error_fields:
                retry_page = FormPage(page_number=page_num, fields=error_fields)
                await filler.fill_page(retry_page, session)
                await asyncio.sleep(0.3)

            advanced = await self._click_next(page_num, portal_name)
            if not advanced:
                logger.error("next_button_gone_after_validation_retry", page=page_num)
                return

        logger.error(
            "validation_retry_exhausted",
            page=page_num,
            retries=max_retries,
        )


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