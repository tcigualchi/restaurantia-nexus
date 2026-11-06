"use client";

import { AlertTriangle, Bot, BrainCircuit, Loader2, ShieldAlert, Sparkles, Wrench } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import useSWR from "swr";

import { JsonView } from "@/components/json-view";
import { useApp } from "@/components/shell/app-context";
import { ApprovalBadge, EmptyState, ErrorState, ModeBadge, PageHeader, RunBadge } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { ApiError, apiPost } from "@/lib/api";
import { AGENT_LABEL, clock, dateTime, n0, pct } from "@/lib/format";
import type { AgentRunBrief, AgentRunDetail, StepView } from "@/lib/types";
import { cn } from "@/lib/utils";

const KIND_ICON: Record<string, React.ReactNode> = {
  tool_call: <Wrench />,
  decision: <BrainCircuit />,
  finding: <Sparkles />,
  model_call: <Bot />,
  approval_request: <ShieldAlert />,
  fallback: <AlertTriangle />,
};

const SEVERITY_LABEL: Record<string, string> = { medium: "médio", high: "alto", critical: "crítico" };

const STATUS_TONE: Record<string, "success" | "danger" | "warning" | "neutral"> = {
  ok: "success",
  error: "danger",
  denied: "danger",
  invalid_arguments: "warning",
  budget_exceeded: "warning",
};

function StepRow({ step }: { step: StepView }) {
  const injection = step.flags.filter((f) => f.startsWith("prompt_injection:"));
  return (
    <li id={step.id} className="relative scroll-mt-24 pl-8">
      <span className="absolute left-0 top-1 flex size-6 items-center justify-center rounded-full border bg-card text-muted-foreground [&_svg]:size-3.5">
        {KIND_ICON[step.kind] ?? <Wrench />}
      </span>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[11px] text-muted-foreground">{step.id}</span>
        <Badge tone="outline">{AGENT_LABEL[step.agent] ?? step.agent}</Badge>
        <span className="text-sm font-medium">{step.title}</span>
        {step.kind === "tool_call" && <Badge tone={STATUS_TONE[step.status] ?? "neutral"}>{step.status}</Badge>}
        {step.latency_ms != null && <span className="text-[11px] text-muted-foreground">{step.latency_ms} ms</span>}
      </div>
      {injection.length > 0 && (
        <div className="mt-1.5 flex items-start gap-1.5 rounded-md bg-danger-soft px-2.5 py-1.5 text-xs text-danger">
          <ShieldAlert className="mt-0.5 size-3.5 shrink-0" />
          Tentativa de prompt injection em texto de cliente ({injection.map((f) => f.split(":")[1]).join(", ")}). O texto foi
          marcado como não confiável e nenhuma instrução dele foi seguida.
        </div>
      )}
      {step.kind === "finding" && typeof step.output?.summary === "string" && (
        <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{step.output.summary}</p>
      )}
      {step.kind === "decision" && typeof step.output?.reason === "string" && (
        <p className="mt-1.5 text-sm text-muted-foreground">{step.output.reason}</p>
      )}
      <div className="mt-2 grid gap-1.5">
        {step.input && Object.keys(step.input).length > 0 && <JsonView value={step.input} label="Parâmetros validados" />}
        {step.output && step.kind !== "finding" && <JsonView value={step.output} label={step.kind === "tool_call" ? "Resultado da ferramenta" : "Detalhes"} />}
      </div>
    </li>
  );
}

export function ControlRoomView() {
  const { rpath, can } = useApp();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { data: runs, error, mutate } = useSWR<AgentRunBrief[]>(rpath("/agent-runs"));
  const selectedId = params.get("run") ?? runs?.[0]?.id ?? null;
  const { data: run, error: runError } = useSWR<AgentRunDetail>(selectedId ? rpath(`/agent-runs/${selectedId}`) : null);
  const [requesting, setRequesting] = useState(false);

  async function requestRun() {
    const path = rpath("/agent-runs");
    if (!path) return;
    setRequesting(true);
    try {
      const created = await apiPost<AgentRunBrief>(path);
      toast.success("Análise solicitada aos agentes.");
      await mutate();
      router.replace(`${pathname}?run=${created.id}`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Não foi possível solicitar a análise.");
    } finally {
      setRequesting(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Agentes"
        description="Cada execução mostra o que os agentes fizeram, passo a passo: as ferramentas que chamaram, os dados que receberam, as conclusões e as ações que sugeriram."
        actions={
          can("agents.run") && (
            <Button variant="outline" onClick={requestRun} disabled={requesting}>
              {requesting ? <Loader2 className="animate-spin" /> : <Bot />} Solicitar análise agora
            </Button>
          )
        }
      />
      {error && <ErrorState error={error} retry={() => mutate()} />}
      <div className="grid gap-4 xl:grid-cols-[320px_1fr]">
        <Card className="h-fit">
          <CardHeader>
            <CardTitle>Execuções</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1.5">
            {!runs ? (
              <Skeleton className="h-40" />
            ) : runs.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nenhuma execução ainda.</p>
            ) : (
              runs.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  onClick={() => router.replace(`${pathname}?run=${r.id}`)}
                  aria-current={r.id === selectedId}
                  className={cn(
                    "w-full rounded-lg border p-3 text-left transition-colors hover:bg-muted/60 cursor-pointer",
                    r.id === selectedId && "border-primary ring-1 ring-primary",
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium">{r.incident_title ?? "Revisão"}</span>
                    <span className="font-mono text-[11px] text-muted-foreground">{clock(r.as_of)}</span>
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    <RunBadge status={r.status} />
                    <ModeBadge mode={r.mode} model={r.model} />
                  </div>
                  <div className="mt-1.5 text-[11px] text-muted-foreground">
                    {r.steps} passos · {r.approvals} aprovações · {r.trigger === "manual" ? "sob demanda" : "incidente"}
                  </div>
                </button>
              ))
            )}
          </CardContent>
        </Card>

        <div className="min-w-0 space-y-4">
          {runError && <ErrorState error={runError} />}
          {!selectedId ? (
            <EmptyState icon={<Bot />} title="Sem execuções" description="Inicie o cenário principal na tela Simulação para gerar um incidente." />
          ) : !run ? (
            <Skeleton className="h-96" />
          ) : (
            <>
              <Card>
                <CardHeader>
                  <div className="flex flex-wrap items-center gap-2">
                    <RunBadge status={run.status} />
                    <ModeBadge mode={run.mode} model={run.model} />
                    <span className="text-xs text-muted-foreground">
                      análise às {clock(run.as_of)} (simulado) · iniciada {dateTime(run.started_at)}
                    </span>
                  </div>
                  <CardTitle className="mt-2 text-base">{run.incident?.title ?? "Revisão sob demanda"}</CardTitle>
                  {run.mode !== "llm" && (
                    <CardDescription>
                      Modo determinístico: sem modelo de linguagem configurado, os agentes seguem planos fixos de ferramentas e montam o resumo a partir de modelos de texto.
                    </CardDescription>
                  )}
                </CardHeader>
                <CardContent className="space-y-4">
                  {run.incident && run.incident.signals.length > 0 && (
                    <div className="space-y-1.5">
                      <div className="text-xs font-medium text-muted-foreground">Sinais dos detectores</div>
                      {run.incident.signals.map((s, i) => (
                        <div key={i} className="flex items-start gap-2 text-sm">
                          <Badge tone={s.severity === "critical" ? "danger" : "warning"}>{SEVERITY_LABEL[s.severity] ?? s.severity}</Badge>
                          <span>{s.message}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {run.summary && (
                    <div>
                      <div className="text-xs font-medium text-muted-foreground">Resumo do orquestrador</div>
                      <p className="mt-1 text-sm leading-relaxed">{run.summary}</p>
                    </div>
                  )}
                  <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
                    <span>Tokens: {n0(run.prompt_tokens + run.completion_tokens)}</span>
                    <span>Custo estimado: {run.estimated_cost_usd != null ? `US$ ${run.estimated_cost_usd.toFixed(4)}` : "N/A (sem modelo de linguagem ou sem preço configurado)"}</span>
                    {run.error && <span className="text-danger">Erro: {run.error}</span>}
                  </div>
                </CardContent>
              </Card>

              {run.outcomes && (
                <div className="grid gap-4 2xl:grid-cols-3">
                  {Object.entries(run.outcomes).map(([agent, o]) => (
                    <Card key={agent}>
                      <CardHeader>
                        <div className="flex items-center justify-between gap-2">
                          <CardTitle>{AGENT_LABEL[agent] ?? agent}</CardTitle>
                          <ModeBadge mode={o.mode} />
                        </div>
                      </CardHeader>
                      <CardContent className="space-y-3 text-sm">
                        <p className="leading-relaxed text-muted-foreground">{o.summary}</p>
                        {o.facts.length > 0 && (
                          <ul className="space-y-1">
                            {o.facts.map((f, i) => (
                              <li key={i} className="flex items-center justify-between gap-2 text-xs">
                                <span className="text-muted-foreground">{f.label}</span>
                                <span className="flex items-center gap-1.5 font-medium">
                                  {f.value}
                                  <a href={`#${f.evidence}`} className="rounded border px-1 font-mono text-[10px] text-muted-foreground hover:bg-muted">
                                    {f.evidence}
                                  </a>
                                </span>
                              </li>
                            ))}
                          </ul>
                        )}
                        {o.flags.length > 0 && (
                          <div className="flex flex-wrap gap-1">
                            {o.flags.map((f) => (
                              <Badge key={f} tone={f.startsWith("prompt_injection") ? "danger" : "warning"}>
                                {f}
                              </Badge>
                            ))}
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}

              {run.plan && (
                <Card>
                  <CardHeader>
                    <CardTitle>Plano proposto</CardTitle>
                    <CardDescription>As ações saem de regras fixas e auditáveis. Um modelo de linguagem, quando configurado, só ordena e explica.</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {run.plan.capacity && (
                      <div className="grid grid-cols-2 gap-3 rounded-lg bg-muted/60 p-3 text-sm sm:grid-cols-4">
                        <div>
                          <div className="text-xs text-muted-foreground">Utilização projetada</div>
                          <div className="font-semibold">{pct(run.plan.capacity.projected_utilization)}</div>
                        </div>
                        <div>
                          <div className="text-xs text-muted-foreground">Demanda projetada</div>
                          <div className="font-semibold">{n0(run.plan.capacity.projected_orders_per_hour)} pedidos/h</div>
                        </div>
                        <div>
                          <div className="text-xs text-muted-foreground">Capacidade estimada</div>
                          <div className="font-semibold">{n0(run.plan.capacity.capacity_orders_per_hour)} pedidos/h</div>
                        </div>
                        <div>
                          <div className="text-xs text-muted-foreground">Linhas ativas</div>
                          <div className="font-semibold">{run.plan.capacity.lines_available}</div>
                        </div>
                      </div>
                    )}
                    {run.approval_list.length > 0 && (
                      <ul className="space-y-2">
                        {run.approval_list.map((a) => (
                          <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3 text-sm">
                            <span className="font-medium">{a.title}</span>
                            <ApprovalBadge status={a.status} />
                          </li>
                        ))}
                      </ul>
                    )}
                    {run.plan.recommendations.length > 0 && (
                      <div>
                        <div className="mb-1.5 text-xs font-medium text-muted-foreground">Recomendações (sem execução automática)</div>
                        <ul className="space-y-1.5 text-sm">
                          {run.plan.recommendations.map((r, i) => (
                            <li key={i}>
                              <span className="font-medium">{r.title}.</span> <span className="text-muted-foreground">{r.detail}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {run.plan.assumptions.length > 0 && (
                      <div className="rounded-md bg-warning-soft px-3 py-2 text-xs text-accent-foreground">
                        {run.plan.assumptions.map((a, i) => (
                          <p key={i}>{a}</p>
                        ))}
                      </div>
                    )}
                  </CardContent>
                </Card>
              )}

              <Card>
                <CardHeader>
                  <CardTitle>Passo a passo da execução ({run.step_list.length} passos)</CardTitle>
                  <CardDescription>Cada passo foi gravado no momento em que aconteceu. O restaurante e o horário de referência vêm do servidor, nunca do modelo.</CardDescription>
                </CardHeader>
                <CardContent>
                  <ol className="relative space-y-5 border-l pl-1 [&>li]:-ml-[13px]">
                    {run.step_list.map((s) => (
                      <StepRow key={s.id} step={s} />
                    ))}
                  </ol>
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </div>
    </>
  );
}
