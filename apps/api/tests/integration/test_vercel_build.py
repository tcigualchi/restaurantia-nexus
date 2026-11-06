"""Vercel build hook (scripts/vercel_build.py): migrations + seed before a deployment gets traffic."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import create_engine, func, select, text

from nexus.config import get_settings
from nexus.infra import db as db_module
from nexus.infra.models import Restaurant
from tests.conftest import TEST_DB

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "vercel_build.py"
URL_VARS = ("MIGRATION_DATABASE_URL", "DATABASE_URL_UNPOOLED", "DATABASE_URL")


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("vercel_build", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in URL_VARS:
        monkeypatch.delenv(name, raising=False)


def test_production_build_without_database_fails_with_guidance(
    no_database: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("VERCEL_ENV", "production")
    assert _load().main() == 1
    assert "Storage" in capsys.readouterr().err


def test_preview_build_without_database_only_warns(no_database: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERCEL_ENV", "preview")
    assert _load().main() == 0


@pytest.mark.integration
def test_build_hook_migrates_and_seeds_a_fresh_database(migrated: None, monkeypatch: pytest.MonkeyPatch) -> None:
    name = f"nexus_build_{uuid.uuid4().hex[:8]}"
    admin = create_engine(TEST_DB, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    fresh_url = TEST_DB.rsplit("/", 1)[0] + "/" + name
    try:
        monkeypatch.setenv("DATABASE_URL", TEST_DB)  # restored at teardown (the hook rewrites it)
        monkeypatch.setenv("DATABASE_URL_UNPOOLED", fresh_url.replace("postgresql+psycopg://", "postgres://"))
        monkeypatch.setenv("VERCEL_ENV", "production")
        get_settings.cache_clear()
        db_module.get_engine.cache_clear()
        db_module.get_session_factory.cache_clear()

        build = _load()
        assert build.main() == 0
        assert build.main() == 0  # idempotent: a redeploy migrates nothing and seeds nothing new

        db_module.get_engine().dispose()
        check = create_engine(fresh_url)
        with check.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM alembic_version")) == 1
            assert conn.scalar(select(func.count()).select_from(Restaurant)) == 2
        check.dispose()
    finally:
        get_settings.cache_clear()
        db_module.get_engine.cache_clear()
        db_module.get_session_factory.cache_clear()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
