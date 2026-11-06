# ADR 0003 — Simulação determinística em lockstep

- **Status:** aceito · **Data:** 2026-11-05

## Contexto
O avaliador precisa reiniciar a demo e obter o mesmo resultado; testes precisam de reprodutibilidade.

## Decisão
- Motor puro (`domain/simulation.py`): um RNG por tick (`Random("nexus-sim:{seed}:{scenario}:{template}:{tick}")`),
  estado serializado em `simulation_runs.state`, chaves de idempotência `sim:{run}:{tick}:{seq}`.
- O motor recebe estoque e disponibilidade atuais e só agenda trabalho na cozinha para pedidos que o projetor aceitará.
- Um tick = gerar → ingerir → projetar → detectar, numa transação. Incidente pausa o relógio (`agents_running`);
  aprovações pendentes mantêm a pausa (`awaiting_approval`) quando `auto_pause_on_approval` está ativo.
- Ações aprovadas entram em ticks determinísticos (ex.: pedido de compra chega em `tick + lead_time`).

## Consequências
- + Mesmo seed + mesmas decisões ⇒ mesma execução (teste de replay); teste diferencial SQL × projeção de referência.
- − Em modo LLM o relógio espera os agentes (segundos). Aceitável num laboratório de simulação; em operação real o
  relógio é o do mundo e a análise ocorre de forma assíncrona.
