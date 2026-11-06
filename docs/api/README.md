# API

- Especificação OpenAPI gerada: [`openapi.json`](openapi.json) (regenerar com o comando abaixo). Com a API rodando, a UI
  interativa fica em `http://localhost:8000/docs`.
- Todas as rotas sob `/api/v1/restaurants/{restaurant_id}` exigem `Authorization: Bearer <jwt>` e associação ao restaurante;
  sem associação a resposta é `404`. Erros seguem `{"error": {"code", "message", "details", "request_id"}}`.

```bash
cd apps/api && uv run python -c "import json; from nexus.main import create_app; print(json.dumps(create_app().openapi(), indent=2, ensure_ascii=False))" > ../../docs/api/openapi.json
```

## Principais rotas

| Método e rota | Papel mínimo | Descrição |
| --- | --- | --- |
| `POST /api/v1/auth/demo` | — | Cria sandbox demo isolado (persona `manager` ou `operator`) e retorna sessão |
| `POST /api/v1/auth/login` · `GET /api/v1/auth/me` | — | Login local (bcrypt) e usuário atual |
| `GET …/overview` · `GET …/timeseries` | viewer | KPIs e séries do Command Center |
| `GET …/orders` · `GET …/inventory` · `GET …/forecast` | viewer | Pedidos (cursor), estoque/cardápio/compras, previsão + backtest |
| `POST …/menu-items/{key}/availability` | manager | Pausa/reativa item manualmente (auditado) |
| `POST …/events` | operator | Ingestão externa idempotente (`idempotency_key`), schema estrito |
| `GET …/events` · `POST …/events/{id}/requeue` | viewer · manager | Inspeção da fila e reprocessamento de dead-letter |
| `POST …/simulation` (+ `/pause`, `/resume`, `/step`, `/reset`, `/stop`) | operator | Controle da simulação |
| `GET …/agent-runs` · `GET …/agent-runs/{id}` · `POST …/agent-runs` | viewer · operator | Execuções, trace completo e análise sob demanda |
| `GET …/approvals` · `POST …/approvals/{id}/decision` | viewer · manager | Aprovações e decisão (`approve`/`reject` + justificativa, `expected_version`) |
| `GET …/audit` | viewer | Trilha de auditoria |
| `GET …/live?cursor=` | viewer | Feed do painel: eventos e auditoria após o cursor + status. Em `RUNTIME_MODE=serverless` também avança a simulação, a fila e os agentes do tenant |
| `GET …/stream` | viewer | SSE: `events`, `audit`, `status` (reconexão com `Last-Event-ID`) |
| `GET /healthz` · `GET /readyz` | — | Liveness e readiness (banco migrado) |

## Exemplo: ingestão idempotente

```bash
curl -X POST "$API/api/v1/restaurants/$RID/events" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{
  "idempotency_key": "pos:1001:created",
  "occurred_at": "2026-03-13T21:40:00Z",
  "payload": {"type": "order.created", "order_ref": "POS-1001", "channel": "dine_in",
              "items": [{"item_key": "item_smash_classico", "qty": 1}]}
}'
# reenviar o mesmo corpo retorna o mesmo event_id com "created": false
```
