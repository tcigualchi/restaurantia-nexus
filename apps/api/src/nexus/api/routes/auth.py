from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from nexus.api.deps import CatalogDep, DbDep, SettingsDep, UserDep, client_ip
from nexus.api.middleware import limiter
from nexus.application.demo import create_demo_sandbox, purge_expired_sandboxes
from nexus.application.queries import restaurant_view
from nexus.application.security import create_access_token, verify_password
from nexus.application.views import RestaurantView
from nexus.domain.errors import RateLimited, Unauthorized
from nexus.infra.models import DemoSession, Membership, Restaurant, User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class DemoIn(BaseModel):
    persona: Literal["manager", "operator"] = "manager"


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=200)


class SessionOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_at: datetime
    user: dict[str, object]
    restaurants: list[RestaurantView]


class MeOut(BaseModel):
    id: str
    display_name: str
    is_demo: bool
    demo_expires_at: datetime | None
    restaurants: list[RestaurantView]


def _restaurants(db: DbDep, user: User) -> list[RestaurantView]:
    rows = db.execute(
        select(Restaurant, Membership.role)
        .join(Membership, Membership.restaurant_id == Restaurant.id)
        .where(Membership.user_id == user.id)
        .order_by(Restaurant.name)
    ).all()
    return [restaurant_view(r, role) for r, role in rows]


@router.post(
    "/demo",
    response_model=SessionOut,
    status_code=201,
    summary="Create an isolated demo sandbox (synthetic data) and return a session",
)
def demo(body: DemoIn, request: Request, db: DbDep, settings: SettingsDep, catalog: CatalogDep) -> SessionOut:
    ip = client_ip(request, settings)
    ok, retry = limiter.check(f"demo:{ip}", limit=settings.demo_burst_per_minute, window_seconds=60)
    if not ok:
        raise RateLimited("Aguarde alguns segundos antes de criar outra sessão demo.", retry_after_seconds=retry)
    if settings.serverless:
        # No housekeeping worker on serverless platforms: retire expired sandboxes as new ones arrive.
        purge_expired_sandboxes(db, batch=5)
    sandbox = create_demo_sandbox(db, catalog=catalog, settings=settings, client_ip=ip, persona=body.persona)
    token, expires = create_access_token(
        sandbox.user.id, is_demo=True, settings=settings, ttl_minutes=settings.demo_session_ttl_minutes
    )
    return SessionOut(
        access_token=token,
        expires_at=expires,
        user={
            "id": str(sandbox.user.id),
            "display_name": sandbox.user.display_name,
            "is_demo": True,
            "persona": body.persona,
        },
        restaurants=_restaurants(db, sandbox.user),
    )


@router.post("/login", response_model=SessionOut, summary="Password login (seeded local users)")
def login(body: LoginIn, request: Request, db: DbDep, settings: SettingsDep) -> SessionOut:
    ip = client_ip(request, settings)
    ok, retry = limiter.check(f"login:{ip}", limit=10, window_seconds=300)
    if not ok:
        raise RateLimited("Muitas tentativas de login.", retry_after_seconds=retry)
    user = db.scalars(select(User).where(func.lower(User.email) == body.email.strip().lower())).one_or_none()
    if user is None or user.is_demo or not verify_password(body.password, user.password_hash if user else None):
        raise Unauthorized("Credenciais inválidas.", code="invalid_credentials")
    token, expires = create_access_token(user.id, is_demo=False, settings=settings)
    return SessionOut(
        access_token=token,
        expires_at=expires,
        user={"id": str(user.id), "display_name": user.display_name, "is_demo": False},
        restaurants=_restaurants(db, user),
    )


@router.get("/me", response_model=MeOut, summary="Current user and accessible restaurants")
def me(user: UserDep, db: DbDep) -> MeOut:
    expires = db.scalar(select(DemoSession.expires_at).where(DemoSession.user_id == user.id)) if user.is_demo else None
    return MeOut(
        id=str(user.id),
        display_name=user.display_name,
        is_demo=user.is_demo,
        demo_expires_at=expires,
        restaurants=_restaurants(db, user),
    )
