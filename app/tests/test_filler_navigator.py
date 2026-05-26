"""
tests/test_filler_navigator.py

Testes unitários para FormFiller e NavigationOrchestrator.
Usa mocks do Playwright para não depender de browser real.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from domain.entities.form import FieldType, FormField, FormPage, FormSession, SemanticType
from infrastructure.browser.filler import FillError, FormFiller, _write_minimal_pdf, _write_minimal_image


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_field(
    selector: str = "#nome",
    field_type: FieldType = FieldType.TEXT,
    semantic_type: SemanticType = SemanticType.RAZAO_SOCIAL,
    name: str = "nome",
) -> FormField:
    f = FormField(
        selector=selector,
        label="Nome",
        tag="input",
        field_type=field_type,
        semantic_type=semantic_type,
        name=name,
        required=True,
    )
    return f


def _make_page(fields: list[FormField]) -> FormPage:
    return FormPage(page_number=1, fields=fields)


def _make_session(fields: list[FormField], values: dict | None = None) -> FormSession:
    session = FormSession(current_page=1)
    if values:
        session.filled_values = values
    else:
        for f in fields:
            session.filled_values[f.selector] = "VALOR_FAKE"
    return session


def _make_mock_locator(visible: bool = True, enabled: bool = True) -> AsyncMock:
    loc = AsyncMock()
    loc.wait_for = AsyncMock()
    loc.clear = AsyncMock()
    loc.type = AsyncMock()
    loc.fill = AsyncMock()
    loc.check = AsyncMock()
    loc.uncheck = AsyncMock()
    loc.select_option = AsyncMock()
    loc.set_input_files = AsyncMock()
    loc.is_visible = AsyncMock(return_value=visible)
    loc.is_enabled = AsyncMock(return_value=enabled)
    loc.count = AsyncMock(return_value=1)
    loc.first = AsyncMock()
    loc.first.check = AsyncMock()
    loc.evaluate = AsyncMock(return_value=["opcao1", "opcao2"])
    return loc


def _make_mock_page() -> MagicMock:
    page = MagicMock()
    page.screenshot = AsyncMock()
    return page


# ---------------------------------------------------------------------------
# FormFiller — fill_field por FieldType
# ---------------------------------------------------------------------------

class TestFormFillerTextInput:
    @pytest.mark.asyncio
    async def test_fill_text_calls_type(self):
        field = _make_field(field_type=FieldType.TEXT)
        session = _make_session([field])
        page = _make_mock_page()
        locator = _make_mock_locator()
        page.locator = MagicMock(return_value=locator)

        filler = FormFiller(page)
        failures = await filler.fill_page(_make_page([field]), session)

        assert failures == []
        locator.type.assert_awaited_once_with("VALOR_FAKE", delay=40, timeout=8_000)

    @pytest.mark.asyncio
    async def test_fill_email_field(self):
        field = _make_field(selector="#email", field_type=FieldType.EMAIL, semantic_type=SemanticType.EMAIL_CORPORATIVO)
        session = _make_session([field], {"#email": "contato@empresa.com"})
        page = _make_mock_page()
        locator = _make_mock_locator()
        page.locator = MagicMock(return_value=locator)

        filler = FormFiller(page)
        failures = await filler.fill_page(_make_page([field]), session)

        assert failures == []
        locator.type.assert_awaited_once_with("contato@empresa.com", delay=40, timeout=8_000)


class TestFormFillerSelect:
    @pytest.mark.asyncio
    async def test_fill_select_by_value(self):
        field = _make_field(selector="#estado", field_type=FieldType.SELECT, semantic_type=SemanticType.ESTADO)
        session = _make_session([field], {"#estado": "SP"})
        page = _make_mock_page()
        locator = _make_mock_locator()
        page.locator = MagicMock(return_value=locator)

        filler = FormFiller(page)
        await filler.fill_page(_make_page([field]), session)

        locator.select_option.assert_awaited()

    @pytest.mark.asyncio
    async def test_fill_select_fallback_to_first_option(self):
        """Quando value e label falham, deve usar primeira opção disponível."""
        field = _make_field(selector="#porte", field_type=FieldType.SELECT, semantic_type=SemanticType.DESCONHECIDO)
        session = _make_session([field], {"#porte": "VALOR_INEXISTENTE"})
        page = _make_mock_page()

        locator = _make_mock_locator()
        # Faz value e label falharem
        locator.select_option = AsyncMock(side_effect=[Exception("no value"), Exception("no label"), None])
        locator.evaluate = AsyncMock(return_value=["", "pequeno", "medio", "grande"])
        page.locator = MagicMock(return_value=locator)

        filler = FormFiller(page)
        failures = await filler.fill_page(_make_page([field]), session)

        # Deve ter tentado com "pequeno" (primeiro não-vazio)
        assert failures == []


class TestFormFillerCheckbox:
    @pytest.mark.asyncio
    async def test_checkbox_checked_when_true(self):
        field = _make_field(selector="#aceito", field_type=FieldType.CHECKBOX, semantic_type=SemanticType.DESCONHECIDO)
        session = _make_session([field], {"#aceito": True})
        page = _make_mock_page()
        locator = _make_mock_locator()
        # is_checked retorna False — força o filler a clicar para marcar
        locator.is_checked = AsyncMock(return_value=False)
        page.locator = MagicMock(return_value=locator)

        filler = FormFiller(page)
        await filler.fill_page(_make_page([field]), session)

        # _fill_checkbox usa evaluate("el => el.click()") em vez de check()
        # para funcionar em SPAs React onde o input fica oculto.
        locator.evaluate.assert_awaited()
        assert "el.click()" in str(locator.evaluate.call_args)

    @pytest.mark.asyncio
    async def test_checkbox_unchecked_when_false(self):
        field = _make_field(selector="#aceito", field_type=FieldType.CHECKBOX, semantic_type=SemanticType.DESCONHECIDO)
        session = _make_session([field], {"#aceito": False})
        page = _make_mock_page()
        locator = _make_mock_locator()
        # is_checked retorna True — força o filler a desmarcar via evaluate
        locator.is_checked = AsyncMock(return_value=True)
        page.locator = MagicMock(return_value=locator)

        filler = FormFiller(page)
        await filler.fill_page(_make_page([field]), session)

        locator.evaluate.assert_awaited()
        assert "el.checked" in str(locator.evaluate.call_args)


class TestFormFillerFile:
    @pytest.mark.asyncio
    async def test_file_upload_creates_temp_pdf(self):
        field = _make_field(selector="#doc", field_type=FieldType.FILE, semantic_type=SemanticType.DOCUMENTO_PDF)
        session = _make_session([field], {"#doc": "application/pdf"})
        page = _make_mock_page()
        locator = _make_mock_locator()
        page.locator = MagicMock(return_value=locator)

        filler = FormFiller(page)
        failures = await filler.fill_page(_make_page([field]), session)

        assert failures == []
        locator.set_input_files.assert_awaited_once()
        # Verifica que o argumento é um path existente
        call_args = locator.set_input_files.call_args[0][0]
        assert Path(call_args).exists()

    @pytest.mark.asyncio
    async def test_file_upload_creates_temp_image(self):
        field = _make_field(selector="#foto", field_type=FieldType.FILE, semantic_type=SemanticType.DOCUMENTO_PDF)
        session = _make_session([field], {"#foto": "foto.jpg"})
        page = _make_mock_page()
        locator = _make_mock_locator()
        page.locator = MagicMock(return_value=locator)

        filler = FormFiller(page)
        await filler.fill_page(_make_page([field]), session)

        call_args = locator.set_input_files.call_args[0][0]
        assert Path(call_args).exists()


class TestFormFillerErrors:
    @pytest.mark.asyncio
    async def test_invisible_field_returns_failure(self):
        field = _make_field()
        session = _make_session([field])
        page = _make_mock_page()
        locator = _make_mock_locator()
        locator.wait_for = AsyncMock(side_effect=Exception("Timeout"))
        page.locator = MagicMock(return_value=locator)

        filler = FormFiller(page)
        failures = await filler.fill_page(_make_page([field]), session)

        assert field.selector in failures

    @pytest.mark.asyncio
    async def test_missing_value_skips_field(self):
        field = _make_field()
        session = FormSession(current_page=1)  # sem filled_values
        page = _make_mock_page()
        locator = _make_mock_locator()
        page.locator = MagicMock(return_value=locator)

        filler = FormFiller(page)
        failures = await filler.fill_page(_make_page([field]), session)

        # Não falhou, só pulou
        assert failures == []
        locator.type.assert_not_awaited()


# ---------------------------------------------------------------------------
# Fake file generators
# ---------------------------------------------------------------------------

class TestFakeFileGenerators:
    def test_write_minimal_pdf_is_valid(self, tmp_path):
        path = tmp_path / "test.pdf"
        _write_minimal_pdf(path)
        assert path.exists()
        assert path.read_bytes().startswith(b"%PDF-")

    def test_write_minimal_image_is_valid(self, tmp_path):
        path = tmp_path / "test.png"
        _write_minimal_image(path)
        assert path.exists()
        # PNG magic bytes
        assert path.read_bytes()[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# NavigationOrchestrator — testes de integração leve
# ---------------------------------------------------------------------------

class TestNavigationOrchestrator:
    """Testa o orquestrador com mocks totais de crawler, classifier e filler."""

    @pytest.mark.asyncio
    async def test_single_page_success(self):
        from infrastructure.browser.navigator import NavigationOrchestrator, NavigationResult
        from domain.entities.form import FormStatus

        field = _make_field()
        classified_field = _make_field()
        classified_field.semantic_type = SemanticType.RAZAO_SOCIAL

        page = _make_mock_page()
        page.url = "https://portal.example.com/form"
        page.evaluate = AsyncMock(return_value="obrigado pelo cadastro")
        page.locator = MagicMock(return_value=_make_mock_locator())
        page.screenshot = AsyncMock()

        classifier = AsyncMock()
        classifier.classify = AsyncMock(return_value=[classified_field])

        generator = MagicMock()
        generator.generate = MagicMock(return_value="Empresa Fake Ltda")

        with patch("infrastructure.browser.navigator.DOMCrawler") as MockCrawler:
            mock_crawler_instance = AsyncMock()
            mock_crawler_instance.extract_fields = AsyncMock(return_value=[field])
            MockCrawler.return_value = mock_crawler_instance

            with patch("infrastructure.browser.navigator.FormFiller") as MockFiller:
                mock_filler_instance = AsyncMock()
                mock_filler_instance.fill_page = AsyncMock(return_value=[])
                mock_filler_instance.take_screenshot = AsyncMock(return_value=Path("/tmp/test.png"))
                MockFiller.return_value = mock_filler_instance

                orchestrator = NavigationOrchestrator(
                    page=page,
                    classifier=classifier,
                    generator=generator,
                )
                report = await orchestrator.run("test_portal")

        assert report.result == NavigationResult.SUCCESS
        assert report.session.status == FormStatus.COMPLETED
        assert len(report.steps) == 1
        assert report.steps[0].fields_found == 1
        assert report.steps[0].fields_filled == 1

    @pytest.mark.asyncio
    async def test_no_next_button_stops_gracefully(self):
        from infrastructure.browser.navigator import NavigationOrchestrator, NavigationResult

        field = _make_field()

        page = _make_mock_page()
        page.url = "https://portal.example.com/form"
        page.content = AsyncMock(return_value="<html><body>formulário</body></html>")

        # Nenhum locator encontrado (count=0)
        mock_locator = _make_mock_locator()
        mock_locator.count = AsyncMock(return_value=0)
        page.locator = MagicMock(return_value=mock_locator)
        page.screenshot = AsyncMock()

        classifier = AsyncMock()
        classified = _make_field()
        classified.semantic_type = SemanticType.RAZAO_SOCIAL
        classifier.classify = AsyncMock(return_value=[classified])

        generator = MagicMock()
        generator.generate = MagicMock(return_value="Fake")

        with patch("infrastructure.browser.navigator.DOMCrawler") as MockCrawler:
            mock_crawler_instance = AsyncMock()
            mock_crawler_instance.extract_fields = AsyncMock(return_value=[field])
            MockCrawler.return_value = mock_crawler_instance

            with patch("infrastructure.browser.navigator.FormFiller") as MockFiller:
                mock_filler_instance = AsyncMock()
                mock_filler_instance.fill_page = AsyncMock(return_value=[])
                mock_filler_instance.take_screenshot = AsyncMock(return_value=Path("/tmp/test.png"))
                MockFiller.return_value = mock_filler_instance

                orchestrator = NavigationOrchestrator(page=page, classifier=classifier, generator=generator)
                report = await orchestrator.run("test_portal")

        assert report.result == NavigationResult.NEXT_BUTTON_NOT_FOUND