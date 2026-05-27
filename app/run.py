"""
run.py — CLI do agente de preenchimento automático de formulários.

O agente recebe a URL da página pública do portal (não o link direto
do formulário), descobre o formulário automaticamente via PortalDiscovery
e executa o pipeline completo: crawl → classify → generate → fill.

Uso:
    python run.py <URL> <PORTAL> [opções]

Exemplos:
    python run.py "https://portal.example.com/cadastro" 
    python run.py "https://portal.example.com" empresa --headless
    python run.py "https://portal.example.com" empresa --slow-fill --max-pages 20
    python run.py "https://portal.example.com" empresa --iframe 'iframe[src*="forms.office.com"]'
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import structlog
import typer
from dotenv import load_dotenv

load_dotenv()

# Garante que app/ está no path quando executado diretamente
_APP_DIR = Path(__file__).parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

logger = structlog.get_logger(__name__)

from infrastructure.audit.audit_session import AuditSession  # noqa: E402


def _configure_logging(log_file: Path | None) -> None:
    """Configura structlog para escrever em stderr e, opcionalmente, em arquivo.

    Quando log_file é informado, todo evento estruturado é gravado também
    no arquivo (sem cores ANSI). A formatação é a mesma do console — o
    arquivo é fiel ao que o usuário viu na tela.
    """
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    # basicConfig respeita handlers já configurados se force=True for omitido
    # em runs subsequentes; usamos force=True para garantir reconfiguração
    # quando o CLI é chamado várias vezes no mesmo processo (ex: testes).
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=handlers,
        force=True,
    )

    # Silencia ruído de INFO de bibliotecas de terceiros que não é da nossa
    # execução: o SDK google-genai loga "AFC is enabled with max remote calls"
    # a cada chamada (AFC = Automatic Function Calling, recurso de tool-calling
    # que não usamos) e o httpx loga cada requisição HTTP.
    for noisy in ("google_genai", "google.genai", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

app = typer.Typer(
    name="url-discovery",
    help="Agente de preenchimento automático de formulários em portais de fornecedores.",
    add_completion=False,
)


@app.command()
def main(
    url: str = typer.Argument(..., help="URL da página pública do portal (não o link do formulário)"),
    portal: str = typer.Argument(..., help="Nome do portal — usado em logs e nomes de screenshot"),
    headless: bool = typer.Option(False, "--headless", help="Rodar sem janela do browser"),
    slow_fill: bool = typer.Option(False, "--slow-fill", help="Delay extra entre campos (portais sensíveis a timing)"),
    max_pages: int = typer.Option(15, "--max-pages", help="Limite de páginas do formulário"),
    iframe: str | None = typer.Option(None, "--iframe", help="Seletor CSS do iframe, se já conhecido (pula a discovery)"),
    audit_dir: Path | None = typer.Option(None, "--audit-dir", help="Raiz dos artefatos de auditoria (padrão: ./audit). Logs e screenshots vão para <audit-dir>/<portal>/<timestamp>/"),
    per_question_shots: bool = typer.Option(True, "--per-question-shots/--no-per-question-shots", help="Tira 1 screenshot por pergunta preenchida (cobertura 100%). Padrão: ativado"),
    model: str = typer.Option("gemma-4-26b-a4b-it", "--model", help="Modelo Gemma para classificação semântica e extração de documentos"),
    docs_dir: Path | None = typer.Option(None, "--docs-dir", help="Diretório com PDFs reais (Cartão CNPJ, Contrato Social, Demonstrações Financeiras)"),
    supplier_kind: str | None = typer.Option(None, "--supplier-kind", help="Tipo de fornecimento: materiais | servicos | ambos (ajuda na classificação de fornecedor e categorias)"),
    supplier_desc: str | None = typer.Option(None, "--supplier-desc", help="Descrição curta do que a empresa fornece"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Força reprocessamento dos PDFs mesmo que cache esteja disponível"),
    clear_cls_cache: bool = typer.Option(False, "--clear-cls-cache", help="Limpa o cache de classificação semântica (~/.url_discovery/cls_cache.json) antes de iniciar"),
    submit: bool = typer.Option(None, "--submit/--no-submit", help="Submete o formulário após preencher (sobrescreve ALLOW_FORM_SUBMIT do .env)"),
    log_file: bool = typer.Option(True, "--log-file/--no-log-file", help="Salva log da sessão em logs/<portal>_<timestamp>.log (padrão: ativado)"),
    log_file_path: Path | None = typer.Option(None, "--log-file-path", help="Caminho customizado para o log (sobrescreve o padrão)"),
) -> None:
    """Descobre e preenche automaticamente o formulário de cadastro de fornecedor.

    AVISO: por padrão (ALLOW_FORM_SUBMIT=false) o agente preenche os campos
    mas NÃO clica em Submit. Use --submit ou ALLOW_FORM_SUBMIT=true apenas
    em produção, após validar os dados gerados para o portal.
    """
    # Sessão de auditoria: logs e screenshots desta execução ficam juntos em
    # <audit-dir>/<portal>/<timestamp>/ (ex: audit/jaguar-mining/20260527_143000/).
    audit = AuditSession(portal=portal, base_dir=audit_dir)
    audit.setup()

    # Configura logging ANTES de qualquer log estruturado para garantir que
    # o arquivo recebe a sessão inteira (incluindo as mensagens de setup).
    resolved_log_path: Path | None = None
    if log_file:
        resolved_log_path = log_file_path if log_file_path is not None else audit.log_path
    _configure_logging(resolved_log_path)
    typer.echo(f"→ Auditoria desta execução: {audit.root}")
    if resolved_log_path is not None:
        typer.echo(f"→ Log da sessão será salvo em: {resolved_log_path}")

    # Resolução de prioridade: flag CLI > variável de ambiente > padrão seguro (false)
    if submit is None:
        allow_submit = os.environ.get("ALLOW_FORM_SUBMIT", "false").strip().lower() == "true"
    else:
        allow_submit = submit

    if allow_submit:
        typer.echo("⚠  ALLOW_FORM_SUBMIT=true — o formulário SERÁ submetido.", err=True)
    else:
        typer.echo("ℹ  ALLOW_FORM_SUBMIT=false — campos serão preenchidos mas NÃO submetidos.")

    if clear_cls_cache:
        from pathlib import Path as _Path
        cache_file = _Path.home() / ".url_discovery" / "cls_cache.json"
        if cache_file.exists():
            cache_file.unlink()
            typer.echo(f"→ Cache de classificação removido: {cache_file}")
        else:
            typer.echo("→ Cache de classificação não encontrado (já estava limpo).")

    supplier_kind, supplier_desc = _collect_supplier_info(supplier_kind, supplier_desc)

    try:
        report = asyncio.run(
            _run(url, portal, headless, slow_fill, max_pages, iframe, audit, per_question_shots, model, allow_submit, docs_dir, no_cache, supplier_kind, supplier_desc)
        )
        _print_report(report, portal, audit)
        raise typer.Exit(code=0 if report.result.name == "SUCCESS" else 1)
    except (KeyboardInterrupt, typer.Exit):
        raise
    except Exception as exc:
        typer.echo(f"\nErro fatal: {exc}", err=True)
        raise typer.Exit(code=1)


_SUPPLIER_KINDS = {
    "materiais": "materiais", "material": "materiais", "produtos": "materiais",
    "servicos": "serviços", "serviços": "serviços", "serviço": "serviços", "servico": "serviços",
    "ambos": "ambos", "materiais e servicos": "ambos", "materiais e serviços": "ambos",
}


def _normalize_supplier_kind(value: str | None) -> str | None:
    """Normaliza a entrada do tipo de fornecedor para materiais|serviços|ambos."""
    if not value:
        return None
    return _SUPPLIER_KINDS.get(value.strip().lower(), value.strip())


def _collect_supplier_info(
    supplier_kind: str | None, supplier_desc: str | None
) -> tuple[str | None, str | None]:
    """Normaliza o contexto de fornecedor vindo das flags --supplier-kind/--supplier-desc.

    É totalmente opcional: se as flags não forem passadas, o agente roda sem esse
    contexto e sem nenhum prompt — não interrompe execuções manuais nem agendadas.
    Quando informado, melhora a escolha de "Classificação de Fornecedor" e a
    seleção de categorias/serviços (a correção ciente das opções funciona mesmo
    sem ele)."""
    supplier_kind = _normalize_supplier_kind(supplier_kind)
    supplier_desc = (supplier_desc or "").strip() or None
    if supplier_kind or supplier_desc:
        typer.echo(f"→ Fornecedor: tipo={supplier_kind or '—'} | descrição={supplier_desc or '—'}")
    return supplier_kind, supplier_desc


async def _run(
    url: str,
    portal: str,
    headless: bool,
    slow_fill: bool,
    max_pages: int,
    iframe_selector: str | None,
    audit: AuditSession,
    per_question_shots: bool,
    model: str,
    allow_submit: bool,
    docs_dir: Path | None = None,
    no_cache: bool = False,
    supplier_kind: str | None = None,
    supplier_desc: str | None = None,
):
    from playwright.async_api import async_playwright
    from domain.entities.company_profile import CompanyProfile
    from infrastructure.llm.gemma_adapter import GemmaClassifier
    from domain.services.generator import DataGenerator
    from domain.services.document_extractor import DocumentExtractor
    from infrastructure.browser.portal_discovery import PortalDiscovery
    from infrastructure.browser.navigator import NavigationOrchestrator

    # ── 1. Extração de documentos ANTES de abrir o browser ────────────────────
    profile = None
    if docs_dir:
        if not docs_dir.is_dir():
            typer.echo(f"⚠  --docs-dir '{docs_dir}' não é um diretório válido — usando dados fake.", err=True)
        else:
            gemini_api_key = os.getenv("GEMINI_API_KEY")
            typer.echo(f"→ Carregando documentos reais de: {docs_dir}")
            extractor = DocumentExtractor(api_key=gemini_api_key, model=model)
            profile = await extractor.load_from_directory(docs_dir, use_cache=not no_cache)
            if profile.is_empty():
                typer.echo("⚠  Nenhum campo extraído dos PDFs — usando dados fake.")
                profile = None
            else:
                typer.echo(f"→ Perfil carregado: {profile.razao_social or '—'} / CNPJ: {profile.cnpj or '—'}")
                _check_minimum_fields(profile)

    # Anexa o contexto de fornecedor informado pelo usuário ao perfil (não vem
    # de PDF). Cria um perfil mínimo se não houver documentos — assim o
    # profile_summary chega ao LLM mesmo sem --docs-dir.
    if supplier_kind or supplier_desc:
        if profile is None:
            profile = CompanyProfile()
        profile = profile.model_copy(update={
            "supplier_kind": supplier_kind,
            "supplier_description": supplier_desc,
        })

    # ── 2. Navegação e preenchimento ──────────────────────────────────────────
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="pt-BR",
        )
        page = await context.new_page()

        typer.echo(f"→ Abrindo portal: {url}")
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        # Descoberta: localiza o formulário a partir da página do portal
        if iframe_selector is None:
            typer.echo("→ Procurando formulário na página...")
            discovery = PortalDiscovery(page)
            result = await discovery.find_and_navigate()
            active_page = result.page
            active_iframe = result.iframe_selector
            typer.echo(
                f"→ Formulário encontrado  [estratégia: {result.strategy}"
                + (f"  iframe: {active_iframe}" if active_iframe else "")
                + f"  url: {result.form_url}]"
            )
        else:
            active_page = page
            active_iframe = iframe_selector
            typer.echo(f"→ Usando iframe informado: {active_iframe}")

        classifier = GemmaClassifier(model=model)
        generator = DataGenerator(profile=profile)

        orchestrator = NavigationOrchestrator(
            page=active_page,
            classifier=classifier,
            generator=generator,
            iframe_selector=active_iframe,
            slow_fill=slow_fill,
            max_pages=max_pages,
            audit=audit,
            per_question_shots=per_question_shots,
            allow_submit=allow_submit,
            profile=profile,
        )

        typer.echo("→ Iniciando preenchimento...")
        report = await orchestrator.run(portal_name=portal)
        await browser.close()
        return report


def _check_minimum_fields(profile) -> None:
    """Avisa sobre campos críticos ausentes antes de iniciar o browser."""
    critical = {"cnpj": profile.cnpj, "razao_social": profile.razao_social}
    banking  = {"banco": profile.banco, "agencia": profile.agencia, "conta": profile.conta}

    missing_critical = [k for k, v in critical.items() if not v]
    missing_banking  = [k for k, v in banking.items() if not v]

    if missing_critical:
        typer.echo(
            f"⚠  Campos críticos ausentes: {', '.join(missing_critical)}"
            " — esses campos usarão dados fake.", err=True
        )
    if missing_banking:
        typer.echo(
            f"ℹ  Dados bancários incompletos: {', '.join(missing_banking)}"
            " — campos de pagamento usarão dados fake."
        )
    if not missing_critical and not missing_banking:
        typer.echo("✓  Todos os campos essenciais extraídos dos documentos.")


def _print_report(report, portal: str, audit: AuditSession | None = None) -> None:
    width = 52
    typer.echo("\n" + "=" * width)
    typer.echo(f"  Portal : {portal}")
    typer.echo(f"  Resultado : {report.result.name}")
    typer.echo(f"  URL final : {report.final_url}")
    typer.echo(f"  Páginas   : {len(report.steps)}")
    if audit is not None:
        typer.echo(f"  Auditoria : {audit.root}")
        n_shots = len(report.session.screenshots) if report.session else 0
        typer.echo(f"  Screenshots: {n_shots}  (veja README.md / manifest.json)")
    typer.echo("-" * width)
    for step in report.steps:
        mark = "✓" if not step.failures else "⚠"
        typer.echo(
            f"  {mark} Página {step.page_number:>2} — "
            f"{step.fields_filled}/{step.fields_found} campos"
            + (f"  falhas: {step.failures}" if step.failures else "")
        )
        if step.screenshot:
            typer.echo(f"           screenshot: {step.screenshot}")

    review = getattr(report, "requires_human_review", [])
    if review:
        typer.echo("-" * width)
        typer.echo(f"  ⚑ Revisão humana sugerida ({len(review)}):")
        for f in review:
            label = (f.label or f.selector)[:60]
            typer.echo(f"      - {label}")

    if report.error:
        typer.echo(f"  Erro: {report.error}", err=True)
    typer.echo("=" * width + "\n")


if __name__ == "__main__":
    app()
