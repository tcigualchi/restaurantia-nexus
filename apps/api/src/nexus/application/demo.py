"""Isolated demo sandboxes for evaluators.

Each visitor who clicks "Entrar no modo demo" gets a private user and private
copies of the synthetic restaurants (separate tenants). Sessions expire; a
retention job deletes the sandbox and its audit trail. Quotas cap sessions per
IP and the total number of active sandboxes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from nexus.application.audit import Actor, record_audit
from nexus.application.sandbox import create_restaurant_from_template
from nexus.application.security import hash_ip
from nexus.config import Settings
from nexus.domain.catalog import Catalog
from nexus.domain.errors import Forbidden, RateLimited
from nexus.domain.rbac import Role
from nexus.infra.models import AuditLog, DemoSession, Membership, Restaurant, User

PERSONA_ROLES = {"manager": Role.MANAGER, "operator": Role.OPERATOR}


@dataclass(frozen=True)
class DemoSandbox:
    user: User
    session: DemoSession
    restaurants: list[Restaurant]


def create_demo_sandbox(
    db: Session, *, catalog: Catalog, settings: Settings, client_ip: str, persona: str
) -> DemoSandbox:
    if not settings.demo_enabled:
        raise Forbidden("Modo demo desabilitado neste ambiente.", code="demo_disabled")
    role = PERSONA_ROLES.get(persona)
    if role is None:
        raise Forbidden("Persona inválida.", code="invalid_persona")
    now = datetime.now(UTC)
    ip_hash = hash_ip(client_ip, settings)
    recent = db.scalar(
        select(func.count())
        .select_from(DemoSession)
        .where(DemoSession.ip_hash == ip_hash, DemoSession.created_at > now - timedelta(hours=1))
    )
    if (recent or 0) >= settings.demo_max_sessions_per_ip_per_hour:
        raise RateLimited(
            "Limite de sessões demo por hora atingido. Tente novamente mais tarde.", retry_after_seconds=900
        )
    active = db.scalar(select(func.count()).select_from(DemoSession).where(DemoSession.expires_at > now))
    if (active or 0) >= settings.demo_max_active_sessions:
        raise RateLimited("Capacidade de sandboxes demo esgotada no momento.", retry_after_seconds=300)

    user = User(email=f"demo+{uuid.uuid4().hex[:12]}@demo.invalid", display_name="Visitante (demo)", is_demo=True)
    db.add(user)
    db.flush()
    sandbox = DemoSession(
        user_id=user.id,
        ip_hash=ip_hash,
        persona=persona,
        expires_at=now + timedelta(minutes=settings.demo_session_ttl_minutes),
    )
    db.add(sandbox)
    db.flush()
    restaurants: list[Restaurant] = []
    for template in catalog.templates:
        restaurant = create_restaurant_from_template(db, template, is_demo=True, demo_session_id=sandbox.id)
        db.add(Membership(user_id=user.id, restaurant_id=restaurant.id, role=role.value))
        record_audit(
            db,
            restaurant_id=restaurant.id,
            actor=Actor("user", str(user.id), user.display_name),
            action="sandbox.created",
            target_type="restaurant",
            target_id=restaurant.id,
            details={"template": template.key, "persona": persona, "expires_at": sandbox.expires_at.isoformat()},
        )
        restaurants.append(restaurant)
    db.flush()
    return DemoSandbox(user, sandbox, restaurants)


def purge_expired_sandboxes(db: Session, *, now: datetime | None = None, batch: int = 20) -> int:
    """Retention job: delete expired sandboxes, their tenant data and their audit trail."""
    now = now or datetime.now(UTC)
    expired = list(db.scalars(select(DemoSession).where(DemoSession.expires_at < now).limit(batch)))
    if not expired:
        return 0
    db.execute(text("SELECT set_config('nexus.retention_purge', 'on', true)"))
    for sandbox in expired:
        restaurant_ids = list(db.scalars(select(Restaurant.id).where(Restaurant.demo_session_id == sandbox.id)))
        if restaurant_ids:
            db.execute(delete(AuditLog).where(AuditLog.restaurant_id.in_(restaurant_ids)))
        db.execute(delete(User).where(User.id == sandbox.user_id))  # cascades to session → restaurants → data
    db.execute(text("SELECT set_config('nexus.retention_purge', 'off', true)"))
    return len(expired)
