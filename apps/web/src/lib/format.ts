const TZ = "America/Sao_Paulo";

const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const int = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const dec1 = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const timeFmt = new Intl.DateTimeFormat("pt-BR", { timeZone: TZ, hour: "2-digit", minute: "2-digit" });
const timeSecFmt = new Intl.DateTimeFormat("pt-BR", { timeZone: TZ, hour: "2-digit", minute: "2-digit", second: "2-digit" });
const dateTimeFmt = new Intl.DateTimeFormat("pt-BR", { timeZone: TZ, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const dayFmt = new Intl.DateTimeFormat("pt-BR", { timeZone: TZ, weekday: "short", day: "2-digit", month: "2-digit" });

export const money = (cents: number | null | undefined) => (cents == null ? "—" : brl.format(cents / 100));
export const n0 = (v: number | null | undefined) => (v == null ? "—" : int.format(v));
export const n1 = (v: number | null | undefined) => (v == null ? "—" : dec1.format(v));
export const pct = (v: number | null | undefined, digits = 0) =>
  v == null ? "—" : `${new Intl.NumberFormat("pt-BR", { maximumFractionDigits: digits }).format(v * 100)}%`;
export const clock = (iso: string | null | undefined) => (iso ? timeFmt.format(new Date(iso)) : "—");
export const clockSec = (iso: string | null | undefined) => (iso ? timeSecFmt.format(new Date(iso)) : "—");
export const dateTime = (iso: string | null | undefined) => (iso ? dateTimeFmt.format(new Date(iso)) : "—");
export const day = (iso: string) => dayFmt.format(new Date(iso));

export function qty(value: number, unit: string): string {
  if (unit === "g" && Math.abs(value) >= 1000) return `${dec1.format(value / 1000)} kg`;
  if (unit === "ml" && Math.abs(value) >= 1000) return `${dec1.format(value / 1000)} L`;
  return `${int.format(value)} ${unit}`;
}

export function relative(iso: string, now = Date.now()): string {
  const diff = Math.round((new Date(iso).getTime() - now) / 1000);
  const abs = Math.abs(diff);
  const rtf = new Intl.RelativeTimeFormat("pt-BR", { numeric: "auto" });
  if (abs < 60) return rtf.format(diff, "second");
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  return rtf.format(Math.round(diff / 3600), "hour");
}

export const CHANNEL_LABEL: Record<string, string> = {
  app_delivery: "Delivery (app)",
  dine_in: "Salão",
  takeout: "Retirada",
};

export const ORDER_STATUS_LABEL: Record<string, string> = {
  received: "Em preparo",
  ready: "Pronto",
  rejected: "Perdido",
  cancelled: "Cancelado",
};

export const AGENT_LABEL: Record<string, string> = {
  orchestrator: "Orquestrador",
  operations: "Operations Agent",
  inventory: "Inventory Agent",
  forecasting: "Forecasting Agent",
};

export const ACTION_LABEL: Record<string, string> = {
  create_purchase_order: "Pedido de compra",
  pause_menu_item: "Pausa de item",
};

export function describeAudit(action: string): string {
  const map: Record<string, string> = {
    "sandbox.created": "Sandbox criado",
    "simulation.started": "Simulação iniciada",
    "simulation.paused": "Simulação pausada",
    "simulation.resumed": "Simulação retomada",
    "simulation.stopped": "Simulação encerrada",
    "simulation.completed": "Simulação concluída",
    "incident.opened": "Incidente detectado",
    "agent_run.requested": "Análise solicitada",
    "agent_run.started": "Agentes iniciaram análise",
    "agent_run.completed": "Agentes concluíram análise",
    "agent_run.failed": "Execução de agentes falhou",
    "approval.requested": "Aprovação solicitada",
    "approval.approved": "Aprovação concedida",
    "approval.rejected": "Aprovação rejeitada",
    "approval.expired": "Aprovação expirada",
    "action.executed": "Ação executada",
    "action.failed": "Ação falhou na revalidação",
    "menu_item.paused": "Item pausado",
    "menu_item.resumed": "Item reativado",
    "purchase_order.created": "Pedido de compra criado",
    "event.ingested": "Evento recebido via API",
    "event.requeued": "Evento reprocessado",
    "restaurant.seeded": "Restaurante criado (seed)",
  };
  return map[action] ?? action;
}
