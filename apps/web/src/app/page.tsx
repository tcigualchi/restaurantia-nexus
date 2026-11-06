import { ArrowUpRight } from "lucide-react";

import { Wordmark } from "@/components/brand";

import { DemoEntry } from "./demo-entry";

const REPO_URL = "https://github.com/tcigualchi/restaurantia-nexus";

const STEPS = [
  {
    title: "Começa o horário de pico",
    text: "A simulação gera pedidos minuto a minuto e desconta o estoque pelas fichas técnicas. Com a mesma seed, o resultado é sempre igual.",
  },
  {
    title: "Algo sai do normal",
    text: "A fila da cozinha cresce e a costela começa a acabar. Um detector abre um incidente e pausa o relógio da simulação.",
  },
  {
    title: "Os agentes investigam",
    text: "Três agentes, de operação, estoque e previsão, consultam os dados por ferramentas que só fazem leitura e montam um diagnóstico com evidências.",
  },
  {
    title: "O gerente decide",
    text: "As ações sugeridas, como uma compra emergencial ou pausar um prato, esperam aprovação. Só o que for aprovado é executado, e tudo fica na auditoria.",
  },
];

export default function Landing() {
  return (
    <div className="min-h-dvh bg-[radial-gradient(ellipse_at_top,var(--secondary),transparent_60%)]">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6">
        <Wordmark />
        <nav aria-label="Links" className="flex items-center gap-5 text-sm">
          <a href="#como-funciona" className="hidden text-muted-foreground transition-colors hover:text-foreground sm:inline">
            Como funciona
          </a>
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 rounded-md border bg-card px-3 py-1.5 font-medium shadow-sm transition-colors hover:bg-muted"
          >
            Código no GitHub
            <ArrowUpRight className="size-3.5" />
          </a>
        </nav>
      </header>

      <main id="main">
        <section className="mx-auto grid max-w-6xl items-start gap-12 px-6 pb-20 pt-8 lg:grid-cols-[1.2fr_1fr] lg:pt-16">
          <div>
            <p className="text-sm font-medium text-primary">Projeto de portfólio</p>
            <h1 className="mt-3 text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
              Agentes de IA na operação de um restaurante, com aprovação humana
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted-foreground text-pretty">
              Criei este projeto para estudar como agentes de IA podem ajudar no dia a dia de um restaurante sem tomar
              decisões sozinhos. Um restaurante fictício entra em horário de pico, um ingrediente começa a faltar e três
              agentes analisam a situação. Eles sugerem o que fazer, mas nada é executado sem a aprovação de um gerente.
            </p>
            <p className="mt-8 text-sm text-muted-foreground">
              Python, FastAPI, LangGraph, Next.js e PostgreSQL. Publicado no Vercel com banco Neon.
            </p>
          </div>
          <div className="lg:pt-2">
            <DemoEntry />
          </div>
        </section>

        <section id="como-funciona" className="border-t bg-card/40">
          <div className="mx-auto max-w-6xl px-6 py-16">
            <h2 className="text-2xl font-semibold tracking-tight">Como funciona</h2>
            <p className="mt-2 max-w-2xl text-muted-foreground">
              O cenário principal da demonstração leva uns dois minutos, do primeiro pedido à decisão do gerente.
            </p>
            <ol className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
              {STEPS.map((step, index) => (
                <li key={step.title} className="rounded-xl border bg-card p-5 shadow-sm">
                  <span className="flex size-7 items-center justify-center rounded-full bg-secondary text-sm font-semibold text-primary">
                    {index + 1}
                  </span>
                  <h3 className="mt-4 font-medium">{step.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{step.text}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>
      </main>

      <footer className="border-t">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-6 py-8 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
          <p>Feito por João Victor Gualchi.</p>
          <p className="max-w-xl sm:text-right">
            Restaurantes, pedidos e estoques são fictícios. O projeto não tem relação com o iFood nem com outros
            aplicativos de delivery.
          </p>
        </div>
      </footer>
    </div>
  );
}
