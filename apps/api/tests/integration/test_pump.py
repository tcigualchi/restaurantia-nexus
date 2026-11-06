"""Serverless mode: the pump (and GET /live) replaces the worker process.

Without any worker, polling must carry the featured scenario to the incident, run the agents,
wait for humans, and continue after the decisions; ticks stay time-based so pollers can't
speed a simulation up.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus.application.approvals import DecisionActor, decide
from nexus.application.pump import MAX_TICKS_PER_CALL, pump_tenant
from nexus.domain.approvals import Decision
from nexus.domain.rbac import Role
from nexus.infra.db import session_scope
from nexus.infra.models import ApprovalRequest, SimulationRun
from nexus.main import create_app
from tests.helpers import demo_login
from tests.integration.test_main_flow import _start

pytestmark = pytest.mark.integration


@pytest.fixture
def serverless(settings):
    return settings.model_copy(update={"runtime_mode": "serverless"})


def _later(minutes: int = 5) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=minutes)


def _sim(factory, run_id):
    with session_scope(factory) as s:
        sim = s.get(SimulationRun, run_id)
        return sim.status, sim.pause_reason, sim.current_tick


def test_ticks_are_time_based(factory, catalog, serverless, make_tenant) -> None:
    tenant = make_tenant()
    run_id = _start(factory, catalog, serverless, tenant)

    assert pump_tenant(factory, serverless, catalog, tenant.restaurant_id).ticks == 1  # first tick is due at once
    assert pump_tenant(factory, serverless, catalog, tenant.restaurant_id).ticks == 0  # 200 ms have not elapsed
    caught_up = pump_tenant(factory, serverless, catalog, tenant.restaurant_id, now=_later())
    assert caught_up.ticks == MAX_TICKS_PER_CALL  # a long gap is capped, not replayed
    assert _sim(factory, run_id)[2] == 1 + MAX_TICKS_PER_CALL


def test_pump_runs_the_featured_scenario_without_a_worker(factory, catalog, serverless, make_tenant) -> None:
    tenant = make_tenant()
    run_id = _start(factory, catalog, serverless, tenant)

    for _ in range(80):
        result = pump_tenant(factory, serverless, catalog, tenant.restaurant_id, now=_later())
        if result.agent_runs:
            break
    assert result.agent_runs == 1, "the incident should trigger an inline agent run"
    status, reason, tick_at_incident = _sim(factory, run_id)
    assert (status, reason) == ("paused", "awaiting_approval")

    with session_scope(factory) as s:
        pending = list(
            s.scalars(
                select(ApprovalRequest).where(
                    ApprovalRequest.restaurant_id == tenant.restaurant_id, ApprovalRequest.status == "pending"
                )
            )
        )
    assert {a.action_type for a in pending} == {"create_purchase_order", "pause_menu_item"}
    assert pump_tenant(factory, serverless, catalog, tenant.restaurant_id, now=_later()).ticks == 0  # waits for humans

    actor = DecisionActor(tenant.user_id, "Gerente (teste)", Role.MANAGER)
    for approval in pending:
        with session_scope(factory) as s:
            decide(
                s,
                restaurant_id=tenant.restaurant_id,
                approval_id=approval.id,
                actor=actor,
                decision=Decision.APPROVE,
                reason=None,
            )

    resumed = pump_tenant(factory, serverless, catalog, tenant.restaurant_id, now=_later())
    assert resumed.ticks > 0
    assert _sim(factory, run_id)[2] > tick_at_incident


def test_live_endpoint_advances_work_only_in_serverless_mode(serverless, client) -> None:
    with TestClient(create_app(serverless)) as app_client:
        headers, restaurants = demo_login(app_client)
        base = f"/api/v1/restaurants/{restaurants[0]['id']}"
        started = app_client.post(
            f"{base}/simulation",
            headers=headers,
            json={"scenario_key": "rush_hour", "seed": 7, "tick_interval_ms": 100},
        )
        assert started.status_code == 201, started.text

        cursor, ticks = None, 0
        for _ in range(20):
            resp = app_client.get(f"{base}/live", headers=headers, params={"cursor": cursor} if cursor else None)
            assert resp.status_code == 200, resp.text
            body = resp.json()
            cursor, ticks = body["cursor"], body["status"]["simulation"]["current_tick"]
            if ticks >= 3:
                break
            time.sleep(0.15)
        assert ticks >= 3
        assert cursor.startswith("e") and ".a" in cursor
        assert resp.headers["cache-control"] == "no-store"

        # A platform service URL with a path prefix still reaches the routes.
        prefixed = app_client.get(f"/_svc/api{base}/live", headers=headers)
        assert prefixed.status_code == 200, prefixed.text

    # Server mode (worker process expected): /live only reads.
    headers, restaurants = demo_login(client)
    base = f"/api/v1/restaurants/{restaurants[0]['id']}"
    client.post(
        f"{base}/simulation", headers=headers, json={"scenario_key": "rush_hour", "seed": 7, "tick_interval_ms": 100}
    )
    time.sleep(0.3)
    for _ in range(3):
        snapshot = client.get(f"{base}/live", headers=headers).json()
    assert snapshot["status"]["simulation"]["current_tick"] == 0
    assert client.get(f"/_svc/api{base}/live", headers=headers).status_code == 404


def test_live_rejects_malformed_cursor_and_other_tenants(client) -> None:
    headers, restaurants = demo_login(client)
    base = f"/api/v1/restaurants/{restaurants[0]['id']}"
    assert client.get(f"{base}/live", headers=headers, params={"cursor": "e1;drop"}).status_code == 422
    other_headers, _ = demo_login(client)
    assert client.get(f"{base}/live", headers=other_headers).status_code == 404
    assert client.get(f"{base}/live").status_code == 401


def test_in_memory_checkpoints_are_dropped_after_each_run(factory, catalog, serverless, make_tenant) -> None:
    from nexus.application.agent_runs import get_checkpointer
    from nexus.infra.models import AgentRun

    saver = get_checkpointer(serverless)
    tenant = make_tenant()
    _start(factory, catalog, serverless, tenant)
    for _ in range(80):
        if pump_tenant(factory, serverless, catalog, tenant.restaurant_id, now=_later()).agent_runs:
            break
    with session_scope(factory) as s:
        run_id = s.scalar(select(AgentRun.id).where(AgentRun.restaurant_id == tenant.restaurant_id))
    assert run_id is not None
    assert str(run_id) not in getattr(saver, "storage", {})  # warm instances must not grow with every run
