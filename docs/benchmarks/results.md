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

## 3. Quanto custa o gerente demorar para responder

Na seção 2, a simulação fica parada enquanto há aprovação pendente, então decidir não custa tempo simulado. Num
restaurante de verdade o relógio não para: os pedidos continuam chegando, a pausa dos pratos começa mais tarde e o
fornecedor só recebe o pedido de compra depois da aprovação. Para medir esse custo, rodei o mesmo cenário, com as
mesmas seeds, deixando a simulação andar enquanto as sugestões esperam e respondendo cada uma N minutos simulados
depois de ela ser feita. A primeira sugestão sai, em média, no minuto 26 do cenário (18h56), e o fornecedor leva
40 minutos para entregar a costela.

```bash
cd apps/api
DATABASE_URL=postgresql+psycopg://nexus:nexus@localhost:5432/nexus_bench JWT_SECRET=$(openssl rand -base64 48) \
  uv run python scripts/run_benchmarks.py --seeds 10 --approval-delays 5,10,15,20,25,30
```

Esse modo grava só o [`approval_delay.json`](approval_delay.json) e não mexe no `results.json`. Executado em
2026-11-07, no mesmo tipo de ambiente. Com resposta imediata, os números repetem os da seção 2, seed a seed.

Pedidos perdidos por falta de ingrediente, média (mín. a máx.), e receita perdida média:

| Tempo até a resposta | Aprovar todas as sugestões | Receita perdida | Aprovar só a compra | Receita perdida |
| --- | --- | --- | --- | --- |
| Imediata (como na seção 2) | 0,0 (0 a 0) | R$ 0,00 | 8,2 (0 a 23) | R$ 666,06 |
| 5 min | 0,0 (0 a 0) | R$ 0,00 | 12,5 (1 a 26) | R$ 1.037,16 |
| 10 min | 0,4 (0 a 4) | R$ 34,48 | 17,8 (9 a 28) | R$ 1.505,17 |
| 15 min | 2,5 (0 a 15) | R$ 224,89 | 23,7 (15 a 35) | R$ 2.051,81 |
| 20 min | 5,9 (0 a 17) | R$ 520,92 | 28,4 (19 a 38) | R$ 2.476,91 |
| 25 min | 10,7 (0 a 23) | R$ 972,70 | 32,9 (22 a 42) | R$ 2.864,49 |
| 30 min, o limite de `APPROVAL_TTL_MINUTES` | 16,1 (5 a 31) | R$ 1.455,54 | 37,4 (22 a 49) | R$ 3.246,46 |
| Sem resposta: a aprovação expira | 55,9 (39 a 71) | R$ 4.765,63 | 55,9 (39 a 71) | R$ 4.765,63 |

Leitura:

- Aprovando tudo, os primeiros 10 minutos quase não custam pedidos, porque a pausa dos pratos foi calculada com folga
  e ainda cobre o intervalo até a reposição. Entre 15 e 30 minutos, cada minuto de espera custa perto de 1 pedido
  (cerca de R$ 80 de receita). Com 15 minutos já há perda em 4 das 10 seeds; com 30, em todas.
- Aprovar tudo com 20 minutos de atraso (5,9) ainda é melhor do que aprovar só a compra na hora (8,2). Com 25
  minutos (10,7), já é pior.
- Aprovando só a compra não há folga: cada minuto de espera vira um minuto a mais sem costela antes da entrega, e a
  perda sobe cerca de 1 pedido por minuto desde o começo.
- Mesmo no limite de 30 minutos, aprovar tudo ainda evita 39,8 dos 55,9 pedidos que se perderiam sem nenhuma ação.
- Com a espera maior, a análise seguinte do mesmo pico volta a sugerir a compra enquanto a primeira ainda está
  pendente, já recalculada para o estoque mais baixo (na seed 6, 28 kg de costela em vez de 20 kg). Respondendo na
  ordem de chegada, a checagem de compra em aberto barra a segunda, e quem vale é a mais antiga. Nenhuma compra saiu em
  dobro: com 30 minutos de espera, foram 7 repetições barradas somando as 10 seeds.

### O que isso diz sobre o prazo de 30 minutos

`APPROVAL_TTL_MINUTES` conta tempo de relógio. Na demonstração a simulação fica parada durante a espera, então o prazo
não custa pedidos. Num restaurante real o tempo do negócio é o do relógio, e uma aprovação dada no minuto 29 ainda é
executada, com um custo perto do da linha de 30 minutos. Por esses números, a sugestão só funciona como foi planejada
se for respondida em até uns 10 minutos. Com 30, ela perde 16 pedidos, e o texto da aprovação ("Deve chegar às ...")
fica errado pelo tamanho do atraso, porque a hora de chegada é calculada no momento da sugestão. O pedido de compra
criado na execução usa a hora certa.

Reduzir o prazo sozinho, porém, piora o resultado. Quando uma aprovação expira, nada é executado e nenhuma análise nova
é disparada para o mesmo ingrediente, porque o detector não abre outro incidente para um risco que já teve incidente
na mesma simulação. Com prazo de 15 minutos, um gerente que leva 20 para responder deixaria de perder 5,9 pedidos para
perder 55,9, porque todas as sugestões expirariam antes da resposta. Um prazo menor só compensa junto com uma reanálise
automática quando a aprovação expira, para o gerente receber uma sugestão recalculada com o estoque daquele momento em
vez de ficar sem nenhuma. Pelo mesmo motivo, uma sugestão nova para o mesmo ingrediente deveria substituir a que ainda
está pendente. Nada disso existe ainda, então não foi medido.

## 4. Latência (modo determinístico, sem LLM)

| Medida | n | p50 | p95 |
| --- | --- | --- | --- |
| Execução completa dos agentes (triagem, 3 agentes, plano e aprovações) | 57 | 100 ms | 134 ms |
| Chamada de ferramenta (inclui consulta SQL) | 395 | 4 ms | 11 ms |
| Tick de simulação (gerar + ingerir + projetar + detectar) | 3.600 | 29 ms | 61 ms |

## 5. Qualidade do código (última execução)

| Verificação | Resultado |
| --- | --- |
| pytest (backend) | 165 passando (100 unitários, 65 integração/segurança com PostgreSQL) |
| Cobertura | ~90% (linhas + ramos) |
| Playwright | 3 passando (fluxo principal, RBAC, mobile) |
| Ruff · mypy strict · ESLint · tsc · next build | sem erros |

## 6. Ainda não medido (N/A, com motivo)

| Métrica pedida | Status |
| --- | --- |
| Taxa de sucesso e acerto na chamada de ferramentas num conjunto de avaliação | N/A: o conjunto com mais de 100 casos é da Fase 4 |
| Fidelidade e grounding de RAG | N/A: o RAG é da Fase 3 |
| Custo estimado por tarefa | N/A no modo determinístico (sem tokens); com LLM, calculado a partir de `LLM_PRICE_*` configurados |
| Latência com LLM real | N/A: nenhum provedor foi configurado neste ambiente |
| Taxa de violação de segurança | Os testes de segurança passam (0 violações nos casos cobertos); uma taxa estatística depende do conjunto de avaliação |
