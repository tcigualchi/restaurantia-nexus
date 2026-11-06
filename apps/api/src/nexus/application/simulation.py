"""Simulation lifecycle and the lock-stepped tick pipeline.

One tick (= one simulated minute), in a single transaction:

1. due purchase orders become ``inventory.received`` events;
2. the engine generates the minute's events (deterministic, seeded);
3. events are ingested idempotently and projected in order;
4. detectors evaluate risk *as of the end of the tick*;
5. a new incident pauses the run (``agents_running``) and queues an agent run.

The agent run executes after the commit (steps are visible live). When it
finishes, the run resumes, or waits for a human if approvals are pending and
``auto_pause_on_approval`` is on. Pausing at fixed ticks keeps replays with the
same decisions fully reproducible.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.application.agent_runs import enqueue_agent_run
from nexus.application.audit import Actor, record_audit
from nexus.application.events import ingest_event, process_pending_events
from nexus.application.sandbox import reset_operational_state
from nexus.config import Settings
from nexus.domain.catalog import Catalog
from nexus.domain.detectors import Signal, incident_title, kitchen_signals, max_severity, stock_signals
from nexus.domain.errors import Conflict, NotFound, ValidationFailed
from nexus.domain.simulation import SCENARIOS, SIM_START, SimState, minutes_to_datetime, run_tick, tick_time
from nexus.infra.models import Incident, Ingredient, MenuItem, PurchaseOrder, Restaurant, SimulationRun
from nexus.infra.read_model import SqlReadModel, bound

DETECTION_WINDOW = 15
DETECTION_HORIZON = 120
INCIDENT_COOLDOWN_MINUTES = 20


def start_simulation(
    s: Session,
    *,
    restaurant: Restaurant,
    catalog: Catalog,
    settings: Settings,
    scenario_key: str,
    seed: int,
    tick_interval_ms: int | None,
    auto_pause_on_approval: bool | None,
    actor: Actor,
    request_id: str | None = None,
) -> SimulationRun:
    scenario = SCENARIOS.get(scenario_key)
    if scenario is None:
        raise ValidationFailed(f"Cenário desconhecido: {scenario_key}", code="unknown_scenario")
    template = catalog.get(restaurant.template_key)
    s.execute(select(Restaurant.id).where(Restaurant.id == restaurant.id).with_for_update())
    summary = reset_operational_state(s, restaurant, template, scenario_stock_override=scenario.stock_override)
    interval = max(settings.min_tick_interval_ms, min(10_000, tick_interval_ms or settings.default_tick_interval_ms))
    run = SimulationRun(
        restaurant_id=restaurant.id,
        scenario_key=scenario.key,
        seed=seed,
        status="running",
        current_tick=0,
        total_ticks=scenario.total_ticks,
        tick_interval_ms=interval,
        auto_pause_on_approval=scenario.auto_pause_on_approval
        if auto_pause_on_approval is None
        else auto_pause_on_approval,
        state=SimState.initial(template).to_json(),
        sim_start=SIM_START,
        created_by=uuid.UUID(actor.id) if actor.type == "user" and actor.id else None,
    )
    s.add(run)
    s.flush()
    record_audit(
        s,
        restaurant_id=restaurant.id,
        actor=actor,
        action="simulation.started",
        target_type="simulation",
        target_id=run.id,
        details={"scenario": scenario.key, "seed": seed, "tick_interval_ms": interval, "reset": summary.__dict__},
        business_time=SIM_START,
        request_id=request_id,
    )
    return run


def get_active_run(s: Session, restaurant_id: uuid.UUID, *, for_update: bool = False) -> SimulationRun | None:
    q = select(SimulationRun).where(
        SimulationRun.restaurant_id == restaurant_id, SimulationRun.status.in_(("running", "paused"))
    )
    if for_update:
        q = q.with_for_update()
    return s.scalars(q).one_or_none()


def set_paused(
    s: Session, *, restaurant_id: uuid.UUID, paused: bool, actor: Actor, request_id: str | None = None
) -> SimulationRun:
    run = get_active_run(s, restaurant_id, for_update=True)
    if run is None:
        raise NotFound("Nenhuma simulação ativa.", code="no_active_simulation")
    if paused and run.status == "running":
        run.status, run.pause_reason = "paused", "manual"
    elif not paused and run.status == "paused":
        if run.pause_reason == "agents_running":
            raise Conflict("Aguarde os agentes concluírem a análise.", code="agents_running")
        run.status, run.pause_reason = "running", None
    run.updated_at = datetime.now(UTC)
    record_audit(
        s,
        restaurant_id=restaurant_id,
        actor=actor,
        action="simulation.paused" if paused else "simulation.resumed",
        target_type="simulation",
        target_id=run.id,
        details={"tick": run.current_tick},
        business_time=minutes_to_datetime(run.sim_start, run.current_tick),
        request_id=request_id,
    )
    return run


def stop_simulation(s: Session, *, restaurant_id: uuid.UUID, actor: Actor) -> SimulationRun:
    run = get_active_run(s, restaurant_id, for_update=True)
    if run is None:
        raise NotFound("Nenhuma simulação ativa.", code="no_active_simulation")
    run.status, run.pause_reason, run.completed_at = "cancelled", None, datetime.now(UTC)
    record_audit(
        s,
        restaurant_id=restaurant_id,
        actor=actor,
        action="simulation.stopped",
        target_type="simulation",
        target_id=run.id,
        details={"tick": run.current_tick},
    )
    return run


@dataclass(frozen=True)
class StepResult:
    run_id: uuid.UUID
    tick: int | None
    events: int
    status: str
    incident_id: uuid.UUID | None = None
    agent_run_id: uuid.UUID | None = None
    skipped: str | None = None


def detect_signals(s: Session, catalog: Catalog, restaurant_id: uuid.UUID, as_of: datetime) -> list[Signal]:
    rm = SqlReadModel(bound(s), catalog)
    snap = rm.kitchen_snapshot(restaurant_id, as_of=as_of, window_minutes=DETECTION_WINDOW)
    risks = rm.inventory_risks(
        restaurant_id, as_of=as_of, window_minutes=DETECTION_WINDOW, horizon_minutes=DETECTION_HORIZON
    )
    return kitchen_signals(snap) + stock_signals(risks)


def _maybe_open_incident(
    s: Session, run: SimulationRun, tick: int, as_of: datetime, signals: list[Signal]
) -> Incident | None:
    if not signals:
        return None
    previous = list(s.scalars(select(Incident).where(Incident.simulation_run_id == run.id)))
    covered = {(sig["kind"], sig["subject"]) for inc in previous for sig in inc.signals}
    new = [sig for sig in signals if (sig.kind, sig.subject) not in covered]
    if not new:
        return None
    recent = [inc for inc in previous if (as_of - inc.detected_at) < timedelta(minutes=INCIDENT_COOLDOWN_MINUTES)]
    if recent:
        return None
    incident = Incident(
        restaurant_id=run.restaurant_id,
        simulation_run_id=run.id,
        title=incident_title(signals),
        severity=max_severity(signals),
        status="open",
        signals=[sig.model_dump(mode="json") for sig in signals],
        detected_at=as_of,
        tick=tick,
        dedupe_key=f"sim:{run.id}:t{tick:04d}",
    )
    s.add(incident)
    s.flush()
    record_audit(
        s,
        restaurant_id=run.restaurant_id,
        actor=Actor.system("Detectores"),
        action="incident.opened",
        target_type="incident",
        target_id=incident.id,
        details={"title": incident.title, "severity": incident.severity, "signals": [sig.message for sig in signals]},
        business_time=as_of,
    )
    return incident


def step_simulation(
    s: Session, *, run_id: uuid.UUID, catalog: Catalog, settings: Settings, manual: bool = False
) -> StepResult:
    run = s.scalars(
        select(SimulationRun).where(SimulationRun.id == run_id).with_for_update(skip_locked=True)
    ).one_or_none()
    if run is None:
        return StepResult(run_id, None, 0, "busy", skipped="locked")
    if run.status == "paused" and not (manual and run.pause_reason in (None, "manual")):
        return StepResult(run.id, None, 0, run.status, skipped=run.pause_reason or "paused")
    if run.status not in ("running", "paused"):
        return StepResult(run.id, None, 0, run.status, skipped="inactive")
    restaurant = s.get(Restaurant, run.restaurant_id)
    assert restaurant is not None
    template = catalog.get(restaurant.template_key)
    scenario = SCENARIOS[run.scenario_key]
    tick = run.current_tick
    if tick >= run.total_ticks:
        _complete(s, run)
        return StepResult(run.id, None, 0, run.status, skipped="finished")

    tick_start = minutes_to_datetime(run.sim_start, tick)
    due = list(
        s.scalars(
            select(PurchaseOrder).where(
                PurchaseOrder.simulation_run_id == run.id,
                PurchaseOrder.status == "ordered",
                PurchaseOrder.expected_tick <= tick,
            )
        )
    )
    for po in due:
        ingredient_key = s.scalar(select(Ingredient.key).where(Ingredient.id == po.ingredient_id))
        ingest_event(
            s,
            restaurant_id=run.restaurant_id,
            event_type="inventory.received",
            payload={"ingredient_key": ingredient_key, "quantity": float(po.quantity), "purchase_order_id": str(po.id)},
            idempotency_key=f"po:{po.id}:received",
            occurred_at=tick_start,
            source="simulator",
            simulation_run_id=run.id,
            tick=tick,
        )
    if due:
        process_pending_events(s, run.restaurant_id, wait_for_lock=True, max_attempts=settings.event_max_attempts)

    availability = dict(
        s.execute(select(MenuItem.key, MenuItem.is_available).where(MenuItem.restaurant_id == run.restaurant_id)).all()
    )
    stock = {
        k: float(v)
        for k, v in s.execute(
            select(Ingredient.key, Ingredient.stock).where(Ingredient.restaurant_id == run.restaurant_id)
        ).all()
    }
    out = run_tick(
        scenario=scenario,
        template=template,
        seed=run.seed,
        tick=tick,
        state=SimState.from_json(run.state),
        availability=availability,
        stock=stock,
        start_at=run.sim_start,
    )
    for ev in out.events:
        ingest_event(
            s,
            restaurant_id=run.restaurant_id,
            event_type=ev.type,
            payload=ev.payload,
            idempotency_key=ev.idempotency_key(str(run.id)),
            occurred_at=ev.occurred_at,
            source="simulator",
            simulation_run_id=run.id,
            tick=tick,
        )
    process_pending_events(s, run.restaurant_id, wait_for_lock=True, max_attempts=settings.event_max_attempts)

    as_of = tick_time(tick, run.sim_start)
    signals = detect_signals(s, catalog, run.restaurant_id, as_of)
    incident = _maybe_open_incident(s, run, tick, as_of, signals)

    run.state = out.state.to_json()
    run.current_tick = tick + 1
    run.last_tick_at = datetime.now(UTC)
    run.updated_at = run.last_tick_at
    agent_run_id = None
    if incident is not None:
        agent_run = enqueue_agent_run(
            s,
            restaurant_id=run.restaurant_id,
            as_of=as_of,
            settings=settings,
            trigger="incident",
            incident=incident,
            simulation_run_id=run.id,
        )
        agent_run_id = agent_run.id
        run.status, run.pause_reason = "paused", "agents_running"
    if run.current_tick >= run.total_ticks and incident is None:
        _complete(s, run)
    return StepResult(
        run.id,
        tick,
        len(out.events),
        run.status,
        incident_id=incident.id if incident else None,
        agent_run_id=agent_run_id,
    )


def _complete(s: Session, run: SimulationRun) -> None:
    run.status, run.pause_reason, run.completed_at = "completed", None, datetime.now(UTC)
    record_audit(
        s,
        restaurant_id=run.restaurant_id,
        actor=Actor.system("Simulador"),
        action="simulation.completed",
        target_type="simulation",
        target_id=run.id,
        details={"ticks": run.current_tick},
        business_time=minutes_to_datetime(run.sim_start, run.current_tick),
    )


def ticks_due(run: SimulationRun, now: datetime, *, cap: int) -> int:
    """How many ticks this run owes at ``now`` (time-based, so polling faster never speeds it up)."""
    if run.status != "running" or cap <= 0:
        return 0
    if run.last_tick_at is None:
        return 1
    elapsed_ms = (now - run.last_tick_at).total_seconds() * 1000
    return max(0, min(cap, int(elapsed_ms // max(1, run.tick_interval_ms))))


def due_runs(
    s: Session, *, now: datetime | None = None, limit: int = 20, restaurant_id: uuid.UUID | None = None
) -> list[uuid.UUID]:
    now = now or datetime.now(UTC)
    query = select(SimulationRun).where(SimulationRun.status == "running")
    if restaurant_id is not None:
        query = query.where(SimulationRun.restaurant_id == restaurant_id)
    runs = s.scalars(query.limit(limit * 3)).all()
    due = [r for r in runs if ticks_due(r, now, cap=1)]
    return [r.id for r in due[:limit]]
