"""
tests/test_crawler.py

Testes unitários para DOMCrawler, _map_field_type e _build_selector.

Grupo 1 — lógica pura (zero browser):
    _map_field_type, _build_selector

Grupo 2 — comportamento com Playwright mockado (AsyncMock):
    DOMCrawler.extract_fields
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from domain.entities.form import FieldType
from infrastructure.browser.crawler import DOMCrawler, _build_selector, _map_field_type


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _attrs(
    *,
    tag: str = "input",
    type_: str = "text",
    name: str = "",
    id_: str = "",
    placeholder: str = "",
    required: bool = False,
    label: str = "",
    aria_labelledby: str = "",
    options: list[str] | None = None,
) -> dict:
    return {
        "tag": tag,
        "type": type_,
        "name": name,
        "id": id_,
        "placeholder": placeholder,
        "required": required,
        "label": label,
        "ariaLabelledby": aria_labelledby,
        "options": options or [],
    }


def _make_element(visible: bool = True, attrs: dict | None = None) -> AsyncMock:
    el = AsyncMock()
    el.is_visible = AsyncMock(return_value=visible)
    el.evaluate = AsyncMock(return_value=attrs)
    return el


def _make_page(*elements: AsyncMock) -> MagicMock:
    locator = MagicMock()
    locator.count = AsyncMock(return_value=len(elements))
    locator.nth = MagicMock(side_effect=lambda i: elements[i])
    page = MagicMock()
    page.locator = MagicMock(return_value=locator)
    return page


# ---------------------------------------------------------------------------
# Grupo 1 — lógica pura
# ---------------------------------------------------------------------------

class TestMapFieldType:
    @pytest.mark.parametrize("tag,input_type,expected", [
        ("select",   "",         FieldType.SELECT),
        ("select",   "text",     FieldType.SELECT),    # tag tem precedência sobre type
        ("textarea", "",         FieldType.TEXTAREA),
        ("textarea", "email",    FieldType.TEXTAREA),  # tag tem precedência sobre type
        ("input",    "email",    FieldType.EMAIL),
        ("input",    "tel",      FieldType.TEL),
        ("input",    "number",   FieldType.NUMBER),
        ("input",    "checkbox", FieldType.CHECKBOX),
        ("input",    "radio",    FieldType.RADIO),
        ("input",    "file",     FieldType.FILE),
        ("input",    "date",     FieldType.TEXT),      # date → TEXT por design
        ("input",    "text",     FieldType.TEXT),
        ("input",    "",         FieldType.TEXT),
        ("input",    "password", FieldType.TEXT),      # tipo desconhecido → TEXT
    ])
    def test_mapping(self, tag, input_type, expected):
        assert _map_field_type(tag, input_type) == expected


class TestBuildSelector:
    def test_id_has_priority_over_name(self):
        a = _attrs(id_="campo-id", name="campo", type_="text")
        assert _build_selector(a) == "#campo-id"

    def test_name_with_type(self):
        a = _attrs(name="telefone", type_="tel")
        assert _build_selector(a) == 'input[type="tel"][name="telefone"]'

    def test_name_without_type(self):
        a = _attrs(name="observacoes", type_="")
        assert _build_selector(a) == 'input[name="observacoes"]'

    def test_name_uses_tag(self):
        a = _attrs(tag="textarea", name="descricao", type_="")
        assert _build_selector(a) == 'textarea[name="descricao"]'

    def test_aria_labelledby_fallback(self):
        a = _attrs(aria_labelledby="lbl-01")
        assert _build_selector(a) == '[aria-labelledby="lbl-01"]'

    def test_no_usable_attrs_returns_none(self):
        a = _attrs()  # id, name, ariaLabelledby todos vazios
        assert _build_selector(a) is None


# ---------------------------------------------------------------------------
# Grupo 2 — comportamento com Playwright mockado
# ---------------------------------------------------------------------------

class TestDOMCrawlerExtractFields:
    async def test_empty_form_returns_empty_list(self):
        page = _make_page()
        fields = await DOMCrawler(page).extract_fields()
        assert fields == []

    async def test_invisible_field_is_excluded(self):
        el = _make_element(visible=False, attrs=_attrs(id_="oculto"))
        page = _make_page(el)
        fields = await DOMCrawler(page).extract_fields()
        assert fields == []

    async def test_evaluate_exception_is_skipped(self):
        el = AsyncMock()
        el.is_visible = AsyncMock(return_value=True)
        el.evaluate = AsyncMock(side_effect=Exception("DOM error"))
        page = _make_page(el)
        fields = await DOMCrawler(page).extract_fields()
        assert fields == []

    async def test_field_without_selector_is_excluded(self):
        # id, name e ariaLabelledby vazios → _build_selector retorna None
        el = _make_element(attrs=_attrs())
        page = _make_page(el)
        fields = await DOMCrawler(page).extract_fields()
        assert fields == []

    async def test_text_field_with_id(self):
        a = _attrs(id_="nome-empresa", name="nome", type_="text",
                   label="Nome da Empresa", required=True)
        el = _make_element(attrs=a)
        page = _make_page(el)

        fields = await DOMCrawler(page).extract_fields()

        assert len(fields) == 1
        f = fields[0]
        assert f.selector == "#nome-empresa"
        assert f.field_type == FieldType.TEXT
        assert f.label == "Nome da Empresa"
        assert f.id == "nome-empresa"
        assert f.required is True

    async def test_select_field_preserves_options(self):
        a = _attrs(tag="select", type_="", name="estado",
                   label="Estado", options=["SP", "RJ", "MG"])
        el = _make_element(attrs=a)
        page = _make_page(el)

        fields = await DOMCrawler(page).extract_fields()

        assert len(fields) == 1
        f = fields[0]
        assert f.field_type == FieldType.SELECT
        assert f.selector == 'select[name="estado"]'
        assert f.options == ["SP", "RJ", "MG"]

    async def test_radio_field_selector_includes_type(self):
        a = _attrs(type_="radio", name="pagamento", label="Forma de Pagamento")
        el = _make_element(attrs=a)
        page = _make_page(el)

        fields = await DOMCrawler(page).extract_fields()

        f = fields[0]
        assert f.selector == 'input[type="radio"][name="pagamento"]'
        assert f.field_type == FieldType.RADIO

    async def test_aria_labelledby_selector_for_spa_fields(self):
        a = _attrs(aria_labelledby="lbl-01", label="Campo SPA")
        el = _make_element(attrs=a)
        page = _make_page(el)

        fields = await DOMCrawler(page).extract_fields()

        assert fields[0].selector == '[aria-labelledby="lbl-01"]'

    async def test_empty_label_becomes_none(self):
        a = _attrs(id_="campo", label="")
        el = _make_element(attrs=a)
        page = _make_page(el)

        fields = await DOMCrawler(page).extract_fields()

        assert fields[0].label is None

    async def test_multiple_fields_all_extracted_in_order(self):
        elements = [
            _make_element(attrs=_attrs(id_="a", label="A")),
            _make_element(attrs=_attrs(id_="b", label="B")),
            _make_element(attrs=_attrs(id_="c", label="C")),
        ]
        page = _make_page(*elements)

        fields = await DOMCrawler(page).extract_fields()

        assert len(fields) == 3
        assert [f.id for f in fields] == ["a", "b", "c"]

    async def test_visible_and_invisible_mixed(self):
        elements = [
            _make_element(visible=True,  attrs=_attrs(id_="visivel-1")),
            _make_element(visible=False, attrs=_attrs(id_="oculto")),
            _make_element(visible=True,  attrs=_attrs(id_="visivel-2")),
        ]
        page = _make_page(*elements)

        fields = await DOMCrawler(page).extract_fields()

        assert len(fields) == 2
        assert fields[0].id == "visivel-1"
        assert fields[1].id == "visivel-2"

    async def test_iframe_selector_uses_frame_locator(self):
        a = _attrs(id_="campo-iframe")
        el = _make_element(attrs=a)

        inner_locator = MagicMock()
        inner_locator.count = AsyncMock(return_value=1)
        inner_locator.nth = MagicMock(return_value=el)

        frame = MagicMock()
        frame.locator = MagicMock(return_value=inner_locator)

        page = MagicMock()
        page.frame_locator = MagicMock(return_value=frame)

        fields = await DOMCrawler(page, iframe_selector="#meu-iframe").extract_fields()

        page.frame_locator.assert_called_once_with("#meu-iframe")
        page.locator.assert_not_called()
        assert len(fields) == 1
        assert fields[0].id == "campo-iframe"
