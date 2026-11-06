"""Settings must accept the environment that Docker Compose actually hands to the containers.

Regression: Compose turns an unset ``${VAR:-}`` into an empty string; optional numeric settings
(LLM prices) failed to parse "" and the API container exited before running migrations.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from nexus.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[4]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
_COMPOSE_VAR = re.compile(r"\$\{(?P<name>[A-Za-z0-9_]+)(?::?-(?P<default>[^}]*))?\}")

OPTIONAL_VARS = (
    "JWT_SECRET",
    "PROXY_SHARED_SECRET",
    "LLM_API_KEY",
    "LLM_MODEL",
    "LLM_PRICE_INPUT_PER_MTOK_USD",
    "LLM_PRICE_OUTPUT_PER_MTOK_USD",
)


def _interpolate(value: Any) -> str:
    """Resolve ``${VAR:-default}`` the way Compose does when VAR is not set on the host."""
    text = str(value).replace("$$", "\0")
    text = _COMPOSE_VAR.sub(lambda m: m.group("default") or "", text)
    return text.replace("\0", "$")


def _compose_environment(service: str) -> dict[str, str]:
    yaml = pytest.importorskip("yaml")
    if not COMPOSE_FILE.exists():
        pytest.skip("docker-compose.yml is not available next to the API package")
    spec = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    environment = spec["services"][service].get("environment") or {}
    return {key: _interpolate(value) for key, value in environment.items()}


def test_empty_values_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    for name in OPTIONAL_VARS:
        monkeypatch.setenv(name, "")

    settings = Settings(_env_file=None)

    assert settings.llm_price_input_per_mtok_usd is None
    assert settings.llm_price_output_per_mtok_usd is None
    assert settings.llm_api_key is None
    assert settings.llm_model == ""
    assert settings.proxy_shared_secret is None
    assert len(settings.jwt_secret.get_secret_value()) >= 32  # ephemeral development secret


@pytest.mark.parametrize("service", ["api", "worker"])
def test_compose_environment_is_accepted(service: str, monkeypatch: pytest.MonkeyPatch) -> None:
    environment = _compose_environment(service)
    assert "" in environment.values(), "the regression needs at least one empty compose value"
    for key, value in environment.items():
        monkeypatch.setenv(key, value)

    settings = Settings(_env_file=None)

    assert settings.app_env == "development"
    assert settings.agent_checkpointer == "postgres"
    assert settings.llm_provider == "deterministic"
    assert settings.llm.enabled is False
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_production_still_rejects_an_empty_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", "")

    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(_env_file=None)


STRONG_SECRET = "x" * 48


def test_vercel_production_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("APP_ENV", "RUNTIME_MODE", "TRUST_PROXY_HEADERS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", STRONG_SECRET)

    settings = Settings(_env_file=None)

    assert settings.app_env == "production"
    assert settings.serverless
    assert settings.trusts_proxy_headers  # still requires the matching PROXY_SHARED_SECRET per request


def test_serverless_never_falls_back_to_an_ephemeral_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("APP_ENV", "RUNTIME_MODE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_ENV", "preview")
    monkeypatch.setenv("JWT_SECRET", "")

    with pytest.raises(ValueError, match="serverless"):
        Settings(_env_file=None)


def test_local_defaults_stay_server_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("APP_ENV", "RUNTIME_MODE", "VERCEL", "VERCEL_ENV", "TRUST_PROXY_HEADERS"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert (settings.app_env, settings.runtime_mode, settings.trusts_proxy_headers) == ("development", "server", False)


@pytest.mark.parametrize(
    ("url", "override", "pooled"),
    [
        ("postgresql://u:p@ep-cool-sun-123456-pooler.us-east-1.aws.neon.tech/neondb?sslmode=require", None, True),
        ("postgresql://u:p@ep-cool-sun-123456.us-east-1.aws.neon.tech/neondb?sslmode=require", None, False),
        ("postgresql://u:p@db:5432/nexus", True, True),
    ],
)
def test_transaction_pooler_disables_prepared_statements_and_session_sets(
    url: str, override: bool | None, pooled: bool
) -> None:
    from nexus.infra.db import engine_options

    settings = Settings(_env_file=None, database_url=url, db_pooled=override)
    connect_args, timeout = engine_options(settings)

    assert settings.uses_pooler is pooled
    assert settings.database_url.startswith("postgresql+psycopg://")
    if pooled:
        assert connect_args["prepare_threshold"] is None and timeout == 0
    else:
        assert "prepare_threshold" not in connect_args and timeout == settings.db_statement_timeout_ms
