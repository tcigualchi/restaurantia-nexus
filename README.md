# RestaurantIA Nexus

**Autonomous Restaurant Intelligence Platform** — plataforma de inteligência operacional para restaurantes com
simulação reproduzível, previsão de demanda, agentes de IA especializados com ferramentas tipadas, aprovação humana
durável e trilha de auditoria.

> **Projeto de portfólio com dados 100% sintéticos.** Restaurantes, cardápios, pedidos e estoques são fictícios.
> Não há integração nem vínculo com iFood ou qualquer marketplace de delivery.

![Command Center após o cenário principal](docs/assets/screenshots/overview.webp)

<details>
<summary><b>English summary</b></summary>

RestaurantIA Nexus is a portfolio project that shows how to build an agentic AI system that is safe to put in front
of operations: a deterministic restaurant simulator feeds an event-sourced PostgreSQL core; threshold detectors open
incidents; a LangGraph orchestrator runs Operations, Inventory and Forecasting agents through typed, permissioned,
tenant-scoped tools; deterministic policies (not the LLM) generate candidate actions; sensitive actions wait for a
durable human approval, are re-validated at execution time and recorded in an append-only audit log. Demand
forecasts come from statistical models evaluated with a temporal backtest (WAPE/MAE, measured interval coverage).
Everything runs end to end in a deterministic, clearly labelled no-LLM mode, and any OpenAI-compatible model can be
plugged in. The same code runs with Docker Compose (API + worker) or fully serverless on Vercel (Services: Next.js +
FastAPI, no background process). 164 backend tests (unit, PostgreSQL integration, API security) and 3 Playwright
end-to-end tests run in CI.
</details>

---

## O que funciona hoje (Fase 1 + partes das Fases 2–3)

| Área | Status | O que está implementado |
| --- | --- | --- |
| Command Center | ✅ | KPIs calculados de dados persistidos (pedidos, fila, p90 de preparo vs SLA, perdas por ruptura, receita, incidentes, aprovações), gráficos e feed ao vivo (polling leve de `/live`; SSE disponível para integrações) |
| Simulation Lab | ✅ | 4 cenários reproduzíveis (seed + relógio simulado): *pico + estoque crítico*, *pico*, *ruptura*, *atraso na cozinha*; iniciar, pausar, avançar, reiniciar; inspetor de eventos |
| Agentes | ✅ 3 de 5 | **Operations**, **Inventory** e **Forecasting** + orquestrador **LangGraph** (checkpoints em memória ou PostgreSQL). Knowledge (RAG) e Customer Experience estão no roadmap |
| Ferramentas tipadas | ✅ | 6 ferramentas read-only com schema Pydantic estrito, allowlist por agente, orçamento de chamadas e tenant injetado pelo servidor |
| Approval Center | ✅ | Aprovação durável com RBAC, expiração, justificativa obrigatória na rejeição, controle otimista de versão, revalidação e execução única |
| AI Control Room | ✅ | Trace persistido passo a passo (triagem, chamadas de ferramenta, resultados, conclusões, plano, pedidos de aprovação), flags de prompt injection |
| Forecasting | ✅ | Baselines sazonais, seleção na semana de validação, métricas na semana de teste, intervalos de 80% com cobertura empírica medida, ajuste por ritmo observado |
| Eventos | ✅ | Fila em PostgreSQL com idempotência, ordem por tenant, retentativas com backoff, dead-letter e reprocessamento |
| Multi-tenancy e segurança | ✅ | Sandbox isolado por visitante, RBAC por restaurante, 404 para acesso cruzado, BFF com cookie httpOnly, CSP, rate limits, auditoria append-only |
| Deploy | ✅ | Docker Compose (API + worker + web + PostgreSQL) ou **Vercel Services** em modo serverless (sem worker: cada consulta do painel avança o trabalho do tenant), banco Neon via Marketplace e migrações no build |
| Knowledge Base (RAG) | 🛣 Fase 3 | pgvector já está na imagem do banco; ingestão, busca híbrida e citações ainda não implementadas |
| Evaluation Lab (100+ casos) | 🛣 Fase 4 | Harness offline já existe (`nexus.agents.harness`); dataset versionado e runner ainda não |

## Demonstração principal (2 minutos)

1. Abra a aplicação e clique em **Entrar no modo demo** (persona *Gerente*). Você recebe um sandbox privado com dois restaurantes sintéticos.
2. Em **Simulation Lab**, inicie **Pico de pedidos + estoque crítico** (seed 42).
3. O simulador gera pedidos e consumo de estoque; o painel atualiza em tempo real.
4. Por volta de 18h54 (relógio simulado), os detectores abrem um incidente: a costela vai acabar antes da reposição.
5. O orquestrador aciona **Operations** (utilização projetada da cozinha ~124%), **Inventory** (ingrediente crítico e itens afetados) e **Forecasting** (consumo previsto com intervalo de 80%).
6. Políticas determinísticas propõem uma compra emergencial e pausas de itens, com evidências ligadas aos passos do trace.
7. O relógio pausa; as ações aguardam no **Approval Center**.
8. Aprove a compra, rejeite (com justificativa) a pausa do *Burger de Costela* e aprove a do *Pastel*. Só o que foi aprovado e revalidado é executado.
9. Dashboard, estoque (pedido de compra a caminho/recebido), **AI Control Room** e **Audit Log** refletem as decisões; um segundo incidente não repropõe a ação rejeitada.
10. **Reiniciar** recria o sandbox e reproduz exatamente os mesmos eventos.

Se nenhum LLM estiver configurado, os agentes rodam em **modo determinístico** (planos de ferramentas fixos e resumos por
template). A interface rotula isso em toda execução — nenhum texto pré-programado é apresentado como inferência de IA.

| Approval Center | AI Control Room |
| --- | --- |
| ![Approval Center](docs/assets/screenshots/approval-center.webp) | ![AI Control Room](docs/assets/screenshots/ai-control-room.webp) |
| **Simulation Lab** | **Forecasting** |
| ![Simulation Lab](docs/assets/screenshots/simulation-lab.webp) | ![Forecasting](docs/assets/screenshots/forecasting.webp) |

🎬 **Vídeo da demo** (1min40, sem áudio, gravado automaticamente com Playwright): [`docs/assets/demo.mp4`](docs/assets/demo.mp4).
Mais capturas (tema escuro, mobile, auditoria) em [`docs/assets/screenshots`](docs/assets/screenshots). Roteiro para uma versão narrada: [`docs/demo-script.md`](docs/demo-script.md).

## Arquitetura

```mermaid
flowchart LR
  subgraph Browser
    UI[Next.js UI<br/>React 19 · Tailwind 4]
  end
  subgraph Web["apps/web (Next.js 16)"]
    BFF[BFF proxy<br/>cookie httpOnly → Bearer]
  end
  subgraph API["apps/api (FastAPI · modular monolith)"]
    R[REST · /live · SSE<br/>RBAC · tenant scope]
    APPR[Approval service<br/>revalidate + execute once]
    Q[Read model / queries]
  end
  subgraph Worker["worker (Docker) ou pump em /live (Vercel)"]
    SIM[Simulador determinístico<br/>1 tick = 1 min]
    EV[Fila de eventos<br/>idempotente · DLQ]
    DET[Detectores]
    ORCH[Orquestrador LangGraph]
    AG[Operations · Inventory · Forecasting]
    TOOLS[Ferramentas tipadas<br/>read-only]
  end
  DB[(PostgreSQL<br/>eventos · pedidos · estoque<br/>agentes · aprovações · auditoria)]
  LLM[[LLM OpenAI-compatible<br/>opcional]]

  UI <--> BFF <--> R
  R --> APPR --> DB
  R --> Q --> DB
  SIM --> EV --> DB
  EV --> DET --> ORCH --> AG --> TOOLS --> DB
  ORCH -->|propõe| APPR
  AG -.-> LLM
```

Decisões principais (detalhes em [`docs/adr`](docs/adr)):

- **Monólito modular + worker** com o mesmo código ([ADR 0001](docs/adr/0001-modular-monolith.md)).
- **PostgreSQL como fila de eventos** com `SKIP LOCKED`, locks consultivos por tenant e dead-letter ([ADR 0002](docs/adr/0002-postgres-event-queue.md)).
- **Simulação em lockstep**: o relógio pausa em pontos de decisão, o que torna o replay determinístico ([ADR 0003](docs/adr/0003-lockstep-simulation.md)).
- **LLM explica, política decide**: ações candidatas vêm de fórmulas auditáveis; o modelo só ordena e resume ([ADR 0004](docs/adr/0004-deterministic-policies.md)).
- **BFF com cookie httpOnly** em vez de token no navegador ([ADR 0005](docs/adr/0005-bff-session.md)).
- **Baseline estatístico honesto** para previsão ([ADR 0006](docs/adr/0006-forecasting-baseline.md)).
- **Serverless sem worker**: no Vercel, o trabalho de fundo roda sob demanda a cada consulta do painel, com o mesmo código ([ADR 0007](docs/adr/0007-serverless-pump.md)).

Visão completa: [`docs/architecture/overview.md`](docs/architecture/overview.md) · Segurança: [`docs/security.md`](docs/security.md).

## Stack

| Camada | Tecnologias |
| --- | --- |
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4, componentes no estilo shadcn/ui (Radix), Recharts, SWR |
| Backend | Python 3.12+, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, psycopg 3 |
| Agentes | LangGraph 1.x (StateGraph + checkpointer), provedor OpenAI-compatible via httpx (timeouts, retry, fallback rotulado) |
| Dados | PostgreSQL 16 (imagem com pgvector para a Fase 3), fila de eventos transacional |
| ML | NumPy: baselines sazonais, backtest temporal, intervalos com sobre-dispersão estimada |
| Qualidade | pytest (+ cobertura), Ruff, mypy `--strict`, ESLint, `tsc`, Playwright |
| Infra | Docker Compose, Dockerfiles multi-stage não-root, Vercel Services (Next.js + FastAPI) com Neon, GitHub Actions (lint, tipos, testes, build, e2e, auditoria de dependências, gitleaks) |

## Como rodar

### Opção A — Docker Compose (recomendado)

```bash
cp .env.example .env          # opcional: todos os valores têm padrão seguro para uso local
docker compose up --build
# abra http://localhost:3000  →  "Entrar no modo demo"
```

Serviços: `db` (PostgreSQL 16 + pgvector), `api` (migra e faz seed ao iniciar), `worker` (simulação, eventos, agentes) e `web`.
A API fica em `http://localhost:8000` (OpenAPI em `/docs`).

### Opção B — Desenvolvimento local

Pré-requisitos: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 22, PostgreSQL 16.

```bash
# API + worker
cd apps/api
uv sync
export DATABASE_URL=postgresql+psycopg://nexus:nexus@localhost:5432/nexus
uv run alembic upgrade head && uv run nexus-seed
uv run uvicorn nexus.main:app --reload --port 8000     # terminal 1
uv run nexus-worker                                    # terminal 2 (ou EMBEDDED_WORKER=true na API)

# Web
cd apps/web
npm ci
API_INTERNAL_URL=http://localhost:8000 npm run dev    # http://localhost:3000
```

### Opção C — Vercel (serverless)

Um único projeto Vercel com dois serviços ([`vercel.json`](vercel.json)): `web` (Next.js, público) e `api` (FastAPI,
privado, acessado pelo BFF via *service binding*), mais um banco **Neon** conectado pelo Marketplace. Não há worker: no
modo serverless cada consulta do painel a `/live` avança a simulação, a fila de eventos e os agentes daquele tenant, e
nada roda (nem custa) quando ninguém está olhando. As migrações e o seed rodam no build. Passo a passo completo, com as
variáveis de ambiente, em [`docs/deploy.md`](docs/deploy.md).

### Usando um LLM

Por padrão `LLM_PROVIDER=deterministic`. Para usar um modelo, configure no **servidor** (nunca no frontend):

```bash
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.openai.com/v1      # ou um gateway, Ollama (http://ollama:11434/v1), vLLM...
LLM_API_KEY=...                              # segredo: variável de ambiente, nunca commitado
LLM_MODEL=<modelo com suporte a tool calling>
```

O caminho com LLM é coberto por testes com um provedor simulado (tool calling, argumentos inválidos, fatos sem
evidência removidos, ações inventadas ignoradas, indisponibilidade → fallback rotulado). **Ele não foi validado contra
um modelo real neste ambiente**; custo por tarefa aparece como N/A até você configurar os preços do seu provedor.

## Testes e qualidade

```bash
cd apps/api
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy                               # strict
uv run pytest --cov=nexus                 # integração/segurança usam TEST_DATABASE_URL (PostgreSQL descartável)

cd apps/web && npm run lint && npx next typegen && npm run typecheck && npm run build

cd tests/e2e && npm ci && npx playwright install chromium && npx playwright test   # stack precisa estar rodando
```

Resultados da última execução local (detalhes e metodologia em [`docs/benchmarks/results.md`](docs/benchmarks/results.md)):

| Verificação | Resultado |
| --- | --- |
| Testes backend | **164 passando** — 100 unitários + 64 de integração/segurança contra PostgreSQL real |
| Cobertura (backend) | **~90%** de linhas+ramos (`pytest --cov`) |
| E2E (Playwright) | **3 passando** — fluxo principal com aprovação/rejeição, RBAC do operador, navegação mobile; rodados nos dois modos (API + worker, e serverless sem worker) |
| Lint / tipos | Ruff, mypy strict, ESLint e `tsc` sem erros; `next build` ok |
| Migrações | `alembic check` sem divergência entre modelos e migração |
| Build Vercel | `vercel build` (CLI 65.12.1) conclui os dois serviços; o hook do build migra e semeia um banco vazio |

O que os testes garantem, entre outros: mesmo seed → mesmos eventos; pipeline SQL idêntico à projeção de referência
(teste diferencial); eventos duplicados sem efeito duplicado; retentativa → dead-letter → reprocessamento; nada sensível
executa sem aprovação válida; decisão dupla não executa duas vezes; aprovação expirada, papel insuficiente e acesso
cruzado bloqueados; auditoria imune a UPDATE/DELETE/TRUNCATE; tokens forjados/expirados rejeitados; prompt injection
marcado e sem efeito.

### Métricas medidas (dados sintéticos)

- **Previsão (semana de teste, item × hora):** média sazonal de 4 semanas com WAPE **33,9%** vs **40,5%** do ingênuo semanal
  e **43,3%** do ingênuo diário (Aurora); cobertura empírica do intervalo de 80%: **89%**.
- **Cenário principal, 10 seeds:** aprovar as propostas → **0** pedidos perdidos em média; aprovar só a compra → **8,2**;
  rejeitar tudo → **55,9** (≈ R$ 4.766 por execução). O simulador assume que clientes trocam de item quando um prato é
  pausado — é um resultado do modelo de simulação, não evidência de desempenho real.
- **Latência (modo determinístico):** execução completa dos agentes p50 **100 ms** / p95 **134 ms**; chamada de ferramenta
  p50 **4 ms** / p95 **11 ms**; tick de simulação p50 **29 ms** / p95 **61 ms**.
- **Não medido ainda (N/A):** task success rate e tool-call accuracy em dataset de avaliação, faithfulness de RAG e custo
  por tarefa com LLM real — dependem das Fases 3–4 e de um provedor configurado.

## Segurança (resumo)

- LLM nunca acessa SQL, segredos ou ações destrutivas: só ferramentas read-only com schema estrito; tenant e horário vêm do servidor.
- Ações sensíveis passam por aprovação humana durável (RBAC, expiração, versão, revalidação, execução única) e ficam na auditoria.
- Conteúdo de terceiros (observações de clientes) é marcado como não confiável e tentativas de injection são sinalizadas no trace.
- Isolamento por tenant em todas as consultas; acesso cruzado responde 404; sandboxes demo expiram e são apagados com sua auditoria.
- Sessão em cookie httpOnly via BFF; CSP restritiva; CORS por allowlist; rate limits; limites de corpo; logs JSON com redação de segredos.

Detalhes e ameaças conhecidas em [`docs/security.md`](docs/security.md).

## Estrutura

```
apps/api/            FastAPI + worker (pacote `nexus`)
  src/nexus/domain/       regras puras: simulação, projeção de referência, métricas, previsão, políticas, guardrails, RBAC
  src/nexus/agents/       ferramentas tipadas, provedores LLM, agentes especialistas, orquestrador LangGraph, harness offline
  src/nexus/application/  serviços: eventos, simulação, agentes, aprovações, demo, auditoria, consultas
  src/nexus/infra/        SQLAlchemy (modelos, sessão, read model)
  src/nexus/api/          rotas REST, /live e SSE, dependências de auth/tenant, middleware
  src/nexus/data/         catálogo sintético dos restaurantes (dados fictícios)
  migrations/             Alembic
  tests/                  unit · integration · security
  scripts/                benchmarks reproduzíveis e hook de build do Vercel (migrações + seed)
  asgi.py                 entrypoint da função Python no Vercel
apps/web/            Next.js (UI + BFF)
tests/e2e/           Playwright
vercel.json          serviços do Vercel (web público, api privada via binding)
docs/                arquitetura, ADRs, API, segurança, deploy, benchmarks, roadmap, case study
```

Os serviços `services/event-worker` e `services/forecasting` sugeridos inicialmente foram mantidos como **módulos do
mesmo pacote** com processos separados, para não duplicar modelos e regras ([ADR 0001](docs/adr/0001-modular-monolith.md)).

## Deploy

Guia passo a passo para **Vercel Services (web + API) + Neon (PostgreSQL)** em [`docs/deploy.md`](docs/deploy.md),
com a alternativa de qualquer host Docker. O build de produção foi validado localmente com o Vercel CLI; o deploy em si
depende da sua conta Vercel e não foi executado a partir deste ambiente.

## Limitações conhecidas

- Agentes Knowledge (RAG) e Customer Experience, Evaluation Lab com 100+ casos e OpenTelemetry/Langfuse ainda não existem.
- Caminho com LLM real não validado aqui; o modo demo usa o modo determinístico rotulado.
- Rate limit em memória por instância (adequado para uma réplica; ver ADR 0005 para escalar).
- O histórico de vendas usado na previsão é sintético e gerado deterministicamente; não há dados reais.
- Pedidos de compra e fornecedores são simulados — nenhum sistema externo é acionado.
- As imagens Docker não podem ser construídas no ambiente de desenvolvimento usado aqui (Docker Hub indisponível). Elas
  foram construídas e executadas com sucesso no Docker Desktop (Windows), e o job `docker` do CI também as constrói.
- No Vercel (modo serverless) a simulação só avança enquanto alguém está com o painel aberto, e o plano Hobby tem cotas
  mensais (CPU, memória, invocações; Neon Free: 100 CU-hora por projeto). Veja [`docs/deploy.md`](docs/deploy.md).

## Roadmap

Backlog priorizado por fase em [`docs/roadmap.md`](docs/roadmap.md). Próximo incremento: Fase 2 (OpenTelemetry/Langfuse,
interrupt nativo do LangGraph para HITL, falhas controladas) e Fase 3 (RAG com pgvector e citações).

## Case study

[`docs/portfolio-case-study.md`](docs/portfolio-case-study.md) — versão em português e inglês, com problema, decisões,
métricas medidas, aprendizados e texto curto para candidaturas.
