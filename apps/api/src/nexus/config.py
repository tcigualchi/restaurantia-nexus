"""Runtime configuration (12-factor). Secrets come only from the environment."""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from nexus.agents.llm import ProviderSettings

INSECURE_SECRETS = {"", "change-me", "changeme", "secret", "dev"}

AppEnv = Literal["development", "test", "production"]
RuntimeMode = Literal["server", "serverless"]


def _default_app_env() -> AppEnv:
    # Vercel exposes VERCEL_ENV=production|preview|development to builds and functions.
    return "production" if os.environ.get("VERCEL_ENV") == "production" else "development"


def _default_runtime_mode() -> RuntimeMode:
    # VERCEL=1 is set by Vercel in builds and functions: there is no long-running worker there.
    return "serverless" if os.environ.get("VERCEL") == "1" else "server"


def normalize_database_url(url: str) -> str:
    """Managed providers hand out postgres:// URLs; SQLAlchemy needs an explicit driver."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


class Settings(BaseSettings):
    # env_ignore_empty: Docker Compose turns unset `${VAR:-}` into "", which must mean "use the default"
    # (otherwise optional numbers such as LLM prices fail to parse and the container exits at startup).
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True)

    app_env: AppEnv = Field(default_factory=_default_app_env)
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    # server: a worker process (or EMBEDDED_WORKER) runs simulations, events and agents.
    # serverless: no background process; the same work runs inline when clients poll /live.
    runtime_mode: RuntimeMode = Field(default_factory=_default_runtime_mode)

    database_url: str = "postgresql+psycopg://nexus:nexus@localhost:5432/nexus"
    db_pool_size: int = 10
    db_statement_timeout_ms: int = 15_000
    # Transaction-mode pooler (e.g. Neon "-pooler" hosts): no session SETs, no prepared statements.
    # Unset = detect from the host name.
    db_pooled: bool | None = None

    jwt_secret: SecretStr = Field(default=SecretStr(""))
    jwt_ttl_minutes: int = 120
    cors_origins: str = "http://localhost:3000"
    # Forwarded client IPs are trusted only with the matching PROXY_SHARED_SECRET (see api.deps.client_ip).
    # Serverless deployments always sit behind the web BFF, so trust is implied there.
    trust_proxy_headers: bool = False
    proxy_shared_secret: SecretStr | None = None

    # Demo sandbox
    demo_enabled: bool = True
    demo_session_ttl_minutes: int = 120
    demo_max_sessions_per_ip_per_hour: int = 5
    demo_max_active_sessions: int = 200
    demo_burst_per_minute: int = 3
    rate_limit_per_minute: int = 240
    rate_limit_mutations_per_minute: int = 60

    # Simulation / worker
    embedded_worker: bool = False
    worker_poll_seconds: float = 0.25
    default_tick_interval_ms: int = 1000
    min_tick_interval_ms: int = 200
    approval_ttl_minutes: int = 30
    event_max_attempts: int = 5
    max_ingest_body_bytes: int = 64 * 1024

    # Agents / LLM (deterministic demo mode when llm_provider=deterministic)
    llm_provider: Literal["deterministic", "openai_compatible"] = "deterministic"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr | None = None
    llm_model: str = ""
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2
    llm_max_tokens: int = 700
    llm_price_input_per_mtok_usd: float | None = None
    llm_price_output_per_mtok_usd: float | None = None
    agent_checkpointer: Literal["memory", "postgres"] = "memory"

    dataset_dir: str | None = None

    @field_validator("database_url")
    @classmethod
    def _normalize_driver(cls, v: str) -> str:
        return normalize_database_url(v)

    @model_validator(mode="after")
    def _check_secrets(self) -> Settings:
        secret = self.jwt_secret.get_secret_value()
        if self.app_env == "production" and (secret.lower() in INSECURE_SECRETS or len(secret) < 32):
            raise ValueError("JWT_SECRET must be set to a random value of at least 32 characters in production")
        if not secret:
            if self.runtime_mode == "serverless":
                # Every function instance would generate its own secret and reject the others' tokens.
                raise ValueError("JWT_SECRET must be set in serverless mode (e.g. on Vercel), even outside production")
            # Development convenience: ephemeral secret (tokens die on restart). Never used in production.
            object.__setattr__(self, "jwt_secret", SecretStr(secrets.token_urlsafe(48)))
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def serverless(self) -> bool:
        return self.runtime_mode == "serverless"

    @property
    def trusts_proxy_headers(self) -> bool:
        return self.trust_proxy_headers or self.serverless

    @property
    def uses_pooler(self) -> bool:
        if self.db_pooled is not None:
            return self.db_pooled
        return "-pooler" in (urlsplit(self.database_url).hostname or "")

    @property
    def llm(self) -> ProviderSettings:
        return ProviderSettings(
            provider=self.llm_provider,
            base_url=self.llm_base_url,
            api_key=self.llm_api_key,
            model=self.llm_model,
            timeout_seconds=self.llm_timeout_seconds,
            max_retries=self.llm_max_retries,
            max_tokens=self.llm_max_tokens,
            price_input_per_mtok_usd=self.llm_price_input_per_mtok_usd,
            price_output_per_mtok_usd=self.llm_price_output_per_mtok_usd,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
