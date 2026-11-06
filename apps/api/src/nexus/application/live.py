"""Live feed for dashboards: new events, new audit entries and a status snapshot for one tenant.

Shared by the polling endpoint (``GET /live``, used by the web app) and the SSE stream.
The cursor ``e<event_id>.a<audit_id>`` makes both resumable without server-side state.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from nexus.application.clock import business_now
from nexus.application.queries import simulation_view
from nexus.infra.models import AgentRun, ApprovalRequest, AuditLog, Event

BATCH_LIMIT = 60
INITIAL_BACKLOG = 15


def parse_cursor(value: str | None) -> tuple[int, int]:
    if not value:
        return 0, 0
    try:
        e_part, a_part = value.split(".")
        return max(0, int(e_part.lstrip("e"))), max(0, int(a_part.lstrip("a")))
    except ValueError:
        return 0, 0


def format_cursor(last_event: int, last_audit: int) -> str:
    return f"e{last_event}.a{last_audit}"


def live_snapshot(s: Session, restaurant_id: uuid.UUID, last_event: int, last_audit: int) -> dict[str, Any]:
    """Everything after the cursor (at most ``BATCH_LIMIT`` of each) plus the current status.

    Without a cursor (0, 0) the feed starts with the last few items instead of the whole history.
    """
    if last_event == 0 and last_audit == 0:
        max_event = s.scalar(select(func.coalesce(func.max(Event.id), 0)).where(Event.restaurant_id == restaurant_id))
        max_audit = s.scalar(
            select(func.coalesce(func.max(AuditLog.id), 0)).where(AuditLog.restaurant_id == restaurant_id)
        )
        last_event = max(0, int(max_event or 0) - INITIAL_BACKLOG)
        last_audit = max(0, int(max_audit or 0) - INITIAL_BACKLOG)
    events = s.execute(
        select(Event.id, Event.type, Event.status, Event.tick, Event.occurred_at, Event.payload, Event.outcome)
        .where(Event.restaurant_id == restaurant_id, Event.id > last_event)
        .order_by(Event.id)
        .limit(BATCH_LIMIT)
    ).all()
    audits = s.execute(
        select(
            AuditLog.id,
            AuditLog.action,
            AuditLog.actor_label,
            AuditLog.actor_type,
            AuditLog.target_type,
            AuditLog.target_id,
            AuditLog.details,
            AuditLog.created_at,
        )
        .where(AuditLog.restaurant_id == restaurant_id, AuditLog.id > last_audit)
        .order_by(AuditLog.id)
        .limit(BATCH_LIMIT)
    ).all()
    sim = simulation_view(s, restaurant_id)
    running_agents = s.scalar(
        select(func.count())
        .select_from(AgentRun)
        .where(AgentRun.restaurant_id == restaurant_id, AgentRun.status.in_(("queued", "running")))
    )
    pending = s.scalar(
        select(func.count())
        .select_from(ApprovalRequest)
        .where(ApprovalRequest.restaurant_id == restaurant_id, ApprovalRequest.status == "pending")
    )
    last_event = events[-1].id if events else last_event
    last_audit = audits[-1].id if audits else last_audit
    return {
        "events": [
            {
                "id": e.id,
                "type": e.type,
                "status": e.status,
                "tick": e.tick,
                "occurred_at": e.occurred_at.isoformat(),
                "order_ref": (e.payload or {}).get("order_ref"),
                "outcome": e.outcome,
            }
            for e in events
        ],
        "audits": [
            {
                "id": a.id,
                "action": a.action,
                "actor": a.actor_label,
                "actor_type": a.actor_type,
                "target_type": a.target_type,
                "target_id": a.target_id,
                "title": (a.details or {}).get("title"),
                "created_at": a.created_at.isoformat(),
            }
            for a in audits
        ],
        "status": {
            "simulation": sim.model_dump(mode="json") if sim else None,
            "business_time": business_now(s, restaurant_id).isoformat(),
            "agents_running": int(running_agents or 0),
            "pending_approvals": int(pending or 0),
        },
        "last_event": last_event,
        "last_audit": last_audit,
        "cursor": format_cursor(last_event, last_audit),
    }
