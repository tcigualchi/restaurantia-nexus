"""Alembic environment: reads DATABASE_URL via application settings."""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from nexus.config import get_settings
from nexus.infra.models import Base

config = context.config
target_metadata = Base.metadata

# Tables owned by LangGraph's PostgresSaver (AGENT_CHECKPOINTER=postgres) live in the same database
# but are created and migrated by the library itself; autogenerate/check must not try to drop them.
EXTERNAL_TABLES = frozenset({"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"})


def include_object(obj: object, name: str | None, type_: str, reflected: bool, compare_to: object) -> bool:
    return not (type_ == "table" and reflected and compare_to is None and name in EXTERNAL_TABLES)


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
