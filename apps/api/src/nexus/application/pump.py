"""Request-driven background work for serverless deployments (``RUNTIME_MODE=serverless``).

Vercel Functions cannot host the long-running worker, so the worker's steps run inline, scoped
to one tenant, whenever a dashboard polls ``/live``: expire stale approvals, reap agent runs left
behind by a timed-out invocation, run queued agents, advance the simulation and project pending
events. A simulation therefore advances while someone is watching it, and nothing runs (or costs)
when nobody is.

Every step is bounded and safe to run concurrently with itself:

* ticks are time-based (``ticks_due``), so polling faster never speeds a simulation up;
* simulation runs and agent runs are claimed with ``FOR UPDATE SKIP LOCKED``;
* event projection is serialised per tenant with a transaction-scoped advisory lock.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from nexus.application.agent_runs import execute_agent_run, reap_stuck_runs, run_queued_agent_runs
from nexus.application.approvals import expire_pending
from nexus.application.events import process_pending_events
from nexus.application.simulation import step_simulation, ticks_due
from nexus.config import Settings
from nexus.domain.catalog import Catalog
from nexus.infra.db import session_scope
from nexus.infra.models import SimulationRun

log = logging.getLogger("nexus.pump")

MAX_TICKS_PER_CALL = 5
# A function invocation can't outlive 300 s on Vercel Hobby; a run "running" for longer was cut off.
STUCK_RUN_AFTER = timedelta(minutes=6)
TIME_BUDGET_SECONDS = 4.0


@dataclass
class PumpResult:
    ticks: int = 0
    agent_runs: int = 0
    events_processed: int = 0
    approvals_expired: int = 0
    runs_reaped: int = 0

    @property
    def did_work(self) -> bool:
        return any((self.ticks, self.agent_runs, self.events_processed, self.approvals_expired, self.runs_reaped))


def pump_tenant(
    factory: sessionmaker[Session],
    settings: Settings,
    catalog: Catalog,
    restaurant_id: uuid.UUID,
    *,
    now: datetime | None = None,
    max_ticks: int = MAX_TICKS_PER_CALL,
) -> PumpResult:
    """Run one bounded scheduling pass for ``restaurant_id`` (see module docstring)."""
    started = time.monotonic()
    now = now or datetime.now(UTC)
    result = PumpResult()

    with session_scope(factory) as s:
        result.approvals_expired = expire_pending(s, now=now, restaurant_id=restaurant_id)
    result.runs_reaped = reap_stuck_runs(factory, older_than=STUCK_RUN_AFTER, restaurant_id=restaurant_id)
    result.agent_runs += run_queued_agent_runs(factory, settings, catalog, restaurant_id=restaurant_id)

    with session_scope(factory) as s:
        run = s.scalars(
            select(SimulationRun).where(SimulationRun.restaurant_id == restaurant_id, SimulationRun.status == "running")
        ).first()
        pending_ticks = ticks_due(run, now, cap=max_ticks) if run else 0
        run_id = run.id if run else None

    for _ in range(pending_ticks):
        if run_id is None or time.monotonic() - started > TIME_BUDGET_SECONDS:
            break
        with session_scope(factory) as s:
            step = step_simulation(s, run_id=run_id, catalog=catalog, settings=settings)
        if step.tick is None:  # paused, finished or claimed by a concurrent poller
            break
        result.ticks += 1
        if step.agent_run_id is not None:
            # The simulation is now paused for the agents (and then for human approvals).
            execute_agent_run(factory, settings, catalog, step.agent_run_id)
            result.agent_runs += 1
            break

    with session_scope(factory) as s:
        stats = process_pending_events(s, restaurant_id, max_attempts=settings.event_max_attempts)
    result.events_processed = stats.processed

    if result.did_work:
        log.debug(
            "pump",
            extra={
                "restaurant_id": str(restaurant_id),
                "ticks": result.ticks,
                "agent_runs": result.agent_runs,
                "events": result.events_processed,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
            },
        )
    return result
