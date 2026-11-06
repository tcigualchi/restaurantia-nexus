"""Live updates for dashboards: a polling endpoint (``/live``) and a Server-Sent Events stream.

The web app polls ``/live`` (about once per second while a simulation runs). Short requests
fit serverless platforms: no connection is held open between polls, and in
``RUNTIME_MODE=serverless`` each poll also advances the tenant's background work
(see ``nexus.application.pump``). The SSE stream remains for integrations; it reads the
same feed once per second (no LISTEN/NOTIFY, so it works behind transaction-mode poolers)
and is resumable via ``Last-Event-ID`` (format ``e<event_id>.a<audit_id>``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from nexus.api.deps import CatalogDep, DbDep, SettingsDep, TenantDep
from nexus.application.live import live_snapshot, parse_cursor
from nexus.application.pump import pump_tenant
from nexus.application.security import decode_access_token
from nexus.config import Settings
from nexus.domain.errors import NotFound, Unauthorized
from nexus.infra.db import get_session_factory, session_scope
from nexus.infra.models import Membership

log = logging.getLogger("nexus.live")

router = APIRouter(prefix="/api/v1/restaurants/{restaurant_id}", tags=["live"])

# Below common serverless proxy limits (e.g. Vercel's 300 s default); clients reconnect with Last-Event-ID.
MAX_STREAM_SECONDS = 240
HEARTBEAT_SECONDS = 15


class LiveEventOut(BaseModel):
    id: int
    type: str
    status: str
    tick: int | None
    occurred_at: str
    order_ref: str | None = None
    outcome: Any = None


class LiveAuditOut(BaseModel):
    id: int
    action: str
    actor: str | None = None
    actor_type: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    title: str | None = None
    created_at: str


class LiveStatusOut(BaseModel):
    simulation: dict[str, Any] | None
    business_time: str
    agents_running: int
    pending_approvals: int


class LiveOut(BaseModel):
    events: list[LiveEventOut]
    audits: list[LiveAuditOut]
    status: LiveStatusOut
    cursor: str


@router.get(
    "/live",
    response_model=LiveOut,
    summary="Live feed for dashboards (in serverless mode, also advances background work)",
)
def live(
    ctx: TenantDep,
    db: DbDep,
    settings: SettingsDep,
    catalog: CatalogDep,
    response: Response,
    cursor: Annotated[str | None, Query(max_length=48, pattern=r"^e\d{1,18}\.a\d{1,18}$")] = None,
) -> LiveOut:
    db.commit()  # end the auth transaction so no connection idles while the pump runs
    if settings.serverless:
        try:
            pump_tenant(get_session_factory(), settings, catalog, ctx.restaurant_id)
        except Exception:
            # The feed must keep working even if a background step fails; the next poll retries it.
            log.exception("pump failed", extra={"restaurant_id": str(ctx.restaurant_id)})
    last_event, last_audit = parse_cursor(cursor)
    data = live_snapshot(db, ctx.restaurant_id, last_event, last_audit)
    response.headers["Cache-Control"] = "no-store"
    return LiveOut.model_validate(data)


def _poll(restaurant_id: uuid.UUID, last_event: int, last_audit: int) -> dict[str, Any]:
    with session_scope() as s:
        return live_snapshot(s, restaurant_id, last_event, last_audit)


def _sse(event: str, data: Any, event_id: str | None = None) -> str:
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append("data: " + json.dumps(data, ensure_ascii=False, default=str))
    return "\n".join(lines) + "\n\n"


def _authorize(restaurant_id: uuid.UUID, authorization: str | None, settings: Settings) -> None:
    """Short-lived auth check so the stream never pins a pooled DB connection."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Autenticação necessária.", code="missing_token")
    claims = decode_access_token(authorization.split(" ", 1)[1].strip(), settings)
    with session_scope() as s:
        member = s.scalar(
            select(Membership.role).where(
                Membership.user_id == claims.user_id, Membership.restaurant_id == restaurant_id
            )
        )
    if member is None:
        raise NotFound("Restaurante não encontrado.")


@router.get("/stream", summary="Server-Sent Events stream for live dashboards")
async def stream(
    restaurant_id: uuid.UUID,
    request: Request,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    await run_in_threadpool(_authorize, restaurant_id, authorization, settings)
    last_event, last_audit = parse_cursor(last_event_id)

    async def gen() -> AsyncIterator[str]:
        nonlocal last_event, last_audit
        started = time.monotonic()
        last_status: str | None = None
        last_beat = 0.0
        yield "retry: 2000\n\n"
        while time.monotonic() - started < MAX_STREAM_SECONDS:
            if await request.is_disconnected():
                break
            data = await run_in_threadpool(_poll, restaurant_id, last_event, last_audit)
            last_event, last_audit = data["last_event"], data["last_audit"]
            cursor = data["cursor"]
            if data["events"]:
                yield _sse("events", data["events"], cursor)
            for audit in data["audits"]:
                yield _sse("audit", audit, cursor)
            status = json.dumps(data["status"], sort_keys=True, default=str)
            if status != last_status:
                last_status = status
                yield _sse("status", data["status"], cursor)
            now = time.monotonic()
            if now - last_beat > HEARTBEAT_SECONDS:
                last_beat = now
                yield ": heartbeat\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
