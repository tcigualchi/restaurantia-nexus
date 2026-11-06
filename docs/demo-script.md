# Roteiro de demonstração (vídeo de ~3 minutos)

**Objetivo:** mostrar agentes de IA úteis e seguros — que investigam, quantificam e propõem, mas só agem com aprovação humana.

| Tempo | Tela | Fala / ação |
| --- | --- | --- |
| 0:00 | Landing | "RestaurantIA Nexus: inteligência operacional para restaurantes. Tudo aqui é sintético." Escolher *Gerente* → **Entrar no modo demo**. |
| 0:15 | Overview | "Cada visitante ganha um sandbox isolado com dois restaurantes." Mostrar KPIs vazios e o seletor de restaurante. |
| 0:25 | Simulation Lab | Escolher **Pico de pedidos + estoque crítico**, seed 42, velocidade rápida → **Iniciar**. "Mesma seed, mesmos eventos." |
| 0:40 | Overview | Pedidos e fila subindo em tempo real (SSE). Feed de eventos. |
| 1:00 | Topbar / toast | Incidente detectado → "Agentes analisando…" → relógio pausa aguardando decisão humana. |
| 1:10 | AI Control Room | Triagem → Operations (utilização projetada 124%) → Inventory (costela acaba antes da reposição) → Forecasting (consumo P10–P90). Abrir um passo e mostrar parâmetros validados e resultado. Destacar o alerta de **prompt injection** neutralizado numa observação de cliente. |
| 1:50 | Approval Center | Ler justificativa e evidências (S07, S10). **Aprovar** a compra, **rejeitar** a pausa do Burger com justificativa, **aprovar** a do Pastel. |
| 2:15 | Estoque | Pedido de compra "a caminho"; item pausado. Relógio retoma. |
| 2:30 | Overview | Pedido de compra chega (salto no gráfico de estoque); perdas mínimas. "Rejeitando tudo, essa mesma seed perde ~56 pedidos em média." |
| 2:45 | Audit Log | Quem aprovou/rejeitou, quando e por quê; trilha append-only. |
| 2:55 | Simulation Lab | **Reiniciar** → replay determinístico. Fim. |

Dica de gravação: tema claro, janela 1440×900, zoom 100%, velocidade "Rápida". Gravação automática sem áudio:
`python tests/e2e/record_demo.py <pasta-de-saida>` com a stack rodando em `http://localhost:3000` (Python + Playwright).
