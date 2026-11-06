# Benchmarks e métricas medidas

Todos os números abaixo foram calculados por código deste repositório, sobre dados sintéticos. Eles descrevem o
simulador, os agentes em modo determinístico e os modelos de previsão, e não servem como evidência de desempenho em
restaurantes reais. Dados brutos: [`results.json`](results.json).

Reproduzir (PostgreSQL descartável):

```bash
cd apps/api
DATABASE_URL=postgresql+psycopg://nexus:nexus@localhost:5432/nexus_bench uv run alembic upgrade head
DATABASE_URL=postgresql+psycopg://nexus:nexus@localhost:5432/nexus_bench JWT_SECRET=$(openssl rand -base64 48) \
  uv run python scripts/run_benchmarks.py --seeds 10
```

Ambiente da execução registrada: contêiner Linux x86-64 de 2 vCPUs, PostgreSQL 16 local, Python 3.13, 2026-11-06.

## 1. Previsão de demanda (backtest temporal)

Granularidade item × hora, só nas horas de funcionamento. O modelo foi escolhido pelo menor WAPE na semana de
validação, e as métricas abaixo são da semana de teste (fora da amostra, 77 horas de operação).

| Restaurante | Modelo | WAPE validação | WAPE teste | MAE teste |
| --- | --- | --- | --- | --- |
| Aurora (burger & bowl) | Ingênuo diário | 46,3% | 43,3% | 3,07 |
| | Ingênuo sazonal (semana) | 43,1% | 40,5% | 2,87 |
| | Média sazonal 4 semanas (selecionado) | 35,6% | 33,9% | 2,40 |
| Sora (sushi & lámen) | Ingênuo diário | 45,8% | 44,9% | 3,89 |
| | Ingênuo sazonal (semana) | 41,6% | 39,4% | 3,41 |
| | Média sazonal 4 semanas (selecionado) | 34,0% | 33,5% | 2,90 |

Intervalos de 80% (Poisson com sobredispersão φ estimada na validação): cobertura empírica na semana de teste de
89,1% (Aurora, φ = 1,33) e 88,7% (Sora, φ = 1,64). Os intervalos são um pouco conservadores.

## 2. Cenário "Pico de pedidos + estoque crítico": políticas de decisão

Executado pela camada de serviço real (eventos, projeções, detectores, agentes LangGraph, aprovações), seeds de 1 a
10, restaurante Aurora. Para cada seed, testei três políticas para as decisões humanas:

| Política | Pedidos (média) | Pedidos perdidos por falta de ingrediente: média (mín. a máx.) | Receita perdida média |
| --- | --- | --- | --- |
| Aprovar todas as sugestões | 153 | 0,0 (0 a 0) | R$ 0,00 |
| Aprovar só a compra emergencial | 153 | 8,2 (0 a 23) | R$ 666,06 |
| Rejeitar tudo (contrafactual) | 153 | 55,9 (39 a 71) | R$ 4.765,63 |

Leitura: em parte das seeds a compra sozinha chega tarde demais, e pausar os pratos que menos faturam por grama do
ingrediente crítico cobre o intervalo até a reposição. Premissa do simulador: quando um item é pausado, o cliente
escolhe outro prato. Na vida real, parte desses clientes desistiria.

## 3. Latência (modo determinístico, sem LLM)

| Medida | n | p50 | p95 |
| --- | --- | --- | --- |
| Execução completa dos agentes (triagem, 3 agentes, plano e aprovações) | 57 | 100 ms | 134 ms |
| Chamada de ferramenta (inclui consulta SQL) | 395 | 4 ms | 11 ms |
| Tick de simulação (gerar + ingerir + projetar + detectar) | 3.600 | 29 ms | 61 ms |

## 4. Qualidade do código (última execução)

| Verificação | Resultado |
| --- | --- |
| pytest (backend) | 164 passando (100 unitários, 64 integração/segurança com PostgreSQL) |
| Cobertura | ~90% (linhas + ramos) |
| Playwright | 3 passando (fluxo principal, RBAC, mobile) |
| Ruff · mypy strict · ESLint · tsc · next build | sem erros |

## 5. Ainda não medido (N/A, com motivo)

| Métrica pedida | Status |
| --- | --- |
| Taxa de sucesso e acerto na chamada de ferramentas num conjunto de avaliação | N/A: o conjunto com mais de 100 casos é da Fase 4 |
| Fidelidade e grounding de RAG | N/A: o RAG é da Fase 3 |
| Custo estimado por tarefa | N/A no modo determinístico (sem tokens); com LLM, calculado a partir de `LLM_PRICE_*` configurados |
| Latência com LLM real | N/A: nenhum provedor foi configurado neste ambiente |
| Taxa de violação de segurança | Os testes de segurança passam (0 violações nos casos cobertos); uma taxa estatística depende do conjunto de avaliação |
