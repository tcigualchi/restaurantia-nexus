"use client";

import { CircleStop, FastForward, Pause, Play, RotateCcw, StepForward } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import useSWR from "swr";

import { useApp } from "@/components/shell/app-context";
import { EmptyState, ErrorState, PageHeader, SimBadge, SyntheticNotice } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/input";
import { Progress, Skeleton } from "@/components/ui/misc";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { Tooltip } from "@/components/ui/tooltip";
import { ApiError, apiPost } from "@/lib/api";
import { clock, clockSec, money, n0 } from "@/lib/format";
import type { EventView, Overview, ScenarioView, Simulation } from "@/lib/types";
import { cn } from "@/lib/utils";

const SPEEDS = [
  { ms: 400, label: "Rápida (0,4 s por minuto simulado)" },
  { ms: 1000, label: "Normal (1 s por minuto simulado)" },
  { ms: 2000, label: "Lenta (2 s por minuto simulado)" },
];

const EVENT_TYPES = ["order.created", "order.ready", "inventory.received", "kitchen.capacity_changed"];

export function SimulationView() {
  const { rpath, can } = useApp();
  const { data: scenarios } = useSWR<ScenarioView[]>("v1/scenarios");
  const { data: simData, mutate: mutateSim } = useSWR<{ simulation: Simulation | null }>(rpath("/simulation"));
  const { data: overview } = useSWR<Overview>(rpath("/overview"));
  const [scenario, setScenario] = useState("rush_stockout");
  const [seed, setSeed] = useState(42);
  const [speed, setSpeed] = useState(1000);
  const [autoPause, setAutoPause] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const qs = new URLSearchParams({ limit: "100" });
  if (typeFilter) qs.set("type", typeFilter);
  if (statusFilter) qs.set("status", statusFilter);
  const { data: events, error: eventsError } = useSWR<EventView[]>(rpath(`/events?${qs.toString()}`));
  const sim = simData?.simulation ?? null;
  const allowed = can("simulation.control");

  async function act(label: string, path: string, body?: unknown, success?: string) {
    const full = rpath(path);
    if (!full) return;
    setBusy(label);
    try {
      await apiPost(full, body);
      if (success) toast.success(success);
      await mutateSim();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Operação não concluída.");
    } finally {
      setBusy(null);
    }
  }

  const running = sim?.status === "running";
  const paused = sim?.status === "paused";
  const blocked = paused && (sim?.pause_reason === "agents_running" || sim?.pause_reason === "awaiting_approval");

  return (
    <>
      <PageHeader
        title="Simulação"
        description="Escolha um cenário e acompanhe a operação minuto a minuto. Com a mesma seed, os eventos se repetem exatamente. Cada início zera os dados deste restaurante."
      />
      {!allowed && (
        <p className="mb-4 rounded-md bg-info-soft px-3 py-2 text-sm text-info">Seu papel permite apenas visualizar a simulação.</p>
      )}
      <div className="grid gap-4 xl:grid-cols-[1.2fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Cenários</CardTitle>
            <CardDescription>Escolha um cenário, a seed e a velocidade do relógio simulado.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Cenário">
              {scenarios ? (
                scenarios.map((s) => (
                  <button
                    key={s.key}
                    type="button"
                    role="radio"
                    aria-checked={scenario === s.key}
                    onClick={() => setScenario(s.key)}
                    className={cn(
                      "rounded-lg border p-3 text-left transition-colors hover:bg-muted/60 cursor-pointer",
                      scenario === s.key && "border-primary ring-1 ring-primary",
                    )}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{s.name}</span>
                      {s.featured && <Badge tone="primary">Principal</Badge>}
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">{s.description}</p>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {s.tags.map((t) => (
                        <Badge key={t}>{t}</Badge>
                      ))}
                      <Badge tone="outline">{s.total_ticks} min</Badge>
                    </div>
                  </button>
                ))
              ) : (
                <Skeleton className="h-24 sm:col-span-2" />
              )}
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="grid gap-1">
                <Label htmlFor="seed">Seed</Label>
                <Input id="seed" type="number" min={0} value={seed} onChange={(e) => setSeed(Number(e.target.value) || 0)} />
              </div>
              <div className="grid gap-1 sm:col-span-2">
                <Label htmlFor="speed">Velocidade</Label>
                <Select id="speed" value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
                  {SPEEDS.map((s) => (
                    <option key={s.ms} value={s.ms}>
                      {s.label}
                    </option>
                  ))}
                </Select>
              </div>
            </div>
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-1 accent-[var(--primary)]" checked={autoPause} onChange={(e) => setAutoPause(e.target.checked)} />
              <span>
                Pausar o relógio enquanto houver aprovações pendentes
                <span className="block text-xs text-muted-foreground">
                  Mantém o ponto de decisão fixo, o que torna o replay determinístico e a demo mais fácil de acompanhar.
                </span>
              </span>
            </label>
            <Button
              disabled={!allowed || busy !== null}
              onClick={() =>
                act("start", "/simulation", { scenario_key: scenario, seed, tick_interval_ms: speed, auto_pause_on_approval: autoPause }, "Simulação iniciada.")
              }
            >
              <Play /> Iniciar (zera os dados)
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Execução atual</CardTitle>
            <CardDescription>Relógio simulado no horário de São Paulo.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {!sim ? (
              <EmptyState title="Nenhuma simulação iniciada" description="Escolha um cenário e clique em Iniciar." />
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <SimBadge status={sim.status} reason={sim.pause_reason} />
                  <Badge>seed {sim.seed}</Badge>
                  <Badge tone="outline">{sim.scenario_name}</Badge>
                </div>
                <div className="flex items-end justify-between">
                  <div>
                    <div className="text-xs text-muted-foreground">Relógio simulado</div>
                    <div className="font-mono text-3xl font-semibold tabular-nums">{clock(sim.business_time)}</div>
                  </div>
                  <div className="text-right text-xs text-muted-foreground">
                    minuto {sim.current_tick} de {sim.total_ticks}
                    <br />
                    {sim.tick_interval_ms} ms por minuto
                  </div>
                </div>
                <Progress value={(sim.current_tick / sim.total_ticks) * 100} label="Progresso da simulação" />
                <div className="flex flex-wrap gap-2">
                  {running && (
                    <Button variant="outline" size="sm" disabled={!allowed || !!busy} onClick={() => act("pause", "/simulation/pause")}>
                      <Pause /> Pausar
                    </Button>
                  )}
                  {paused && (
                    <Tooltip content={sim.pause_reason === "agents_running" ? "Aguarde os agentes concluírem" : "Retomar o relógio"}>
                      <span>
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={!allowed || !!busy || sim.pause_reason === "agents_running"}
                          onClick={() => act("resume", "/simulation/resume")}
                        >
                          <Play /> Retomar
                        </Button>
                      </span>
                    </Tooltip>
                  )}
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!allowed || !!busy || blocked || !(running || paused)}
                    onClick={() => act("step1", "/simulation/step", { ticks: 1 })}
                  >
                    <StepForward /> +1 min
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={!allowed || !!busy || blocked || !(running || paused)}
                    onClick={() => act("step10", "/simulation/step", { ticks: 10 })}
                  >
                    <FastForward /> +10 min
                  </Button>
                  <Button variant="outline" size="sm" disabled={!allowed || !!busy} onClick={() => act("reset", "/simulation/reset", undefined, "Simulação reiniciada com a mesma seed.")}>
                    <RotateCcw /> Reiniciar
                  </Button>
                  {(running || paused) && (
                    <Button variant="ghost" size="sm" disabled={!allowed || !!busy} onClick={() => act("stop", "/simulation/stop")}>
                      <CircleStop /> Encerrar
                    </Button>
                  )}
                </div>
                {overview && (
                  <dl className="grid grid-cols-2 gap-3 border-t pt-4 text-sm">
                    <div>
                      <dt className="text-xs text-muted-foreground">Pedidos</dt>
                      <dd className="font-medium tabular-nums">{n0(overview.kpis.orders_total)}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">Perdidos por falta de insumo</dt>
                      <dd className="font-medium tabular-nums">{n0(overview.kpis.lost_orders_total)}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">Receita</dt>
                      <dd className="font-medium tabular-nums">{money(overview.kpis.revenue_total_cents)}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted-foreground">Incidentes / aprovações pendentes</dt>
                      <dd className="font-medium tabular-nums">
                        {n0(overview.kpis.open_incidents)} / {n0(overview.kpis.pending_approvals)}
                      </dd>
                    </div>
                  </dl>
                )}
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader className="sm:flex-row sm:items-end sm:justify-between">
          <div>
            <CardTitle>Inspetor de eventos</CardTitle>
            <CardDescription>
              Cada evento tem uma chave única, é processado em ordem e, se falhar, volta para a fila até ir para a lista de falhas.
            </CardDescription>
          </div>
          <div className="flex gap-2">
            <Select aria-label="Filtrar por tipo" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
              <option value="">Todos os tipos</option>
              {EVENT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </Select>
            <Select aria-label="Filtrar por status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">Todos os status</option>
              <option value="processed">processed</option>
              <option value="pending">pending</option>
              <option value="rejected">rejected</option>
              <option value="dead_letter">dead_letter</option>
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          {eventsError ? (
            <ErrorState error={eventsError} />
          ) : !events ? (
            <Skeleton className="h-40" />
          ) : events.length === 0 ? (
            <EmptyState title="Sem eventos" description="Inicie ou avance a simulação para gerar eventos." />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>#</TH>
                  <TH>Minuto</TH>
                  <TH>Horário</TH>
                  <TH>Tipo</TH>
                  <TH>Referência</TH>
                  <TH>Status</TH>
                  <TH>Resultado</TH>
                  <TH>Tentativas</TH>
                </TR>
              </THead>
              <TBody>
                {events.map((e) => (
                  <TR key={e.id}>
                    <TD className="font-mono text-xs text-muted-foreground">{e.id}</TD>
                    <TD className="tabular-nums">{e.tick ?? "—"}</TD>
                    <TD className="font-mono text-xs">{clockSec(e.occurred_at)}</TD>
                    <TD className="font-mono text-xs">{e.type}</TD>
                    <TD className="font-mono text-xs">{String(e.payload.order_ref ?? e.payload.ingredient_key ?? "—")}</TD>
                    <TD>
                      <Badge tone={e.status === "processed" ? "success" : e.status === "dead_letter" ? "danger" : e.status === "rejected" ? "warning" : "neutral"}>
                        {e.status}
                      </Badge>
                    </TD>
                    <TD className={cn("text-xs", e.outcome?.startsWith("rejected") && "text-danger")}>{e.outcome ?? e.last_error ?? "—"}</TD>
                    <TD className="tabular-nums">{e.attempts}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <SyntheticNotice className="mt-6" />
    </>
  );
}
