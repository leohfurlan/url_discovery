"""
infrastructure/browser/filler.py

FormFiller — responsável por preencher campos detectados no DOM usando os
valores gerados pelo generator. Opera sobre o frame correto (iframe ou
documento principal) e delega cada tipo de campo a um método especializado.
"""

from __future__ import annotations

import asyncio
import mimetypes
import tempfile
from pathlib import Path
from typing import Any

import structlog
from playwright.async_api import Frame, FrameLocator, Locator, Page

from domain.entities.form import FieldType, FormField, FormPage, FormSession

logger = structlog.get_logger(__name__)

# Tempo máximo (ms) para aguardar um elemento ficar interagível
_DEFAULT_TIMEOUT = 8_000
# Delay entre keystrokes para portais sensíveis a ritmo de digitação
_TYPE_DELAY_MS = 40


class FillError(Exception):
    """Erro recuperável ao preencher um campo individual."""


class FormFiller:
    """
    Preenche uma FormPage usando os valores de FormSession.

    Recebe o `page` do Playwright e, opcionalmente, um `frame_locator`
    para operar dentro de iframes — mesma abstração já usada no DOMCrawler.

    Uso:
        filler = FormFiller(page, frame_locator=page.frame_locator("#iframe"))
        await filler.fill_page(form_page, session)
    """

    def __init__(
        self,
        page: Page,
        frame_locator: FrameLocator | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
        slow_fill: bool = False,
    ) -> None:
        self._page = page
        self._fl = frame_locator
        self._timeout = timeout
        self._slow_fill = slow_fill  # adiciona delay após cada campo

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    async def fill_page(self, form_page: FormPage, session: FormSession) -> list[str]:
        """
        Preenche todos os campos de `form_page` com os valores armazenados
        em `session.filled_values`.

        Retorna lista de seletores que falharam (para logging / retry).
        """
        failures: list[str] = []

        for field in form_page.fields:
            value = session.filled_values.get(field.selector)
            if value is None:
                logger.warning("no_value_for_field", selector=field.selector, semantic=field.semantic_type)
                continue

            try:
                await self._fill_field(field, value)
                logger.info(
                    "field_filled",
                    selector=field.selector,
                    field_type=field.field_type,
                    semantic=field.semantic_type,
                )
            except FillError as exc:
                logger.error("fill_error", selector=field.selector, error=str(exc))
                failures.append(field.selector)

            if self._slow_fill:
                await asyncio.sleep(0.3)

        return failures

    async def take_screenshot(self, name: str = "screenshot") -> Path:
        """Tira screenshot da página atual e salva em /tmp."""
        path = Path(tempfile.gettempdir()) / f"{name}.png"
        await self._page.screenshot(path=str(path), full_page=True)
        logger.info("screenshot_saved", path=str(path))
        return path

    # ------------------------------------------------------------------
    # Roteador interno por FieldType
    # ------------------------------------------------------------------

    async def _fill_field(self, field: FormField, value: Any) -> None:
        locator = self._resolve_locator(field.selector)

        try:
            await locator.wait_for(state="visible", timeout=self._timeout)
        except Exception as exc:
            raise FillError(f"Campo não ficou visível: {field.selector}") from exc

        match field.field_type:
            case FieldType.TEXT | FieldType.EMAIL | FieldType.TEL | FieldType.NUMBER:
                await self._fill_text(locator, str(value))
            case FieldType.TEXTAREA:
                await self._fill_text(locator, str(value))
            case FieldType.SELECT:
                await self._fill_select(locator, str(value))
            case FieldType.RADIO:
                await self._fill_radio(field, str(value))
            case FieldType.CHECKBOX:
                await self._fill_checkbox(locator, value)
            case FieldType.FILE:
                await self._fill_file(locator, field, str(value))
            case FieldType.DATE:
                await self._fill_date(locator, str(value))
            case _:
                # fallback genérico para tipos desconhecidos
                await self._fill_text(locator, str(value))

    # ------------------------------------------------------------------
    # Implementações por tipo
    # ------------------------------------------------------------------

    async def _fill_text(self, locator: Locator, value: str) -> None:
        try:
            await locator.clear()
            await locator.type(value, delay=_TYPE_DELAY_MS)
        except Exception as exc:
            raise FillError(str(exc)) from exc

    async def _fill_select(self, locator: Locator, value: str) -> None:
        """
        Tenta selecionar por value, label ou index=0 como fallback.
        Portais brasileiros frequentemente têm options sem value consistente.
        """
        try:
            # tenta value exato
            await locator.select_option(value=value, timeout=self._timeout)
            return
        except Exception:
            pass

        try:
            # tenta label (texto visível)
            await locator.select_option(label=value, timeout=self._timeout)
            return
        except Exception:
            pass

        try:
            # fallback: primeira opção não-placeholder (index 1 ou 0)
            options = await locator.evaluate(
                "el => Array.from(el.options).map(o => o.value)"
            )
            non_empty = [o for o in options if o.strip()]
            if non_empty:
                await locator.select_option(value=non_empty[0], timeout=self._timeout)
                return
        except Exception as exc:
            raise FillError(f"Não foi possível selecionar opção: {exc}") from exc

    async def _fill_radio(self, field: FormField, value: str) -> None:
        """
        Radio buttons agrupados por `name`. Procura o input cujo value ou
        label associado contenha o valor desejado, senão clica no primeiro.
        """
        # tenta localizar pelo atributo value
        selector_value = f'input[type="radio"][name="{field.name}"][value="{value}"]'
        locator = self._resolve_locator(selector_value)

        try:
            count = await locator.count()
            if count > 0:
                await locator.first.check(timeout=self._timeout)
                return
        except Exception:
            pass

        # fallback: clica no primeiro radio do grupo
        fallback_selector = f'input[type="radio"][name="{field.name}"]'
        fallback = self._resolve_locator(fallback_selector)
        try:
            await fallback.first.check(timeout=self._timeout)
        except Exception as exc:
            raise FillError(f"Radio não encontrado: {exc}") from exc

    async def _fill_checkbox(self, locator: Locator, value: Any) -> None:
        should_check = bool(value) if not isinstance(value, str) else value.lower() in ("true", "sim", "yes", "1")
        try:
            if should_check:
                await locator.check(timeout=self._timeout)
            else:
                await locator.uncheck(timeout=self._timeout)
        except Exception as exc:
            raise FillError(str(exc)) from exc

    async def _fill_date(self, locator: Locator, value: str) -> None:
        """
        Tenta fill() direto (funciona em inputs nativos), senão usa type().
        Portais com date pickers customizados podem precisar de estratégia extra.
        """
        try:
            await locator.fill(value, timeout=self._timeout)
        except Exception:
            await self._fill_text(locator, value)

    async def _fill_file(self, locator: Locator, field: FormField, value: str) -> None:
        """
        Faz upload de um arquivo fake. `value` pode ser:
        - caminho absoluto já existente
        - extensão/tipo MIME (ex: "application/pdf") → cria arquivo temporário
        - nome de arquivo (ex: "contrato.pdf") → cria arquivo temporário
        """
        file_path = await self._resolve_fake_file(value)
        try:
            await locator.set_input_files(str(file_path), timeout=self._timeout)
            logger.info("file_uploaded", path=str(file_path), selector=field.selector)
        except Exception as exc:
            raise FillError(f"Upload falhou: {exc}") from exc

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_locator(self, selector: str) -> Locator:
        """Retorna Locator operando no frame correto (iframe ou page)."""
        if self._fl is not None:
            return self._fl.locator(selector)
        return self._page.locator(selector)

    @staticmethod
    async def _resolve_fake_file(value: str) -> Path:
        """
        Retorna Path para um arquivo temporário fake baseado no value recebido.

        Estratégia:
        1. Se for caminho existente → usa direto
        2. Se tiver extensão conhecida → cria arquivo com esse nome
        3. Caso contrário → cria PDF mínimo válido
        """
        # Caminho existente
        existing = Path(value)
        if existing.exists():
            return existing

        # Detecta extensão pelo nome ou MIME
        suffix = ".pdf"
        if "." in value.split("/")[-1]:
            suffix = Path(value).suffix or ".pdf"
        elif "/" in value:
            # MIME type
            ext = mimetypes.guess_extension(value)
            suffix = ext or ".pdf"

        tmp = Path(tempfile.mkdtemp()) / f"fake_document{suffix}"

        if suffix == ".pdf":
            _write_minimal_pdf(tmp)
        elif suffix in (".jpg", ".jpeg", ".png"):
            _write_minimal_image(tmp)
        else:
            tmp.write_bytes(b"FAKE_DOCUMENT_CONTENT")

        return tmp


# ------------------------------------------------------------------
# Geradores de arquivos fake mínimos válidos
# ------------------------------------------------------------------

def _write_minimal_pdf(path: Path) -> None:
    """Escreve um PDF mínimo válido (sem texto, mas parseável)."""
    content = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n190\n%%EOF"
    )
    path.write_bytes(content)


def _write_minimal_image(path: Path) -> None:
    """Escreve um PNG mínimo válido (1x1 pixel branco)."""
    # PNG signature + IHDR + IDAT + IEND para 1x1 pixel branco
    content = bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
        0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,  # IHDR length + type
        0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,  # 1x1
        0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,  # 8-bit RGB
        0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,  # IDAT
        0x54, 0x08, 0xD7, 0x63, 0xF8, 0xFF, 0xFF, 0x3F,
        0x00, 0x05, 0xFE, 0x02, 0xFE, 0xA7, 0x35, 0x81,
        0x84, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E,  # IEND
        0x44, 0xAE, 0x42, 0x60, 0x82,
    ])
    path.write_bytes(content)