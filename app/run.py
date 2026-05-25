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
    screenshot_dir: str | None = typer.Option(None, "--screenshots", help="Diretório para salvar screenshots (padrão: /tmp)"),
    model: str = typer.Option("gemma-4-26b-a4b-it", "--model", help="Modelo Gemma para classificação semântica e extração de documentos"),
    docs_dir: Path | None = typer.Option(None, "--docs-dir", help="Diretório com PDFs reais (Cartão CNPJ, Contrato Social, Demonstrações Financeiras)"),
    submit: bool = typer.Option(None, "--submit/--no-submit", help="Submete o formulário após preencher (sobrescreve ALLOW_FORM_SUBMIT do .env)"),
) -> None:
    """Descobre e preenche automaticamente o formulário de cadastro de fornecedor.

    AVISO: por padrão (ALLOW_FORM_SUBMIT=false) o agente preenche os campos
    mas NÃO clica em Submit. Use --submit ou ALLOW_FORM_SUBMIT=true apenas
    em produção, após validar os dados gerados para o portal.
    """
    # Resolução de prioridade: flag CLI > variável de ambiente > padrão seguro (false)
    if submit is None:
        allow_submit = os.environ.get("ALLOW_FORM_SUBMIT", "false").strip().lower() == "true"
    else:
        allow_submit = submit

    if allow_submit:
        typer.echo("⚠  ALLOW_FORM_SUBMIT=true — o formulário SERÁ submetido.", err=True)
    else:
        typer.echo("ℹ  ALLOW_FORM_SUBMIT=false — campos serão preenchidos mas NÃO submetidos.")

    try:
        report = asyncio.run(
            _run(url, portal, headless, slow_fill, max_pages, iframe, screenshot_dir, model, allow_submit, docs_dir)
        )
        _print_report(report, portal)
        raise typer.Exit(code=0 if report.result.name == "SUCCESS" else 1)
    except (KeyboardInterrupt, typer.Exit):
        raise
    except Exception as exc:
        typer.echo(f"\nErro fatal: {exc}", err=True)
        raise typer.Exit(code=1)


async def _run(
    url: str,
    portal: str,
    headless: bool,
    slow_fill: bool,
    max_pages: int,
    iframe_selector: str | None,
    screenshot_dir: str | None,
    model: str,
    allow_submit: bool,
    docs_dir: Path | None = None,
):
    from playwright.async_api import async_playwright
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
            profile = extractor.load_from_directory(docs_dir)
            if profile.is_empty():
                typer.echo("⚠  Nenhum campo extraído dos PDFs — usando dados fake.")
                profile = None
            else:
                typer.echo(f"→ Perfil carregado: {profile.razao_social or '—'} / CNPJ: {profile.cnpj or '—'}")
                _check_minimum_fields(profile)

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
            screenshot_dir=screenshot_dir,
            allow_submit=allow_submit,
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


def _print_report(report, portal: str) -> None:
    width = 52
    typer.echo("\n" + "=" * width)
    typer.echo(f"  Portal : {portal}")
    typer.echo(f"  Resultado : {report.result.name}")
    typer.echo(f"  URL final : {report.final_url}")
    typer.echo(f"  Páginas   : {len(report.steps)}")
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
    if report.error:
        typer.echo(f"  Erro: {report.error}", err=True)
    typer.echo("=" * width + "\n")


if __name__ == "__main__":
    app()
