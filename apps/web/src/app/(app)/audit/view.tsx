"use client";

import { useState } from "react";
import useSWRInfinite from "swr/infinite";

import { JsonView } from "@/components/json-view";
import { useApp } from "@/components/shell/app-context";
import { EmptyState, ErrorState, PageHeader } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { AGENT_LABEL, clock, dateTime, describeAudit } from "@/lib/format";
import type { AuditView as Audit } from "@/lib/types";

const TARGET_LABEL: Record<string, string> = {
  agent_run: "execução dos agentes",
  approval: "aprovação",
  incident: "incidente",
  menu_item: "item do cardápio",
  purchase_order: "pedido de compra",
  restaurant: "restaurante",
  simulation: "simulação",
};

const PREFIXES = ["approval", "action", "agent_run", "incident", "simulation", "menu_item", "purchase_order", "event", "sandbox"];
const ACTOR_TONE: Record<string, "primary" | "info" | "neutral"> = { user: "primary", agent: "info", system: "neutral" };
const ACTOR_LABEL: Record<string, string> = { user: "Usuário", agent: "Agente", system: "Sistema" };

export function AuditView() {
  const { rpath } = useApp();
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const base = rpath("/audit");
  const { data, error, size, setSize, mutate } = useSWRInfinite<Audit[]>((index, prev) => {
    if (!base || (prev && prev.length < 100)) return null;
    const qs = new URLSearchParams({ limit: "100" });
    if (action) qs.set("action", action);
    if (actor) qs.set("actor_type", actor);
    const last = prev?.[prev.length - 1];
    if (index > 0 && last) qs.set("before_id", String(last.id));
    return `${base}?${qs.toString()}`;
  });
  const rows = data?.flat() ?? [];
  const hasMore = (data?.[data.length - 1]?.length ?? 0) === 100;

  return (
    <>
      <PageHeader
        title="Auditoria"
        description="Registro de quem fez o quê, seja pessoa, agente ou sistema, com o horário real e o horário da simulação. O banco bloqueia qualquer alteração ou exclusão nesses registros."
        actions={
          <>
            <Select aria-label="Filtrar por ação" value={action} onChange={(e) => setAction(e.target.value)}>
              <option value="">Todas as ações</option>
              {PREFIXES.map((p) => (
                <option key={p} value={p}>
                  {p}.*
                </option>
              ))}
            </Select>
            <Select aria-label="Filtrar por ator" value={actor} onChange={(e) => setActor(e.target.value)}>
              <option value="">Todos os atores</option>
              <option value="user">Usuários</option>
              <option value="agent">Agentes</option>
              <option value="system">Sistema</option>
            </Select>
          </>
        }
      />
      {error && <ErrorState error={error} retry={() => mutate()} />}
      <Card>
        <CardContent className="pt-5">
          {!data ? (
            <Skeleton className="h-64" />
          ) : rows.length === 0 ? (
            <EmptyState title="Sem registros" description="As ações importantes aparecem aqui." />
          ) : (
            <>
              <Table>
                <THead>
                  <TR>
                    <TH>#</TH>
                    <TH>Registrado em</TH>
                    <TH>Horário do negócio</TH>
                    <TH>Ator</TH>
                    <TH>Ação</TH>
                    <TH>Detalhes</TH>
                  </TR>
                </THead>
                <TBody>
                  {rows.map((a) => (
                    <TR key={a.id} className="align-top">
                      <TD className="font-mono text-xs text-muted-foreground">{a.id}</TD>
                      <TD className="whitespace-nowrap text-xs">{dateTime(a.created_at)}</TD>
                      <TD className="font-mono text-xs">{a.business_time ? clock(a.business_time) : "—"}</TD>
                      <TD>
                        <div className="flex flex-col gap-1">
                          <Badge tone={ACTOR_TONE[a.actor_type]}>{ACTOR_LABEL[a.actor_type]}</Badge>
                          <span className="text-xs text-muted-foreground">
                            {a.actor_type === "agent" ? (AGENT_LABEL[a.actor_label.replace(/^Agente /, "")] ?? a.actor_label) : a.actor_label}
                          </span>
                        </div>
                      </TD>
                      <TD>
                        <div className="text-sm font-medium">{describeAudit(a.action)}</div>
                        <div className="font-mono text-[11px] text-muted-foreground">{a.action}</div>
                      </TD>
                      <TD className="min-w-64 max-w-md">
                        <JsonView
                          value={a.details}
                          label={String(a.details.title ?? TARGET_LABEL[a.target_type ?? ""] ?? a.target_type ?? "detalhes")}
                        />
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
              {hasMore && (
                <div className="mt-4 flex justify-center">
                  <Button variant="outline" onClick={() => setSize(size + 1)}>
                    Carregar mais
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </>
  );
}
