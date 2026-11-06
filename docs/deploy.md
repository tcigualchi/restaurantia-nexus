# Deploy público no Vercel (Services + Neon)

Um único projeto Vercel publica a aplicação inteira:

```
navegador ──HTTPS──▶ Vercel · serviço web (Next.js: UI + BFF /api/*)
                              │  service binding (rede interna, sem rota pública)
                              ▼
                     Vercel · serviço api (FastAPI, função Python)
                              │  TLS
                              ▼
                     Neon PostgreSQL (Marketplace do Vercel)
```

- [`vercel.json`](../vercel.json) declara os dois serviços. Só o `web` recebe tráfego público. A API fica privada: o BFF
  a chama pela URL injetada em `API_INTERNAL_URL` pelo binding, sempre com o token da sessão.
- **Não existe worker no Vercel.** O plano Hobby não mantém processos contínuos (Daemons estão em beta e esgotariam a
  cota em poucos dias). No modo serverless, cada consulta do painel a `GET /live` executa, só para aquele tenant, o mesmo
  trabalho do worker: ticks da simulação, fila de eventos, agentes, expiração de aprovações. A simulação avança enquanto
  alguém está olhando e nada roda quando ninguém está. Veja o [ADR 0007](adr/0007-serverless-pump.md).
- O modo é detectado sozinho (`VERCEL=1` → `RUNTIME_MODE=serverless`). Docker e desenvolvimento local continuam com
  o worker.
- O build da API roda [`apps/api/scripts/vercel_build.py`](../apps/api/scripts/vercel_build.py): `alembic upgrade head`
  com lock consultivo, pela conexão direta do Neon, e o seed idempotente, antes de o deploy receber tráfego.

> Validado localmente com o Vercel CLI 65.12.1 (`vercel build --prod`): os dois serviços compilam, a função Python fica
> com ~173 MB (limite de 500 MB) e o hook migra e semeia um banco vazio. O fluxo completo (e2e) também passa com a API em
> modo serverless, sem worker. O deploy em si depende da sua conta e não foi executado a partir deste ambiente.

## Pré-requisitos

- Conta no GitHub e Git instalado.
- Conta no Vercel (o plano **Hobby** é gratuito, para uso pessoal e não comercial).
- O arquivo `.github/workflows/ci.yml` na pasta do projeto (opcional, ativa o CI no GitHub).

## 1. Enviar o código para o GitHub

No terminal (cmd), dentro da pasta `restaurantia-nexus`:

```
git init -b main
git add .
git commit -m "RestaurantIA Nexus"
```

Se o Git pedir nome e e-mail, configure uma vez com `git config --global user.name "Seu Nome"` e
`git config --global user.email "voce@exemplo.com"`, e repita o commit.

No GitHub, crie um repositório **vazio** (*New repository*, sem README, .gitignore ou licença), por exemplo
`restaurantia-nexus`, e envie:

```
git remote add origin https://github.com/<seu-usuario>/restaurantia-nexus.git
git push -u origin main
```

O [`.gitattributes`](../.gitattributes) mantém tudo com fim de linha LF, assim os scripts dos containers continuam
funcionando mesmo editados no Windows.

## 2. Criar o projeto no Vercel

1. Em vercel.com: **Add New… → Project** e importe o repositório (autorize o GitHub se for a primeira vez).
2. **Root Directory**: deixe a raiz do repositório (não escolha `apps/web`).
3. **Framework Preset**: **Services**. O Vercel costuma detectar isso pelo `vercel.json`.
4. Em **Environment Variables**, adicione as duas abaixo marcando **Production** e **Preview**:

| Variável | Valor |
| --- | --- |
| `JWT_SECRET` | segredo aleatório com 32 caracteres ou mais |
| `PROXY_SHARED_SECRET` | outro segredo aleatório (o BFF o envia para a API confiar no IP real do visitante; sem ele, todos os visitantes dividiriam a mesma cota da demo) |

   Para gerar cada segredo (rode duas vezes, um valor por variável):

   ```
   docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

5. Clique em **Deploy**. **O primeiro build vai falhar** com a mensagem `ERRO: nenhum banco configurado`. É o
   esperado: o banco é criado no próximo passo.

Não defina `API_INTERNAL_URL` (o binding injeta) nem `DATABASE_URL` à mão (o Neon injeta). `APP_ENV` vira
`production` sozinho no ambiente Production.

## 3. Conectar o banco Neon

1. No projeto: **Storage → Create Database → Neon** (plano Free).
2. Região: **AWS US East 1 (N. Virginia)**, a mesma das funções (`iad1`, padrão do Vercel).
3. Conecte o banco ao ambiente **Production**. O Vercel adiciona `DATABASE_URL` (com pooler, usado pela API) e
   `DATABASE_URL_UNPOOLED` (direto, usado pelas migrações), entre outras.
4. **Deployments →** último deploy **→ ⋯ → Redeploy**. No log do serviço `api`, procure
   `Migrações aplicadas e seed concluído (production)`.

Previews (outras branches) só funcionam com um banco próprio. Crie um segundo banco Neon e conecte-o ao ambiente
**Preview**. Não compartilhe o banco de produção com previews.

## 4. Testar

Abra `https://<seu-projeto>.vercel.app`, clique em **Entrar no modo demo** e siga a
[demonstração principal](../README.md#demonstração-principal-2-minutos). A simulação avança enquanto o painel está aberto.
O primeiro acesso depois de um tempo parado pode levar alguns segundos: o Neon acorda o banco e o Vercel inicia a
função Python.

Testes automatizados contra a URL pública (requer Node.js 22):

```
cd tests/e2e
npm ci
npx playwright install chromium
set E2E_BASE_URL=https://<seu-projeto>.vercel.app
npx playwright test
```

## 5. Problemas comuns

| Sintoma | Causa provável e solução |
| --- | --- |
| Build da `api` falha com `nenhum banco configurado` | Banco ainda não conectado ao ambiente do deploy (passo 3). |
| Build ou funções falham com `JWT_SECRET must be set` | Variável ausente ou com menos de 32 caracteres naquele ambiente. Corrija e faça Redeploy. |
| Tela "API indisponível" ou erro 502 | A função Python falhou ao iniciar. Veja **Logs** filtrando pelo serviço `api`. |
| A simulação não avança | Ela só avança com o painel aberto. Confira, nos Logs, se as requisições `/live` retornam 200. |
| "Muitas sessões demo" | Quota por IP (`DEMO_MAX_SESSIONS_PER_IP_PER_HOUR`, padrão 5). Confira se `PROXY_SHARED_SECRET` está definido. |

## Cotas do plano gratuito

Conferidas na documentação em novembro de 2026. Elas mudam: confira antes de divulgar o link.

- **Vercel Hobby** (por mês): 4 horas de CPU ativa, 360 GB-hora de memória provisionada e 1 milhão de invocações. Cada
  painel aberto faz cerca de uma consulta `/live` por segundo enquanto a simulação roda, a cada 4 s quando ela está
  parada, e nenhuma com a aba em segundo plano. Funções podem durar até 300 s.
- **Neon Free**: 100 CU-hora por projeto por mês, 1 GB de armazenamento, e o banco dorme após 5 minutos sem uso. Os
  sandboxes da demo expiram (`DEMO_SESSION_TTL_MINUTES`) e são apagados quando novas sessões são criadas.
- O modo determinístico dos agentes não gasta nada com modelos. Com LLM, configure limites de gasto no provedor.

## Alternativa: qualquer host com Docker

A mesma imagem da API roda como `api` e `worker` (`apps/api/Dockerfile`, contexto na raiz) e o web como container
Next.js standalone (`apps/web/Dockerfile`), igual ao `docker-compose.yml`. Use o modo padrão (`RUNTIME_MODE=server`,
com worker), `APP_ENV=production`, um `JWT_SECRET` forte, `PROXY_SHARED_SECRET` igual nos dois serviços com
`TRUST_PROXY_HEADERS=true` na API, e rode as migrações antes de cada versão com
`sh /usr/local/bin/docker-entrypoint.sh migrate`.

## Referências

- [Vercel Services](https://vercel.com/docs/services), [service bindings](https://vercel.com/docs/services/bindings) e
  [roteamento](https://vercel.com/docs/services/routing)
- [Python backend com Next.js no Vercel](https://vercel.com/kb/guide/python-backend-on-vercel) e
  [FastAPI no Vercel](https://vercel.com/docs/frameworks/backend/fastapi)
- [Runtime Python](https://vercel.com/docs/functions/runtimes/python) e
  [limites das funções](https://vercel.com/docs/functions/limitations)
- [Plano Hobby](https://vercel.com/docs/plans/hobby) e [limites dos Daemons](https://vercel.com/docs/daemons/limits)
- [Limites do plano Free do Neon](https://neon.com/faqs/free-plan-limits-and-quotas)
