"""Simulation control, agent runs and the approval workflow."""

from __future__ import annotations

import secrets
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Query
from pydantic import BaseModel, Field

from nexus.api.deps import CatalogDep, DbDep, SettingsDep, TenantDep, request_id
from nexus.application import queries
from nexus.application.agent_runs import enqueue_agent_run, execute_agent_run
from nexus.application.approvals import DecisionActor, decide
from nexus.application.audit import record_audit
from nexus.application.clock import business_now
from nexus.application.simulation import (
    detect_signals,
    get_active_run,
    set_paused,
    start_simulation,
    step_simulation,
    stop_simulation,
)
from nexus.application.views import AgentRunBrief, AgentRunDetail, ApprovalView, SimulationView
from nexus.domain.approvals import Decision
from nexus.domain.errors import Conflict, NotFound
from nexus.domain.rbac import Permission
from nexus.infra.db import get_session_factory
from nexus.infra.models import Incident

router = APIRouter(prefix="/api/v1/restaurants/{restaurant_id}", tags=["operations"])


class StartIn(BaseModel):
    scenario_key: str = Field(default="rush_stockout", pattern=r"^[a-z_]{3,40}$")
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    tick_interval_ms: int | None = Field(default=None, ge=100, le=10_000)
    auto_pause_on_approval: bool | None = None


class SimulationOut(BaseModel):
    simulation: SimulationView | None


@router.get("/simulation", response_model=SimulationOut, tags=["simulation"])
def get_simulation(ctx: TenantDep, db: DbDep) -> SimulationOut:
    return SimulationOut(simulation=queries.simulation_view(db, ctx.restaurant_id))


@router.post(
    "/simulation",
    response_model=SimulationOut,
    status_code=201,
    tags=["simulation"],
    summary="Reset the sandbox and start a scenario (deterministic for a given seed)",
)
def start(body: StartIn, ctx: TenantDep, db: DbDep, settings: SettingsDep, catalog: CatalogDep) -> SimulationOut:
    ctx.require(Permission.SIMULATION_CONTROL)
    seed = body.seed if body.seed is not None else 42
    start_simulation(
        db,
        restaurant=ctx.restaurant,
        catalog=catalog,
        settings=settings,
        scenario_key=body.scenario_key,
        seed=seed,
        tick_interval_ms=body.tick_interval_ms,
        auto_pause_on_approval=body.auto_pause_on_approval,
        actor=ctx.actor,
        request_id=request_id(),
    )
    db.flush()
    return SimulationOut(simulation=queries.simulation_view(db, ctx.restaurant_id))


@router.post(
    "/simulation/reset",
    response_model=SimulationOut,
    tags=["simulation"],
    summary="Restart the latest scenario with the same seed (deterministic replay)",
)
def reset(ctx: TenantDep, db: DbDep, settings: SettingsDep, catalog: CatalogDep) -> SimulationOut:
    ctx.require(Permission.SIMULATION_CONTROL)
    current = queries.simulation_view(db, ctx.restaurant_id)
    scenario, seed = (current.scenario_key, current.seed) if current else ("rush_stockout", 42)
    interval = current.tick_interval_ms if current else None
    start_simulation(
        db,
        restaurant=ctx.restaurant,
        catalog=catalog,
        settings=settings,
        scenario_key=scenario,
        seed=seed,
        tick_interval_ms=interval,
        auto_pause_on_approval=None,
        actor=ctx.actor,
        request_id=request_id(),
    )
    db.flush()
    return SimulationOut(simulation=queries.simulation_view(db, ctx.restaurant_id))


@router.post("/simulation/pause", response_model=SimulationOut, tags=["simulation"])
def pause(ctx: TenantDep, db: DbDep) -> SimulationOut:
    ctx.require(Permission.SIMULATION_CONTROL)
    set_paused(db, restaurant_id=ctx.restaurant_id, paused=True, actor=ctx.actor, request_id=request_id())
    db.flush()
    return SimulationOut(simulation=queries.simulation_view(db, ctx.restaurant_id))


@router.post("/simulation/resume", response_model=SimulationOut, tags=["simulation"])
def resume(ctx: TenantDep, db: DbDep) -> SimulationOut:
    ctx.require(Permission.SIMULATION_CONTROL)
    set_paused(db, restaurant_id=ctx.restaurant_id, paused=False, actor=ctx.actor, request_id=request_id())
    db.flush()
    return SimulationOut(simulation=queries.simulation_view(db, ctx.restaurant_id))


@router.post("/simulation/stop", response_model=SimulationOut, tags=["simulation"])
def stop(ctx: TenantDep, db: DbDep) -> SimulationOut:
    ctx.require(Permission.SIMULATION_CONTROL)
    stop_simulation(db, restaurant_id=ctx.restaurant_id, actor=ctx.actor)
    db.flush()
    return SimulationOut(simulation=queries.simulation_view(db, ctx.restaurant_id))


class StepIn(BaseModel):
    ticks: int = Field(default=1, ge=1, le=30)


class StepOut(BaseModel):
    simulation: SimulationView | None
    ticks_run: int
    incident_id: uuid.UUID | None
    agent_run_id: uuid.UUID | None


@router.post(
    "/simulation/step",
    response_model=StepOut,
    tags=["simulation"],
    summary="Advance a paused (or running) simulation by N minutes",
)
def step(
    body: StepIn, ctx: TenantDep, db: DbDep, settings: SettingsDep, catalog: CatalogDep, background: BackgroundTasks
) -> StepOut:
    ctx.require(Permission.SIMULATION_CONTROL)
    run = get_active_run(db, ctx.restaurant_id)
    if run is None:
        raise NotFound("Nenhuma simulação ativa.", code="no_active_simulation")
    ran, incident_id, agent_run_id = 0, None, None
    for _ in range(body.ticks):
        result = step_simulation(db, run_id=run.id, catalog=catalog, settings=settings, manual=True)
        if result.skipped:
            if ran == 0:
                raise Conflict(f"Simulação não pode avançar agora ({result.skipped}).", code="cannot_step")
            break
        ran += 1
        if result.agent_run_id:
            incident_id, agent_run_id = result.incident_id, result.agent_run_id
            break
    db.commit()  # the background task (or the worker) must see the queued run
    if agent_run_id is not None:
        background.add_task(execute_agent_run, get_session_factory(), settings, catalog, agent_run_id)
    return StepOut(
        simulation=queries.simulation_view(db, ctx.restaurant_id),
        ticks_run=ran,
        incident_id=incident_id,
        agent_run_id=agent_run_id,
    )


@router.get("/agent-runs", response_model=list[AgentRunBrief], tags=["agents"])
def agent_runs(ctx: TenantDep, db: DbDep, limit: Annotated[int, Query(ge=1, le=100)] = 50) -> list[AgentRunBrief]:
    return queries.list_agent_runs(db, ctx.restaurant_id, limit=limit)


@router.get("/agent-runs/{run_id}", response_model=AgentRunDetail, tags=["agents"])
def agent_run(run_id: uuid.UUID, ctx: TenantDep, db: DbDep) -> AgentRunDetail:
    detail = queries.agent_run_detail(db, ctx.restaurant_id, run_id, ctx.role.value)
    if detail is None:
        raise NotFound("Execução não encontrada.")
    return detail


@router.post(
    "/agent-runs",
    response_model=AgentRunBrief,
    status_code=202,
    tags=["agents"],
    summary="Request an on-demand analysis by the agents (operator+)",
)
def trigger_agent_run(
    ctx: TenantDep, db: DbDep, settings: SettingsDep, catalog: CatalogDep, background: BackgroundTasks
) -> AgentRunBrief:
    ctx.require(Permission.AGENTS_RUN)
    as_of = business_now(db, ctx.restaurant_id)
    signals = detect_signals(db, catalog, ctx.restaurant_id, as_of)
    incident = Incident(
        restaurant_id=ctx.restaurant_id,
        title="Revisão sob demanda",
        severity="medium",
        status="open",
        signals=[sig.model_dump(mode="json") for sig in signals],
        detected_at=as_of,
        dedupe_key=f"manual:{secrets.token_hex(8)}",
    )
    db.add(incident)
    db.flush()
    sim = get_active_run(db, ctx.restaurant_id)
    run = enqueue_agent_run(
        db,
        restaurant_id=ctx.restaurant_id,
        as_of=as_of,
        settings=settings,
        trigger="manual",
        incident=incident,
        simulation_run_id=sim.id if sim else None,
        requested_by=ctx.user.id,
    )
    record_audit(
        db,
        restaurant_id=ctx.restaurant_id,
        actor=ctx.actor,
        action="agent_run.requested",
        target_type="agent_run",
        target_id=run.id,
        details={"signals": len(signals)},
        business_time=as_of,
        request_id=request_id(),
    )
    db.commit()  # the background task (or the worker) must see the queued run
    background.add_task(execute_agent_run, get_session_factory(), settings, catalog, run.id)
    return queries.list_agent_runs(db, ctx.restaurant_id, limit=1)[0]


@router.get("/approvals", response_model=list[ApprovalView], tags=["approvals"])
def approvals(
    ctx: TenantDep,
    db: DbDep,
    status: Literal["pending", "approved", "rejected", "expired", "executed", "failed", "cancelled"] | None = None,
) -> list[ApprovalView]:
    return queries.list_approvals(db, ctx.restaurant_id, status=status, role=ctx.role.value)


class DecisionIn(BaseModel):
    decision: Decision
    reason: str | None = Field(default=None, max_length=500)
    expected_version: int | None = Field(default=None, ge=1, description="Optimistic concurrency check")


@router.post(
    "/approvals/{approval_id}/decision",
    response_model=ApprovalView,
    tags=["approvals"],
    summary="Approve or reject a sensitive action (manager+). Executes only if approved and still valid.",
)
def decide_approval(approval_id: uuid.UUID, body: DecisionIn, ctx: TenantDep, db: DbDep) -> ApprovalView:
    if body.expected_version is not None:
        current = next(
            (
                a
                for a in queries.list_approvals(db, ctx.restaurant_id, status=None, role=ctx.role.value)
                if a.id == approval_id
            ),
            None,
        )
        if current is not None and current.version != body.expected_version:
            raise Conflict("A aprovação mudou desde que você a abriu; recarregue.", code="version_conflict")
    approval = decide(
        db,
        restaurant_id=ctx.restaurant_id,
        approval_id=approval_id,
        actor=DecisionActor(user_id=ctx.user.id, label=ctx.user.display_name, role=ctx.role),
        decision=body.decision,
        reason=body.reason,
        request_id=request_id(),
    )
    db.flush()
    users = {ctx.user.id: ctx.user.display_name}
    return queries.approval_view(approval, users, ctx.role.value)
