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

        # Dedupe radios e agrega labels de opções: vários <input type="radio">
        # com o mesmo `name` formam UM grupo e compartilham o mesmo seletor —
        # tratar como FormFields separados gera classificações redundantes
        # (ex: cada label "Materiais"/"Serviços" classificada isoladamente) e
        # logs duplicados em fill_page. Mantém o primeiro como representante
        # do grupo, agregando demais labels em `options`.
        radio_groups: dict[str, FormField] = {}
        for i in range(count):
            el = locator.nth(i)
            try:
                attrs = await el.evaluate(
                    r"""el => {
                        // Lê o texto de um elemento juntando seus text nodes com espaço.
                        // Em SPAs (ex: MS Forms) o título da pergunta e a dica de
                        // acessibilidade ("Texto de linha única") ficam em spans irmãos
                        // sem espaço entre eles; textContent puro os cola ("AgênciaTexto"),
                        // quebrando os word-boundaries da classificação heurística.
                        const readText = (node) => {
                            if (!node) return '';
                            const parts = [];
                            const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, null);
                            let n;
                            while ((n = walker.nextNode())) {
                                const t = n.textContent.trim();
                                if (t) parts.push(t);
                            }
                            return parts.join(' ').replace(/\s+/g, ' ').trim();
                        };
                        // Resolve label text via aria-labelledby (suporta múltiplos IDs separados por espaço)
                        const ariaLabelledby = el.getAttribute('aria-labelledby') || '';
                        let labelText = '';
                        if (ariaLabelledby) {
                            labelText = ariaLabelledby.trim().split(/\s+/)
                                .map(id => readText(document.getElementById(id)))
                                .filter(t => t)
                                .join(' ');
                        }
                        // Fallback: <label for="id"> explícito
                        if (!labelText && el.id) {
                            const lbl = document.querySelector('label[for="' + el.id + '"]');
                            if (lbl) labelText = readText(lbl);
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

                        // Label do GRUPO (radiogroup / fieldset) — mais informativo que
                        // o label da opção individual quando se quer classificar o que
                        // a pergunta está pedindo (ex: "Tipo de Fornecimento" em vez
                        // de "Materiais"). Usado para radios e para checkbox groups.
                        let groupLabel = '';
                        const t = (el.type || '').toLowerCase();
                        if (t === 'radio' || t === 'checkbox') {
                            const grp = el.closest('[role="radiogroup"], [role="group"], fieldset');
                            if (grp) {
                                const grpAria = grp.getAttribute('aria-labelledby') || '';
                                if (grpAria) {
                                    groupLabel = grpAria.trim().split(/\s+/)
                                        .map(id => readText(document.getElementById(id)))
                                        .filter(t => t)
                                        .join(' ');
                                }
                                if (!groupLabel) {
                                    const legend = grp.querySelector('legend');
                                    if (legend) groupLabel = readText(legend);
                                }
                                if (!groupLabel) {
                                    groupLabel = grp.getAttribute('aria-label') || '';
                                }
                            }
                        }

                        return {
                            tag: el.tagName.toLowerCase(),
                            type: t,
                            name: el.name || '',
                            id: el.id || '',
                            value: el.value || '',
                            placeholder: el.placeholder || '',
                            required: el.required || false,
                            label: labelText,
                            groupLabel: groupLabel,
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

            # Radio: agrega no grupo já visto em vez de criar FormField duplicado.
            # Todos os radios de um mesmo `name` compartilham o seletor de grupo,
            # então qualquer um deles é suficiente para preencher; só agrego
            # labels para enriquecer a classificação.
            if field_type == FieldType.RADIO:
                existing = radio_groups.get(selector)
                if existing is not None:
                    if attrs["label"] and attrs["label"] not in existing.options:
                        existing.options.append(attrs["label"])
                    continue
                group_label = attrs.get("groupLabel") or ""
                effective_label = group_label or attrs["label"]
                options_init = [attrs["label"]] if attrs["label"] else []
                radio_field = FormField(
                    tag=attrs["tag"],
                    field_type=field_type,
                    label=effective_label or None,
                    name=attrs["name"] or None,
                    id=attrs["id"] or None,
                    placeholder=attrs["placeholder"] or None,
                    required=bool(attrs["required"]),
                    selector=selector,
                    options=options_init,
                )
                radio_groups[selector] = radio_field
                fields.append(radio_field)
                continue

            # Checkbox em grupo de seleção múltipla: prefere o label do grupo
            # como contexto da classificação. Cada checkbox segue como FormField
            # próprio (seletor único via [value=...]) para que o FormFiller possa
            # marcar/desmarcar individualmente. Label efetivo combina grupo+opção
            # quando ambos existem, permitindo que o classificador veja a pergunta
            # ("Quais materiais sua empresa fornece?") junto da opção ("ROLAMENTOS").
            effective_label = attrs["label"] or None
            if field_type == FieldType.CHECKBOX:
                group_label = attrs.get("groupLabel") or ""
                if group_label and attrs["label"] and group_label != attrs["label"]:
                    effective_label = f"{group_label} — {attrs['label']}"
                elif group_label and not attrs["label"]:
                    effective_label = group_label

            fields.append(
                FormField(
                    tag=attrs["tag"],
                    field_type=field_type,
                    label=effective_label,
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
                        const readText = (node) => {
                            if (!node) return '';
                            const parts = [];
                            const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, null);
                            let n;
                            while ((n = walker.nextNode())) {
                                const t = n.textContent.trim();
                                if (t) parts.push(t);
                            }
                            return parts.join(' ').replace(/\s+/g, ' ').trim();
                        };
                        const ariaLabelledby = el.getAttribute('aria-labelledby') || '';
                        let labelText = '';
                        if (ariaLabelledby) {
                            labelText = ariaLabelledby.trim().split(/\s+/)
                                .map(id => readText(document.getElementById(id)))
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
