# Deploy no Vercel (Services + Neon)

A versão pública, em [restaurantia-nexus.vercel.app](https://restaurantia-nexus.vercel.app), foi publicada seguindo
estes passos. Um único projeto Vercel publica a aplicação inteira:

```
navegador ──HTTPS──▶ Vercel · serviço web (Next.js: interface + BFF /api/*)
                              │  service binding (rede interna, sem rota pública)
                              ▼
                     Vercel · serviço api (FastAPI, função Python)
                              │  TLS
                              ▼
                     Neon PostgreSQL (Marketplace do Vercel)
```

- O [`vercel.json`](../vercel.json) declara os dois serviços. Só o `web` recebe tráfego público. A API fica privada: o
  BFF a chama pela URL que o binding injeta em `API_INTERNAL_URL`, sempre com o token da sessão.
- Não existe worker no Vercel. O plano Hobby não mantém processos contínuos (os Daemons estão em beta e esgotariam a
  cota em poucos dias). No modo serverless, cada consulta do painel a `GET /live` faz, só para aquele restaurante, o
  mesmo trabalho do worker: ticks da simulação, fila de eventos, agentes e expiração de aprovações. A simulação anda
  enquanto alguém está olhando, e nada roda quando ninguém está. Os motivos estão no
  [ADR 0007](adr/0007-serverless-pump.md).
- O modo é detectado sozinho (`VERCEL=1` liga `RUNTIME_MODE=serverless`). Docker e desenvolvimento local continuam
  usando o worker.
- O build da API roda [`apps/api/scripts/vercel_build.py`](../apps/api/scripts/vercel_build.py), que aplica as
  migrações (`alembic upgrade head`, com lock consultivo e pela conexão direta do Neon) e cria os dados iniciais antes
  de o deploy receber tráfego.

## Pré-requisitos

- Conta no GitHub e Git instalado.
- Conta no Vercel. O plano Hobby é gratuito, para uso pessoal e não comercial.

## 1. Enviar o código para o GitHub

No terminal, dentro da pasta `restaurantia-nexus` (não na pasta de cima, porque o `vercel.json` e a pasta `.github/`
precisam ficar na raiz do repositório):

```
git init -b main
git add .
git commit -m "RestaurantIA Nexus"
```

Se o Git pedir nome e e-mail, configure uma vez com `git config --global user.name "Seu Nome"` e
`git config --global user.email "voce@exemplo.com"` e repita o commit.

No GitHub, crie um repositório vazio (New repository, sem README, .gitignore ou licença), por exemplo
`restaurantia-nexus`, e envie o código. Troque `SEU-USUARIO` pelo seu usuário do GitHub:

```
git remote add origin https://github.com/SEU-USUARIO/restaurantia-nexus.git
git push -u origin main
```

O [`.gitattributes`](../.gitattributes) mantém os arquivos com fim de linha LF, para os scripts dos containers
continuarem funcionando mesmo editados no Windows.

## 2. Criar o projeto no Vercel

1. Em vercel.com, clique em **Add New… → Project** e importe o repositório (autorize o GitHub se for a primeira vez).
2. Em **Root Directory**, deixe a raiz do repositório (não escolha `apps/web`).
3. Em **Framework Preset**, use **Services**. O Vercel costuma detectar isso pelo `vercel.json`.
4. Em **Environment Variables**, adicione as duas variáveis abaixo, marcando **Production** e **Preview**:

| Variável | Valor |
| --- | --- |
| `JWT_SECRET` | um segredo aleatório com 32 caracteres ou mais |
| `PROXY_SHARED_SECRET` | outro segredo aleatório. O BFF o envia para a API confiar no IP real do visitante; sem ele, todos os visitantes dividiriam a mesma cota da demonstração |

   Para gerar cada segredo (rode duas vezes, um valor para cada variável):

   ```
   docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

5. Clique em **Deploy**. O primeiro build vai falhar com a mensagem `ERRO: nenhum banco configurado`. Isso é esperado:
   o banco é criado no próximo passo.

Não defina `API_INTERNAL_URL` (o binding injeta) nem `DATABASE_URL` à mão (o Neon injeta). `APP_ENV` vira
`production` sozinho no ambiente Production.

## 3. Conectar o banco Neon

1. No projeto, vá em **Storage → Create Database → Neon** (plano Free).
2. Escolha a região do banco e use a mesma nas funções do Vercel. Por padrão as funções rodam em `iad1`
   (Washington, EUA), que combina com **AWS US East 1** no Neon. Se preferir São Paulo no Neon, mude a região das
   funções para `gru1` em **Settings → Functions**. Banco e função em regiões diferentes deixam cada consulta lenta.
3. Deixe o Neon Auth desligado. O projeto tem a própria autenticação.
4. Conecte o banco ao ambiente **Production** e deixe o campo de prefixo das variáveis vazio. Com um prefixo, as
   variáveis viram algo como `STORAGE_DATABASE_URL` e o build não encontra o banco. Sem prefixo, o Vercel adiciona
   `DATABASE_URL` (com pooler, usado pela API) e `DATABASE_URL_UNPOOLED` (direto, usado pelas migrações).
5. Em **Deployments**, abra o último deploy e use **⋯ → Redeploy**. No log do serviço `api`, procure a linha
   `Migrações aplicadas e seed concluído (production)`.

Previews (outras branches) só funcionam com um banco próprio. Crie um segundo banco Neon e conecte-o ao ambiente
**Preview**. Não compartilhe o banco de produção com previews.

## 4. Testar

Abra `https://<seu-projeto>.vercel.app`, clique em **Entrar no modo demo** e siga o
[roteiro da demonstração](../README.md#o-que-acontece-na-demonstração). A simulação anda enquanto o painel está aberto.
O primeiro acesso depois de um tempo parado pode levar alguns segundos, porque o Neon acorda o banco e o Vercel inicia
a função Python.

Para rodar os testes de ponta a ponta contra a URL pública (precisa de Node.js 22), no cmd do Windows:

```
cd tests/e2e
npm ci
npx playwright install chromium
set E2E_BASE_URL=https://<seu-projeto>.vercel.app
npx playwright test
```

## 5. Problemas que encontrei

| Sintoma | Causa e solução |
| --- | --- |
| Na importação, o Vercel pede um `vercel.json` ou mostra caminhos como `restaurantia-nexus/apps` | O repositório foi criado na pasta de cima. Recrie-o dentro de `restaurantia-nexus` e envie com `git push --force` (passo 1). Não use o `vercel.json` sugerido pelo Vercel: ele expõe a API em `/api/*` e quebra as rotas do próprio site. |
| `git push` falha com "repository not found" | A URL do `origin` ainda tem um texto de exemplo. Corrija com `git remote set-url origin https://github.com/<seu-usuario>/restaurantia-nexus.git`. |
| Build da `api` falha com `nenhum banco configurado` | O banco ainda não está conectado ao ambiente do deploy, ou foi conectado com prefixo nas variáveis (passo 3). |
| Build ou funções falham com `JWT_SECRET must be set` | A variável está ausente ou tem menos de 32 caracteres naquele ambiente. Corrija e faça Redeploy. |
| Tela "API indisponível" ou erro 502 | A função Python falhou ao iniciar. Veja **Logs** filtrando pelo serviço `api`. |
| O painel demora a responder | Banco e funções em regiões diferentes (passo 3), ou o primeiro acesso depois de o banco dormir. |
| A simulação não avança | Ela só avança com o painel aberto. Confira nos Logs se as requisições a `/live` retornam 200. |
| "Muitas sessões demo" | Cota por IP (`DEMO_MAX_SESSIONS_PER_IP_PER_HOUR`, padrão 5). Confira se `PROXY_SHARED_SECRET` está definido. |

## Cotas do plano gratuito

Conferi na documentação em novembro de 2026. Elas mudam, então vale conferir antes de divulgar o link.

- Vercel Hobby, por mês: 4 horas de CPU ativa, 360 GB-hora de memória provisionada e 1 milhão de invocações. Cada
  painel aberto faz cerca de uma consulta a `/live` por segundo enquanto a simulação roda, uma a cada 4 s quando ela
  está parada, e nenhuma com a aba em segundo plano. As funções podem durar até 300 s.
- Neon Free: 100 CU-hora por projeto por mês e 1 GB de armazenamento, e o banco dorme depois de 5 minutos sem uso. As
  demonstrações expiram (`DEMO_SESSION_TTL_MINUTES`) e são apagadas quando novas sessões são criadas.
- O modo determinístico dos agentes não gasta nada com modelos. Se usar um LLM, configure limites de gasto no provedor.

## Alternativa: qualquer host com Docker

A mesma imagem da API roda como `api` e como `worker` (`apps/api/Dockerfile`, com contexto na raiz), e o web roda como
container Next.js standalone (`apps/web/Dockerfile`), igual ao `docker-compose.yml`. Use o modo padrão
(`RUNTIME_MODE=server`, com worker), `APP_ENV=production`, um `JWT_SECRET` forte, o mesmo `PROXY_SHARED_SECRET` nos dois
serviços com `TRUST_PROXY_HEADERS=true` na API, e rode as migrações antes de cada versão com
`sh /usr/local/bin/docker-entrypoint.sh migrate`.

## Referências

- [Vercel Services](https://vercel.com/docs/services), [service bindings](https://vercel.com/docs/services/bindings) e
  [roteamento](https://vercel.com/docs/services/routing)
- [Backend Python com Next.js no Vercel](https://vercel.com/kb/guide/python-backend-on-vercel) e
  [FastAPI no Vercel](https://vercel.com/docs/frameworks/backend/fastapi)
- [Runtime Python](https://vercel.com/docs/functions/runtimes/python) e
  [limites das funções](https://vercel.com/docs/functions/limitations)
- [Plano Hobby](https://vercel.com/docs/plans/hobby) e [limites dos Daemons](https://vercel.com/docs/daemons/limits)
- [Limites do plano Free do Neon](https://neon.com/faqs/free-plan-limits-and-quotas)
