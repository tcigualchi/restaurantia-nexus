# Estudo de caso: RestaurantIA Nexus

Português primeiro. A versão em inglês está [no fim da página](#english).

Demonstração: [restaurantia-nexus.vercel.app](https://restaurantia-nexus.vercel.app) · Código:
[github.com/tcigualchi/restaurantia-nexus](https://github.com/tcigualchi/restaurantia-nexus)

## O problema

No horário de pico, um restaurante costuma perder dinheiro de duas formas que se alimentam: a cozinha passa da
capacidade e algum ingrediente importante acaba antes de a reposição chegar. As decisões que evitam o prejuízo
(comprar com urgência, tirar um prato do cardápio, reorganizar a produção) precisam ser tomadas em minutos, com dados
espalhados entre o sistema de pedidos, o estoque e o histórico de vendas.

Esse cenário me pareceu bom para estudar agentes de IA porque tem dados de verdade para consultar, decisões com
consequência e um ponto claro em que uma pessoa precisa dar a palavra final.

## O que eu construí

Uma aplicação web em que agentes investigam e sugerem, modelos estatísticos estimam a demanda e o gerente decide.

- Um simulador determinístico gera a operação de dois restaurantes fictícios, minuto a minuto.
- Detectores percebem quando a fila ou o estoque saem do normal e abrem um incidente.
- Um orquestrador em LangGraph aciona três agentes (operação, estoque e previsão), que consultam os dados por
  ferramentas de leitura com schema estrito.
- Regras fixas transformam o diagnóstico em sugestões de ação, cada uma com justificativa e evidências.
- O gerente aprova ou rejeita. O que foi aprovado é conferido de novo e executado uma única vez, e tudo fica num
  registro de auditoria que não aceita alteração.

O frontend é Next.js 16 com um BFF que guarda a sessão em cookie httpOnly. O backend é FastAPI com SQLAlchemy, e o
PostgreSQL guarda os eventos, as projeções, os passos dos agentes, as aprovações e a auditoria. Está publicado no
Vercel, com o banco no Neon.

## Decisões técnicas

- Usei o PostgreSQL como fila de eventos (`SKIP LOCKED`, lock por restaurante, dead-letter). O efeito de cada evento e
  o registro de auditoria entram na mesma transação, e não precisei de outro serviço.
- A simulação roda em lockstep: o relógio para enquanto os agentes analisam e enquanto o gerente decide. Com a mesma
  seed e as mesmas decisões, o resultado é sempre o mesmo, o que permitiu testar o fluxo inteiro.
- O LLM explica, mas não decide. As ações candidatas vêm de fórmulas (consumo previsto, estoque de segurança, tempo de
  reposição, receita por grama de ingrediente). O modelo só pode ordenar e resumir, e não consegue criar nem remover
  ações.
- Na previsão, escolhi o modelo numa semana de validação e reportei as métricas numa semana de teste. Os intervalos
  têm a cobertura medida, e o ajuste pelo ritmo do dia aparece explicitamente na tela.
- Sem chave de API, os agentes rodam num modo determinístico que a interface identifica em toda execução. Nenhum texto
  pronto é apresentado como se fosse inferência de um modelo.
- O mesmo código roda em Docker, com um worker, e no Vercel, onde não há processo contínuo no plano gratuito. Lá,
  cada consulta do painel avança o trabalho daquele restaurante pelo tempo decorrido. Quando ninguém está usando, nada
  roda e nada custa.

## Os agentes

- Operação: tamanho da fila, p90 do tempo de preparo contra o SLA, capacidade da cozinha e utilização prevista.
- Estoque: ingredientes em risco, tempo até acabarem, tempo de reposição e pratos afetados pelas fichas técnicas.
- Previsão: demanda e consumo das próximas horas, com intervalo de 80% e as limitações do modelo.
- Orquestrador: decide quem é acionado, monta o plano, escreve o resumo e abre os pedidos de aprovação.

Os agentes de base de conhecimento (RAG) e de atendimento ao cliente estão no roadmap.

## Segurança

Comecei pela arquitetura, e não pelo prompt. As ferramentas só leem e o restaurante é injetado pelo servidor. As ações
sensíveis passam por aprovação com permissão por papel, prazo de validade, controle de versão, execução única e nova
conferência antes de rodar. Textos de clientes são tratados como não confiáveis. Um restaurante não enxerga o outro
(a resposta é 404). A sessão fica em cookie httpOnly, há CSP, limites de requisição e cotas para a demonstração, e um
trigger no banco protege a auditoria. Detalhes em [`security.md`](security.md).

## Resultados medidos (dados sintéticos)

- 164 testes de backend (100 unitários e 64 de integração e segurança com PostgreSQL), cerca de 90% de cobertura, e 3
  testes de ponta a ponta com Playwright.
- Previsão: WAPE de 33,9% contra 40,5% do ingênuo semanal na semana de teste. O intervalo de 80% cobriu 89% dos
  valores reais.
- Cenário principal em 10 seeds: aprovando as sugestões, 0 pedidos perdidos; aprovando só a compra, 8,2; rejeitando
  tudo, 55,9 pedidos (cerca de R$ 4,8 mil). Isso vale dentro da premissa do simulador de que o cliente troca de prato
  quando um item é pausado.
- Agentes no modo determinístico: p50 de 100 ms e p95 de 134 ms por execução completa.
- Ainda não medi: avaliação dos agentes com um conjunto de casos, RAG e custo com um LLM real.

## O que aprendi

- Um teste diferencial achou um bug de fuso horário. A projeção em SQL divergia da projeção de referência em memória
  porque o perfil de demanda usava a hora UTC do banco. Comparar duas implementações do mesmo contrato encontrou o
  problema mais rápido do que testes isolados.
- Pedidos que seriam recusados por falta de ingrediente ainda ocupavam a cozinha no simulador. Passei a mandar o
  estoque para o simulador, que só agenda os pedidos que de fato podem ser aceitos.
- Para ter determinismo, precisei decidir onde o tempo para. Sem o lockstep, o tempo de reação de cada pessoa mudava a
  simulação.
- Deixar um agente seguro é mais uma questão de arquitetura do que de prompt. A principal defesa é não existir
  ferramenta com efeito colateral ao alcance do modelo.
- No começo, eu não tinha acesso aos registros de pacotes. Escrevi e testei primeiro a lógica de domínio, com o mínimo
  de dependências, e isso acabou deixando a separação entre domínio e infraestrutura mais limpa.
- O primeiro `docker compose up` de verdade achou o que os testes não cobriam: o Compose passava variáveis opcionais
  vazias que a configuração rejeitava, e o checkpointer do LangGraph não se recuperava depois de o banco reiniciar.
  Os dois casos viraram testes de regressão.
- Publicar no Vercel me obrigou a repensar o worker. Em vez de manter um processo rodando, o trabalho de fundo passou a
  ser feito sob demanda a cada consulta do painel, com os mesmos passos e seguro sob concorrência.

## Próximos passos

Observabilidade com OpenTelemetry ou Langfuse, aprovação usando o `interrupt` nativo do LangGraph, o agente de base de
conhecimento com RAG (pgvector, busca híbrida e citações), o agente de atendimento ao cliente e um conjunto de
avaliação com mais de 100 casos.

## Texto curto para candidaturas

> Construí o RestaurantIA Nexus, um projeto de portfólio com agentes de IA na operação de um restaurante, usando dados
> sintéticos. Ele tem um simulador determinístico, uma fila de eventos idempotente em PostgreSQL, agentes orquestrados
> com LangGraph que só acessam dados por ferramentas tipadas e com escopo por restaurante, regras auditáveis para as
> ações, aprovação humana conferida antes da execução e auditoria que não aceita alteração. A previsão de demanda usa
> modelos estatísticos avaliados com backtest temporal (WAPE de 33,9% contra 40,5% do modelo ingênuo). Stack: FastAPI,
> SQLAlchemy, LangGraph, Next.js 16 e TypeScript, com 164 testes de backend, testes e2e com Playwright e CI. Está
> publicado no Vercel. Não é um produto em produção e não tem vínculo com plataformas de delivery.

---

## English

Live demo: [restaurantia-nexus.vercel.app](https://restaurantia-nexus.vercel.app)

### The problem

During a dinner rush, restaurants lose money in two ways that feed each other: the kitchen runs over capacity and a key
ingredient runs out before the next delivery. The decisions that prevent the loss (a rush purchase, pausing a dish,
reprioritising orders) have to be made in minutes, with data spread across the order system, inventory and sales
history. I picked this problem to study AI agents because it has real data to query, decisions with consequences and
an obvious point where a person should have the final word.

### What I built

A web app where agents investigate and suggest, statistical models estimate demand and the manager decides. A
deterministic simulator runs two fictional restaurants minute by minute; detectors open incidents; a LangGraph
orchestrator runs operations, inventory and forecasting agents that read data through strictly typed tools; fixed
rules turn the findings into candidate actions with evidence; the manager approves or rejects; approved actions are
re-validated, executed exactly once and written to an append-only audit log. Next.js 16 with a BFF (httpOnly session
cookie), FastAPI and PostgreSQL, deployed on Vercel with Neon.

### Key decisions

- PostgreSQL as the event queue (`SKIP LOCKED`, per-tenant locks, dead-letter), so effects and audit commit together.
- A lock-step simulation that pauses while agents work and while the manager decides, so the same seed and the same
  decisions always produce the same run.
- The LLM explains, the rules decide: candidates come from formulas, and a model may only rank and summarise them.
- Forecast models are selected on a validation week and reported on a held-out test week, with measured interval
  coverage.
- A clearly labelled deterministic mode, so the demo works without an API key and never passes templates off as
  model output.
- The same code runs on Docker with a worker and on Vercel without one: there, each dashboard poll advances that
  tenant's work based on elapsed time, and nothing runs when nobody is watching.

### Measured results (synthetic data)

- 164 backend tests (100 unit, 64 PostgreSQL integration and security), about 90% coverage, 3 Playwright end-to-end tests.
- Forecasting: 33.9% WAPE against 40.5% for the seasonal naive baseline on the test week; the 80% interval covered 89%
  of actual values.
- Featured scenario over 10 seeds: approving the suggestions leads to 0 lost orders, approving only the purchase to
  8.2 and rejecting everything to 55.9 (about BRL 4.8k), under the simulator's assumption that customers switch dishes.
- Deterministic agent runs: p50 of 100 ms and p95 of 134 ms end to end.
- Not measured yet: dataset-based agent evaluation, RAG quality and real LLM cost.

### What I learned

- A differential test caught a timezone bug: the SQL projection disagreed with the in-memory reference because the
  demand profile used the database's UTC hour.
- Orders that would be rejected for missing stock were still taking kitchen capacity; the simulator now receives the
  stock and only schedules orders that can be accepted.
- Determinism meant deciding where time stops. Without lock-step, human reaction time changed the simulation.
- Making agents safe is mostly an architecture problem: the main defence is that no tool with side effects is within
  the model's reach.
- The first real `docker compose up` found what tests did not cover (empty optional variables and a checkpointer that
  did not recover after a database restart). Both are regression tests now.
- Deploying to Vercel made me rethink the worker: background work now runs on demand on each dashboard poll, with the
  same steps and safe under concurrency.

### Short blurb for applications

> I built RestaurantIA Nexus, a portfolio project with AI agents in restaurant operations, on synthetic data: a
> deterministic simulator, an idempotent PostgreSQL event queue, LangGraph-orchestrated agents that only read data
> through typed, tenant-scoped tools, auditable rules for actions, human approvals that are re-validated before
> execution and an append-only audit trail. Demand forecasting uses statistical models evaluated with a temporal
> backtest (33.9% vs 40.5% WAPE for the naive baseline). Stack: FastAPI, SQLAlchemy, LangGraph, Next.js 16 and
> TypeScript, with 164 backend tests, Playwright end-to-end tests and CI. It is live on Vercel. It is not a production
> product and has no affiliation with any delivery platform.
