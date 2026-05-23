from __future__ import annotations

import asyncio
from playwright.async_api import FrameLocator, Page

from domain.entities.form import FieldType, FormField

_FIELD_SELECTOR = (
    "input:not([type='hidden']):not([type='submit']):not([type='button']):not([type='image']),"
    "select,"
    "textarea"
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
                    """el => {
                        // Resolve label text: <label for="id">, parent <label>, aria-label, aria-labelledby
                        let labelText = '';
                        if (el.id) {
                            const lbl = document.querySelector('label[for="' + el.id + '"]');
                            if (lbl) labelText = lbl.textContent.trim();
                        }
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
                        if (!labelText) labelText = el.getAttribute('aria-label') || '';
                        if (!labelText) {
                            const lblId = el.getAttribute('aria-labelledby');
                            if (lblId) {
                                const lblEl = document.getElementById(lblId);
                                if (lblEl) labelText = lblEl.textContent.trim();
                            }
                        }
                        return {
                            tag: el.tagName.toLowerCase(),
                            type: (el.type || '').toLowerCase(),
                            name: el.name || '',
                            id: el.id || '',
                            placeholder: el.placeholder || '',
                            required: el.required || false,
                            label: labelText,
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
        if t:
            return f'{tag}[type="{t}"][name="{name}"]'
        return f'{tag}[name="{name}"]'
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
