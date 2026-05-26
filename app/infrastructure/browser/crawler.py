from __future__ import annotations

import asyncio
from playwright.async_api import FrameLocator, Page

from domain.entities.form import FieldType, FormField

_FIELD_SELECTOR = (
    "input:not([type='hidden']):not([type='submit']):not([type='button']):not([type='image']),"
    "select,"
    "textarea"
)

# Seletores para dropdowns customizados (React/SPA) — captura dois padrões:
# 1. role="combobox" (padrão ARIA combobox)
# 2. role="button" + aria-haspopup="listbox" (padrão MS Forms — trigger de listbox)
_COMBOBOX_SELECTOR = (
    "[role='combobox']:not(input),"
    "[role='button'][aria-haspopup='listbox']"
)


class DOMCrawler:
    """Extrai FormField a partir do DOM da página atual."""

    def __init__(self, page: Page, iframe_selector: str | None = None) -> None:
        self._page = page
        self._iframe_selector = iframe_selector

    async def extract_fields(self) -> list[FormField]:
        root: Page | FrameLocator = (
            self._page.frame_locator(self._iframe_selector)
            if self._iframe_selector
            else self._page
        )
        locator = root.locator(_FIELD_SELECTOR)
        count = await locator.count()
        fields: list[FormField] = []

        for i in range(count):
            el = locator.nth(i)
            try:
                attrs = await el.evaluate(
                    r"""el => {
                        // Resolve label text via aria-labelledby (suporta múltiplos IDs separados por espaço)
                        const ariaLabelledby = el.getAttribute('aria-labelledby') || '';
                        let labelText = '';
                        if (ariaLabelledby) {
                            labelText = ariaLabelledby.trim().split(/\s+/)
                                .map(id => {
                                    const el2 = document.getElementById(id);
                                    return el2 ? el2.textContent.trim() : '';
                                })
                                .filter(t => t)
                                .join(' ');
                        }
                        // Fallback: <label for="id"> explícito
                        if (!labelText && el.id) {
                            const lbl = document.querySelector('label[for="' + el.id + '"]');
                            if (lbl) labelText = lbl.textContent.trim();
                        }
                        // Fallback: elemento <label> pai
                        if (!labelText) {
                            const parent = el.closest('label');
                            if (parent) {
                                labelText = Array.from(parent.childNodes)
                                    .filter(n => n.nodeType === Node.TEXT_NODE)
                                    .map(n => n.textContent.trim())
                                    .filter(t => t)
                                    .join(' ');
                            }
                        }
                        // Fallback: aria-label (pode ser genérico como "Single line text")
                        if (!labelText) labelText = el.getAttribute('aria-label') || '';
                        return {
                            tag: el.tagName.toLowerCase(),
                            type: (el.type || '').toLowerCase(),
                            name: el.name || '',
                            id: el.id || '',
                            value: el.value || '',
                            placeholder: el.placeholder || '',
                            required: el.required || false,
                            label: labelText,
                            ariaLabelledby: ariaLabelledby,
                            options: el.tagName === 'SELECT'
                                ? Array.from(el.options)
                                    .map(o => o.text.trim())
                                    .filter(v => v)
                                : [],
                        };
                    }"""
                )
            except Exception:
                continue

            # <select> pode estar oculto por CSS em SPAs que usam componente custom
            # por cima do native select — inclui mesmo sem visibilidade.
            if attrs["tag"] != "select" and not await el.is_visible():
                continue

            field_type = _map_field_type(attrs["tag"], attrs["type"])
            selector = _build_selector(attrs)
            if not selector:
                continue

            fields.append(
                FormField(
                    tag=attrs["tag"],
                    field_type=field_type,
                    label=attrs["label"] or None,
                    name=attrs["name"] or None,
                    id=attrs["id"] or None,
                    placeholder=attrs["placeholder"] or None,
                    required=bool(attrs["required"]),
                    selector=selector,
                    options=attrs["options"],
                )
            )

        # ── Comboboxes React/SPA (role="combobox", não native <select>) ─────────
        # MS Forms usa isso para questões de Dropdown que não rendem <select>.
        seen_selectors = {f.selector for f in fields}
        cb_locator = root.locator(_COMBOBOX_SELECTOR)
        cb_count = await cb_locator.count()
        for i in range(cb_count):
            el = cb_locator.nth(i)
            try:
                if not await el.is_visible():
                    continue
                attrs = await el.evaluate(
                    r"""el => {
                        const ariaLabelledby = el.getAttribute('aria-labelledby') || '';
                        let labelText = '';
                        if (ariaLabelledby) {
                            labelText = ariaLabelledby.trim().split(/\s+/)
                                .map(id => {
                                    const el2 = document.getElementById(id);
                                    return el2 ? el2.textContent.trim() : '';
                                })
                                .filter(t => t)
                                .join(' ');
                        }
                        if (!labelText) labelText = el.getAttribute('aria-label') || '';
                        return {
                            tag: el.tagName.toLowerCase(),
                            id: el.id || '',
                            name: el.getAttribute('name') || '',
                            label: labelText,
                            ariaLabelledby: ariaLabelledby,
                            placeholder: el.getAttribute('placeholder') || '',
                        };
                    }"""
                )
            except Exception:
                continue

            selector = (
                f"#{attrs['id']}" if attrs["id"]
                else f'[aria-labelledby="{attrs["ariaLabelledby"]}"]' if attrs["ariaLabelledby"]
                else None
            )
            if not selector or selector in seen_selectors:
                continue
            seen_selectors.add(selector)
            fields.append(
                FormField(
                    tag=attrs["tag"],
                    field_type=FieldType.COMBOBOX,
                    label=attrs["label"] or None,
                    name=attrs["name"] or None,
                    id=attrs["id"] or None,
                    placeholder=attrs["placeholder"] or None,
                    selector=selector,
                )
            )

        return fields


def _map_field_type(tag: str, input_type: str) -> FieldType:
    if tag == "select":
        return FieldType.SELECT
    if tag == "textarea":
        return FieldType.TEXTAREA
    return {
        "email":    FieldType.EMAIL,
        "tel":      FieldType.TEL,
        "number":   FieldType.NUMBER,
        "checkbox": FieldType.CHECKBOX,
        "radio":    FieldType.RADIO,
        "file":     FieldType.FILE,
        "date":     FieldType.TEXT,
    }.get(input_type, FieldType.TEXT)


def _build_selector(attrs: dict) -> str | None:
    if attrs["id"]:
        return f"#{attrs['id']}"
    if attrs["name"]:
        tag = attrs["tag"]
        name = attrs["name"]
        t = attrs["type"]
        # Checkbox: inclui [value] para diferenciar cada opção do mesmo grupo.
        # Sem isso, o seletor de grupo resolve múltiplos elementos → strict mode.
        if t == "checkbox" and attrs.get("value"):
            v = attrs["value"].replace('"', '\\"')
            return f'{tag}[type="{t}"][name="{name}"][value="{v}"]'
        if t:
            return f'{tag}[type="{t}"][name="{name}"]'
        return f'{tag}[name="{name}"]'
    # Fallback para formulários SPA (ex: Microsoft Forms) que não usam id/name
    if attrs.get("ariaLabelledby"):
        return f'[aria-labelledby="{attrs["ariaLabelledby"]}"]'
    return None


# ------------------------------------------------------------------
# Script de diagnóstico — executar diretamente, nunca em import
# ------------------------------------------------------------------

async def _test_conexao(url: str, portal: str) -> None:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle")
        await page.screenshot(path=f"{portal}_inicial.png")
        crawler = DOMCrawler(page)
        fields = await crawler.extract_fields()
        print(f"Campos encontrados: {len(fields)}")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(_test_conexao(
        url="https://forms.office.com/pages/responsepage.aspx?id=fksHnnCQs0inUeM698H4-1cQwu8TX79CrqJ-qCil_whUQ1BGNkZLUDNPNTZLSk5TUkYwTUlCV1hBSS4u&origin=lprLink&route=shorturl",
        portal="anglo-gold-ashanti",
    ))
