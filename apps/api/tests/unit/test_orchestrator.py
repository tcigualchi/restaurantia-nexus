"""Agent pipeline tests on the in-memory harness (no DB, no network)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from nexus.agents.harness import simulate_until_incident
from nexus.agents.llm import ChatResponse, LLMUnavailable, ToolCall, Usage
from nexus.agents.orchestrator import IncidentInfo, MemoryApprovalSink, Orchestrator, next_node
from nexus.agents.specialists import AgentRunner
from nexus.agents.tools import MemoryStepRecorder, ToolContext, ToolExecutor
from nexus.domain.detectors import incident_title, max_severity


@pytest.fixture(scope="module")
def incident(catalog):
    return simulate_until_incident(catalog, template_key="aurora_pinheiros", scenario_key="rush_stockout", seed=42)


def _orchestrator(incident, provider=None):
    rec = MemoryStepRecorder()
    ex = ToolExecutor(incident.read_model(), rec)
    ctx = ToolContext(restaurant_id=incident.restaurant_id, as_of=incident.as_of)
    sink = MemoryApprovalSink()
    orch = Orchestrator(
        runner=AgentRunner(ex, rec, provider=provider), recorder=rec, sink=sink, ctx=ctx, provider=provider
    )
    info = IncidentInfo(
        incident_id="inc-test",
        title=incident_title(incident.signals),
        severity=max_severity(incident.signals),
        signals=incident.signals,
    )
    return orch, info, rec, sink


def test_incident_opens_during_the_rush(incident) -> None:
    assert incident.tick is not None and 10 <= incident.tick <= 40
    assert any(s.kind == "stockout_risk" and s.subject == "ing_costela" for s in incident.signals)


def test_deterministic_pipeline_proposes_but_never_executes(incident) -> None:
    orch, info, rec, sink = _orchestrator(incident)
    stock_before = dict(incident.projection.stock)
    available_before = dict(incident.projection.available)
    result = orch.run(info, engine="sequential")
    assert result.status == "awaiting_approval" and result.mode == "deterministic"
    kinds = [c.action_type for c in sink.requested]
    assert kinds[0] == "create_purchase_order" and "pause_menu_item" in kinds
    # proposing changes nothing: execution only happens after a human decision
    assert incident.projection.stock == stock_before and incident.projection.available == available_before
    agents = [s["agent"] for s in rec.steps if s["kind"] == "tool_call"]
    assert {"operations", "inventory", "forecasting"} <= set(agents)
    assert all(s["status"] == "ok" for s in rec.steps if s["kind"] == "tool_call")


def test_injection_attempt_is_surfaced_not_obeyed(incident) -> None:
    orch, info, _, sink = _orchestrator(incident)
    result = orch.run(info, engine="sequential")
    ops = result.outcomes["operations"]
    assert any(f.startswith("prompt_injection:") for f in ops.flags)
    assert "manipulação" in ops.summary
    assert {c.action_type for c in sink.requested} <= {"create_purchase_order", "pause_menu_item"}


def test_kitchen_only_incident_skips_inventory() -> None:
    state = {"route": ["operations", "forecasting"]}
    assert next_node(state, "triage") == "operations"
    assert next_node(state, "operations") == "forecasting"
    assert next_node(state, "forecasting") == "plan"


class ScriptedProvider:
    """Fake model: replays a script of responses (or raises)."""

    name = "scripted"
    model = "scripted-model"

    def __init__(self, script: Callable[[list[dict[str, Any]], bool], ChatResponse]):
        self.script = script
        self.calls = 0

    def chat(self, messages, *, tools=None, max_tokens=None, json_mode=False) -> ChatResponse:
        self.calls += 1
        return self.script(messages, json_mode)


def _resp(content=None, calls=()) -> ChatResponse:
    return ChatResponse(
        content=content,
        tool_calls=list(calls),
        usage=Usage(prompt_tokens=100, completion_tokens=20),
        model="scripted-model",
        latency_ms=5,
    )


def test_llm_mode_uses_tools_drops_ungrounded_facts_and_cannot_invent_actions(incident) -> None:
    def script(messages, json_mode):
        if json_mode:  # orchestrator narrative: tries to add an unknown action id
            return _resp(
                json.dumps(
                    {
                        "summary": "Resumo executivo do incidente com base nos dados.",
                        "priority": ["refund:everything", "pause:item_pastel_costela"],
                    }
                )
            )
        last = messages[-1]
        if last["role"] == "user":  # first turn: call an allowed tool and a forbidden one
            return _resp(
                calls=[
                    ToolCall(id="1", name="get_kitchen_snapshot", arguments='{"window_minutes": 30}'),
                    ToolCall(id="2", name="get_inventory_status", arguments="{}"),
                ]
            )
        tool_steps = [m for m in messages if m["role"] == "tool"]
        step_id = json.loads(tool_steps[0]["content"]).get("step_id", "x")
        return _resp(
            json.dumps(
                {
                    "summary": "A cozinha está pressionada pela demanda acima do previsto.",
                    "facts": [
                        {"label": "fila", "value": "10", "evidence": step_id},
                        {"label": "inventado", "value": "999", "evidence": "step-999"},
                    ],
                }
            )
        )

    provider = ScriptedProvider(script)
    orch, info, rec, sink = _orchestrator(incident, provider)
    result = orch.run(info, engine="sequential")
    ops = result.outcomes["operations"]
    assert ops.mode == "llm"
    assert [f.label for f in ops.facts] == ["fila"]
    assert "ungrounded_facts_removed" in ops.flags
    denied = [s for s in rec.steps if s.get("status") == "denied"]
    assert denied and denied[0]["tool_name"] == "get_inventory_status"
    # required evidence is still collected and marked as such
    assert any("required_evidence" in s["title"] for s in rec.steps if s["kind"] == "tool_call")
    assert "refund:everything" not in result.priority
    assert result.priority[0] == "pause:item_pastel_costela"
    assert all(c.action_type in ("create_purchase_order", "pause_menu_item") for c in sink.requested)
    assert result.usage.total > 0


def test_provider_outage_falls_back_to_labelled_deterministic_mode(incident) -> None:
    def script(messages, json_mode):
        raise LLMUnavailable("provider unavailable after 3 attempts (HTTP 503)")

    orch, info, rec, sink = _orchestrator(incident, ScriptedProvider(script))
    result = orch.run(info, engine="sequential")
    assert {o.mode for o in result.outcomes.values()} == {"llm_fallback"}
    assert result.status == "awaiting_approval" and sink.requested
    assert any(s["kind"] == "fallback" for s in rec.steps)


def test_langgraph_and_sequential_engines_agree(incident) -> None:
    pytest.importorskip("langgraph")
    a, info, _, _ = _orchestrator(incident)
    b, _, _, _ = _orchestrator(incident)
    seq = a.run(info, engine="sequential")
    graph = b.run(info, engine="langgraph")
    assert seq.priority == graph.priority and seq.summary == graph.summary
