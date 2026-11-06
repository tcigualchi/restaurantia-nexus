# Segurança

O princípio é tratar o modelo de linguagem como um componente não confiável. A arquitetura limita o que ele pode
fazer, e cada camada tem testes.

## Controles implementados

| Ameaça | Controle | Onde | Teste |
| --- | --- | --- | --- |
| LLM executa ação destrutiva | Ferramentas só leitura; nenhuma ferramenta de escrita exposta; ações só via aprovação humana | `agents/tools.py`, ADR 0004 | `test_tools.py`, `test_orchestrator.py` |
| Modelo escolhe outro tenant | `restaurant_id`/`as_of` injetados pelo servidor; argumentos com `extra="forbid"` | `ToolExecutor` | `test_invalid_arguments_are_rejected`, `test_cross_tenant_context_is_refused` |
| SQL arbitrário / injection em argumentos | Sem SQL livre; chaves validadas por regex; consultas parametrizadas (SQLAlchemy) | `domain/catalog.KEY_PATTERN` | `test_key_pattern_blocks_injection_in_arguments` |
| Prompt injection em dados de terceiros | Texto marcado `untrusted`, normalizado, truncado e neutralizado; flags no trace; sem poder de efeito | `domain/guardrails.py` | `test_guardrails.py`, cenário com nota adversarial |
| Modelo inventa fatos/ações | Fatos sem `step_id` válido descartados; prioridade só reordena candidatos existentes | `specialists.py`, `orchestrator.py` | `test_llm_mode_uses_tools_drops_ungrounded_facts…` |
| Execução sem aprovação / dupla execução | Estado `pending` → decisão única sob row lock; `version`; expiração; revalidação | `application/approvals.py` | `test_double_decision_executes_once`, `test_expired_approval_is_gone` |
| Papel insuficiente | RBAC por restaurante (viewer < operator < manager < owner) | `domain/rbac.py`, `TenantContext.require` | `test_operator_cannot_approve…`, e2e RBAC |
| Acesso cruzado entre tenants | Associação obrigatória; 404 indistinguível de inexistente | `api/deps.py` | `test_cross_tenant_access_is_indistinguishable_from_missing` |
| Roubo de token por XSS | JWT só em cookie httpOnly via BFF; CSP `connect-src 'self'` | `apps/web` | inspeção do cookie no e2e/smoke |
| Token forjado/expirado/`alg=none` | HS256 com `iss`/`aud`/`exp` obrigatórios | `application/security.py` | `test_forged_and_expired_tokens_are_rejected` |
| Abuso do modo demo | Quotas por hash de IP e total ativo, janela de rajada, TTL e purga | `application/demo.py` | `test_demo_sandboxes_are_isolated_and_purged` |
| Adulteração da auditoria | Trigger bloqueia UPDATE/DELETE/TRUNCATE; purga só com opt-in transacional de retenção | migração `0001` | `test_audit_log_is_append_only` |
| Vazamento de segredos | Segredos só por env; `SecretStr`; redação em logs e saídas do modelo; info pública sem segredos | `config.py`, `logging_config.py`, `guardrails.redact_secrets` | `test_secrets_are_redacted…`, `test_system_info_exposes_no_secrets` |
| Payloads grandes / DoS simples | Limite de corpo (64 KB), rate limit por sujeito, timeouts de statement e de LLM | `api/middleware.py`, `config.py` | `test_oversized_body_is_rejected_before_parsing` |
| Provedor LLM indisponível | Timeouts, retry com backoff só para erros transitórios, fallback determinístico rotulado | `agents/llm.py` | `test_llm_provider.py` |
| API exposta na internet (Vercel) | API sem rota pública: só o BFF a alcança por *service binding*; IP do visitante aceito apenas com `PROXY_SHARED_SECRET` | `vercel.json`, `api/deps.client_ip` | `test_live_endpoint_advances_work_only_in_serverless_mode` |
| Segredo efêmero em ambiente serverless | Sem `JWT_SECRET`, o modo serverless recusa iniciar (cada instância assinaria tokens com um segredo diferente) | `config.py` | `test_serverless_never_falls_back_to_an_ephemeral_secret` |
| Consulta ao vivo usada para acelerar ou abusar | Ticks dependem do tempo, não do número de consultas; cota própria de 150 consultas `/live` por minuto | `application/pump.py`, `api/middleware.py` | `test_ticks_are_time_based` |

## Riscos conhecidos e próximos passos

- Rate limit em memória por instância → mover para Redis/tabela quando houver múltiplas réplicas (no Vercel cada instância tem a sua janela; as quotas da demo ficam no banco e continuam valendo).
- CSP ainda usa `'unsafe-inline'` para scripts (requisito do runtime) → migrar para CSP com nonce.
- Detecção de injection por padrões é uma camada de visibilidade, não uma garantia; a defesa real é a ausência de
  ferramentas com efeito e a aprovação humana revalidada.
- Sem MFA/SSO para usuários locais; a versão pública usa apenas demonstrações temporárias.
- Auditoria não é encadeada por hash; trigger protege contra a aplicação, não contra um DBA com superusuário.
