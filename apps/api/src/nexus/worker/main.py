"""Background worker: advances simulations, processes events, runs agents, housekeeping.

Run as a separate process (``nexus-worker``) or embedded in the API process
(``EMBEDDED_WORKER=true``) for single-container deployments. Multiple workers
can run concurrently: simulation runs and agent runs are claimed with
``FOR UPDATE SKIP LOCKED`` and event processing is serialised per tenant with
advisory locks.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from datetime import UTC, datetime

from sqlalchemy import select

from nexus.application.agent_runs import execute_agent_run, reap_stuck_runs, run_queued_agent_runs
from nexus.application.approvals import expire_pending
from nexus.application.demo import purge_expired_sandboxes
from nexus.application.events import process_pending_events
from nexus.application.simulation import due_runs, step_simulation
from nexus.config import Settings, get_settings
from nexus.domain.catalog import cached_catalog
from nexus.infra.db import get_session_factory, session_scope
from nexus.infra.models import Event
from nexus.logging_config import configure_logging

log = logging.getLogger("nexus.worker")


def tick_once(settings: Settings) -> bool:
    """One scheduling pass. Returns True if any work was done."""
    factory = get_session_factory()
    catalog = cached_catalog(settings.dataset_dir)
    did_work = False
    with session_scope(factory) as s:
        runs = due_runs(s)
    for run_id in runs:
        try:
            with session_scope(factory) as s:
                result = step_simulation(s, run_id=run_id, catalog=catalog, settings=settings)
            did_work = did_work or result.tick is not None
            if result.agent_run_id is not None:
                execute_agent_run(factory, settings, catalog, result.agent_run_id)
        except Exception:
            log.exception("simulation step failed", extra={"simulation_run_id": str(run_id)})
    with session_scope(factory) as s:
        tenants = list(
            s.scalars(
                select(Event.restaurant_id)
                .where(Event.status == "pending", Event.next_attempt_at <= datetime.now(UTC))
                .distinct()
                .limit(20)
            )
        )
    for rid in tenants:
        with session_scope(factory) as s:
            stats = process_pending_events(s, rid, max_attempts=settings.event_max_attempts)
            did_work = did_work or bool(stats.processed or stats.retried or stats.dead_lettered)
    did_work = run_queued_agent_runs(factory, settings, catalog) > 0 or did_work
    return did_work


def housekeeping(settings: Settings) -> None:
    factory = get_session_factory()
    with session_scope(factory) as s:
        expired = expire_pending(s)
    with session_scope(factory) as s:
        purged = purge_expired_sandboxes(s)
    reaped = reap_stuck_runs(factory)
    if expired or purged or reaped:
        log.info(
            "housekeeping", extra={"approvals_expired": expired, "sandboxes_purged": purged, "runs_reaped": reaped}
        )


def run_worker(stop: threading.Event | None = None, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    stop = stop or threading.Event()
    last_housekeeping = 0.0
    log.info("worker started", extra={"poll_seconds": settings.worker_poll_seconds})
    while not stop.is_set():
        try:
            busy = tick_once(settings)
            if time.monotonic() - last_housekeeping > 30:
                housekeeping(settings)
                last_housekeeping = time.monotonic()
        except Exception:
            log.exception("worker iteration failed")
            busy = False
        stop.wait(0.02 if busy else settings.worker_poll_seconds)
    log.info("worker stopped")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    run_worker(stop, settings)


if __name__ == "__main__":
    main()
