# ADR 0004 — Políticas determinísticas decidem; o LLM explica

- **Status:** aceito · **Data:** 2026-11-05

## Contexto
Números e ações sensíveis não podem depender de texto gerado. Prompt injection em dados de terceiros é um risco real.

## Decisão
- Ferramentas dos agentes são **somente leitura**; não existe ferramenta de escrita exposta a modelos.
- Ações candidatas (compra emergencial, pausa de item) são geradas por fórmulas em `domain/policies.py` a partir das
  saídas das ferramentas (consumo P90 ajustado, lead time, embalagem, receita por grama do ingrediente crítico).
- Se um modelo está configurado, ele só **ordena** candidatos existentes e escreve o resumo; ids desconhecidos são
  ignorados e nenhum candidato pode ser removido ou inventado.
- Toda candidata sensível vira `approval_request`; execução só após decisão humana válida e **revalidação**.
- Ações rejeitadas por humanos na mesma simulação não são repropostas automaticamente.

## Consequências
- + Comportamento auditável e testável; o LLM agrega valor em explicação e priorização sem poder de efeito colateral.
- − Novas ações exigem código de política + executor + testes (intencional).
