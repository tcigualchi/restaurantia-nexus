# ADR 0006 — Baseline estatístico de previsão com avaliação honesta

- **Status:** aceito · **Data:** 2026-11-05

## Contexto
O prompt pede comparação com baseline ingênuo, avaliação temporal e intervalos apenas quando sustentados.

## Decisão
- Histórico sintético horário por item (8 semanas) gerado deterministicamente do mesmo perfil de demanda do simulador.
- Modelos: ingênuo diário, ingênuo sazonal semanal e média sazonal de 4 semanas (day-ahead).
- **Seleção na semana de validação; métricas reportadas na semana de teste** (sem vazamento).
- Intervalos de 80% com variância Poisson inflada por sobre-dispersão estimada na validação; **cobertura empírica medida**
  na semana de teste (≈ 89% para 80% nominais: conservador).
- Ajuste por ritmo observado (*nowcast*) explícito e limitado a 0,5–3,0×, exibido ao usuário.
- LightGBM/regressões ficam para depois: com dados sintéticos sem covariáveis, ganho seria ilusório.

## Consequências
- + Números verificáveis e reprodutíveis; o LLM nunca produz números de previsão.
- − Não captura eventos sem precedentes (registrado no disclaimer exibido na UI).
