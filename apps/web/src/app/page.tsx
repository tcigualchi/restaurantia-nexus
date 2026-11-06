import { Bot, ClipboardCheck, FlaskConical, LineChart, ShieldCheck, Workflow } from "lucide-react";

import { Wordmark } from "@/components/brand";
import { Badge } from "@/components/ui/badge";

import { DemoEntry } from "./demo-entry";

const STEPS = [
  { icon: FlaskConical, title: "Simulação reproduzível", text: "Um restaurante sintético recebe um pico de pedidos com estoque crítico — mesma seed, mesmo resultado." },
  { icon: Workflow, title: "Detecção e orquestração", text: "Detectores determinísticos abrem um incidente; um grafo LangGraph aciona os agentes especialistas." },
  { icon: Bot, title: "Agentes com ferramentas tipadas", text: "Operations, Inventory e Forecasting consultam dados via ferramentas com schema, permissões e limites." },
  { icon: LineChart, title: "Previsão estatística", text: "Números vêm de modelos avaliados em backtest (WAPE/MAE), nunca inventados por um LLM." },
  { icon: ClipboardCheck, title: "Aprovação humana", text: "Ações sensíveis ficam pendentes; só executam após aprovação válida, com revalidação e auditoria." },
  { icon: ShieldCheck, title: "Segurança por padrão", text: "Isolamento por tenant, RBAC, guardrails contra prompt injection e trilha de auditoria append-only." },
];

export default function Landing() {
  return (
    <div className="min-h-dvh bg-[radial-gradient(ellipse_at_top,var(--secondary),transparent_55%)]">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <Wordmark />
        <Badge tone="warning">Projeto de portfólio · dados sintéticos</Badge>
      </header>
      <main id="main" className="mx-auto grid max-w-6xl gap-12 px-6 pb-16 pt-6 lg:grid-cols-[1.15fr_1fr] lg:pt-12">
        <section>
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            Inteligência operacional autônoma para restaurantes — com humanos no controle.
          </h1>
          <p className="mt-4 max-w-xl text-base text-muted-foreground">
            RestaurantIA Nexus combina simulação de operações, previsão de demanda e agentes de IA especializados que
            investigam gargalos, antecipam rupturas de estoque e propõem ações. Nada sensível acontece sem aprovação.
          </p>
          <ul className="mt-8 grid gap-4 sm:grid-cols-2">
            {STEPS.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-3">
                <div className="mt-0.5 h-fit self-start rounded-lg bg-card p-2 text-primary shadow-sm ring-1 ring-border">
                  <Icon className="size-4" />
                </div>
                <div>
                  <div className="text-sm font-medium">{title}</div>
                  <div className="text-sm text-muted-foreground">{text}</div>
                </div>
              </li>
            ))}
          </ul>
        </section>
        <section aria-label="Acesso">
          <DemoEntry />
          <p className="mt-4 text-xs text-muted-foreground">
            Todos os restaurantes, pedidos e estoques são fictícios e gerados por simulação. Este projeto não tem
            vínculo com iFood ou qualquer marketplace de delivery.
          </p>
        </section>
      </main>
    </div>
  );
}
