"""Idempotency, retries/dead-letter, approval invariants and tenant isolation (service layer)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from nexus.application.approvals import DecisionActor, decide, expire_pending
from nexus.application.demo import create_demo_sandbox, purge_expired_sandboxes
from nexus.application.events import ingest_event, process_pending_events, requeue_dead_letter
from nexus.domain.approvals import Decision
from nexus.domain.errors import Conflict, Forbidden, Gone, NotFound, ValidationFailed
from nexus.domain.rbac import Role
from nexus.infra.db import session_scope
from nexus.infra.models import (
    ApprovalRequest,
    AuditLog,
    DemoSession,
    Event,
    Ingredient,
    Order,
    PurchaseOrder,
    Restaurant,
)

pytestmark = pytest.mark.integration
NOW = datetime(2026, 3, 13, 21, 40, tzinfo=UTC)


def _order(ref: str) -> dict:
    return {
        "order_ref": ref,
        "channel": "dine_in",
        "items": [{"item_key": "item_burger_costela", "qty": 2}],
        "promised_prep_minutes": 18,
    }


def _costela(s, rid) -> float:
    return float(
        s.scalar(select(Ingredient.stock).where(Ingredient.restaurant_id == rid, Ingredient.key == "ing_costela"))
    )


def test_duplicate_events_have_no_duplicate_effects(factory, make_tenant) -> None:
    t = make_tenant()
    with session_scope(factory) as s:
        before = _costela(s, t.restaurant_id)
        a = ingest_event(
            s,
            restaurant_id=t.restaurant_id,
            event_type="order.created",
            payload=_order("EXT-0001"),
            idempotency_key="pos:EXT-0001:created",
            occurred_at=NOW,
            source="api",
        )
        b = ingest_event(
            s,
            restaurant_id=t.restaurant_id,
            event_type="order.created",
            payload=_order("EXT-0001"),
            idempotency_key="pos:EXT-0001:created",
            occurred_at=NOW,
            source="api",
        )
        # same business fact delivered under a *different* key: the projection is still idempotent
        c = ingest_event(
            s,
            restaurant_id=t.restaurant_id,
            event_type="order.created",
            payload=_order("EXT-0001"),
            idempotency_key="retry:EXT-0001",
            occurred_at=NOW,
            source="api",
        )
        process_pending_events(s, t.restaurant_id)
    assert a.created and not b.created and a.event_id == b.event_id and c.created
    with session_scope(factory) as s:
        assert s.scalar(select(func.count()).select_from(Order).where(Order.restaurant_id == t.restaurant_id)) == 1
        assert _costela(s, t.restaurant_id) == before - 360
        outcomes = dict(
            s.execute(select(Event.idempotency_key, Event.outcome).where(Event.restaurant_id == t.restaurant_id)).all()
        )
    assert outcomes == {"pos:EXT-0001:created": "applied", "retry:EXT-0001": "duplicate"}


def test_out_of_order_event_retries_then_dead_letters_then_requeues(factory, make_tenant) -> None:
    t = make_tenant()
    with session_scope(factory) as s:
        ev = ingest_event(
            s,
            restaurant_id=t.restaurant_id,
            event_type="order.ready",
            payload={"order_ref": "EXT-0404"},
            idempotency_key="pos:EXT-0404:ready",
            occurred_at=NOW,
            source="api",
        )
    for attempt in range(1, 4):
        with session_scope(factory) as s:
            s.execute(
                update(Event)
                .where(Event.id == ev.event_id)
                .values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            stats = process_pending_events(s, t.restaurant_id, max_attempts=3)
            row = s.get(Event, ev.event_id)
            assert row.attempts == attempt
    assert row.status == "dead_letter" and stats.dead_lettered == 1 and "order_not_found" in row.last_error
    with session_scope(factory) as s:  # the missing fact arrives, operator re-queues the dead letter
        ingest_event(
            s,
            restaurant_id=t.restaurant_id,
            event_type="order.created",
            payload=_order("EXT-0404"),
            idempotency_key="pos:EXT-0404:created",
            occurred_at=NOW - timedelta(minutes=10),
            source="api",
        )
        process_pending_events(s, t.restaurant_id)
        requeue_dead_letter(s, t.restaurant_id, ev.event_id)
        process_pending_events(s, t.restaurant_id)
        assert s.get(Event, ev.event_id).status == "processed"
        assert s.scalars(select(Order).where(Order.restaurant_id == t.restaurant_id)).one().status == "ready"


def test_invalid_payload_never_blocks_the_queue(factory, make_tenant) -> None:
    t = make_tenant()
    with session_scope(factory) as s:
        ingest_event(
            s,
            restaurant_id=t.restaurant_id,
            event_type="inventory.received",
            payload={"ingredient_key": "ing_inexistente", "quantity": 10},
            idempotency_key="inv:bad:0001",
            occurred_at=NOW,
            source="api",
        )
        ingest_event(
            s,
            restaurant_id=t.restaurant_id,
            event_type="order.created",
            payload=_order("EXT-0002"),
            idempotency_key="pos:EXT-0002:created",
            occurred_at=NOW,
            source="api",
        )
        stats = process_pending_events(s, t.restaurant_id)
    assert stats.rejected == 1 and stats.processed == 1


def _approval(
    factory, tenant, *, action="pause_menu_item", payload=None, expires_in=timedelta(minutes=30)
) -> uuid.UUID:
    with session_scope(factory) as s:
        a = ApprovalRequest(
            restaurant_id=tenant.restaurant_id,
            action_type=action,
            payload=payload or {"item_key": "item_pastel_costela", "reason": "Preservar costela"},
            title="Pausar Pastel",
            rationale="teste",
            expected_impact="teste",
            risk_level="medium",
            evidence=[],
            required_role="manager",
            idempotency_key=f"test:{uuid.uuid4().hex}",
            expires_at=datetime.now(UTC) + expires_in,
        )
        s.add(a)
        s.flush()
        return a.id


def _actor(tenant, role=Role.MANAGER) -> DecisionActor:
    return DecisionActor(user_id=tenant.user_id, label="Teste", role=role)


def test_operator_cannot_approve_and_nothing_executes(factory, make_tenant) -> None:
    t = make_tenant(role="operator")
    aid = _approval(factory, t)
    with session_scope(factory) as s, pytest.raises(Forbidden):
        decide(
            s,
            restaurant_id=t.restaurant_id,
            approval_id=aid,
            actor=_actor(t, Role.OPERATOR),
            decision=Decision.APPROVE,
            reason=None,
        )
    with session_scope(factory) as s:
        assert s.get(ApprovalRequest, aid).status == "pending"


def test_double_decision_executes_once(factory, make_tenant) -> None:
    t = make_tenant()
    aid = _approval(
        factory,
        t,
        action="create_purchase_order",
        payload={
            "ingredient_key": "ing_costela",
            "quantity": 5000,
            "unit": "g",
            "expected_arrival_minutes": 40,
            "estimated_cost_cents": 45000,
        },
    )
    with session_scope(factory) as s:
        assert (
            decide(
                s,
                restaurant_id=t.restaurant_id,
                approval_id=aid,
                actor=_actor(t),
                decision=Decision.APPROVE,
                reason=None,
            ).status
            == "executed"
        )
    with session_scope(factory) as s, pytest.raises(Conflict):
        decide(
            s, restaurant_id=t.restaurant_id, approval_id=aid, actor=_actor(t), decision=Decision.APPROVE, reason=None
        )
    with session_scope(factory) as s:
        assert (
            s.scalar(
                select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.restaurant_id == t.restaurant_id)
            )
            == 1
        )


def test_revalidation_blocks_duplicate_purchase_orders(factory, make_tenant) -> None:
    t = make_tenant()
    payload = {
        "ingredient_key": "ing_costela",
        "quantity": 5000,
        "unit": "g",
        "expected_arrival_minutes": 40,
        "estimated_cost_cents": 45000,
    }
    first, second = (
        _approval(factory, t, action="create_purchase_order", payload=payload),
        _approval(factory, t, action="create_purchase_order", payload=payload),
    )
    with session_scope(factory) as s:
        decide(
            s, restaurant_id=t.restaurant_id, approval_id=first, actor=_actor(t), decision=Decision.APPROVE, reason=None
        )
    with session_scope(factory) as s:
        result = decide(
            s,
            restaurant_id=t.restaurant_id,
            approval_id=second,
            actor=_actor(t),
            decision=Decision.APPROVE,
            reason=None,
        )
    assert result.status == "failed" and result.execution_result["error"] == "duplicate_purchase_order"


def test_out_of_bounds_quantity_fails_revalidation(factory, make_tenant) -> None:
    t = make_tenant()
    aid = _approval(
        factory,
        t,
        action="create_purchase_order",
        payload={
            "ingredient_key": "ing_costela",
            "quantity": 900000,
            "unit": "g",
            "expected_arrival_minutes": 40,
            "estimated_cost_cents": 100,
        },
    )
    with session_scope(factory) as s:
        result = decide(
            s, restaurant_id=t.restaurant_id, approval_id=aid, actor=_actor(t), decision=Decision.APPROVE, reason=None
        )
    assert result.status == "failed" and result.execution_result["error"] == "quantity_out_of_bounds"


def test_expired_approval_is_gone(factory, make_tenant) -> None:
    t = make_tenant()
    aid = _approval(factory, t, expires_in=timedelta(seconds=-1))
    with session_scope(factory) as s, pytest.raises(Gone):
        decide(
            s, restaurant_id=t.restaurant_id, approval_id=aid, actor=_actor(t), decision=Decision.APPROVE, reason=None
        )
    with session_scope(factory) as s:
        assert s.get(ApprovalRequest, aid).status == "expired"
    other = _approval(factory, t, expires_in=timedelta(seconds=-1))
    with session_scope(factory) as s:
        assert expire_pending(s) >= 1
        assert s.get(ApprovalRequest, other).status == "expired"


def test_rejection_requires_justification(factory, make_tenant) -> None:
    t = make_tenant()
    aid = _approval(factory, t)
    with session_scope(factory) as s, pytest.raises(ValidationFailed):
        decide(s, restaurant_id=t.restaurant_id, approval_id=aid, actor=_actor(t), decision=Decision.REJECT, reason=" ")


def test_cross_tenant_decision_is_not_found(factory, make_tenant) -> None:
    owner, intruder = make_tenant(), make_tenant()
    aid = _approval(factory, owner)
    with session_scope(factory) as s, pytest.raises(NotFound):
        decide(
            s,
            restaurant_id=intruder.restaurant_id,
            approval_id=aid,
            actor=_actor(intruder),
            decision=Decision.APPROVE,
            reason=None,
        )


def test_audit_log_is_append_only(factory, make_tenant) -> None:
    t = make_tenant()
    with session_scope(factory) as s:
        s.add(AuditLog(restaurant_id=t.restaurant_id, actor_type="system", actor_label="t", action="test.event"))
    for stmt in ("UPDATE audit_logs SET action = 'tampered'", "DELETE FROM audit_logs", "TRUNCATE audit_logs"):
        with pytest.raises(DBAPIError, match="append-only"), session_scope(factory) as s:
            s.execute(text(stmt))


def test_demo_sandboxes_are_isolated_and_purged(factory, catalog, settings) -> None:
    with session_scope(factory) as s:
        a = create_demo_sandbox(s, catalog=catalog, settings=settings, client_ip="203.0.113.10", persona="manager")
        b = create_demo_sandbox(s, catalog=catalog, settings=settings, client_ip="203.0.113.11", persona="operator")
        ids_a = {r.id for r in a.restaurants}
        ids_b = {r.id for r in b.restaurants}
        assert ids_a.isdisjoint(ids_b) and len(ids_a) == 2
        s.execute(
            update(DemoSession)
            .where(DemoSession.id == a.session.id)
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
    with session_scope(factory) as s:
        assert purge_expired_sandboxes(s) >= 1
    with session_scope(factory) as s:
        assert s.scalar(select(func.count()).select_from(Restaurant).where(Restaurant.id.in_(ids_a))) == 0
        assert s.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.restaurant_id.in_(ids_a))) == 0
        assert s.scalar(select(func.count()).select_from(Restaurant).where(Restaurant.id.in_(ids_b))) == 2
