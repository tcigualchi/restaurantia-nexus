"""Engine and session management (SQLAlchemy 2, psycopg 3, synchronous)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from nexus.config import Settings, get_settings


def engine_options(settings: Settings) -> tuple[dict[str, Any], int]:
    """Connect args and statement timeout for the configured database endpoint."""
    connect_args: dict[str, Any] = {"application_name": "restaurantia-nexus"}
    timeout = int(settings.db_statement_timeout_ms)
    if settings.uses_pooler:
        # Transaction-mode poolers (PgBouncer, Neon "-pooler" hosts) hand each transaction to any
        # server connection: no server-side prepared statements and no session-level SETs.
        connect_args["prepare_threshold"] = None
        timeout = 0
    return connect_args, timeout


def make_engine(settings: Settings) -> Engine:
    connect_args, timeout = engine_options(settings)
    engine = create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_size,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args=connect_args,
    )

    if timeout > 0:
        # Session-level SETs need a direct (unpooled) connection. Behind a transaction-mode
        # pooler they are skipped (see engine_options); configure timeouts on the role instead.
        @event.listens_for(engine, "connect")
        def _on_connect(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            with dbapi_conn.cursor() as cur:
                cur.execute(f"SET statement_timeout = {timeout}")
                cur.execute("SET timezone = 'UTC'")
            dbapi_conn.commit()

    return engine


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return make_engine(get_settings())


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope(factory: sessionmaker[Session] | None = None) -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on error."""
    session = (factory or get_session_factory())()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def ping(session: Session) -> bool:
    return bool(session.execute(text("SELECT 1")).scalar_one() == 1)
