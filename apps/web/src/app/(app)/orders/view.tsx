"use client";

import { ShieldAlert } from "lucide-react";
import { useState } from "react";
import useSWRInfinite from "swr/infinite";

import { useApp } from "@/components/shell/app-context";
import { EmptyState, ErrorState, PageHeader, SyntheticNotice } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { Tooltip } from "@/components/ui/tooltip";
import { CHANNEL_LABEL, ORDER_STATUS_LABEL, clockSec, money, n0, n1 } from "@/lib/format";
import type { OrderView, Page } from "@/lib/types";

const TONE: Record<string, "success" | "info" | "danger" | "neutral"> = { ready: "success", received: "info", rejected: "danger", cancelled: "neutral" };

export function OrdersView() {
  const { rpath, restaurant } = useApp();
  const [status, setStatus] = useState("");
  const [channel, setChannel] = useState("");
  const base = rpath("/orders");
  const { data, error, size, setSize, isLoading, mutate } = useSWRInfinite<Page<OrderView>>((index, prev) => {
    if (!base) return null;
    if (prev && !prev.next_cursor) return null;
    const qs = new URLSearchParams({ limit: "50" });
    if (status) qs.set("status", status);
    if (channel) qs.set("channel", channel);
    if (index > 0 && prev?.next_cursor) qs.set("cursor", prev.next_cursor);
    return `${base}?${qs.toString()}`;
  });
  const rows = data?.flatMap((p) => p.items) ?? [];
  const hasMore = !!data?.[data.length - 1]?.next_cursor;

  return (
    <>
      <PageHeader
        title="Pedidos"
        description={`Pedidos persistidos de ${restaurant?.name ?? "—"}. Observações de clientes são tratadas como dados não confiáveis.`}
        actions={
          <>
            <Select aria-label="Filtrar por status" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Todos os status</option>
              {Object.entries(ORDER_STATUS_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </Select>
            <Select aria-label="Filtrar por canal" value={channel} onChange={(e) => setChannel(e.target.value)}>
              <option value="">Todos os canais</option>
              {Object.entries(CHANNEL_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </Select>
          </>
        }
      />
      {error && <ErrorState error={error} retry={() => mutate()} />}
      <Card>
        <CardContent className="pt-5">
          {isLoading && !data ? (
            <Skeleton className="h-64" />
          ) : rows.length === 0 ? (
            <EmptyState title="Nenhum pedido" description="Inicie uma simulação para gerar pedidos sintéticos." />
          ) : (
            <>
              <div className="mb-3 text-xs text-muted-foreground">{n0(data?.[0]?.total ?? rows.length)} pedidos no total</div>
              <Table>
                <THead>
                  <TR>
                    <TH>Pedido</TH>
                    <TH>Recebido</TH>
                    <TH>Canal</TH>
                    <TH>Itens</TH>
                    <TH className="text-right">Total</TH>
                    <TH>Status</TH>
                    <TH className="text-right">Preparo</TH>
                    <TH>Observação</TH>
                  </TR>
                </THead>
                <TBody>
                  {rows.map((o) => (
                    <TR key={o.id}>
                      <TD className="font-mono text-xs">{o.order_ref}</TD>
                      <TD className="font-mono text-xs">{clockSec(o.created_at)}</TD>
                      <TD className="text-xs">{CHANNEL_LABEL[o.channel] ?? o.channel}</TD>
                      <TD className="max-w-xs text-xs">{o.items.map((i) => `${i.qty}× ${i.name}`).join(", ")}</TD>
                      <TD className="text-right tabular-nums">{money(o.total_cents)}</TD>
                      <TD>
                        <Tooltip content={o.reject_reason ?? ORDER_STATUS_LABEL[o.status]}>
                          <span>
                            <Badge tone={TONE[o.status] ?? "neutral"}>{ORDER_STATUS_LABEL[o.status] ?? o.status}</Badge>
                          </span>
                        </Tooltip>
                      </TD>
                      <TD className="text-right tabular-nums">{o.prep_minutes != null ? `${n1(o.prep_minutes)} min` : "—"}</TD>
                      <TD className="max-w-xs text-xs">
                        {o.customer_note ? (
                          <span className="flex items-start gap-1.5">
                            {o.note_flags.length > 0 && (
                              <Tooltip content={`Não confiável: ${o.note_flags.join(", ")}`}>
                                <ShieldAlert className="mt-0.5 size-3.5 shrink-0 text-danger" aria-label="Conteúdo não confiável" />
                              </Tooltip>
                            )}
                            <span className={o.note_flags.length > 0 ? "text-danger" : ""}>{o.customer_note}</span>
                          </span>
                        ) : (
                          "—"
                        )}
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
      <SyntheticNotice className="mt-6" />
    </>
  );
}
