# ADR 0001: Monólito modular com worker separado

- Status: aceito · Data: 2026-11-05

## Contexto
O plano inicial previa `services/event-worker` e `services/forecasting` como serviços separados. Só que simulação,
projeção de eventos, detectores, agentes e aprovações compartilham o mesmo modelo de dados e as mesmas regras de negócio.

## Decisão
Um único pacote Python (`nexus`) com fronteiras explícitas (`domain` puro → `agents` → `application` → `api`/`worker`)
e dois processos: a API (FastAPI) e o worker (`nexus-worker`). O worker também pode rodar embutido na API
(`EMBEDDED_WORKER=true`) para deploys de um único contêiner.

## Consequências
- + Sem duplicação de modelos/contratos; transações atômicas entre evento, projeção e auditoria; deploy simples.
- + Testes cobrem o sistema real (mesmas funções no teste, na API e no worker).
- − Escala vertical por processo; separar serviços exigiria contratos de mensageria (a fila já existe, veja o ADR 0002).
