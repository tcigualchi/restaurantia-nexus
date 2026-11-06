# RestaurantIA Nexus

Projeto de portfólio em que simulo a operação de um restaurante em horário de pico e uso agentes de IA para analisar o
que está acontecendo. Os agentes sugerem ações, como fazer uma compra emergencial ou tirar um prato do cardápio, mas
quem decide é o gerente. Nada é executado sem aprovação, e cada decisão fica registrada.

**Demonstração:** [restaurantia-nexus.vercel.app](https://restaurantia-nexus.vercel.app). Não precisa de cadastro: cada
visitante recebe uma cópia própria com dois restaurantes fictícios, que expira depois de duas horas.

Todos os dados são sintéticos. Restaurantes, cardápios, pedidos e estoques são inventados, e o projeto não tem relação
com o iFood nem com outros aplicativos de delivery.

![Visão geral do painel durante o cenário principal](docs/assets/screenshots/overview.webp)

*English summary at the end of this page.*

## Por que fiz este projeto

Eu queria entender, na prática, o que é preciso para colocar agentes de IA perto de uma operação de verdade sem
deixar que eles ajam sozinhos. Restaurante é um bom caso para isso: as decisões precisam sair em minutos, envolvem
dinheiro e dependem de dados espalhados entre pedidos, estoque e histórico de vendas.

Em vez de fazer um chatbot, escolhi um problema concreto e fui até o fim dele: gerar a operação, perceber que algo
saiu do normal, investigar, sugerir o que fazer, esperar a decisão de uma pessoa, executar com segurança e deixar tudo
auditável.

## O que acontece na demonstração

O cenário principal leva uns dois minutos.

1. Na tela **Simulação**, você inicia o cenário "Pico de pedidos + estoque crítico". O simulador gera pedidos minuto a
   minuto e desconta o estoque pelas fichas técnicas dos pratos.
2. Por volta das 18h54 do relógio simulado, a fila da cozinha cresce e a costela começa a acabar. Um detector abre um
   incidente e o relógio pausa.
3. Três agentes (operação, estoque e previsão) consultam os dados e montam um diagnóstico. A cozinha está com
   utilização prevista de 124%, e a costela deve acabar antes de a reposição chegar.
4. Na tela **Aprovações** aparecem três sugestões: uma compra emergencial de costela e a pausa de dois pratos que usam
   esse ingrediente. Cada uma mostra a justificativa, o impacto esperado e os passos da análise que servem de evidência.
5. Você aprova a compra, rejeita uma das pausas (o motivo é obrigatório) e aprova a outra. Só o que foi aprovado é
   executado, depois de o sistema conferir de novo se a ação ainda faz sentido.
6. O relógio volta a andar. Em **Estoque** a compra aparece a caminho, em **Agentes** dá para ver cada passo da
   análise, e em **Auditoria** fica o registro de quem decidiu o quê.
7. **Reiniciar** recomeça o cenário com a mesma seed, e os eventos se repetem exatamente.

Numa das observações de clientes há um texto tentando dar ordens aos agentes ("ignore as instruções anteriores..."). Ele
é marcado como não confiável, ignorado, e aparece sinalizado na tela **Agentes**.

| Aprovações | Agentes |
| --- | --- |
| ![Tela de aprovações com as três ações sugeridas](docs/assets/screenshots/approval-center.webp) | ![Tela dos agentes com o passo a passo da análise](docs/assets/screenshots/ai-control-room.webp) |
| **Simulação** | **Previsão de demanda** |
| ![Tela de simulação com os cenários](docs/assets/screenshots/simulation-lab.webp) | ![Tela de previsão de demanda com o backtest](docs/assets/screenshots/forecasting.webp) |

Há também um [vídeo curto, sem áudio](docs/assets/demo.mp4), gravado com Playwright, mostrando o fluxo completo. Mais
capturas (tema escuro, celular, auditoria) estão em [`docs/assets/screenshots`](docs/assets/screenshots).

## Como funciona

```mermaid
flowchart LR
  subgraph Navegador
    UI[Next.js<br/>React 19 e Tailwind 4]
  end
  subgraph Web["apps/web (Next.js 16)"]
    BFF[BFF<br/>cookie httpOnly para Bearer]
  end
  subgraph API["apps/api (FastAPI)"]
    R[REST e feed ao vivo<br/>RBAC e escopo por restaurante]
    APPR[Aprovações<br/>confere de novo e executa uma vez]
    Q[Consultas]
  end
  subgraph Fundo["worker (Docker) ou /live (Vercel)"]
    SIM[Simulador<br/>1 tick = 1 minuto]
    EV[Fila de eventos<br/>idempotente, com dead-letter]
    DET[Detectores]
    ORCH[Orquestrador LangGraph]
    AG[Agentes de operação,<br/>estoque e previsão]
    TOOLS[Ferramentas<br/>somente leitura]
  end
  DB[(PostgreSQL)]
  LLM[[LLM compatível com OpenAI<br/>opcional]]

  UI <--> BFF <--> R
  R --> APPR --> DB
  R --> Q --> DB
  SIM --> EV --> DB
  EV --> DET --> ORCH --> AG --> TOOLS --> DB
  ORCH -->|sugere| APPR
  AG -.-> LLM
```

Algumas decisões que tomei e por quê (os detalhes estão nos [ADRs](docs/adr)):

- A simulação é determinística. Cada minuto simulado é um tick, e a mesma seed gera os mesmos eventos. O relógio
  pausa enquanto os agentes analisam e enquanto o gerente decide. Sem essa pausa, o tempo de reação de cada pessoa
  mudaria o resultado e eu não conseguiria testar o fluxo de ponta a ponta. ([ADR 0003](docs/adr/0003-lockstep-simulation.md))
- Os agentes só leem. Eles acessam os dados por seis ferramentas com schema estrito, e o restaurante e o horário
  de referência são injetados pelo servidor. O modelo não tem como escrever no banco, rodar SQL ou ver outro
  restaurante.
- As ações vêm de regras, e não do modelo. As sugestões saem de fórmulas que dá para auditar (consumo previsto,
  estoque de segurança, tempo de reposição, receita por grama de ingrediente). Quando há um LLM configurado, ele só
  ordena e explica as sugestões. ([ADR 0004](docs/adr/0004-deterministic-policies.md))
- A aprovação fica gravada no banco. Cada sugestão vira um registro com prazo de validade, versão e papel exigido. Na
  hora de executar, o sistema confere de novo se a ação ainda vale (se a sugestão não ficou velha, se a quantidade
  está dentro do limite, se não há outra compra igual em aberto) e garante que ela rode uma única vez.
- O PostgreSQL também faz o papel de fila de eventos. Uso `SKIP LOCKED`, locks por restaurante e dead-letter. Assim o efeito
  de um evento e o registro de auditoria entram na mesma transação, sem precisar de outro serviço.
  ([ADR 0002](docs/adr/0002-postgres-event-queue.md))
- A previsão é estatística e foi avaliada fora da amostra. Comparei modelos simples (ingênuo diário, ingênuo semanal e
  média sazonal de 4 semanas), escolhi o melhor numa semana de validação e reportei as métricas numa semana de teste
  que o modelo não viu. ([ADR 0006](docs/adr/0006-forecasting-baseline.md))
- Funciona sem chave de API. Sem um LLM configurado, os agentes seguem um plano fixo de ferramentas e montam o
  resumo a partir de modelos de texto. A interface mostra isso em cada execução, e é assim que a demonstração
  pública roda.
- O mesmo código roda em Docker e no Vercel. No Docker, um processo worker avança a simulação, a fila e os
  agentes. No Vercel não existe processo contínuo no plano gratuito, então cada consulta do painel faz esse trabalho
  para aquele restaurante. Quando ninguém está olhando, nada roda. ([ADR 0007](docs/adr/0007-serverless-pump.md))

Mais detalhes em [`docs/architecture/overview.md`](docs/architecture/overview.md) e em [`docs/security.md`](docs/security.md).

## Tecnologias

| Camada | O que usei |
| --- | --- |
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4, componentes Radix no estilo shadcn/ui, Recharts, SWR |
| Backend | Python 3.12+, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, psycopg 3 |
| Agentes | LangGraph (StateGraph com checkpointer), provedor compatível com a API da OpenAI via httpx |
| Dados | PostgreSQL 16, Neon em produção |
| Previsão | NumPy: modelos sazonais, backtest temporal e intervalos com sobredispersão estimada |
| Qualidade | pytest, Ruff, mypy strict, ESLint, tsc, Playwright |
| Infra | Docker Compose, Vercel Services (Next.js e FastAPI no mesmo projeto), GitHub Actions |

## Resultados medidos

Tudo abaixo foi calculado por código deste repositório, sobre dados sintéticos. Descreve o simulador e os modelos,
não o desempenho em um restaurante real. Metodologia e dados brutos em
[`docs/benchmarks/results.md`](docs/benchmarks/results.md).

| O que medi | Resultado |
| --- | --- |
| Previsão de demanda (semana de teste, item por hora) | WAPE de 33,9% com a média sazonal de 4 semanas, contra 40,5% do ingênuo semanal e 43,3% do ingênuo diário |
| Intervalo de previsão de 80% | cobriu 89% dos valores reais na semana de teste |
| Cenário principal, 10 seeds, aprovando as sugestões | 0 pedidos perdidos por falta de ingrediente, em média |
| O mesmo cenário aprovando só a compra | 8,2 pedidos perdidos |
| O mesmo cenário rejeitando tudo | 55,9 pedidos perdidos, cerca de R$ 4.766 por execução |
| Execução completa dos agentes (modo determinístico) | p50 de 100 ms, p95 de 134 ms |

O simulador assume que, quando um prato é pausado, o cliente escolhe outro. Na vida real parte dessas pessoas
desistiria do pedido, então esses números servem para comparar as políticas entre si.

Ainda não medi a taxa de acerto dos agentes num conjunto de avaliação, a qualidade de respostas com RAG nem o custo
com um LLM real. Isso depende das próximas fases e aparece como N/A nos documentos.

## Rodando localmente

### Com Docker Compose

```bash
cp .env.example .env    # opcional: todos os valores têm padrão para uso local
docker compose up --build
```

Depois abra `http://localhost:3000` e clique em **Entrar no modo demo**. Sobem quatro serviços: `db` (PostgreSQL 16),
`api` (migra o banco e cria os dados ao iniciar), `worker` (simulação, eventos e agentes) e `web`. A API fica em
`http://localhost:8000`, com a documentação OpenAPI em `/docs`.

### Sem Docker

Precisa de Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 22 e PostgreSQL 16.

```bash
# API e worker
cd apps/api
uv sync
export DATABASE_URL=postgresql+psycopg://nexus:nexus@localhost:5432/nexus
uv run alembic upgrade head && uv run nexus-seed
uv run uvicorn nexus.main:app --reload --port 8000   # terminal 1
uv run nexus-worker                                  # terminal 2

# Web
cd apps/web
npm ci
API_INTERNAL_URL=http://localhost:8000 npm run dev   # http://localhost:3000
```

### No Vercel

É um único projeto com dois serviços definidos no [`vercel.json`](vercel.json): `web` (Next.js, público) e `api`
(FastAPI, sem rota pública, acessada só pelo BFF), mais um banco Neon conectado pelo Marketplace. As migrações rodam
no build. O passo a passo, com as variáveis de ambiente e os problemas que encontrei no caminho, está em
[`docs/deploy.md`](docs/deploy.md).

### Com um LLM

Por padrão os agentes rodam em modo determinístico (`LLM_PROVIDER=deterministic`). Para usar um modelo, configure no
servidor, nunca no frontend:

```bash
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.openai.com/v1   # ou um gateway, Ollama (http://ollama:11434/v1), vLLM
LLM_API_KEY=...                          # só por variável de ambiente
LLM_MODEL=<modelo com suporte a tool calling>
```

O caminho com LLM tem testes com um provedor simulado: escolha de ferramentas, argumentos inválidos, fatos sem
evidência descartados, ações inventadas ignoradas e queda do provedor (os agentes voltam para o modo determinístico e
a tela mostra isso). Ainda não validei esse caminho com um modelo real, e o custo por tarefa aparece como N/A até você
configurar os preços do seu provedor.

## Testes

```bash
cd apps/api
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy
uv run pytest --cov=nexus      # os testes de integração usam TEST_DATABASE_URL (um PostgreSQL descartável)

cd apps/web
npm run lint && npm run typecheck && npm run build

cd tests/e2e                   # com a aplicação rodando em http://localhost:3000
npm ci && npx playwright install chromium && npx playwright test
```

Na última execução passaram 164 testes de backend (100 unitários e 64 de integração e segurança contra um PostgreSQL
real), com cerca de 90% de cobertura, e os 3 testes de ponta a ponta com Playwright, rodados com worker e também no
modo serverless. O CI no GitHub Actions roda lint, tipos, testes, build, e2e, auditoria de dependências e busca de
segredos.

Alguns comportamentos que os testes garantem: a mesma seed gera os mesmos eventos; um evento duplicado não tem efeito
duplicado; nada sensível executa sem aprovação válida; uma decisão enviada duas vezes executa uma vez só; aprovação
vencida, papel insuficiente e acesso a outro restaurante são bloqueados; o registro de auditoria não aceita UPDATE nem
DELETE; e a tentativa de prompt injection não produz efeito.

## Estrutura do repositório

```
apps/api/                 FastAPI e worker (pacote nexus)
  src/nexus/domain/         regras puras: simulação, métricas, previsão, políticas, guardrails, permissões
  src/nexus/agents/         ferramentas, provedores de LLM, agentes e orquestrador LangGraph
  src/nexus/application/    serviços: eventos, simulação, agentes, aprovações, demo, auditoria, consultas
  src/nexus/infra/          modelos SQLAlchemy e acesso ao banco
  src/nexus/api/            rotas REST, feed ao vivo, autenticação e escopo por restaurante
  src/nexus/data/           catálogo fictício dos restaurantes
  migrations/               Alembic
  tests/                    unitários, integração e segurança
  scripts/                  benchmarks e hook de build do Vercel
apps/web/                 Next.js (interface e BFF)
tests/e2e/                Playwright
docs/                     arquitetura, ADRs, API, segurança, deploy, benchmarks, roadmap e estudo de caso
```

## Limitações

- Faltam os agentes de base de conhecimento (RAG) e de atendimento ao cliente, um conjunto de avaliação com mais de
  100 casos e observabilidade com OpenTelemetry ou Langfuse.
- O caminho com LLM real ainda não foi testado com um provedor de verdade.
- O rate limit fica em memória, por instância.
- Pedidos de compra e fornecedores são simulados. Nenhum sistema externo é acionado.
- No Vercel, a simulação só anda enquanto alguém está com o painel aberto, e o plano gratuito tem cotas mensais de
  CPU, memória e invocações.

O backlog por fase está em [`docs/roadmap.md`](docs/roadmap.md), e o estudo de caso, com o que aprendi no caminho, em
[`docs/portfolio-case-study.md`](docs/portfolio-case-study.md).

## English summary

RestaurantIA Nexus is a portfolio project I built to learn what it takes to put AI agents close to real operations
without letting them act on their own. A deterministic simulator runs a restaurant's dinner rush; detectors open an
incident when the kitchen falls behind and an ingredient is about to run out; a LangGraph orchestrator runs three
agents (operations, inventory and forecasting) that can only read data through typed, tenant-scoped tools. Candidate
actions come from auditable rules, not from the model. A manager approves or rejects each one, and approved actions are
re-validated and executed exactly once, with an append-only audit trail.

It runs without an API key in a clearly labelled deterministic mode, and any OpenAI-compatible model can be plugged
in. The same code runs on Docker Compose (API and worker) or serverless on Vercel with Neon. All data is synthetic, and
the project has no connection to iFood or any delivery platform.
[Live demo](https://restaurantia-nexus.vercel.app) and the [case study](docs/portfolio-case-study.md#english).

---

Feito por João Victor Gualchi.
