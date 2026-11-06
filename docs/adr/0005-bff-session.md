# ADR 0005 — BFF no Next.js com cookie httpOnly; baseline de segurança

- **Status:** aceito · **Data:** 2026-11-05

## Contexto
O frontend (Vercel) e a API (container) ficam em domínios diferentes. Tokens no `localStorage` ficam expostos a XSS;
cookies de terceiros são bloqueados por navegadores.

## Decisão
- O navegador fala apenas com o próprio Next.js. `/api/session/*` troca credenciais por um JWT e o guarda em cookie
  `httpOnly`, `SameSite=Lax`, `Secure` em produção. `/api/proxy/v1/*` repassa chamadas à API com `Authorization: Bearer`.
- O proxy só aceita caminhos `v1/*`, repassa cabeçalhos permitidos e faz streaming de SSE.
- `API_INTERNAL_URL` é variável de servidor; `NEXT_PUBLIC_API_URL` não é usada (a URL da API nunca vai ao navegador).
- CSP restritiva (`connect-src 'self'`), `frame-ancestors 'none'`, `nosniff`, CORS por allowlist na API.
- O IP real do cliente só é aceito pela API quando o BFF envia `X-Proxy-Secret` válido (`PROXY_SHARED_SECRET`).
- Rate limit em memória por instância (janela deslizante) + quotas de demo no banco (por hash de IP e total ativo).

## Consequências
- + Token inacessível a JavaScript; superfície pública reduzida.
- − Rate limit não é compartilhado entre réplicas; para várias instâncias mover para Redis/tabela.
- − `script-src 'unsafe-inline'` é mantido por compatibilidade com o runtime do Next; próximo passo: CSP com nonce.
