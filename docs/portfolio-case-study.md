# Case study — RestaurantIA Nexus

*Português primeiro; English version below.*

---

## 🇧🇷 Português

### Problema
Em horários de pico, restaurantes perdem dinheiro por dois motivos que se alimentam: a cozinha passa da capacidade e
ingredientes-chave acabam antes da reposição. As decisões que evitam o prejuízo (comprar com urgência, tirar um item
do cardápio, reorganizar a produção) precisam ser tomadas em minutos, com dados espalhados entre PDV, estoque e histórico.

### Público-alvo
Gerentes de operação de restaurantes com delivery e salão — e, como peça de portfólio, times que avaliam engenharia de IA
aplicada: agentes com ferramentas, avaliação, segurança e produto.

### Solução
Uma plataforma em que **agentes especializados investigam e propõem**, **modelos estatísticos quantificam** e **humanos
decidem**. Um simulador determinístico gera a operação; detectores abrem incidentes; um orquestrador LangGraph aciona os
agentes de Operações, Estoque e Previsão por meio de ferramentas tipadas; políticas auditáveis transformam os achados em
ações candidatas; ações sensíveis esperam aprovação, são revalidadas e auditadas.

### Arquitetura (resumo)
Next.js 16 (UI + BFF com cookie httpOnly) → FastAPI (monólito modular) + worker → PostgreSQL (log de eventos idempotente,
projeções, traces dos agentes, aprovações e auditoria append-only). Detalhes em `docs/architecture/overview.md`.

### Escolhas técnicas e por quê
- **PostgreSQL como fila de eventos** (`SKIP LOCKED`, locks de transação por tenant, DLQ): efeitos e auditoria na mesma
  transação, sem infraestrutura extra.
- **Simulação em lockstep**: o relógio pausa nos pontos de decisão, então *mesma seed + mesmas decisões = mesmo resultado*.
- **Mesmo código em Docker e no Vercel**: com worker no Docker; no Vercel, sem processo contínuo, cada consulta do
  painel avança o trabalho do tenant (ticks pelo tempo decorrido, `SKIP LOCKED`). Custo zero quando ninguém usa.
- **LLM explica, política decide**: candidatos vêm de fórmulas; o modelo só ordena e resume — não cria nem remove ações.
- **Previsão honesta**: seleção na validação, métricas no teste, intervalos com cobertura medida, ajuste de ritmo explícito.
- **Modo determinístico rotulado**: a demo funciona sem chave de API e nunca apresenta template como inferência.

### Responsabilidade de cada agente
- **Operations:** fila, p90 de preparo vs SLA, capacidade efetiva e utilização projetada; prioriza pedidos antigos.
- **Inventory:** ingredientes em risco, tempo até ruptura, lead time, itens afetados pelas fichas técnicas.
- **Forecasting:** demanda e consumo das próximas horas com intervalo de 80% e limitações explícitas.
- **Orquestrador:** triagem, plano, resumo e pedidos de aprovação. *(Knowledge/RAG e Customer Experience: roadmap.)*

### Controles de segurança
Ferramentas somente leitura com schema estrito e tenant injetado pelo servidor; aprovação humana com RBAC, expiração,
versão, execução única e revalidação; prompt injection marcado e sem poder de efeito; isolamento por tenant com 404;
JWT em cookie httpOnly via BFF; CSP; rate limits e quotas; auditoria protegida por trigger. Ver `docs/security.md`.

### Métricas realmente medidas (dados sintéticos)
- 164 testes de backend (100 unitários + 64 de integração/segurança com PostgreSQL), ~90% de cobertura; 3 testes e2e.
- Previsão: WAPE de **33,9%** vs **40,5%** do ingênuo semanal na semana de teste; cobertura de **89%** para intervalo de 80%.
- Cenário principal em 10 seeds: aprovar as propostas → **0** pedidos perdidos; só a compra → **8,2**; rejeitar tudo →
  **55,9** pedidos (≈ R$ 4,8 mil) — sob a premissa de substituição de pratos do simulador.
- Agentes (modo determinístico): p50 **100 ms** / p95 **134 ms** por execução completa.
- Não medido ainda: métricas de avaliação de agentes com dataset, RAG e custo com LLM real (Fases 3–4).

### Dificuldades e aprendizados
- **Teste diferencial pegou um bug de fuso horário**: a projeção SQL divergia da projeção em memória porque o perfil de
  demanda usava a hora UTC do banco. Comparar duas implementações do mesmo contrato foi mais eficaz que testes isolados.
- **Carga fantasma na cozinha**: pedidos que seriam recusados por falta de insumo ainda ocupavam linhas de preparo; o
  simulador passou a receber o estoque e só agendar pedidos aceitáveis.
- **Determinismo exige decidir onde o tempo para**: sem o lockstep, o tempo de reação humano mudava a simulação.
- **Agentes seguros são um problema de arquitetura**, não de prompt: a defesa principal é não existir ferramenta com efeito.
- **Restrições de ambiente**: sem acesso inicial a registries de pacotes, a lógica de domínio foi escrita e testada primeiro,
  com dependências mínimas — o que acabou reforçando a separação entre domínio e infraestrutura.
- **O primeiro `docker compose up` real achou o que os testes não cobriam**: o compose passava variáveis opcionais vazias
  que a configuração rejeitava, e o checkpointer do LangGraph não se recuperava depois de o banco reiniciar. Os dois
  viraram testes de regressão (contrato compose ↔ configuração e perda de conexão).

### Vídeo
`docs/assets/demo.mp4` — walkthrough de 1min40 sem áudio, gravado automaticamente (Playwright). Roteiro para versão narrada em `docs/demo-script.md`.

### Próximos passos
OpenTelemetry/Langfuse, HITL nativo do LangGraph, Knowledge Agent com RAG (pgvector, busca híbrida, citações), Customer
Experience Agent, Evaluation Lab com 100+ casos e deploy público com quotas.

### Texto curto para candidatura (AI Engineer)
> Construí o **RestaurantIA Nexus**, um projeto de portfólio de IA agêntica para operações de restaurante com dados
> sintéticos: simulador determinístico, fila de eventos idempotente em PostgreSQL, orquestração **LangGraph** de agentes
> com **ferramentas tipadas e escopo por tenant**, políticas determinísticas para ações, **aprovação humana revalidada** e
> auditoria append-only. A previsão de demanda usa baselines estatísticos avaliados em backtest temporal (WAPE 33,9% vs
> 40,5% do ingênuo). Stack: FastAPI, SQLAlchemy, Next.js 16, TypeScript; 164 testes de backend, e2e com Playwright e CI.
> Não é um produto em produção nem tem vínculo com plataformas de delivery.

---

## 🇺🇸 English

### Problem
At peak hours restaurants lose money in two compounding ways: the kitchen runs over capacity and key ingredients run out
before replenishment. The decisions that prevent losses — rush purchases, pausing a menu item, re-prioritising
production — must be made in minutes, with data scattered across POS, inventory and history.

### Audience
Operations managers of delivery/dine-in restaurants — and, as a portfolio piece, teams evaluating applied AI engineering:
tool-using agents, evaluation, safety and product sense.

### Solution
A platform where **specialised agents investigate and propose**, **statistical models quantify** and **humans decide**.
A deterministic simulator drives operations; detectors open incidents; a LangGraph orchestrator runs Operations,
Inventory and Forecasting agents through typed tools; auditable policies turn findings into candidate actions; sensitive
actions wait for approval, are re-validated at execution time and audited.

### Architecture
Next.js 16 (UI + BFF with an httpOnly session cookie) → FastAPI modular monolith + worker → PostgreSQL (idempotent event
log, projections, agent traces, approvals, append-only audit). See `docs/architecture/overview.md`.

### Key technical choices
- **PostgreSQL as the event queue** (`SKIP LOCKED`, per-tenant transaction locks, dead-letter): effects and audit commit atomically.
- **Lock-step simulation**: the clock pauses at decision points, so *same seed + same decisions = same run*.
- **Same code on Docker and Vercel**: a worker under Docker; on Vercel, with no long-running process, each dashboard
  poll advances that tenant's work (time-based ticks, `SKIP LOCKED`). Nothing runs, or costs, when nobody is watching.
- **The LLM explains, policies decide**: candidates come from formulas; a model may only rank and summarise them.
- **Honest forecasting**: selection on a validation week, metrics on a held-out week, measured interval coverage.
- **Clearly labelled deterministic mode**: the demo works without an API key and never presents templates as inference.

### Agent responsibilities
Operations (queue, p90 vs SLA, projected utilisation), Inventory (at-risk ingredients, time to stock-out, lead time,
affected items), Forecasting (demand and consumption with 80% intervals) and the Orchestrator (triage, plan, summary,
approval requests). Knowledge (RAG) and Customer Experience agents are on the roadmap.

### Safety controls
Read-only, strictly typed tools with server-injected tenant scope; durable human approval with RBAC, expiry,
versioning, single execution and re-validation; prompt-injection marking with no path to side effects; tenant isolation
with indistinguishable 404s; JWT in an httpOnly cookie behind a BFF; CSP; rate limits and quotas; trigger-protected audit log.

### Measured results (synthetic data)
- 164 backend tests (100 unit + 64 PostgreSQL integration/security), ~90% coverage; 3 Playwright end-to-end tests.
- Forecasting: **33.9%** WAPE vs **40.5%** for the seasonal-naive baseline on the test week; **89%** empirical coverage of 80% intervals.
- Featured scenario over 10 seeds: approving proposals → **0** lost orders; purchase only → **8.2**; rejecting everything →
  **55.9** lost orders (≈ BRL 4.8k), under the simulator's dish-substitution assumption.
- Deterministic agent runs: p50 **100 ms** / p95 **134 ms** end to end.
- Not yet measured: dataset-based agent evaluation, RAG faithfulness and real-LLM cost (phases 3–4).

### Challenges and lessons
- A **differential test caught a timezone bug**: the SQL projection diverged from the in-memory reference because the
  demand profile read the database's UTC hour.
- **Phantom kitchen load**: orders later rejected for missing stock still occupied prep lines; the engine now receives
  stock and only schedules orders that will be accepted.
- **Determinism requires choosing where time stops**; without lock-step, human reaction time changed the simulation.
- **Safe agents are an architecture problem, not a prompt problem**: the main defence is the absence of side-effecting tools.
- **The first real `docker compose up` found what the tests did not cover**: Compose passed empty optional variables that
  the settings rejected, and the LangGraph checkpointer did not recover after a database restart. Both are now regression
  tests (compose ↔ settings contract and connection loss).

### Short blurb for applications
> I built **RestaurantIA Nexus**, a portfolio agentic-AI system for restaurant operations on synthetic data: a deterministic
> simulator, an idempotent PostgreSQL event queue, **LangGraph** orchestration of agents with **typed, tenant-scoped tools**,
> deterministic action policies, **re-validated human approvals** and an append-only audit trail. Demand forecasting uses
> statistical baselines evaluated with a temporal backtest (33.9% vs 40.5% WAPE for the naive baseline). Stack: FastAPI,
> SQLAlchemy, Next.js 16, TypeScript; 164 backend tests, Playwright e2e and CI. Not a production product and not affiliated
> with any delivery platform.
