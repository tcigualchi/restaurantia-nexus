# Roadmap e backlog

Legenda: ✅ feito · 🟡 parcial · ⬜ pendente

## Fase 0 — Inspeção e plano ✅
- Repositório criado do zero (pasta vazia); restrições do ambiente registradas (rede de pacotes liberada durante a sessão; Docker Hub indisponível).

## Fase 1 — Vertical slice ✅
- ✅ Autenticação (demo isolado + login local com bcrypt), RBAC por restaurante
- ✅ Esquema, migração Alembic com trigger de auditoria, seed sintético idempotente
- ✅ Simulador determinístico (4 cenários) e fila de eventos idempotente com DLQ
- ✅ Painel com dados persistidos e feed ao vivo (polling de `/live`; SSE para integrações)
- ✅ Agentes Operations e Inventory (+ Forecasting) com ferramentas tipadas
- ✅ Aprovação humana persistente, revalidação, execução única e auditoria
- ✅ Testes (164 backend, 3 e2e), Docker Compose, CI

## Fase 2 — Incidentes ponta a ponta 🟡
- ✅ Orquestração LangGraph com checkpointer (memória/PostgreSQL), feed ao vivo, falhas controladas (fallback de LLM, DLQ, reaper de runs presos)
- ✅ Testes e2e do fluxo principal
- ⬜ OpenTelemetry (traces HTTP → serviço → ferramenta) e/ou Langfuse para chamadas de LLM
- ⬜ HITL nativo do LangGraph (`interrupt`/`Command(resume)`) além da aprovação durável já existente
- ⬜ Injeção de falhas configurável (latência/erro em ferramentas) no Simulation Lab

## Fase 3 — RAG e Forecasting 🟡
- ✅ Forecasting com baselines, backtest temporal, intervalos com cobertura medida, gráficos
- ⬜ Knowledge Agent: upload de documentos (políticas, manuais), chunking, embeddings (pgvector), busca híbrida, citações, filtro por tenant, resposta "sem evidência"
- ⬜ Testes de prompt injection em documentos

## Fase 4 — Agentes restantes e avaliação ⬜
- ⬜ Customer Experience Agent (cenário "reclamação crítica"; reembolso/desconto exigindo papel owner)
- ⬜ Evaluation Lab: dataset versionado (100+ casos) — execução correta, escolha de ferramenta, argumentos, RAG, falhas, eventos duplicados, autorização, isolamento
- ⬜ Métricas: task success, tool-call accuracy, grounding, latência p50/p95, violações de segurança, custo por tarefa
- ⬜ Rate limit distribuído, CSP com nonce

## Fase 5 — Publicação ⬜
- ✅ CI (lint, tipos, testes, build, e2e, auditoria de dependências, gitleaks) e guia de deploy
- ✅ Deploy no Vercel preparado e validado com `vercel build`: Services (web + API privada), Neon, modo serverless sem worker (ADR 0007)
- ⬜ Deploy público no ar com monitoramento (OpenTelemetry/Langfuse)
- ✅ Vídeo sem áudio gerado com Playwright (`docs/assets/demo.mp4`, script `tests/e2e/record_demo.py`)
- ⬜ Versão narrada a partir de `docs/demo-script.md`
