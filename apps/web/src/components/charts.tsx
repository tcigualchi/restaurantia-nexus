"use client";

import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { clock, day, n0, n1, qty } from "@/lib/format";
import type { Timeseries } from "@/lib/types";

const axis = { stroke: "var(--muted-foreground)", fontSize: 11, tickLine: false, axisLine: false } as const;
const tooltipStyle = {
  contentStyle: {
    background: "var(--card)",
    border: "1px solid var(--border)",
    borderRadius: 8,
    fontSize: 12,
    color: "var(--foreground)",
  },
  labelStyle: { color: "var(--muted-foreground)" },
};

export function OrdersQueueChart({ data }: { data: Timeseries }) {
  const rows = data.points.map((p) => ({ t: clock(p.t), pedidos: p.orders, perdidos: p.rejected, fila: p.queue_length, preparo: p.avg_prep_minutes }));
  return (
    <div className="h-64" role="img" aria-label="Pedidos por intervalo, pedidos perdidos e fila da cozinha ao longo da simulação">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="t" {...axis} minTickGap={24} />
          <YAxis {...axis} allowDecimals={false} />
          <Tooltip {...tooltipStyle} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="pedidos" name="Pedidos" fill="var(--chart-1)" radius={[3, 3, 0, 0]} maxBarSize={22} />
          <Bar dataKey="perdidos" name="Perdidos" fill="var(--danger)" radius={[3, 3, 0, 0]} maxBarSize={22} />
          <Line dataKey="fila" name="Fila" stroke="var(--chart-2)" strokeWidth={2} dot={false} type="monotone" />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function StockChart({ data, units }: { data: Timeseries; units: Record<string, string> }) {
  const keys = Object.keys(data.ingredients);
  const colors = ["var(--chart-3)", "var(--chart-4)", "var(--chart-5)"];
  const rows = data.points.map((p) => ({ t: clock(p.t), ...p.stock }));
  return (
    <div className="h-64" role="img" aria-label="Estoque dos ingredientes mais críticos ao longo da simulação">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 4 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="t" {...axis} minTickGap={24} />
          <YAxis {...axis} tickFormatter={(v: number) => (v >= 1000 ? `${n0(v / 1000)}k` : n0(v))} />
          <Tooltip {...tooltipStyle} formatter={(v, name) => [qty(Number(v), units[String(name)] ?? ""), data.ingredients[String(name)] ?? String(name)]} />
          <Legend wrapperStyle={{ fontSize: 12 }} formatter={(key: string) => data.ingredients[key] ?? key} />
          {keys.map((k, i) => (
            <Line key={k} dataKey={k} stroke={colors[i % colors.length]} strokeWidth={2} dot={false} type="stepAfter" />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function HistoryChart({ history }: { history: { hour: string; orders: number; expected: number }[] }) {
  const rows = history.map((h) => ({ label: `${day(h.hour)} ${clock(h.hour)}`, pedidos: h.orders, esperado: h.expected }));
  return (
    <div className="h-64" role="img" aria-label="Histórico sintético de pedidos por hora nos últimos 14 dias">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="label" {...axis} minTickGap={48} />
          <YAxis {...axis} allowDecimals={false} />
          <Tooltip {...tooltipStyle} formatter={(v) => n1(Number(v))} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Area dataKey="pedidos" name="Pedidos (sintético)" fill="var(--chart-1)" fillOpacity={0.18} stroke="var(--chart-1)" type="monotone" />
          <Line dataKey="esperado" name="Perfil esperado" stroke="var(--chart-2)" dot={false} strokeDasharray="4 3" type="monotone" />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
