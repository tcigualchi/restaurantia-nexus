"""Records a silent walkthrough video of the featured scenario (Python Playwright).

Usage: python tests/e2e/record_demo.py <output-dir>   # stack running at http://localhost:3000
"""

import sys, time
from playwright.sync_api import sync_playwright
OUT = sys.argv[1]
BASE = "http://localhost:3000"
def pause(page, ms): page.wait_for_timeout(ms)
with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, locale="pt-BR", timezone_id="America/Sao_Paulo",
                              color_scheme="light", record_video_dir=OUT, record_video_size={"width": 1280, "height": 800})
    page = ctx.new_page()
    page.goto(BASE + "/"); pause(page, 3500)
    page.get_by_role("button", name="Entrar no modo demo").click(); page.wait_for_url("**/overview"); pause(page, 3000)
    page.get_by_role("link", name="Simulation Lab").first.click(); pause(page, 2500)
    page.get_by_label("Velocidade").select_option("400"); pause(page, 800)
    page.get_by_role("button", name="Iniciar (reinicia o sandbox)").click(); pause(page, 2500)
    page.get_by_role("link", name="Overview").first.click()
    page.get_by_text("aguardando decisão humana").first.wait_for(timeout=90000); pause(page, 3500)
    page.get_by_role("link", name="AI Control Room").first.click(); pause(page, 3500)
    page.mouse.wheel(0, 700); pause(page, 2500)
    page.mouse.wheel(0, 900); pause(page, 2500)
    page.get_by_text("Resultado da ferramenta").nth(2).click(); pause(page, 3000)
    page.mouse.wheel(0, 600); pause(page, 2500)
    page.get_by_role("link", name="Approval Center").first.click(); pause(page, 3500)
    cards = page.locator(".rounded-xl").filter(has=page.get_by_role("button", name="Aprovar"))
    cards.filter(has_text="Pedido de compra emergencial").first.get_by_role("button", name="Aprovar").click(); pause(page, 2500)
    cards.filter(has_text="Burger de Costela").first.get_by_role("button", name="Rejeitar").click(); pause(page, 1200)
    page.get_by_role("dialog").get_by_label("Justificativa (obrigatória, registrada na auditoria)").type("Carro-chefe da casa: manter no cardápio.", delay=35)
    pause(page, 800); page.get_by_role("button", name="Confirmar rejeição").click(); pause(page, 2500)
    cards.filter(has_text="Pastel de Costela").first.get_by_role("button", name="Aprovar").click(); pause(page, 2500)
    page.get_by_role("tab", name="Histórico").click(); pause(page, 3000)
    page.get_by_role("link", name="Estoque").first.click(); pause(page, 4000)
    page.get_by_role("link", name="Overview").first.click(); pause(page, 22000)
    page.get_by_role("link", name="Audit Log").first.click(); pause(page, 4000)
    page.get_by_role("link", name="Forecasting").first.click(); pause(page, 4000)
    page.get_by_role("link", name="Simulation Lab").first.click(); pause(page, 1500)
    page.get_by_role("button", name="Reiniciar").click(); pause(page, 3500)
    ctx.close(); browser.close()
print("recorded")
