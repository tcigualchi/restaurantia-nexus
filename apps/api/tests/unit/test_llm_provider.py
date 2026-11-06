import json

import httpx
import pytest
from pydantic import SecretStr

from nexus.agents.llm import (
    LLMBadResponse,
    LLMUnavailable,
    OpenAICompatibleProvider,
    ProviderSettings,
    Usage,
    build_provider,
    estimate_cost_usd,
)

OK_BODY = {
    "model": "test-model",
    "choices": [
        {
            "message": {
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "get_kitchen_snapshot", "arguments": '{"window_minutes": 30}'},
                    }
                ],
            }
        }
    ],
    "usage": {"prompt_tokens": 120, "completion_tokens": 30},
}


def _provider(handler, retries=2):
    return OpenAICompatibleProvider(
        base_url="https://llm.test/v1",
        model="test-model",
        api_key=SecretStr("sk-test-secret-123456789"),
        max_retries=retries,
        transport=httpx.MockTransport(handler),
        sleep=lambda s: None,
    )


def test_parses_tool_calls_and_usage() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=OK_BODY)

    resp = _provider(handler).chat([{"role": "user", "content": "oi"}], tools=[{"type": "function"}])
    assert resp.tool_calls[0].name == "get_kitchen_snapshot"
    assert resp.usage.total == 150
    assert seen["auth"] == "Bearer sk-test-secret-123456789"
    assert seen["body"]["tool_choice"] == "auto" and seen["body"]["temperature"] == 0.0


def test_retries_on_429_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429) if calls["n"] < 3 else httpx.Response(200, json=OK_BODY)

    resp = _provider(handler).chat([{"role": "user", "content": "x"}])
    assert resp.attempts == 3


def test_non_retryable_error_fails_fast_without_leaking_key() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": "bad key sk-test-secret-123456789"})

    with pytest.raises(LLMUnavailable) as exc:
        _provider(handler).chat([{"role": "user", "content": "x"}])
    assert calls["n"] == 1
    assert "sk-test" not in str(exc.value)


def test_timeouts_exhaust_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(LLMUnavailable, match="timeout"):
        _provider(handler, retries=1).chat([{"role": "user", "content": "x"}])


def test_malformed_body_is_typed_error() -> None:
    with pytest.raises(LLMBadResponse):
        _provider(lambda r: httpx.Response(200, json={"unexpected": True})).chat([{"role": "user", "content": "x"}])


def test_deterministic_mode_when_not_configured() -> None:
    assert build_provider(ProviderSettings()) is None
    assert build_provider(ProviderSettings(provider="openai_compatible", model="")) is None


def test_cost_is_na_without_configured_prices() -> None:
    usage = Usage(prompt_tokens=1_000_000, completion_tokens=500_000)
    assert estimate_cost_usd(usage, ProviderSettings()) is None
    priced = ProviderSettings(price_input_per_mtok_usd=0.5, price_output_per_mtok_usd=1.5)
    assert estimate_cost_usd(usage, priced) == 1.25
