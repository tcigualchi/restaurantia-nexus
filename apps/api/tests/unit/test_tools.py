from uuid import uuid4

import pytest

from nexus.agents.harness import simulate_until_incident
from nexus.agents.tools import MemoryStepRecorder, ToolContext, ToolExecutor


@pytest.fixture(scope="module")
def incident(catalog):
    return simulate_until_incident(catalog, template_key="aurora_pinheiros", scenario_key="rush_stockout", seed=42)


@pytest.fixture
def executor(incident):
    return ToolExecutor(incident.read_model(), MemoryStepRecorder())


def _ctx(incident):
    return ToolContext(restaurant_id=incident.restaurant_id, as_of=incident.as_of)


def test_allowed_call_is_recorded_with_validated_args(incident, executor) -> None:
    res = executor.invoke("operations", "get_kitchen_snapshot", '{"window_minutes": 20}', _ctx(incident))
    assert res.status == "ok" and res.output["window_minutes"] == 20
    step = executor.recorder.steps[-1]
    assert step["input"] == {"window_minutes": 20} and step["status"] == "ok"


def test_agent_cannot_call_tools_outside_its_allowlist(incident, executor) -> None:
    res = executor.invoke("forecasting", "get_inventory_status", {}, _ctx(incident))
    assert res.status == "denied"


def test_unknown_tool_is_denied(incident, executor) -> None:
    assert (
        executor.invoke("operations", "execute_sql", {"query": "DROP TABLE orders"}, _ctx(incident)).status == "denied"
    )


@pytest.mark.parametrize(
    "args",
    [
        {"window_minutes": 9999},
        {"window_minutes": 30, "restaurant_id": str(uuid4())},  # tenant can never come from the model
        "not-json",
        "[1, 2]",
    ],
)
def test_invalid_arguments_are_rejected(incident, executor, args) -> None:
    assert executor.invoke("operations", "get_kitchen_snapshot", args, _ctx(incident)).status == "invalid_arguments"


def test_key_pattern_blocks_injection_in_arguments(incident, executor) -> None:
    res = executor.invoke(
        "inventory", "get_ingredient_details", {"ingredient_key": "ing_costela' OR 1=1 --"}, _ctx(incident)
    )
    assert res.status == "invalid_arguments"


def test_call_budget_is_enforced(incident, executor) -> None:
    statuses = [executor.invoke("operations", "get_kitchen_capacity", {}, _ctx(incident)).status for _ in range(3)]
    assert statuses == ["ok", "ok", "budget_exceeded"]


def test_handler_errors_become_structured_results(incident, executor) -> None:
    res = executor.invoke("inventory", "get_ingredient_details", {"ingredient_key": "ing_inexistente"}, _ctx(incident))
    assert res.status == "error" and "LookupError" in res.error


def test_cross_tenant_context_is_refused(incident, executor) -> None:
    ctx = ToolContext(restaurant_id=uuid4(), as_of=incident.as_of)
    res = executor.invoke("operations", "get_kitchen_snapshot", {}, ctx)
    assert res.status == "error" and "PermissionError" in res.error


def test_untrusted_notes_are_wrapped_and_flagged(incident, executor) -> None:
    res = executor.invoke("operations", "list_open_orders", {"min_age_minutes": 0, "limit": 20}, _ctx(incident))
    notes = [o["customer_note"] for o in res.output["orders"] if "customer_note" in o]
    assert notes and all(n["untrusted"] for n in notes)
    assert any(f.startswith("prompt_injection:") for f in res.flags)
