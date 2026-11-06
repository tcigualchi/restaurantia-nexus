"use client";

import useSWR from "swr";

import { HistoryChart } from "@/components/charts";
import { useApp } from "@/components/shell/app-context";
import { ErrorState, PageHeader, SyntheticNotice } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { clock, dateTime, n0, n1, pct, qty } from "@/lib/format";
import type { ForecastView, Interval } from "@/lib/types";

const MODEL_LABEL: Record<string, string> = {
  naive_1d: "Ingênuo diário (mesma hora ontem)",
  seasonal_naive_7d: "Ingênuo sazonal (mesma hora, semana passada)",
  seasonal_mean_4w: "Média sazonal de 4 semanas",
};

function IntervalCell({ v, unit }: { v: Interval; unit?: string }) {
  const f = (x: number) => (unit ? qty(x, unit) : n0(x));
  return (
    <span className="inline-flex flex-col items-end tabular-nums">
      <span className="font-medium">{f(v.expected)}</span>
      <span className="whitespace-nowrap text-[11px] text-muted-foreground">
        {f(v.p10)} – {f(v.p90)}
      </span>
    </span>
  );
}

export function ForecastingView() {
  const { rpath } = useApp();
  const { data, error, mutate } = useSWR<ForecastView>(rpath("/forecast?horizon_minutes=120"));
  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!data) return <Skeleton className="h-96" />;
  const f = data.forecast;
  const bt = f.backtest;
  const val = Object.fromEntries(bt.validation.map((s) => [s.model, s]));
  return (
    <>
      <PageHeader
        title="Forecasting"
        description="Previsão estatística de demanda (não gerada por LLM), avaliada com backtest temporal. Intervalos de 80% com cobertura medida — previsão não é certeza."
      />
      <div className="grid gap-4 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Próximas {f.horizon_minutes / 60}h a partir de {clock(f.as_of)}</CardTitle>
            <CardDescription>Modelo selecionado: {MODEL_LABEL[f.model] ?? f.model}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex items-start justify-between">
              <span className="text-muted-foreground">Pedidos — linha de base</span>
              <IntervalCell v={f.orders} />
            </div>
            <div className="flex items-start justify-between">
              <span className="text-muted-foreground">Pedidos — ajustado ao ritmo</span>
              <IntervalCell v={f.orders_adjusted} />
            </div>
            <div className="rounded-md bg-muted px-3 py-2 text-xs leading-relaxed">{f.nowcast.note}</div>
            <p className="text-xs text-muted-foreground">{f.disclaimer}</p>
          </CardContent>
        </Card>
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle>Histórico de pedidos por hora (14 dias)</CardTitle>
            <CardDescription>{data.data_label}</CardDescription>
          </CardHeader>
          <CardContent>
            <HistoryChart history={data.history} />
          </CardContent>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Backtest (item × hora)</CardTitle>
            <CardDescription>
              Seleção na semana de validação ({dateTime(bt.validation_window[0])} → {dateTime(bt.validation_window[1])}); métricas reportadas na semana de teste
              ({dateTime(bt.test_window[0])} → {dateTime(bt.test_window[1])}), {bt.test_hours} horas de operação.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <THead>
                <TR>
                  <TH>Modelo</TH>
                  <TH className="text-right">WAPE validação</TH>
                  <TH className="text-right">WAPE teste</TH>
                  <TH className="text-right">MAE teste</TH>
                </TR>
              </THead>
              <TBody>
                {bt.test.map((s) => (
                  <TR key={s.model}>
                    <TD>
                      {MODEL_LABEL[s.model] ?? s.model} {s.model === bt.selected_model && <Badge tone="primary">selecionado</Badge>}
                    </TD>
                    <TD className="text-right tabular-nums">{pct(val[s.model]?.wape, 1)}</TD>
                    <TD className="text-right tabular-nums">{pct(s.wape, 1)}</TD>
                    <TD className="text-right tabular-nums">{n1(s.mae)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
            <p className="mt-3 text-xs text-muted-foreground">
              Intervalo de {pct(bt.interval_level)}: cobertura empírica de {pct(bt.interval_coverage_test)} na semana de teste (sobre-dispersão estimada φ = {n1(bt.dispersion)}).
              Método: {bt.method}.
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Consumo previsto de ingredientes</CardTitle>
            <CardDescription>Esperado (P10–P90) nas próximas {f.horizon_minutes / 60}h, a partir das fichas técnicas.</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <THead>
                <TR>
                  <TH>Ingrediente</TH>
                  <TH className="text-right">Linha de base</TH>
                  <TH className="text-right">Ajustado</TH>
                </TR>
              </THead>
              <TBody>
                {[...f.ingredients]
                  .sort((a, b) => b.adjusted.expected - a.adjusted.expected)
                  .slice(0, 10)
                  .map((i) => (
                    <TR key={i.ingredient_key}>
                      <TD>{i.name}</TD>
                      <TD className="text-right">
                        <IntervalCell v={i.baseline} unit={i.unit} />
                      </TD>
                      <TD className="text-right">
                        <IntervalCell v={i.adjusted} unit={i.unit} />
                      </TD>
                    </TR>
                  ))}
              </TBody>
            </Table>
          </CardContent>
        </Card>
      </div>
      <SyntheticNotice className="mt-6" />
    </>
  );
}
