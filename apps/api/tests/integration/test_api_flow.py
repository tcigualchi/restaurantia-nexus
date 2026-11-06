"""HTTP-level walk-through of the demo: sandbox → scenario → agents → approvals → audit."""

from __future__ import annotations

import time

import pytest

from tests.helpers import demo_login

pytestmark = pytest.mark.integration


def _wait(fn, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError("condition not met in time")


def test_health_readiness_and_openapi(client) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    ready = client.get("/readyz").json()
    assert ready["status"] == "ready" and ready["migration"]
    spec = client.get("/openapi.json").json()
    assert "/api/v1/restaurants/{restaurant_id}/approvals/{approval_id}/decision" in spec["paths"]
    assert client.get("/api/v1/scenarios").json()[0]["key"]


def test_demo_walkthrough(client) -> None:
    headers, restaurants = demo_login(client)
    rid = next(r["id"] for r in restaurants if r["template_key"] == "aurora_pinheiros")
    base = f"/api/v1/restaurants/{rid}"
    assert (
        client.post(
            f"{base}/simulation", headers=headers, json={"scenario_key": "rush_stockout", "seed": 42}
        ).status_code
        == 201
    )
    client.post(f"{base}/simulation/pause", headers=headers)
    steps = 0
    agent_run_id = None
    while agent_run_id is None and steps < 60:
        resp = client.post(f"{base}/simulation/step", headers=headers, json={"ticks": 10}).json()
        steps += resp["ticks_run"]
        agent_run_id = resp["agent_run_id"]
    assert agent_run_id is not None
    pending = _wait(lambda: client.get(f"{base}/approvals?status=pending", headers=headers).json())
    assert len(pending) >= 2 and all(a["can_decide"] for a in pending)
    detail = client.get(f"{base}/agent-runs/{agent_run_id}", headers=headers).json()
    assert detail["status"] == "awaiting_approval" and detail["mode"] == "deterministic"
    assert any(s["tool_name"] == "get_inventory_status" for s in detail["step_list"])
    assert any(f.startswith("prompt_injection:") for s in detail["step_list"] for f in s["flags"])

    po = next(a for a in pending if a["action_type"] == "create_purchase_order")
    stale = client.post(
        f"{base}/approvals/{po['id']}/decision",
        headers=headers,
        json={"decision": "approve", "expected_version": po["version"] + 1},
    )
    assert stale.status_code == 409
    done = client.post(
        f"{base}/approvals/{po['id']}/decision",
        headers=headers,
        json={"decision": "approve", "expected_version": po["version"]},
    ).json()
    assert done["status"] == "executed"
    for other in pending:
        if other["id"] != po["id"]:
            r = client.post(
                f"{base}/approvals/{other['id']}/decision",
                headers=headers,
                json={"decision": "reject", "reason": "Manter cardápio completo"},
            )
            assert r.json()["status"] == "rejected"
    sim = client.get(f"{base}/simulation", headers=headers).json()["simulation"]
    assert sim["status"] == "running"
    inventory = client.get(f"{base}/inventory", headers=headers).json()
    assert inventory["purchase_orders"][0]["status"] == "ordered"
    overview = client.get(f"{base}/overview", headers=headers).json()
    assert overview["kpis"]["pending_approvals"] == 0 and "sintéticos" in overview["data_label"]
    actions = [a["action"] for a in client.get(f"{base}/audit?limit=200", headers=headers).json()]
    assert {"approval.approved", "approval.rejected", "purchase_order.created", "agent_run.completed"} <= set(actions)
    ts = client.get(f"{base}/timeseries", headers=headers).json()
    assert ts["points"] and sum(p["orders"] for p in ts["points"]) > 0
    fc = client.get(f"{base}/forecast", headers=headers).json()
    assert fc["forecast"]["backtest"]["selected_model"] and fc["history"]


def test_reset_restores_sandbox(client) -> None:
    headers, restaurants = demo_login(client)
    rid = next(r["id"] for r in restaurants if r["template_key"] == "sora_moema")
    base = f"/api/v1/restaurants/{rid}"
    client.post(f"{base}/simulation", headers=headers, json={"scenario_key": "rush_hour", "seed": 3})
    client.post(f"{base}/simulation/pause", headers=headers)
    client.post(f"{base}/simulation/step", headers=headers, json={"ticks": 15})
    assert client.get(f"{base}/orders", headers=headers).json()["total"] > 0
    reset = client.post(f"{base}/simulation/reset", headers=headers).json()["simulation"]
    assert reset["current_tick"] == 0 and reset["scenario_key"] == "rush_hour" and reset["seed"] == 3
    assert client.get(f"{base}/orders", headers=headers).json()["total"] == 0
