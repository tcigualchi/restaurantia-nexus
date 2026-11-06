"""FastAPI dependencies: settings, DB session, authentication and tenant scope."""

from __future__ import annotations

import hmac
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Path, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.application.audit import Actor
from nexus.application.security import decode_access_token
from nexus.config import Settings, get_settings
from nexus.domain.catalog import Catalog, cached_catalog
from nexus.domain.errors import Forbidden, NotFound, Unauthorized
from nexus.domain.rbac import Permission, Role, has_permission
from nexus.infra.db import get_session_factory
from nexus.infra.models import Membership, Restaurant, User
from nexus.logging_config import request_id_var


def settings_dep(request: Request) -> Settings:
    """The settings the app was created with (``create_app(settings)``), else the process-wide ones."""
    settings = getattr(request.app.state, "settings", None)
    return settings if isinstance(settings, Settings) else get_settings()


def catalog_dep(settings: Annotated[Settings, Depends(settings_dep)]) -> Catalog:
    return cached_catalog(settings.dataset_dir)


def db_session() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


SettingsDep = Annotated[Settings, Depends(settings_dep)]
CatalogDep = Annotated[Catalog, Depends(catalog_dep)]
DbDep = Annotated[Session, Depends(db_session)]


def client_ip(request: Request, settings: Settings) -> str:
    """Client IP. Forwarded headers are trusted only from the authenticated BFF proxy."""
    if settings.trusts_proxy_headers and settings.proxy_shared_secret is not None:
        provided = request.headers.get("x-proxy-secret", "")
        if hmac.compare_digest(provided, settings.proxy_shared_secret.get_secret_value()):
            forwarded = request.headers.get("x-client-ip") or request.headers.get("x-forwarded-for", "")
            first = forwarded.split(",")[0].strip()
            if first:
                return first[:64]
    return request.client.host if request.client else "unknown"


def request_id() -> str | None:
    return request_id_var.get()


def current_user(db: DbDep, settings: SettingsDep, authorization: Annotated[str | None, Header()] = None) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Autenticação necessária.", code="missing_token")
    claims = decode_access_token(authorization.split(" ", 1)[1].strip(), settings)
    user = db.get(User, claims.user_id)
    if user is None:
        raise Unauthorized("Sessão inválida.", code="unknown_user")
    return user


UserDep = Annotated[User, Depends(current_user)]


@dataclass(frozen=True)
class TenantContext:
    user: User
    restaurant: Restaurant
    role: Role

    @property
    def restaurant_id(self) -> uuid.UUID:
        return self.restaurant.id

    @property
    def actor(self) -> Actor:
        return Actor("user", str(self.user.id), self.user.display_name)

    def require(self, permission: Permission) -> None:
        if not has_permission(self.role, permission):
            raise Forbidden(
                "Seu papel não permite esta operação.",
                code="permission_denied",
                details={"required": permission.value, "role": self.role.value},
            )


def tenant(
    restaurant_id: Annotated[uuid.UUID, Path(description="ID do restaurante (tenant)")], db: DbDep, user: UserDep
) -> TenantContext:
    """Resolve the tenant from the path and the caller's membership.

    Unknown restaurants and restaurants the user cannot access both return 404,
    so the API never reveals whether another tenant exists.
    """
    row = db.execute(
        select(Restaurant, Membership.role)
        .join(Membership, Membership.restaurant_id == Restaurant.id)
        .where(Restaurant.id == restaurant_id, Membership.user_id == user.id)
    ).one_or_none()
    if row is None:
        raise NotFound("Restaurante não encontrado.")
    restaurant, role = row
    return TenantContext(user=user, restaurant=restaurant, role=Role(role))


TenantDep = Annotated[TenantContext, Depends(tenant)]
