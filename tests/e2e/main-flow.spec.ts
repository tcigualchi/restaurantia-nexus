import { expect, test, type Page } from "@playwright/test";

async function enterDemo(page: Page, persona: "Gerente" | "Operador" = "Gerente") {
  await page.goto("/");
  await page.getByRole("radio", { name: new RegExp(persona) }).check();
  await page.getByRole("button", { name: "Entrar no modo demo" }).click();
  await expect(page).toHaveURL(/\/overview/);
  await expect(page.getByRole("heading", { name: "Visão geral", exact: true })).toBeVisible();
}

async function startFeaturedScenario(page: Page) {
  await page.getByRole("link", { name: "Simulação" }).first().click();
  await expect(page.getByRole("heading", { name: "Simulação", exact: true })).toBeVisible();
  await page.getByRole("radio", { name: /Pico de pedidos \+ estoque crítico/ }).click();
  await page.getByLabel("Velocidade").selectOption("400");
  await page.getByRole("button", { name: /Iniciar \(zera os dados\)/ }).click();
  await expect(page.getByText("Simulação iniciada.")).toBeVisible();
}

test("cenário principal: pico + estoque crítico → agentes → aprovação humana → auditoria", async ({ page }) => {
  await enterDemo(page);
  await startFeaturedScenario(page);

  // The detectors open an incident, agents analyse it and the clock pauses for a human decision.
  await expect(page.getByText("aguardando aprovação do gerente").first()).toBeVisible({ timeout: 60_000 });

  await page.getByRole("link", { name: "Aprovações" }).first().click();
  const cards = page.locator("[data-slot=approval-card], .rounded-xl").filter({ has: page.getByRole("button", { name: "Aprovar" }) });
  await expect(cards.first()).toBeVisible();
  expect(await cards.count()).toBeGreaterThanOrEqual(2);

  // Approve the emergency purchase order.
  const po = cards.filter({ hasText: "Pedido de compra emergencial" }).first();
  await po.getByRole("button", { name: "Aprovar" }).click();
  await expect(page.getByText(/Pedido de compra registrado/)).toBeVisible();

  // Reject one menu pause with a justification (required).
  const burger = cards.filter({ hasText: "Burger de Costela" }).first();
  await burger.getByRole("button", { name: "Rejeitar" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("button", { name: "Confirmar rejeição" })).toBeDisabled();
  await dialog.getByLabel(/Motivo/).fill("Carro-chefe da casa: manter no cardápio.");
  await dialog.getByRole("button", { name: "Confirmar rejeição" }).click();
  await expect(page.getByText(/Ação rejeitada/)).toBeVisible();

  // Approve the remaining pause (Pastel), if still pending.
  const pastel = cards.filter({ hasText: "Pastel de Costela" }).first();
  if (await pastel.isVisible()) {
    await pastel.getByRole("button", { name: "Aprovar" }).click();
    await expect(page.getByText(/pausado no cardápio/)).toBeVisible();
  }

  await page.getByRole("tab", { name: "Histórico" }).click();
  await expect(page.getByText("Executada").first()).toBeVisible();
  await expect(page.getByText("Rejeitada").first()).toBeVisible();

  // The trace shows typed tool calls and the neutralised prompt-injection attempt.
  await page.getByRole("link", { name: "Agentes" }).first().click();
  await expect(page.getByText("get_inventory_status").first()).toBeVisible();
  await expect(page.getByText(/Tentativa de prompt injection/).first()).toBeVisible();

  // Inventory reflects the approved purchase order; audit log records every decision.
  await page.getByRole("link", { name: "Estoque" }).first().click();
  await expect(page.getByText("A caminho").or(page.getByText("Recebido")).first()).toBeVisible();
  await page.getByRole("link", { name: "Auditoria" }).first().click();
  await expect(page.getByText("Aprovação concedida").first()).toBeVisible();
  await expect(page.getByText("Aprovação rejeitada").first()).toBeVisible();
  await expect(page.getByText("Pedido de compra criado").first()).toBeVisible();

  // Deterministic reset.
  await page.getByRole("link", { name: "Simulação" }).first().click();
  await page.getByRole("button", { name: "Reiniciar" }).click();
  await expect(page.getByText("Simulação reiniciada com a mesma seed.")).toBeVisible();
  await expect(page.getByText(/minuto [0-9] de 120/)).toBeVisible();
});

test("RBAC: persona operador não consegue aprovar", async ({ page }) => {
  await enterDemo(page, "Operador");
  await startFeaturedScenario(page);
  await expect(page.getByText("aguardando aprovação do gerente").first()).toBeVisible({ timeout: 60_000 });
  await page.getByRole("link", { name: "Aprovações" }).first().click();
  await expect(page.getByText(/decidir exige o papel de gerente/)).toBeVisible();
  const approve = page.getByRole("button", { name: "Aprovar" }).first();
  await expect(approve).toBeDisabled();
});

test("layout mobile funcional @mobile", async ({ page }) => {
  await enterDemo(page);
  await page.getByRole("button", { name: "Abrir menu" }).click();
  await page.getByRole("link", { name: "Aprovações" }).click();
  await expect(page.getByRole("heading", { name: "Aprovações", exact: true })).toBeVisible();
});
