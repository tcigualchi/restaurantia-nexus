"""Model provider abstraction.

* ``OpenAICompatibleProvider`` talks to any server implementing the OpenAI
  ``/chat/completions`` contract with tool calling (hosted APIs, a gateway, or a
  local Ollama/vLLM server). Timeouts, bounded retries with backoff and typed
  errors are built in; the API key never appears in logs, errors or traces.
* When no provider is configured the platform runs in **deterministic demo
  mode**: agents follow scripted tool plans and template summaries, and the UI
  labels every result as "determinístico (sem LLM)". Nothing pre-written is ever
  presented as model inference.
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, Field, SecretStr

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class LLMError(Exception):
    """Base class for provider failures (safe to show: never contains secrets)."""


class LLMUnavailable(LLMError):
    pass


class LLMBadResponse(LLMError):
    pass


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class ChatResponse(BaseModel):
    content: str | None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    model: str
    latency_ms: int
    attempts: int = 1


class LLMProvider(Protocol):
    name: str
    model: str

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> ChatResponse: ...


class ProviderSettings(BaseModel):
    provider: Literal["deterministic", "openai_compatible"] = "deterministic"
    base_url: str = "https://api.openai.com/v1"
    api_key: SecretStr | None = None
    model: str = ""
    timeout_seconds: float = 30.0
    max_retries: int = 2
    max_tokens: int = 700
    temperature: float = 0.0
    price_input_per_mtok_usd: float | None = None
    price_output_per_mtok_usd: float | None = None

    @property
    def enabled(self) -> bool:
        return self.provider == "openai_compatible" and bool(self.model)


@dataclass
class OpenAICompatibleProvider:
    base_url: str
    model: str
    api_key: SecretStr | None = None
    timeout_seconds: float = 30.0
    max_retries: int = 2
    temperature: float = 0.0
    default_max_tokens: int = 700
    transport: httpx.BaseTransport | None = None
    sleep: Any = time.sleep
    name: str = "openai_compatible"
    _rng: random.Random = field(default_factory=lambda: random.Random(7))

    def _client(self) -> httpx.Client:
        headers = {"Content-Type": "application/json"}
        if self.api_key is not None and self.api_key.get_secret_value():
            headers["Authorization"] = f"Bearer {self.api_key.get_secret_value()}"
        return httpx.Client(
            base_url=self.base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(self.timeout_seconds, connect=min(5.0, self.timeout_seconds)),
            transport=self.transport,
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> ChatResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens or self.default_max_tokens,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        started = time.perf_counter()
        last_error = "unknown error"
        with self._client() as client:
            for attempt in range(1, self.max_retries + 2):
                try:
                    resp = client.post("/chat/completions", json=body)
                except httpx.TimeoutException:
                    last_error = "timeout"
                except httpx.TransportError as exc:
                    last_error = f"transport error: {type(exc).__name__}"
                else:
                    if resp.status_code == 200:
                        return self._parse(resp, started, attempt)
                    last_error = f"HTTP {resp.status_code}"
                    if resp.status_code not in RETRYABLE_STATUS:
                        raise LLMUnavailable(f"provider rejected the request ({last_error})")
                if attempt <= self.max_retries:
                    self.sleep(min(8.0, 0.5 * 2 ** (attempt - 1)) + self._rng.uniform(0, 0.25))
        raise LLMUnavailable(f"provider unavailable after {self.max_retries + 1} attempts ({last_error})")

    def _parse(self, resp: httpx.Response, started: float, attempt: int) -> ChatResponse:
        try:
            data = resp.json()
            choice = data["choices"][0]["message"]
            calls = [
                ToolCall(
                    id=c.get("id") or f"call_{i}",
                    name=c["function"]["name"],
                    arguments=c["function"].get("arguments") or "{}",
                )
                for i, c in enumerate(choice.get("tool_calls") or [])
            ]
            usage = data.get("usage") or {}
            return ChatResponse(
                content=choice.get("content"),
                tool_calls=calls,
                usage=Usage(
                    prompt_tokens=int(usage.get("prompt_tokens", 0)),
                    completion_tokens=int(usage.get("completion_tokens", 0)),
                ),
                model=str(data.get("model") or self.model),
                latency_ms=int((time.perf_counter() - started) * 1000),
                attempts=attempt,
            )
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LLMBadResponse(f"malformed provider response: {type(exc).__name__}") from exc


def build_provider(settings: ProviderSettings, transport: httpx.BaseTransport | None = None) -> LLMProvider | None:
    """Return a provider, or ``None`` for deterministic demo mode."""
    if not settings.enabled:
        return None
    return OpenAICompatibleProvider(
        base_url=settings.base_url,
        model=settings.model,
        api_key=settings.api_key,
        timeout_seconds=settings.timeout_seconds,
        max_retries=settings.max_retries,
        temperature=settings.temperature,
        default_max_tokens=settings.max_tokens,
        transport=transport,
    )


def estimate_cost_usd(usage: Usage, settings: ProviderSettings) -> float | None:
    """Cost from *configured* prices only; returns None (shown as N/A) when unknown."""
    if settings.price_input_per_mtok_usd is None or settings.price_output_per_mtok_usd is None:
        return None
    return round(
        usage.prompt_tokens / 1e6 * settings.price_input_per_mtok_usd
        + usage.completion_tokens / 1e6 * settings.price_output_per_mtok_usd,
        6,
    )
