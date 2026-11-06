"""Persisted agent runs: step recording, approval requests and execution."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from nexus.agents.llm import build_provider, estimate_cost_usd
from nexus.agents.orchestrator import IncidentInfo, Orchestrator
from nexus.agents.specialists import AgentRunner
from nexus.agents.tools import ToolContext, ToolExecutor
from nexus.application.audit import Actor, record_audit
from nexus.config import Settings
from nexus.domain.approvals import parse_action, required_role_for
from nexus.domain.catalog import Catalog
from nexus.domain.detectors import Signal
from nexus.domain.guardrails import validate_model_text
from nexus.domain.policies import CandidateAction
from nexus.infra.db import session_scope
from nexus.infra.models import AgentRun, AgentStep, ApprovalRequest, Incident, SimulationRun
from nexus.infra.read_model import SqlReadModel, from_factory

log = logging.getLogger("nexus.agents")


class DbStepRecorder:
    """Each step is committed on its own so the UI can follow a run live."""

    def __init__(self, factory: sessionmaker[Session], run_id: uuid.UUID, restaurant_id: uuid.UUID):
        self.factory = factory
        self.run_id = run_id
        self.restaurant_id = restaurant_id
        self.seq = 0
        self._lock = threading.Lock()

    def record(
        self,
        *,
        agent: str,
        kind: str,
        title: str,
        tool_name: str | None = None,
        input: Any = None,
        output: Any = None,
        status: str = "ok",
        latency_ms: int | None = None,
        flags: list[str] | None = None,
    ) -> str:
        with self._lock:
            self.seq += 1
            seq = self.seq
        with session_scope(self.factory) as s:
            s.add(
                AgentStep(
                    run_id=self.run_id,
                    restaurant_id=self.restaurant_id,
                    seq=seq,
                    agent=agent,
                    kind=kind,
                    title=title[:200],
                    tool_name=tool_name,
                    input=dict(input) if input else None,
                    output=dict(output) if output else None,
                    status=status,
                    latency_ms=latency_ms,
                    flags=list(flags or []),
                )
            )
        return f"S{seq:02d}"


class DbApprovalSink:
    def __init__(self, factory: sessionmaker[Session], settings: Settings, *, run: AgentRun):
        self.factory = factory
        self.settings = settings
        self.run_id = run.id
        self.restaurant_id = run.restaurant_id
        self.incident_id = run.incident_id
        self.simulation_run_id = run.simulation_run_id
        self.business_time = run.as_of

    def request(self, candidate: CandidateAction, *, summary: str) -> str:
        payload = parse_action(candidate.action_type, dict(candidate.payload)).model_dump(mode="json")
        payload.pop("action_type", None)
        scope = self.incident_id or self.run_id
        with session_scope(self.factory) as s:
            stmt = (
                pg_insert(ApprovalRequest)
                .values(
                    restaurant_id=self.restaurant_id,
                    run_id=self.run_id,
                    incident_id=self.incident_id,
                    simulation_run_id=self.simulation_run_id,
                    action_type=candidate.action_type,
                    payload=payload,
                    title=candidate.title[:200],
                    rationale=candidate.rationale,
                    expected_impact=candidate.expected_impact,
                    risk_level=candidate.risk_level,
                    evidence=candidate.evidence,
                    required_role=required_role_for(candidate.action_type).value,
                    idempotency_key=f"{scope}:{candidate.candidate_id}",
                    business_time=self.business_time,
                    expires_at=datetime.now(UTC) + timedelta(minutes=self.settings.approval_ttl_minutes),
                )
                .on_conflict_do_nothing(constraint="uq_approval_idempotency")
                .returning(ApprovalRequest.id)
            )
            approval_id = s.execute(stmt).scalar_one_or_none()
            if approval_id is None:
                approval_id = s.scalar(
                    select(ApprovalRequest.id).where(
                        ApprovalRequest.restaurant_id == self.restaurant_id,
                        ApprovalRequest.idempotency_key == f"{scope}:{candidate.candidate_id}",
                    )
                )
            else:
                record_audit(
                    s,
                    restaurant_id=self.restaurant_id,
                    actor=Actor.agent("orchestrator"),
                    action="approval.requested",
                    target_type="approval",
                    target_id=approval_id,
                    details={
                        "action_type": candidate.action_type,
                        "title": candidate.title,
                        "payload": payload,
                        "run_id": str(self.run_id),
                    },
                    business_time=self.business_time,
                )
        return str(approval_id)


CHECKPOINTER_APP_NAME = "restaurantia-nexus-checkpointer"
_checkpointer_lock = threading.Lock()
_checkpointer_holder: dict[str, Any] = {}


def get_checkpointer(settings: Settings) -> Any:
    """LangGraph checkpointer: in-memory by default, PostgreSQL when configured (process-wide singleton)."""
    with _checkpointer_lock:
        if "saver" in _checkpointer_holder:
            return _checkpointer_holder["saver"]
        if settings.agent_checkpointer == "postgres":
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            # A small pool (not a single long-lived connection): connections are checked on checkout,
            # so the worker recovers after the database restarts instead of failing every later run.
            url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
            pool: ConnectionPool[Any] = ConnectionPool(
                conninfo=url,
                min_size=1,
                max_size=4,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                    "application_name": CHECKPOINTER_APP_NAME,
                },
                check=ConnectionPool.check_connection,
                name="langgraph-checkpointer",
                open=True,
            )
            try:
                saver: Any = PostgresSaver(pool)
                saver.setup()
            except BaseException:
                pool.close()
                raise
        else:
            from langgraph.checkpoint.memory import InMemorySaver

            saver = InMemorySaver()
        _checkpointer_holder["saver"] = saver
        return saver


def _forget_in_memory_thread(checkpointer: Any, thread_id: str) -> None:
    """In-memory checkpoints are never read after a run (the trace lives in our own tables), so drop
    them: long-lived processes and warm serverless instances must not grow with every run."""
    from langgraph.checkpoint.memory import InMemorySaver

    if isinstance(checkpointer, InMemorySaver):
        checkpointer.delete_thread(thread_id)


def enqueue_agent_run(
    s: Session,
    *,
    restaurant_id: uuid.UUID,
    as_of: datetime,
    settings: Settings,
    trigger: str,
    incident: Incident | None = None,
    simulation_run_id: uuid.UUID | None = None,
    requested_by: uuid.UUID | None = None,
) -> AgentRun:
    llm = settings.llm
    run = AgentRun(
        restaurant_id=restaurant_id,
        incident_id=incident.id if incident else None,
        simulation_run_id=simulation_run_id,
        trigger=trigger,
        status="queued",
        provider="openai_compatible" if llm.enabled else "deterministic",
        model=llm.model if llm.enabled else None,
        as_of=as_of,
        requested_by=requested_by,
    )
    s.add(run)
    s.flush()
    return run


def _claim(factory: sessionmaker[Session], run_id: uuid.UUID) -> AgentRun | None:
    with session_scope(factory) as s:
        run = s.scalars(select(AgentRun).where(AgentRun.id == run_id).with_for_update(skip_locked=True)).one_or_none()
        if run is None or run.status != "queued":
            return None
        run.status, run.started_at, run.attempts = "running", datetime.now(UTC), run.attempts + 1
        record_audit(
            s,
            restaurant_id=run.restaurant_id,
            actor=Actor.agent("orchestrator"),
            action="agent_run.started",
            target_type="agent_run",
            target_id=run.id,
            details={"trigger": run.trigger, "provider": run.provider},
            business_time=run.as_of,
        )
        s.flush()
        s.expunge(run)
        return run


def execute_agent_run(factory: sessionmaker[Session], settings: Settings, catalog: Catalog, run_id: uuid.UUID) -> str:
    """Run the orchestrator for a queued run. Returns the final status."""
    run = _claim(factory, run_id)
    if run is None:
        return "skipped"
    try:
        with session_scope(factory) as s:
            incident = s.get(Incident, run.incident_id) if run.incident_id else None
            signals = [Signal.model_validate(x) for x in (incident.signals if incident else [])]
            info = IncidentInfo(
                incident_id=str(incident.id if incident else run.id),
                title=incident.title if incident else "Revisão sob demanda",
                severity=incident.severity if incident else "medium",
                signals=signals,
            )
            excluded = (
                frozenset(
                    key.split(":", 1)[1]
                    for key in s.scalars(
                        select(ApprovalRequest.idempotency_key).where(
                            ApprovalRequest.restaurant_id == run.restaurant_id,
                            ApprovalRequest.status == "rejected",
                            ApprovalRequest.simulation_run_id == run.simulation_run_id,
                        )
                    )
                    if ":" in key
                )
                if run.simulation_run_id
                else frozenset()
            )
        provider = build_provider(settings.llm)
        recorder = DbStepRecorder(factory, run.id, run.restaurant_id)
        executor = ToolExecutor(SqlReadModel(from_factory(factory), catalog), recorder)
        checkpointer = get_checkpointer(settings)
        orchestrator = Orchestrator(
            runner=AgentRunner(executor, recorder, provider=provider),
            recorder=recorder,
            sink=DbApprovalSink(factory, settings, run=run),
            ctx=ToolContext(restaurant_id=run.restaurant_id, as_of=run.as_of, run_id=run.id),
            provider=provider,
            checkpointer=checkpointer,
            excluded_candidates=excluded,
        )
        try:
            result = orchestrator.run(info, engine="langgraph", thread_id=str(run.id))
        finally:
            _forget_in_memory_thread(checkpointer, str(run.id))
    except Exception as exc:
        log.exception("agent run failed", extra={"run_id": str(run_id)})
        with session_scope(factory) as s:
            s.execute(
                update(AgentRun)
                .where(AgentRun.id == run_id)
                .values(status="failed", error=f"{type(exc).__name__}: {str(exc)[:300]}", finished_at=datetime.now(UTC))
            )
            record_audit(
                s,
                restaurant_id=run.restaurant_id,
                actor=Actor.agent("orchestrator"),
                action="agent_run.failed",
                target_type="agent_run",
                target_id=run_id,
                details={"error": type(exc).__name__},
                business_time=run.as_of,
            )
            failed = s.get(AgentRun, run_id)
            if failed is not None:
                _after_agents(s, failed)
        return "failed"
    cost = estimate_cost_usd(result.usage, settings.llm)
    outcomes = {
        name: {
            "mode": o.mode,
            "summary": o.summary,
            "facts": [f.model_dump() for f in o.facts],
            "flags": o.flags,
            "error": o.error,
            "evidence": o.evidence,
        }
        for name, o in result.outcomes.items()
    }
    with session_scope(factory) as s:
        db_run = s.get(AgentRun, run_id, with_for_update=True)
        assert db_run is not None
        db_run.status = result.status
        db_run.mode = result.mode
        db_run.summary = validate_model_text(result.summary, max_chars=3000)
        db_run.plan = {
            **result.plan.model_dump(mode="json"),
            "priority": result.priority,
            "approvals": result.approvals,
        }
        db_run.outcomes = outcomes
        db_run.prompt_tokens = result.usage.prompt_tokens
        db_run.completion_tokens = result.usage.completion_tokens
        db_run.estimated_cost_usd = Decimal(str(cost)) if cost is not None else None
        db_run.finished_at = datetime.now(UTC)
        record_audit(
            s,
            restaurant_id=db_run.restaurant_id,
            actor=Actor.agent("orchestrator"),
            action="agent_run.completed",
            target_type="agent_run",
            target_id=db_run.id,
            details={
                "status": result.status,
                "mode": result.mode,
                "approvals": len(result.approvals),
                "candidates": [c.title for c in result.plan.candidates],
            },
            business_time=db_run.as_of,
        )
        if db_run.incident_id:
            s.execute(update(Incident).where(Incident.id == db_run.incident_id).values(status="mitigating"))
        _after_agents(s, db_run)
    return result.status


def _after_agents(s: Session, run: AgentRun) -> None:
    """Resume the lock-stepped simulation once agents finish (or wait for a human)."""
    if run.simulation_run_id is None:
        return
    sim = s.get(SimulationRun, run.simulation_run_id, with_for_update=True)
    if sim is None or sim.status != "paused" or sim.pause_reason != "agents_running":
        return
    pending = s.scalar(
        select(ApprovalRequest.id)
        .where(ApprovalRequest.simulation_run_id == sim.id, ApprovalRequest.status == "pending")
        .limit(1)
    )
    if pending is not None and sim.auto_pause_on_approval:
        sim.pause_reason = "awaiting_approval"
    else:
        sim.status, sim.pause_reason = "running", None
    sim.updated_at = datetime.now(UTC)


def run_queued_agent_runs(
    factory: sessionmaker[Session],
    settings: Settings,
    catalog: Catalog,
    *,
    limit: int = 2,
    restaurant_id: uuid.UUID | None = None,
) -> int:
    query = select(AgentRun.id).where(AgentRun.status == "queued")
    if restaurant_id is not None:
        query = query.where(AgentRun.restaurant_id == restaurant_id)
    with session_scope(factory) as s:
        ids = list(s.scalars(query.order_by(AgentRun.created_at).limit(limit)))
    for run_id in ids:
        execute_agent_run(factory, settings, catalog, run_id)
    return len(ids)


def reap_stuck_runs(
    factory: sessionmaker[Session],
    *,
    older_than: timedelta = timedelta(minutes=10),
    restaurant_id: uuid.UUID | None = None,
) -> int:
    """Fail runs left 'running' by a crashed worker (or a timed-out function) and unblock their simulations."""
    cutoff = datetime.now(UTC) - older_than
    query = select(AgentRun).where(AgentRun.status == "running", AgentRun.started_at < cutoff)
    if restaurant_id is not None:
        query = query.where(AgentRun.restaurant_id == restaurant_id)
    with session_scope(factory) as s:
        stuck = list(s.scalars(query.with_for_update(skip_locked=True)))
        for run in stuck:
            run.status, run.error, run.finished_at = "failed", "worker interrupted", datetime.now(UTC)
            record_audit(
                s,
                restaurant_id=run.restaurant_id,
                actor=Actor.system(),
                action="agent_run.failed",
                target_type="agent_run",
                target_id=run.id,
                details={"error": "worker interrupted"},
            )
            _after_agents(s, run)
        return len(stuck)
