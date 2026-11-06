# ADR 0002 — PostgreSQL como log e fila de eventos

- **Status:** aceito · **Data:** 2026-11-05

## Contexto
Eventos precisam de idempotência, ordem por restaurante, retentativas e dead-letter. A stack sugerida citava Redis
Streams "ou fila equivalente". O volume do produto (dezenas de eventos por minuto por tenant) é baixo.

## Decisão
Tabela `events` como log + fila: `UNIQUE (restaurant_id, idempotency_key)` com `INSERT … ON CONFLICT DO NOTHING`;
processamento por tenant serializado com `pg_advisory_xact_lock`, reivindicação em ordem de id com
`FOR UPDATE SKIP LOCKED`; cada evento aplicado em SAVEPOINT; falhas retentáveis com backoff exponencial
(`next_attempt_at`), `dead_letter` após `EVENT_MAX_ATTEMPTS`; reprocessamento manual auditado.
Handlers também são idempotentes por fato de negócio (mesmo `order_ref`, pedido já pronto).

## Consequências
- + Exatamente-uma-vez *efetivo*: evento, projeção e auditoria na mesma transação; sem infraestrutura extra.
- + Replays e auditoria triviais (o log é consultável).
- − Throughput limitado pelo Postgres; para volume alto, migrar a reivindicação para Redis Streams/Kafka mantendo
  a chave de idempotência e o handler idempotente.
- Locks consultivos de *transação* funcionam atrás de poolers em modo transação; locks de sessão não seriam usados.
