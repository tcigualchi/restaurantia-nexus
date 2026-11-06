"use client";

import { Check, ClipboardCheck, ExternalLink, Loader2, ShieldAlert, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import useSWR from "swr";

import { useApp } from "@/components/shell/app-context";
import { ApprovalBadge, EmptyState, ErrorState, PageHeader } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label, Textarea } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip } from "@/components/ui/tooltip";
import { ApiError, apiPost } from "@/lib/api";
import { ACTION_LABEL, clock, dateTime, money, qty } from "@/lib/format";
import type { ApprovalView } from "@/lib/types";

function useNow(interval = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), interval);
    return () => clearInterval(id);
  }, [interval]);
  return now;
}

function Countdown({ until }: { until: string }) {
  const now = useNow();
  const left = Math.max(0, Math.round((new Date(until).getTime() - now) / 1000));
  const mm = Math.floor(left / 60);
  const ss = String(left % 60).padStart(2, "0");
  return (
    <span className={left < 120 ? "text-danger" : "text-muted-foreground"}>
      expira em {mm}:{ss}
    </span>
  );
}

function PayloadSummary({ a }: { a: ApprovalView }) {
  const p = a.payload as Record<string, string | number>;
  if (a.action_type === "create_purchase_order") {
    return (
      <span>
        {qty(Number(p.quantity), String(p.unit))} · chegada em {p.expected_arrival_minutes} min · custo estimado {money(Number(p.estimated_cost_cents))}
      </span>
    );
  }
  return <span>Item: {String(p.item_key)} · motivo: {String(p.reason)}</span>;
}

export function ApprovalsView() {
  const { rpath, restaurant } = useApp();
  const { data, error, mutate } = useSWR<ApprovalView[]>(rpath("/approvals"));
  const [rejecting, setRejecting] = useState<ApprovalView | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  async function decide(a: ApprovalView, decision: "approve" | "reject", why?: string) {
    const path = rpath(`/approvals/${a.id}/decision`);
    if (!path) return;
    setBusy(a.id);
    try {
      const result = await apiPost<ApprovalView>(path, { decision, reason: why, expected_version: a.version });
      if (result.status === "executed") toast.success(result.execution_result?.message ?? "Ação executada.");
      else if (result.status === "failed") toast.error(`Revalidação bloqueou a execução: ${result.execution_result?.message ?? "estado mudou"}`);
      else toast.info("Ação rejeitada e registrada na auditoria.");
      setRejecting(null);
      setReason("");
      await mutate();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Não foi possível registrar a decisão.");
      await mutate();
    } finally {
      setBusy(null);
    }
  }

  // Oldest first = the orchestrator's priority order.
  const pending = (data?.filter((a) => a.status === "pending") ?? []).sort((a, b) => a.requested_at.localeCompare(b.requested_at));
  const history = data?.filter((a) => a.status !== "pending") ?? [];
  const canDecide = restaurant?.permissions.includes("approvals.decide");

  return (
    <>
      <PageHeader
        title="Approval Center"
        description="Ações sensíveis propostas pelos agentes. Nada é executado sem uma decisão humana válida; a ação é revalidada no momento da execução e tudo vai para a trilha de auditoria."
      />
      {!canDecide && (
        <p className="mb-4 flex items-center gap-2 rounded-md bg-info-soft px-3 py-2 text-sm text-info">
          <ShieldAlert className="size-4" /> Seu papel (operador) pode visualizar, mas decidir exige o papel de gerente.
        </p>
      )}
      {error && <ErrorState error={error} retry={() => mutate()} />}
      <Tabs defaultValue="pending">
        <TabsList>
          <TabsTrigger value="pending">
            Pendentes {pending.length > 0 && <Badge tone="warning">{pending.length}</Badge>}
          </TabsTrigger>
          <TabsTrigger value="history">Histórico</TabsTrigger>
        </TabsList>
        <TabsContent value="pending">
          {!data ? (
            <Skeleton className="h-48" />
          ) : pending.length === 0 ? (
            <EmptyState
              icon={<ClipboardCheck />}
              title="Nenhuma aprovação pendente"
              description="Quando os agentes propuserem uma ação sensível (compra emergencial, pausa de item), ela aparecerá aqui."
            />
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              {pending.map((a) => (
                <Card key={a.id} className="flex flex-col">
                  <CardHeader>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone="primary">{ACTION_LABEL[a.action_type] ?? a.action_type}</Badge>
                      <Badge tone={a.risk_level === "high" ? "danger" : "warning"}>risco {a.risk_level === "high" ? "alto" : "médio"}</Badge>
                      <span className="ml-auto text-xs">
                        <Countdown until={a.expires_at} />
                      </span>
                    </div>
                    <CardTitle className="mt-2 text-base leading-snug">{a.title}</CardTitle>
                  </CardHeader>
                  <CardContent className="flex flex-1 flex-col gap-3 text-sm">
                    <div>
                      <div className="text-xs font-medium text-muted-foreground">Justificativa</div>
                      <p className="mt-0.5 leading-relaxed">{a.rationale}</p>
                    </div>
                    <div>
                      <div className="text-xs font-medium text-muted-foreground">Impacto esperado</div>
                      <p className="mt-0.5 leading-relaxed">{a.expected_impact}</p>
                    </div>
                    <div className="rounded-md bg-muted px-3 py-2 text-xs">
                      <PayloadSummary a={a} />
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                      Evidências:
                      {a.evidence.map((ev) => (
                        <Link key={ev} href={`/control-room?run=${a.run_id}#${ev}`} className="rounded border bg-card px-1.5 py-0.5 font-mono hover:bg-muted">
                          {ev}
                        </Link>
                      ))}
                      <span className="ml-auto">proposta às {clock(a.business_time)} (simulado) · requer {a.required_role === "manager" ? "gerente" : a.required_role}</span>
                    </div>
                    <div className="mt-auto flex gap-2 pt-2">
                      <Tooltip content={a.can_decide ? "Executa após revalidar o estado atual" : "Requer papel de gerente"}>
                        <span className="flex-1">
                          <Button
                            className="w-full"
                            variant="success"
                            disabled={!a.can_decide || busy === a.id}
                            onClick={() => decide(a, "approve")}
                          >
                            {busy === a.id ? <Loader2 className="animate-spin" /> : <Check />} Aprovar
                          </Button>
                        </span>
                      </Tooltip>
                      <Button className="flex-1" variant="outline" disabled={!a.can_decide || busy === a.id} onClick={() => setRejecting(a)}>
                        <X /> Rejeitar
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>
        <TabsContent value="history">
          <Card>
            <CardHeader>
              <CardTitle>Decisões registradas</CardTitle>
            </CardHeader>
            <CardContent>
              {history.length === 0 ? (
                <p className="text-sm text-muted-foreground">Nenhuma decisão ainda.</p>
              ) : (
                <Table>
                  <THead>
                    <TR>
                      <TH>Ação</TH>
                      <TH>Status</TH>
                      <TH>Decidido por</TH>
                      <TH>Quando</TH>
                      <TH>Justificativa / resultado</TH>
                      <TH>Trace</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {history.map((a) => (
                      <TR key={a.id}>
                        <TD className="max-w-sm">
                          <div className="font-medium">{a.title}</div>
                          <div className="text-xs text-muted-foreground">{ACTION_LABEL[a.action_type]}</div>
                        </TD>
                        <TD>
                          <ApprovalBadge status={a.status} />
                        </TD>
                        <TD>{a.decided_by_label ?? (a.status === "expired" ? "sistema (expirou)" : "—")}</TD>
                        <TD className="whitespace-nowrap text-xs">{dateTime(a.decided_at ?? a.requested_at)}</TD>
                        <TD className="max-w-md text-xs">{a.decision_reason ?? a.execution_result?.message ?? "—"}</TD>
                        <TD>
                          {a.run_id && (
                            <Link href={`/control-room?run=${a.run_id}`} className="inline-flex items-center gap-1 text-xs text-primary hover:underline">
                              abrir <ExternalLink className="size-3" />
                            </Link>
                          )}
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <Dialog open={!!rejecting} onOpenChange={(open) => !open && setRejecting(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rejeitar ação</DialogTitle>
            <DialogDescription>{rejecting?.title}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-1.5">
            <Label htmlFor="reason">Justificativa (obrigatória, registrada na auditoria)</Label>
            <Textarea id="reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="Ex.: item é o carro-chefe da casa; prefiro manter no cardápio." />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRejecting(null)}>
              Cancelar
            </Button>
            <Button
              variant="danger"
              disabled={reason.trim().length < 3 || busy === rejecting?.id}
              onClick={() => rejecting && decide(rejecting, "reject", reason.trim())}
            >
              Confirmar rejeição
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
