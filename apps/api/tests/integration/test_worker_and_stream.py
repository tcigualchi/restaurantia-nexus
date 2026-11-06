"""Worker scheduling pass, seed command and the SSE stream."""

from __future__ import annotations

import json
import time

import pytest
from sqlalchemy import select, update

from nexus.application.seed import seed
from nexus.infra.db import session_scope
from nexus.infra.models import AgentRun, Restaurant, SimulationRun
from nexus.worker.main import housekeeping, tick_once
from tests.helpers import demo_login

pytestmark = pytest.mark.integration


def test_seed_is_idempotent(factory, monkeypatch) -> None:
    monkeypatch.setenv("SEED_ADMIN_EMAIL", "admin@test.invalid")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "a-long-local-password")
    first = seed()
    second = seed()
    assert second == {"restaurants_created": 0, "users_created": 0}
    assert first["users_created"] in (0, 1)
    with session_scope(factory) as s:
        assert s.scalar(select(Restaurant.id).where(Restaurant.is_demo.is_(False)).limit(1)) is not None


def test_worker_advances_simulation_and_runs_agents(client, factory, settings) -> None:
    headers, restaurants = demo_login(client)
    rid = next(r["id"] for r in restaurants if r["template_key"] == "aurora_pinheiros")
    client.post(f"/api/v1/restaurants/{rid}/simulation", headers=headers, json={"seed": 42, "tick_interval_ms": 200})
    deadline = time.time() + 60
    while time.time() < deadline:
        with session_scope(factory) as s:  # make every running simulation due right now
            s.execute(update(SimulationRun).where(SimulationRun.status == "running").values(last_tick_at=None))
        tick_once(settings)
        with session_scope(factory) as s:
            run = s.scalars(select(AgentRun).where(AgentRun.restaurant_id == rid)).first()
            if run is not None and run.status in ("awaiting_approval", "completed"):
                break
    assert run is not None and run.status == "awaiting_approval"
    housekeeping(settings)  # expiring/purging/reaping must be safe to run at any time


def test_stream_emits_status_and_events(client) -> None:
    headers, restaurants = demo_login(client)
    rid = next(r["id"] for r in restaurants if r["template_key"] == "aurora_pinheiros")
    client.post(f"/api/v1/restaurants/{rid}/simulation", headers=headers, json={"seed": 1})
    client.post(f"/api/v1/restaurants/{rid}/simulation/pause", headers=headers)
    client.post(f"/api/v1/restaurants/{rid}/simulation/step", headers=headers, json={"ticks": 5})
    seen: dict[str, object] = {}
    with client.stream("GET", f"/api/v1/restaurants/{rid}/stream", headers=headers) as resp:
        assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
        event = None
        for line in resp.iter_lines():
            if line.startswith("event: "):
                event = line.removeprefix("event: ")
            elif line.startswith("data: ") and event:
                seen[event] = json.loads(line.removeprefix("data: "))
            if {"status", "events"} <= seen.keys():
                break
    assert seen["status"]["simulation"]["status"] == "paused"
    assert any(e["type"] == "order.created" for e in seen["events"])
