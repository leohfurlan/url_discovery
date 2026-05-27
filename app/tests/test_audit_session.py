"""
tests/test_audit_session.py

Testes para AuditSession (manifesto/README e estrutura de pastas),
FormFiller.screenshot_field e a integração de auditoria no orquestrador.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from domain.entities.form import FieldType, FormField, FormPage, FormSession, SemanticType
from infrastructure.audit.audit_session import AuditSession, _slugify
from infrastructure.browser.filler import FormFiller


def _field(selector="#nome", semantic=SemanticType.RAZAO_SOCIAL, ftype=FieldType.TEXT, name="nome"):
    return FormField(
        selector=selector, label="Razão Social", tag="input",
        field_type=ftype, semantic_type=semantic, name=name, required=True,
        confidence="high", classification_source="profile_match",
    )


# ---------------------------------------------------------------------------
# AuditSession
# ---------------------------------------------------------------------------

class TestAuditSession:
    def test_setup_creates_dirs(self, tmp_path):
        audit = AuditSession(portal="jaguar-mining", base_dir=tmp_path, timestamp="20260527_120000")
        audit.setup()
        assert audit.root == tmp_path / "jaguar-mining" / "20260527_120000"
        assert audit.screenshots_dir.is_dir()
        assert audit.log_path == audit.root / "session.log"

    def test_paths_are_named_by_page_and_question(self, tmp_path):
        audit = AuditSession(portal="p", base_dir=tmp_path, timestamp="t")
        assert audit.overview_path(1).name == "pagina-01.png"
        assert audit.question_path(2, 3, "cnpj").name == "p02-q03-cnpj.png"

    def test_slug_for_uses_semantic_then_label(self, tmp_path):
        audit = AuditSession(portal="p", base_dir=tmp_path, timestamp="t")
        assert audit.slug_for(_field(semantic=SemanticType.CNPJ)) == "cnpj"
        f = _field(semantic=None)
        f.semantic_type = None
        f.label = "Nome Fantasia!"
        assert audit.slug_for(f) == "nome-fantasia"

    def test_manifest_and_readme_report_full_coverage(self, tmp_path):
        audit = AuditSession(portal="jaguar-mining", base_dir=tmp_path, timestamp="t")
        audit.setup()
        audit.record_page(1, audit.overview_path(1), url="https://x")
        f1 = _field("#nome", SemanticType.RAZAO_SOCIAL)
        f2 = _field("#cnpj", SemanticType.CNPJ)
        audit.record_question(1, 1, f1, "Empresa Fake Ltda", audit.question_path(1, 1, "razao_social"), True)
        audit.record_question(1, 2, f2, "12.345.678/0001-90", audit.question_path(1, 2, "cnpj"), True)

        readme = audit.write_manifest(result="SUCCESS", final_url="https://x")

        manifest = json.loads((audit.root / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["totals"] == {"pages": 1, "questions": 2, "captured": 2, "coverage_pct": 100.0}
        assert manifest["pages"][0]["questions"][0]["screenshot"] == "screenshots/p01-q01-razao_social.png"
        assert manifest["pages"][0]["questions"][0]["value"] == "Empresa Fake Ltda"

        text = readme.read_text(encoding="utf-8")
        assert "Cobertura: **100.0%**" in text
        assert "12.345.678/0001-90" in text

    def test_uncaptured_question_lowers_coverage(self, tmp_path):
        audit = AuditSession(portal="p", base_dir=tmp_path, timestamp="t")
        audit.setup()
        audit.record_question(1, 1, _field(), "v", audit.question_path(1, 1, "a"), True)
        audit.record_question(1, 2, _field("#x"), "v", audit.question_path(1, 2, "b"), False)
        audit.write_manifest()
        manifest = json.loads((audit.root / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["totals"]["coverage_pct"] == 50.0

    def test_long_value_is_truncated(self, tmp_path):
        audit = AuditSession(portal="p", base_dir=tmp_path, timestamp="t")
        audit.setup()
        audit.record_question(1, 1, _field(), "x" * 500, audit.question_path(1, 1, "a"), True)
        audit.write_manifest()
        manifest = json.loads((audit.root / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["pages"][0]["questions"][0]["value"].endswith("…")

    def test_slugify_handles_empty(self):
        assert _slugify("") == "campo"
        assert _slugify("  ") == "campo"
        assert _slugify("Razão Social / Nome") == "raz-o-social-nome"


# ---------------------------------------------------------------------------
# FormFiller.screenshot_field
# ---------------------------------------------------------------------------

class TestScreenshotField:
    @pytest.mark.asyncio
    async def test_captures_and_returns_true(self, tmp_path):
        page = MagicMock()
        page.screenshot = AsyncMock()
        locator = AsyncMock()
        locator.count = AsyncMock(return_value=1)
        locator.scroll_into_view_if_needed = AsyncMock()
        locator.evaluate = AsyncMock()
        first = MagicMock()
        first_loc = AsyncMock()
        first_loc.count = AsyncMock(return_value=1)
        first_loc.scroll_into_view_if_needed = AsyncMock()
        first_loc.evaluate = AsyncMock()
        locator.first = first_loc
        page.locator = MagicMock(return_value=locator)

        filler = FormFiller(page)
        dest = tmp_path / "q.png"
        ok = await filler.screenshot_field(_field(), dest)

        assert ok is True
        page.screenshot.assert_awaited_once_with(path=str(dest))

    @pytest.mark.asyncio
    async def test_returns_false_when_field_absent(self, tmp_path):
        page = MagicMock()
        page.screenshot = AsyncMock()
        locator = MagicMock()
        first_loc = AsyncMock()
        first_loc.count = AsyncMock(return_value=0)
        locator.first = first_loc
        page.locator = MagicMock(return_value=locator)

        filler = FormFiller(page)
        ok = await filler.screenshot_field(_field(), tmp_path / "q.png")

        assert ok is False
        page.screenshot.assert_not_awaited()


# ---------------------------------------------------------------------------
# Integração: orquestrador registra evidências por pergunta
# ---------------------------------------------------------------------------

class TestOrchestratorAudit:
    @pytest.mark.asyncio
    async def test_run_writes_manifest_with_questions(self, tmp_path):
        from infrastructure.browser.navigator import NavigationOrchestrator

        field = _field()
        page = MagicMock()
        page.url = "https://portal.example.com/form"
        page.evaluate = AsyncMock(return_value="obrigado pelo cadastro")
        page.screenshot = AsyncMock()
        page.locator = MagicMock(return_value=AsyncMock())

        classifier = AsyncMock()
        classifier.classify = AsyncMock(return_value=[field])
        generator = MagicMock()

        audit = AuditSession(portal="jaguar-mining", base_dir=tmp_path, timestamp="t")
        audit.setup()

        with patch("infrastructure.browser.navigator.DOMCrawler") as MockCrawler:
            crawler = AsyncMock()
            crawler.extract_fields = AsyncMock(return_value=[field])
            MockCrawler.return_value = crawler

            with patch("infrastructure.browser.navigator.FormFiller") as MockFiller:
                filler = AsyncMock()
                filler.fill_page = AsyncMock(return_value=[])
                filler.take_screenshot = AsyncMock(return_value=audit.overview_path(1))
                filler.screenshot_field = AsyncMock(return_value=True)
                MockFiller.return_value = filler

                orch = NavigationOrchestrator(
                    page=page, classifier=classifier, generator=generator, audit=audit,
                )
                # filled_values precisa conter o campo para gerar a evidência.
                orch._resolve_value = AsyncMock(return_value="Empresa Fake Ltda")
                report = await orch.run("jaguar-mining")

        # screenshot_field foi chamado para a pergunta preenchida
        filler.screenshot_field.assert_awaited()
        manifest = json.loads((audit.root / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["totals"]["questions"] >= 1
        assert manifest["totals"]["captured"] >= 1
        assert (audit.root / "README.md").exists()
        _ = report
