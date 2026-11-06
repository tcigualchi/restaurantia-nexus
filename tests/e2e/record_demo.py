"""Records a silent walkthrough of the featured scenario with Python Playwright.

Usage:
    python tests/e2e/record_demo.py <output-dir> [base-url]

The base URL defaults to http://localhost:3000 (stack started with docker compose or locally).
Playwright saves the video as a .webm file inside <output-dir>.
"""

import sys

from playwright.sync_api import Page, sync_playwright

OUT = sys.argv[1]
BASE = sys.argv[2].rstrip("/") if len(sys.argv) > 2 else "http://localhost:3000"
SIZE = {"width": 1280, "height": 800}


def wait(page: Page, ms: int) -> None:
    page.wait_for_timeout(ms)


def go(page: Page, link: str, ms: int = 3000) -> None:
    page.get_by_role("link", name=link).first.click()
    wait(page, ms)


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(
        viewport=SIZE,
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
        color_scheme="light",
        record_video_dir=OUT,
        record_video_size=SIZE,
    )
    page = ctx.new_page()

    page.goto(BASE + "/")
    wait(page, 3500)
    page.get_by_role("button", name="Entrar no modo demo").click()
    page.wait_for_url("**/overview")
    wait(page, 3000)

    # Start the featured scenario at the fastest speed and wait for the first decision point.
    go(page, "Simulação", 2500)
    page.get_by_label("Velocidade").select_option("400")
    wait(page, 800)
    page.get_by_role("button", name="Iniciar (zera os dados)").click()
    wait(page, 2500)
    page.get_by_role("link", name="Visão geral").first.click()
    page.get_by_text("aguardando aprovação do gerente").first.wait_for(timeout=90_000)
    wait(page, 3500)

    # What the agents did, step by step.
    go(page, "Agentes", 3500)
    page.mouse.wheel(0, 700)
    wait(page, 2500)
    page.mouse.wheel(0, 900)
    wait(page, 2500)
    page.get_by_text("Resultado da ferramenta").nth(2).click()
    wait(page, 3000)
    page.mouse.wheel(0, 600)
    wait(page, 2500)

    # The manager approves the purchase, rejects one pause with a reason and approves the other.
    go(page, "Aprovações", 3500)
    cards = page.locator(".rounded-xl").filter(has=page.get_by_role("button", name="Aprovar"))
    cards.filter(has_text="Pedido de compra emergencial").first.get_by_role("button", name="Aprovar").click()
    wait(page, 2500)
    cards.filter(has_text="Burger de Costela").first.get_by_role("button", name="Rejeitar").click()
    wait(page, 1200)
    page.get_by_role("dialog").get_by_label("Motivo (obrigatório, fica registrado na auditoria)").type(
        "Carro-chefe da casa, prefiro manter no cardápio.", delay=35
    )
    wait(page, 800)
    page.get_by_role("button", name="Confirmar rejeição").click()
    wait(page, 2500)
    cards.filter(has_text="Pastel de Costela").first.get_by_role("button", name="Aprovar").click()
    wait(page, 2500)
    page.get_by_role("tab", name="Histórico").click()
    wait(page, 3000)

    # Effects of the decisions: stock on the way, the rest of the peak and the audit trail.
    go(page, "Estoque", 4000)
    go(page, "Visão geral", 22_000)
    go(page, "Auditoria", 4000)
    go(page, "Previsão", 4000)
    go(page, "Simulação", 1500)
    page.get_by_role("button", name="Reiniciar").click()
    wait(page, 3500)

    ctx.close()
    browser.close()

print("recorded")
