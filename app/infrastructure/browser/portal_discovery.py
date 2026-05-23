"""
infrastructure/browser/portal_discovery.py

PortalDiscovery — localiza e navega até o formulário a partir de uma
página de portal. O sistema NÃO recebe o link direto do formulário,
mas sim a URL pública do portal do fornecedor.

Pipeline de descoberta (em ordem de prioridade):
  1. Iframe com plataforma conhecida já embutido na página
  2. Link direto para plataforma conhecida (mesma aba ou nova aba)
  3. Botão/link com texto associado a acesso de formulário → clica e observa
  4. Fallback: retorna a página atual como está

Plataformas conhecidas: Microsoft Forms, Google Forms, Typeform, JotForm,
SurveyMonkey, Cognito Forms.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog
from playwright.async_api import Page

logger = structlog.get_logger(__name__)

# Plataformas de formulário cujos domínios identificamos automaticamente
_KNOWN_PLATFORMS = [
    "forms.office.com",
    "forms.microsoft.com",
    "forms.google.com",
    "docs.google.com/forms",
    "typeform.com",
    "jotform.com",
    "surveymonkey.com",
    "cognitoforms.com",
    "123formbuilder.com",
]

# Seletores de botões/links que tipicamente levam ao formulário —
# tentados em ordem, do mais específico ao mais genérico
_FORM_ENTRY_SELECTORS = [
    # Links com texto explícito de formulário
    'a:has-text("Acessar formulário")',
    'a:has-text("Acessar Formulário")',
    'a:has-text("Preencher formulário")',
    'a:has-text("Cadastrar fornecedor")',
    'a:has-text("Cadastro de fornecedor")',
    'a:has-text("Cadastro")',
    'a:has-text("Iniciar cadastro")',
    'a:has-text("Formulário")',
    # Botões com texto de início
    'button:has-text("Iniciar")',
    'button:has-text("Começar")',
    'button:has-text("Acessar")',
    'button:has-text("Preencher")',
    'button:has-text("Cadastrar")',
    'button:has-text("Enviar documentos")',
    # Elementos com role
    '[role="button"]:has-text("Iniciar")',
    '[role="button"]:has-text("Acessar")',
    '[role="link"]:has-text("Formulário")',
    # Links genéricos com href de plataforma (redundante com strategy 2, mas como fallback)
    'a[href*="forms.office.com"]',
    'a[href*="forms.google.com"]',
    'a[href*="typeform.com"]',
    'a[href*="jotform.com"]',
]

# Tempo máximo (ms) para aguardar navegação após clique
_NAV_TIMEOUT = 15_000
# Tempo (ms) para detectar abertura de nova aba após clique
_NEW_TAB_TIMEOUT = 3_000


@dataclass
class DiscoveryResult:
    """Resultado da descoberta: página e seletor de iframe (se houver)."""
    page: Page
    iframe_selector: str | None = None
    form_url: str = ""
    strategy: str = "fallback"


class PortalDiscovery:
    """
    Localiza o formulário a partir da página pública do portal.

    Uso:
        discovery = PortalDiscovery(page)
        result = await discovery.find_and_navigate()
        # result.page    → página onde o formulário está
        # result.iframe_selector → seletor do iframe, ou None
    """

    def __init__(self, page: Page, nav_timeout: int = _NAV_TIMEOUT) -> None:
        self._page = page
        self._nav_timeout = nav_timeout

    async def find_and_navigate(self) -> DiscoveryResult:
        # 1. Iframe de plataforma conhecida já presente
        result = await self._check_embedded_iframe(self._page)
        if result:
            logger.info("portal_discovery", strategy=result.strategy, url=result.form_url)
            return result

        # 2. Link direto para plataforma conhecida
        result = await self._follow_platform_link()
        if result:
            logger.info("portal_discovery", strategy=result.strategy, url=result.form_url)
            return result

        # 3. Botão/link com texto de acesso ao formulário
        result = await self._click_form_entry()
        if result:
            logger.info("portal_discovery", strategy=result.strategy, url=result.form_url)
            return result

        # Fallback: usa página atual como está
        logger.warning("portal_discovery_fallback", url=self._page.url)
        return DiscoveryResult(page=self._page, form_url=self._page.url, strategy="fallback")

    # ------------------------------------------------------------------
    # Estratégias
    # ------------------------------------------------------------------

    async def _check_embedded_iframe(self, page: Page) -> DiscoveryResult | None:
        """Verifica se um iframe de plataforma conhecida já está na página."""
        for platform in _KNOWN_PLATFORMS:
            sel = f'iframe[src*="{platform}"]'
            try:
                if await page.locator(sel).count() > 0:
                    src = await page.locator(sel).first.get_attribute("src") or ""
                    return DiscoveryResult(
                        page=page,
                        iframe_selector=sel,
                        form_url=src,
                        strategy="iframe_present",
                    )
            except Exception:
                continue
        return None

    async def _follow_platform_link(self) -> DiscoveryResult | None:
        """Encontra link href direto para plataforma conhecida e navega."""
        for platform in _KNOWN_PLATFORMS:
            sel = f'a[href*="{platform}"]'
            locator = self._page.locator(sel)
            try:
                if await locator.count() == 0:
                    continue
                link = locator.first
                new_page = await self._click_and_detect_new_tab(link)
                target = new_page or self._page
                await self._wait_for_load(target)
                iframe_sel = await self._detect_iframe_selector(target)
                strategy = "platform_link_new_tab" if new_page else "platform_link_same_tab"
                return DiscoveryResult(
                    page=target,
                    iframe_selector=iframe_sel,
                    form_url=target.url,
                    strategy=strategy,
                )
            except Exception as exc:
                logger.debug("portal_discovery_platform_link_failed", platform=platform, error=str(exc))
                continue
        return None

    async def _click_form_entry(self) -> DiscoveryResult | None:
        """Tenta clicar em botões/links com texto de acesso ao formulário."""
        for sel in _FORM_ENTRY_SELECTORS:
            locator = self._page.locator(sel)
            try:
                if await locator.count() == 0:
                    continue
                btn = locator.first
                if not await btn.is_visible():
                    continue

                logger.debug("portal_discovery_trying_entry", selector=sel)
                new_page = await self._click_and_detect_new_tab(btn)
                target = new_page or self._page
                await self._wait_for_load(target)
                iframe_sel = await self._detect_iframe_selector(target)
                strategy = "button_new_tab" if new_page else "button_same_tab"
                return DiscoveryResult(
                    page=target,
                    iframe_selector=iframe_sel,
                    form_url=target.url,
                    strategy=strategy,
                )
            except Exception as exc:
                logger.debug("portal_discovery_entry_failed", selector=sel, error=str(exc))
                continue
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _click_and_detect_new_tab(self, locator) -> Page | None:
        """
        Clica no elemento e retorna a nova Page se uma nova aba for aberta,
        ou None se a navegação ocorreu na aba atual.
        """
        try:
            async with self._page.context.expect_page(timeout=_NEW_TAB_TIMEOUT) as page_info:
                await locator.click()
            return await page_info.value
        except Exception:
            # Nenhuma nova aba — clique causou navegação na aba atual (ou nada)
            return None

    async def _wait_for_load(self, page: Page) -> None:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=self._nav_timeout)
        except Exception:
            pass

    @staticmethod
    async def _detect_iframe_selector(page: Page) -> str | None:
        """Verifica se a página destino contém iframe de plataforma conhecida."""
        for platform in _KNOWN_PLATFORMS:
            sel = f'iframe[src*="{platform}"]'
            try:
                if await page.locator(sel).count() > 0:
                    return sel
            except Exception:
                continue
        return None
