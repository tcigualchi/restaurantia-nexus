"use client";

import {
  AlertTriangle,
  ArrowRight,
  Bot,
  ChefHat,
  ClipboardCheck,
  Flame,
  Loader2,
  PackageX,
  Play,
  ReceiptText,
  Timer,
  Wallet,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import useSWR from "swr";

import { OrdersQueueChart, StockChart } from "@/components/charts";
import { useApp } from "@/components/shell/app-context";
import {
  EmptyState,
  ErrorState,
  KpiCard,
  ModeBadge,
  PageHeader,
  PAUSE_REASON,
  RiskBadge,
  RunBadge,
  SimBadge,
  SyntheticNotice,
} from "@/components/status";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress, Skeleton } from "@/components/ui/misc";
import { apiPost } from "@/lib/api";
import { clock, clockSec, money, n0, n1, pct, qty } from "@/lib/format";
import type { Overview, Timeseries } from "@/lib/types";

const EVENT_LABEL: Record<string, string> = {
  "order.created": "Pedido recebido",
  "order.ready": "Pedido pronto",
  "order.cancelled": "Pedido cancelado",
  "inventory.received": "Estoque recebido",
  "inventory.adjusted": "Ajuste de estoque",
  "kitchen.capacity_changed": "Capacidade da cozinha alterada",
};

export function OverviewView() {
  const { rpath, can, live } = useApp();
  const { data, error, mutate } = useSWR<Overview>(rpath("/overview"));
  const { data: series } = useSWR<Timeseries>(rpath("/timeseries?bucket_minutes=5"));
  const [starting, setStarting] = useState(false);

  async function startFeatured() {
    const path = rpath("/simulation");
    if (!path) return;
    setStarting(true);
    try {
      await apiPost(path, { scenario_key: "rush_stockout", seed: 42 });
      toast.success("Cenário “Pico de pedidos + estoque crítico” iniciado (seed 42).");
      await mutate();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Falha ao iniciar a simulação.");
    } finally {
      setStarting(false);
    }
  }

  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!data) return <OverviewSkeleton />;
  const { kpis, simulation: sim } = data;
  const units = Object.fromEntries(data.ingredients_at_risk.map((r) => [r.ingredient_key, r.unit]));

  return (
    <>
      <PageHeader
        title={`Command Center — ${data.restaurant.name}`}
        description="Indicadores calculados a partir de pedidos e eventos persistidos; atualizados em tempo real via SSE."
        actions={
          can("simulation.control") && (
            <Button onClick={startFeatured} disabled={starting}>
              {starting ? <Loader2 className="animate-spin" /> : <Play />}
              {sim ? "Reiniciar cenário principal" : "Iniciar cenário principal"}
            </Button>
          )
        }
      />

      {sim ? (
        <Card className="mb-6 overflow-hidden">
          <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
            <div className="flex items-center gap-3">
              <span className="rounded bg-warning-soft px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-accent-foreground">
                Simulação
              </span>
              <div>
                <div className="text-sm font-medium">{sim.scenario_name}</div>
                <div className="text-xs text-muted-foreground">
                  seed {sim.seed} · relógio simulado {clock(sim.business_time)} · minuto {sim.current_tick}/{sim.total_ticks}
                </div>
              </div>
            </div>
            <div className="flex flex-1 items-center gap-3 sm:justify-end">
              <SimBadge status={sim.status} reason={sim.pause_reason} />
              {sim.pause_reason === "awaiting_approval" && (
                <Button asChild size="sm" variant="secondary">
                  <Link href="/approvals">
                    Revisar aprovações <ArrowRight />
                  </Link>
                </Button>
              )}
            </div>
          </div>
          <Progress value={(sim.current_tick / sim.total_ticks) * 100} label="Progresso da simulação" className="rounded-none" />
        </Card>
      ) : (
        <div className="mb-6">
          <EmptyState
            icon={<Play />}
            title="Nenhuma simulação neste restaurante"
            description="Inicie o cenário principal para gerar pedidos, consumo de estoque e incidentes analisados pelos agentes."
          />
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard label="Pedidos (60 min)" value={n0(kpis.orders_last_60)} hint={`${money(kpis.revenue_last_60_cents)} em receita`} icon={<ReceiptText />} />
        <KpiCard
          label="Fila da cozinha"
          value={n0(kpis.queue_length)}
          hint={kpis.oldest_open_minutes != null ? `mais antigo há ${n0(kpis.oldest_open_minutes)} min` : "sem pedidos em aberto"}
          icon={<ChefHat />}
          tone={kpis.queue_length >= 15 ? "warning" : "neutral"}
        />
        <KpiCard
          label="Preparo p90"
          value={kpis.p90_prep_minutes != null ? `${n1(kpis.p90_prep_minutes)} min` : "—"}
          hint={`SLA ${kpis.sla_minutes} min · ${pct(kpis.sla_breach_rate)} acima do SLA`}
          icon={<Timer />}
          tone={(kpis.p90_prep_minutes ?? 0) > kpis.sla_minutes ? "danger" : "neutral"}
        />
        <KpiCard
          label="Ingredientes em risco"
          value={n0(kpis.ingredients_at_risk)}
          hint="risco alto, crítico ou esgotado"
          icon={<Flame />}
          tone={kpis.ingredients_at_risk > 0 ? "warning" : "success"}
        />
        <KpiCard
          label="Pedidos perdidos"
          value={n0(kpis.lost_orders_total)}
          hint={`${money(kpis.lost_revenue_total_cents)} não faturados`}
          icon={<PackageX />}
          tone={kpis.lost_orders_total > 0 ? "danger" : "neutral"}
        />
        <KpiCard
          label="Aprovações pendentes"
          value={n0(kpis.pending_approvals)}
          hint={<Link className="underline underline-offset-2" href="/approvals">abrir Approval Center</Link>}
          icon={<ClipboardCheck />}
          tone={kpis.pending_approvals > 0 ? "warning" : "neutral"}
        />
        <KpiCard label="Receita total" value={money(kpis.revenue_total_cents)} hint={`${n0(kpis.orders_total)} pedidos no período`} icon={<Wallet />} />
        <KpiCard
          label="Incidentes abertos"
          value={n0(kpis.open_incidents)}
          hint={`${kpis.kitchen_lines_available}/${kpis.kitchen_lines} linhas de preparo ativas`}
          icon={<AlertTriangle />}
          tone={kpis.open_incidents > 0 ? "warning" : "neutral"}
        />
      </div>

      <div className="mt-6 grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Pedidos e fila (intervalos de 5 min)</CardTitle>
            <CardDescription>Barras: pedidos recebidos e perdidos por falta de insumo. Linha: pedidos em preparo.</CardDescription>
          </CardHeader>
          <CardContent>{series && series.points.length > 0 ? <OrdersQueueChart data={series} /> : <Skeleton className="h-64" />}</CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Estoque dos ingredientes mais críticos</CardTitle>
            <CardDescription>Reconstruído a partir das movimentações de estoque (consumo e recebimentos).</CardDescription>
          </CardHeader>
          <CardContent>
            {series && Object.keys(series.ingredients).length > 0 ? (
              <StockChart data={series} units={units} />
            ) : (
              <Skeleton className="h-64" />
            )}
          </CardContent>
        </Card>
      </div>

      <div className="mt-6 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-1">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bot className="size-4 text-primary" /> Última análise dos agentes
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {data.latest_agent_run ? (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <RunBadge status={data.latest_agent_run.status} />
                  <ModeBadge mode={data.latest_agent_run.mode} model={data.latest_agent_run.model} />
                </div>
                <p className="text-sm leading-relaxed">{data.latest_agent_run.summary ?? "Análise em andamento…"}</p>
                <Button asChild variant="outline" size="sm">
                  <Link href={`/control-room?run=${data.latest_agent_run.id}`}>
                    Ver trace completo <ArrowRight />
                  </Link>
                </Button>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">Nenhuma análise ainda. Os agentes são acionados quando um detector abre um incidente.</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Ingredientes em risco</CardTitle>
            <CardDescription>Tempo até ruptura pelo consumo dos últimos 15 min.</CardDescription>
          </CardHeader>
          <CardContent>
            {data.ingredients_at_risk.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nenhum ingrediente em risco alto.</p>
            ) : (
              <ul className="space-y-2">
                {data.ingredients_at_risk.map((r) => (
                  <li key={r.ingredient_key} className="flex items-center justify-between gap-2 text-sm">
                    <div>
                      <div className="font-medium">{r.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {qty(r.stock, r.unit)} · {qty(r.consumption_per_hour, r.unit)}/h · ruptura em {r.eta_minutes != null ? `~${n0(r.eta_minutes)} min` : "—"}
                      </div>
                    </div>
                    <RiskBadge risk={r.risk} />
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              Eventos ao vivo
              <span className="text-[11px] font-normal text-muted-foreground">{live.connected ? "conectado" : "reconectando…"}</span>
            </CardTitle>
          </CardHeader>
          <CardContent>
            {live.events.length === 0 ? (
              <p className="text-sm text-muted-foreground">Aguardando eventos…</p>
            ) : (
              <ol className="max-h-72 space-y-1.5 overflow-y-auto pr-1 text-xs" aria-live="polite">
                {live.events.slice(0, 30).map((e) => (
                  <li key={e.id} className="flex items-center gap-2">
                    <span className="font-mono text-muted-foreground tabular-nums">{clockSec(e.occurred_at)}</span>
                    <span className="flex-1 truncate">
                      {EVENT_LABEL[e.type] ?? e.type}
                      {e.order_ref ? ` · ${e.order_ref}` : ""}
                    </span>
                    {e.outcome?.startsWith("rejected") && <span className="text-danger">perdido</span>}
                  </li>
                ))}
              </ol>
            )}
            {live.status?.simulation?.pause_reason && (
              <p className="mt-3 text-xs text-muted-foreground">
                Simulação pausada: {PAUSE_REASON[live.status.simulation.pause_reason] ?? live.status.simulation.pause_reason}.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
      <SyntheticNotice className="mt-6" />
    </>
  );
}

function OverviewSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Carregando">
      <Skeleton className="h-10 w-72" />
      <Skeleton className="h-20" />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-28" />
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Skeleton className="h-80" />
        <Skeleton className="h-80" />
      </div>
    </div>
  );
}
