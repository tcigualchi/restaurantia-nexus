"use client";

import { ArrowRight, Store } from "lucide-react";
import Link from "next/link";
import useSWR from "swr";

import { useApp } from "@/components/shell/app-context";
import { PageHeader, SimBadge } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { money, n0, n1 } from "@/lib/format";
import type { Overview, Restaurant } from "@/lib/types";

function RestaurantCard({ r, active, onSelect }: { r: Restaurant; active: boolean; onSelect: () => void }) {
  const { data } = useSWR<Overview>(`v1/restaurants/${r.id}/overview`);
  return (
    <Card className={active ? "ring-1 ring-primary" : ""}>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Store className="size-4 text-primary" />
          <CardTitle className="text-base">{r.name}</CardTitle>
          {active && <Badge tone="primary">ativo</Badge>}
        </div>
        <CardDescription>
          Tenant isolado · papel {r.role} · {r.kitchen_lines} linhas de preparo · SLA {r.prep_sla_minutes} min
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {!data ? (
          <Skeleton className="h-16" />
        ) : (
          <dl className="grid grid-cols-3 gap-2 text-sm">
            <div>
              <dt className="text-xs text-muted-foreground">Pedidos (60 min)</dt>
              <dd className="font-semibold tabular-nums">{n0(data.kpis.orders_last_60)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">p90 preparo</dt>
              <dd className="font-semibold tabular-nums">{data.kpis.p90_prep_minutes != null ? `${n1(data.kpis.p90_prep_minutes)} min` : "—"}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Receita</dt>
              <dd className="font-semibold tabular-nums">{money(data.kpis.revenue_total_cents)}</dd>
            </div>
          </dl>
        )}
        <div className="flex items-center justify-between">
          {data?.simulation ? <SimBadge status={data.simulation.status} reason={data.simulation.pause_reason} /> : <Badge>sem simulação</Badge>}
          {active ? (
            <Button asChild size="sm" variant="outline">
              <Link href="/overview">
                Abrir <ArrowRight />
              </Link>
            </Button>
          ) : (
            <Button size="sm" variant="outline" onClick={onSelect}>
              Tornar ativo
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export function RestaurantsView() {
  const { restaurants, restaurant, setRestaurantId } = useApp();
  return (
    <>
      <PageHeader
        title="Restaurantes"
        description="Cada restaurante é um tenant: toda consulta é filtrada no servidor pela sua associação. Seu sandbox demo contém cópias privadas dos dois restaurantes sintéticos."
      />
      <div className="grid gap-4 lg:grid-cols-2">
        {restaurants.map((r) => (
          <RestaurantCard key={r.id} r={r} active={r.id === restaurant?.id} onSelect={() => setRestaurantId(r.id)} />
        ))}
      </div>
    </>
  );
}
