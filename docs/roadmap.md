# Roadmap

O projeto está dividido em fases. Abaixo está o que já foi feito e o que falta em cada uma.

## Fase 0: inspeção e plano (concluída)

- Repositório criado do zero e restrições do ambiente registradas.

## Fase 1: fluxo completo de ponta a ponta (concluída)

- Autenticação com demonstração isolada por visitante e login local com bcrypt, permissões por restaurante.
- Esquema do banco, migração Alembic com trigger de auditoria e dados iniciais sintéticos idempotentes.
- Simulador determinístico com quatro cenários e fila de eventos idempotente com dead-letter.
- Painel com dados persistidos e atualização ao vivo (consultas a `/live`; SSE disponível para integrações).
- Agentes de operação, estoque e previsão com ferramentas tipadas.
- Aprovação humana persistente, conferência antes de executar, execução única e auditoria.
- Testes (164 de backend e 3 de ponta a ponta), Docker Compose e CI.

## Fase 2: incidentes de ponta a ponta (parcial)

Feito:

- Orquestração com LangGraph e checkpointer em memória ou PostgreSQL, feed ao vivo e tratamento de falhas (queda do
  LLM, dead-letter, execuções presas).
- Testes de ponta a ponta do fluxo principal.

Falta:

- OpenTelemetry (rastreando HTTP, serviço e ferramenta) e/ou Langfuse para as chamadas de LLM.
- Aprovação com o `interrupt`/`Command(resume)` nativo do LangGraph, além da aprovação persistente que já existe.
- Falhas configuráveis nas ferramentas (latência e erro) pela tela de simulação.

## Fase 3: RAG e previsão (parcial)

Feito:

- Previsão com modelos de referência, backtest temporal, intervalos com cobertura medida e gráficos.

Falta:

- Agente de base de conhecimento: upload de documentos (políticas, manuais), divisão em trechos, embeddings com
  pgvector, busca híbrida, citações, filtro por restaurante e resposta explícita quando não houver evidência.
- Testes de prompt injection em documentos.

## Fase 4: agentes restantes e avaliação (pendente)

- Agente de atendimento ao cliente (cenário de reclamação crítica; reembolso ou desconto exigindo o papel de dono).
- Conjunto de avaliação versionado com mais de 100 casos: execução correta, escolha de ferramenta, argumentos, RAG,
  falhas, eventos duplicados, autorização e isolamento.
- Métricas: taxa de sucesso, acerto na chamada de ferramentas, grounding, latência p50/p95, violações de segurança e
  custo por tarefa.
- Rate limit distribuído e CSP com nonce.

## Fase 5: publicação (parcial)

Feito:

- CI com lint, tipos, testes, build, e2e, auditoria de dependências e busca de segredos.
- Deploy público no Vercel: Next.js e FastAPI no mesmo projeto, API sem rota pública, banco Neon e modo serverless
  sem worker ([ADR 0007](adr/0007-serverless-pump.md)). Está em
  [restaurantia-nexus.vercel.app](https://restaurantia-nexus.vercel.app).
- Vídeo sem áudio gravado com Playwright (`docs/assets/demo.mp4`, script em `tests/e2e/record_demo.py`).

Falta:

- Monitoramento em produção (OpenTelemetry ou Langfuse).
- Versão narrada do vídeo a partir de [`demo-script.md`](demo-script.md).
