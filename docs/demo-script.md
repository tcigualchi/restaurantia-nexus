# Roteiro para o vídeo da demonstração (cerca de 3 minutos)

A ideia é mostrar agentes que investigam e sugerem, mas só agem com a aprovação de uma pessoa.

| Tempo | Tela | O que falar ou fazer |
| --- | --- | --- |
| 0:00 | Página inicial | "Este é o RestaurantIA Nexus, um projeto de portfólio. Todos os dados são fictícios." Escolher Gerente e clicar em Entrar no modo demo. |
| 0:15 | Visão geral | "Cada visitante recebe uma cópia própria com dois restaurantes." Mostrar os indicadores zerados e o seletor de restaurante. |
| 0:25 | Simulação | Escolher "Pico de pedidos + estoque crítico", seed 42, velocidade rápida, e clicar em Iniciar. "Com a mesma seed, os eventos se repetem." |
| 0:40 | Visão geral | Pedidos e fila subindo. Comentar que os números vêm dos eventos gravados no banco. |
| 1:00 | Barra do topo | O incidente é detectado, os agentes começam a análise e o relógio pausa esperando o gerente. |
| 1:10 | Agentes | Mostrar a ordem: triagem, agente de operação (utilização prevista de 124%), agente de estoque (a costela acaba antes da reposição) e agente de previsão (faixa de consumo). Abrir um passo para mostrar os parâmetros validados e o resultado. Apontar o aviso de prompt injection na observação de um cliente. |
| 1:50 | Aprovações | Ler a justificativa e as evidências. Aprovar a compra, rejeitar a pausa do Burger de Costela com um motivo e aprovar a do Pastel. |
| 2:15 | Estoque | A compra aparece a caminho e o prato pausado sai do cardápio. O relógio volta a andar. |
| 2:30 | Visão geral | A compra chega (salto no gráfico de estoque) e quase nenhum pedido se perde. "Rejeitando tudo, essa mesma seed perde cerca de 56 pedidos em média." |
| 2:45 | Auditoria | Quem aprovou e quem rejeitou, quando e por quê. Os registros não podem ser alterados. |
| 2:55 | Simulação | Clicar em Reiniciar para mostrar que o cenário se repete. Fim. |

Para gravar: tema claro, janela de 1440 × 900, zoom de 100% e velocidade rápida. Para uma gravação automática sem
áudio, com a aplicação rodando em `http://localhost:3000` (Python e Playwright instalados):

```bash
python tests/e2e/record_demo.py <pasta-de-saida>
```
