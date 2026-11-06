"""Vercel build hook for the API service (pyproject.toml → [tool.vercel.scripts] build).

Runs before the new deployment receives traffic:

1. ``alembic upgrade head`` over a direct connection, holding a session advisory lock so two
   concurrent builds never migrate at the same time;
2. the idempotent seed (reference restaurants; an admin only if SEED_ADMIN_* are set).

The Neon integration provides ``DATABASE_URL`` (pooled, used by the app at runtime) and
``DATABASE_URL_UNPOOLED`` (direct, preferred here: DDL and advisory locks need a real session).
A production build without a database fails with an actionable message; a preview build without
one only warns, so branches can still be built.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
MIGRATION_LOCK_KEY = 7_239_001  # arbitrary, constant across deployments


def _database_url() -> str | None:
    for name in ("MIGRATION_DATABASE_URL", "DATABASE_URL_UNPOOLED", "DATABASE_URL"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def main() -> int:
    sys.path.insert(0, str(API_DIR / "src"))
    environment = os.environ.get("VERCEL_ENV", "local")
    raw_url = _database_url()
    if raw_url is None:
        if environment == "production":
            print(
                "ERRO: nenhum banco configurado. No Vercel, abra o projeto → Storage → conecte um banco Neon "
                "ao ambiente Production e faça Redeploy.",
                file=sys.stderr,
            )
            return 1
        print(f"Aviso: DATABASE_URL ausente no ambiente '{environment}'; migrações não executadas.")
        return 0

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, pool, text

    from nexus.config import normalize_database_url

    url = normalize_database_url(raw_url)
    # Build-time work uses the direct connection too (the seed reads DATABASE_URL via Settings).
    os.environ["DATABASE_URL"] = url

    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as lock_conn:
        lock_conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
        lock_conn.commit()
        try:
            cfg = Config(str(API_DIR / "alembic.ini"))
            cfg.set_main_option("script_location", str(API_DIR / "migrations"))
            cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))  # configparser interpolation
            command.upgrade(cfg, "head")
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY})
            lock_conn.commit()
    engine.dispose()

    from nexus.application.seed import seed

    result = seed()
    print(f"Migrações aplicadas e seed concluído ({environment}): {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
