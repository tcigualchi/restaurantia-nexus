"use client";

import { Pause, Play } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import useSWR from "swr";

import { useApp } from "@/components/shell/app-context";
import { EmptyState, ErrorState, PageHeader, RiskBadge, SyntheticNotice } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label, Textarea } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { ApiError, apiPost } from "@/lib/api";
import { clock, money, n0, qty } from "@/lib/format";
import type { InventoryView as Inventory, MenuItemView } from "@/lib/types";

export function InventoryView() {
  const { rpath, can } = useApp();
  const { data, error, mutate } = useSWR<Inventory>(rpath("/inventory"));
  const [pausing, setPausing] = useState<MenuItemView | null>(null);
  const [reason, setReason] = useState("");
  const canEdit = can("menu.update");

  async function setAvailability(item: MenuItemView, available: boolean, why?: string) {
    const path = rpath(`/menu-items/${item.key}/availability`);
    if (!path) return;
    try {
      await apiPost(path, { available, reason: why });
      toast.success(available ? `“${item.name}” reativado.` : `“${item.name}” pausado.`);
      setPausing(null);
      setReason("");
      await mutate();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Não foi possível alterar o item.");
    }
  }

  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  return (
    <>
      <PageHeader
        title="Estoque e cardápio"
        description={`Estoque atual, consumo recente (15 min) e tempo estimado até ruptura${data ? ` — horário simulado ${clock(data.business_time)}` : ""}.`}
      />
      <Card>
        <CardHeader>
          <CardTitle>Ingredientes</CardTitle>
          <CardDescription>Ordenados por risco. Fichas técnicas ligam cada ingrediente aos itens do cardápio.</CardDescription>
        </CardHeader>
        <CardContent>
          {!data ? (
            <Skeleton className="h-64" />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Ingrediente</TH>
                  <TH className="text-right">Estoque</TH>
                  <TH className="text-right">Segurança</TH>
                  <TH className="text-right">Consumo/h</TH>
                  <TH className="text-right">Ruptura em</TH>
                  <TH>Risco</TH>
                  <TH className="text-right">Em pedido</TH>
                  <TH>Usado em</TH>
                </TR>
              </THead>
              <TBody>
                {data.ingredients.map((i) => (
                  <TR key={i.id}>
                    <TD className="font-medium">{i.name}</TD>
                    <TD className="text-right tabular-nums">{qty(i.stock, i.unit)}</TD>
                    <TD className="text-right tabular-nums text-muted-foreground">{qty(i.safety_stock, i.unit)}</TD>
                    <TD className="text-right tabular-nums">{i.consumption_per_hour > 0 ? qty(i.consumption_per_hour, i.unit) : "—"}</TD>
                    <TD className="text-right tabular-nums">{i.eta_minutes != null ? `~${n0(i.eta_minutes)} min` : "—"}</TD>
                    <TD>
                      <RiskBadge risk={i.risk} />
                    </TD>
                    <TD className="text-right tabular-nums">{i.open_po_qty > 0 ? qty(i.open_po_qty, i.unit) : "—"}</TD>
                    <TD className="max-w-xs text-xs text-muted-foreground">{i.used_by.join(", ")}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Cardápio</CardTitle>
            <CardDescription>Pausas manuais exigem papel de gerente e ficam registradas na auditoria.</CardDescription>
          </CardHeader>
          <CardContent>
            {!data ? (
              <Skeleton className="h-48" />
            ) : (
              <ul className="divide-y">
                {data.menu_items.map((m) => (
                  <li key={m.id} className="flex items-center justify-between gap-3 py-2.5">
                    <div>
                      <div className="text-sm font-medium">{m.name}</div>
                      <div className="text-xs text-muted-foreground">
                        {money(m.price_cents)} · {m.category}
                        {m.unavailable_reason ? ` · pausado: ${m.unavailable_reason}` : ""}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge tone={m.is_available ? "success" : "warning"}>{m.is_available ? "Disponível" : "Pausado"}</Badge>
                      {canEdit &&
                        (m.is_available ? (
                          <Button size="sm" variant="ghost" onClick={() => setPausing(m)} aria-label={`Pausar ${m.name}`}>
                            <Pause />
                          </Button>
                        ) : (
                          <Button size="sm" variant="ghost" onClick={() => setAvailability(m, true)} aria-label={`Reativar ${m.name}`}>
                            <Play />
                          </Button>
                        ))}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Pedidos de compra</CardTitle>
            <CardDescription>Criados somente a partir de aprovações. Fornecedores são simulados.</CardDescription>
          </CardHeader>
          <CardContent>
            {!data ? (
              <Skeleton className="h-48" />
            ) : data.purchase_orders.length === 0 ? (
              <EmptyState title="Nenhum pedido de compra" description="Aprovações de compra emergencial aparecem aqui." />
            ) : (
              <Table>
                <THead>
                  <TR>
                    <TH>Ingrediente</TH>
                    <TH className="text-right">Quantidade</TH>
                    <TH className="text-right">Custo est.</TH>
                    <TH>Chegada</TH>
                    <TH>Status</TH>
                  </TR>
                </THead>
                <TBody>
                  {data.purchase_orders.map((p) => (
                    <TR key={p.id}>
                      <TD>{p.ingredient_name}</TD>
                      <TD className="text-right tabular-nums">{qty(p.quantity, p.unit)}</TD>
                      <TD className="text-right tabular-nums">{money(p.estimated_cost_cents)}</TD>
                      <TD className="font-mono text-xs">{clock(p.received_at ?? p.expected_at)}</TD>
                      <TD>
                        <Badge tone={p.status === "received" ? "success" : "info"}>{p.status === "received" ? "Recebido" : "A caminho"}</Badge>
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>

      <Dialog open={!!pausing} onOpenChange={(open) => !open && setPausing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Pausar “{pausing?.name}”</DialogTitle>
            <DialogDescription>O item deixa de aparecer para novos pedidos até ser reativado.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-1.5">
            <Label htmlFor="pause-reason">Motivo</Label>
            <Textarea id="pause-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={200} />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setPausing(null)}>
              Cancelar
            </Button>
            <Button disabled={reason.trim().length < 3} onClick={() => pausing && setAvailability(pausing, false, reason.trim())}>
              Pausar item
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <SyntheticNotice className="mt-6" />
    </>
  );
}
