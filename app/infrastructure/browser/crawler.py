import asyncio
from playwright.async_api import async_playwright

async def test_conexao(url: str, portal: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        await page.goto(url, wait_until="networkidle")
        await page.screenshot(path=f"{portal}_inicial.png")
        print(f"Screenshot salvo: {portal}_inicial.png")
        
        iframe_locator = page.frame_locator('iframe[src*="forms.office.com"]')
        count = await iframe_locator.locator("input, select, textarea").count()
        print(f"Campos encontrados no iframe: {count}")

        botao = page.get_by_role("button", name="Iniciar")
        await botao.click()
        await page.wait_for_load_state("networkidle")
        await page.screenshot(path=f"{portal}_formulario.png")

        count = await page.locator("input, select, textarea").count()
        print(f"Campos encontrados após iniciar: {count}")

        await browser.close()

asyncio.run(test_conexao(
    url="https://forms.office.com/pages/responsepage.aspx?id=fksHnnCQs0inUeM698H4-1cQwu8TX79CrqJ-qCil_whUQ1BGNkZLUDNPNTZLSk5TUkYwTUlCV1hBSS4u&origin=lprLink&route=shorturl",
    portal="anglo-gold-ashanti"
))