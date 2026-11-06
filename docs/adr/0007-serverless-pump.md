# ADR 0007: Trabalho de fundo sob demanda no Vercel (serverless)

- Status: aceito
- Data: 2026-11-06

## Contexto

Em Docker, um processo `worker` faz quatro coisas o tempo todo: avança simulações tick a tick, projeta a fila de
eventos, executa agentes enfileirados e cuida da manutenção (expirar aprovações, apagar sandboxes vencidos, liberar
execuções presas). O deploy público alvo é o Vercel no plano Hobby, onde:

- funções atendem requisições e duram no máximo 300 s, sem processos de fundo entre elas;
- Daemons (processos contínuos) estão em beta, rodam só em produção e têm cota mensal (5 horas de CPU e 420 GB-hora
  de memória por mês no Hobby): uma instância de 1 GB contínua esgota a cota de memória em cerca de 17 dias, e o polling
  constante manteria o banco Neon sempre acordado;
- cron jobs no Hobby rodam no máximo uma vez por dia.

## Decisão

Ter dois modos de execução com o mesmo código, escolhidos por `RUNTIME_MODE` (o Vercel é detectado sozinho por
`VERCEL=1`):

- `server` (Docker, local): o worker roda como hoje.
- `serverless` (Vercel): não há worker. O painel consulta `GET /restaurants/{id}/live` (1 s com a simulação ativa,
  4 s parada, pausado com a aba oculta), e cada consulta executa `pump_tenant`: os mesmos passos do worker, limitados
  àquele tenant e a um orçamento por chamada. A limpeza de sandboxes vencidos acontece quando uma nova sessão demo é
  criada.

Garantias que tornam isso seguro:

- Ticks dependem do tempo, não da quantidade de consultas (`ticks_due`): consultar mais rápido não acelera a
  simulação, e um intervalo longo vira no máximo 5 ticks, sem replay acumulado.
- Concorrência: execuções de simulação e de agentes são reivindicadas com `FOR UPDATE SKIP LOCKED` e a fila de
  eventos é serializada por tenant com lock consultivo transacional. Duas abas abertas não duplicam trabalho.
- Falhas: se o pump falhar, `/live` ainda devolve o feed e a próxima consulta tenta de novo. Execuções de agentes
  interrompidas por timeout são liberadas depois de 6 minutos.
- Lockstep preservado: a simulação continua pausando para os agentes e para as aprovações humanas (ADR 0003).

O transporte do feed ao vivo passou de SSE para polling curto também em Docker, para que o código testado seja o mesmo
publicado. O endpoint SSE continua disponível para integrações.

## Consequências

- Positivas: custo zero com o sistema parado; o Neon pode dormir; não depende de recursos em beta; o e2e roda nos dois
  modos.
- Negativas: no Vercel a simulação só avança com alguém olhando (aceitável para uma demo, não para uma operação real),
  e cada consulta faz um pouco mais de trabalho (medido localmente na casa de dezenas de milissegundos por tick).
- Um cliente real, com eventos chegando sem ninguém olhando, precisaria de um worker contínuo (Daemon, container
  ou Vercel Queues/Workflows). O modo `server` já cobre esse caso.

## Alternativas consideradas

- Daemon no Vercel: menos código, mas beta, só em produção e incompatível com as cotas do Hobby.
- API e worker em outro provedor (Railway, Render): mantém a arquitetura, mas exige outra conta, normalmente paga.
- Cron: no Hobby, uma vez por dia; inútil para ticks de 1 s.
- Vercel Workflows/Queues: bons para jobs duráveis, mas a simulação precisa de ticks curtos enquanto alguém assiste,
  não de jobs em fila.
