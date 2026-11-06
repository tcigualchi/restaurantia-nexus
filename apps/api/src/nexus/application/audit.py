"""Append-only audit trail helper."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from nexus.domain.guardrails import redact_secrets
from nexus.infra.models import AuditLog

# Display names for agent actors, matching the labels used in the web app.
AGENT_LABELS = {
    "orchestrator": "Orquestrador",
    "operations": "Agente de operação",
    "inventory": "Agente de estoque",
    "forecasting": "Agente de previsão",
}
SENSITIVE_KEYS = {"password", "password_hash", "token", "access_token", "api_key", "authorization", "secret", "jwt"}


@dataclass(frozen=True)
class Actor:
    type: str  # user | agent | system
    id: str | None
    label: str

    @classmethod
    def system(cls, label: str = "Sistema") -> Actor:
        return cls("system", None, label)

    @classmethod
    def agent(cls, name: str) -> Actor:
        return cls("agent", name, AGENT_LABELS.get(name, f"Agente {name}"))


def _sanitize(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "…"
    if isinstance(value, Mapping):
        return {
            str(k): ("[REDACTED]" if str(k).lower() in SENSITIVE_KEYS else _sanitize(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [_sanitize(v, depth + 1) for v in value[:50]]
    if isinstance(value, str):
        return redact_secrets(value)[:1000]
    if isinstance(value, uuid.UUID | datetime):
        return str(value)
    return value


def record_audit(
    session: Session,
    *,
    restaurant_id: uuid.UUID | None,
    actor: Actor,
    action: str,
    target_type: str | None = None,
    target_id: str | uuid.UUID | None = None,
    details: Mapping[str, Any] | None = None,
    business_time: datetime | None = None,
    request_id: str | None = None,
) -> AuditLog:
    row = AuditLog(
        restaurant_id=restaurant_id,
        actor_type=actor.type,
        actor_id=actor.id,
        actor_label=actor.label[:120],
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        details=_sanitize(dict(details or {})),
        business_time=business_time,
        request_id=request_id,
    )
    session.add(row)
    return row
