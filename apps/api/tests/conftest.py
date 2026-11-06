"""Shared fixtures.

Unit tests only use the catalog fixtures. Database fixtures are lazy: they are
created only when an integration/security test requests ``settings``,
``factory``, ``client`` or ``make_tenant`` (PostgreSQL via TEST_DATABASE_URL).
"""

from __future__ import annotations

import os
import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://nexus:nexus@127.0.0.1:5432/nexus_test")
os.environ.update(
    {
        "DATABASE_URL": TEST_DB,
        "APP_ENV": "test",
        "JWT_SECRET": os.environ.get("TEST_JWT_SECRET", secrets.token_urlsafe(48)),
        "DEMO_MAX_SESSIONS_PER_IP_PER_HOUR": "1000",
        "DEMO_BURST_PER_MINUTE": "1000",
        "RATE_LIMIT_PER_MINUTE": "100000",
        "RATE_LIMIT_MUTATIONS_PER_MINUTE": "100000",
        "LLM_PROVIDER": "deterministic",
        "AGENT_CHECKPOINTER": "memory",
        "EMBEDDED_WORKER": "false",
    }
)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from nexus.config import Settings, get_settings  # noqa: E402
from nexus.domain.catalog import Catalog, load_catalog  # noqa: E402
from nexus.infra import db as db_module  # noqa: E402

API_DIR = Path(__file__).resolve().parents[1]


def _reset_schema() -> None:
    engine = create_engine(TEST_DB)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", TEST_DB)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def migrated() -> Iterator[None]:
    try:
        _reset_schema()
    except Exception as exc:
        if os.environ.get("REQUIRE_DB_TESTS") == "1":
            raise
        pytest.skip(f"PostgreSQL not available for integration tests: {exc}")
    get_settings.cache_clear()
    db_module.get_engine.cache_clear()
    db_module.get_session_factory.cache_clear()
    yield
    db_module.get_engine().dispose()


@pytest.fixture(scope="session")
def settings(migrated: None) -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def factory(migrated: None) -> sessionmaker[Session]:
    return db_module.get_session_factory()


@dataclass
class Tenant:
    user_id: uuid.UUID
    restaurant_id: uuid.UUID
    role: str


@pytest.fixture
def make_tenant(factory, catalog):
    from nexus.application.sandbox import create_restaurant_from_template
    from nexus.infra.db import session_scope
    from nexus.infra.models import Membership, User

    def _make(role: str = "manager", template: str = "aurora_pinheiros") -> Tenant:
        with session_scope(factory) as s:
            user = User(email=f"u{uuid.uuid4().hex[:10]}@test.invalid", display_name=f"Teste {role}")
            s.add(user)
            s.flush()
            restaurant = create_restaurant_from_template(s, catalog.get(template))
            s.add(Membership(user_id=user.id, restaurant_id=restaurant.id, role=role))
            return Tenant(user.id, restaurant.id, role)

    return _make


@pytest.fixture(scope="session")
def client(migrated: None):
    from fastapi.testclient import TestClient

    from nexus.main import create_app

    with TestClient(create_app(get_settings())) as c:
        yield c


@pytest.fixture(scope="session")
def catalog() -> Catalog:
    return load_catalog()


@pytest.fixture(scope="session")
def aurora(catalog: Catalog):
    return catalog.get("aurora_pinheiros")
