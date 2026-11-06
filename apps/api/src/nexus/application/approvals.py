"""Human approval workflow and sensitive-action executors.

Execution is only reachable from an *approved* decision, inside the same
transaction, after re-validating the action against the current state:
schema, tenant ownership, entity existence, bounds, duplicates and staleness.
A row lock plus the ``pending``-only transition guarantees at most one execution.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus.application.audit import Actor, record_audit
from nexus.application.clock import business_now
from nexus.domain.approvals import (
    ApprovalStatus,
    Decision,
    PauseMenuItemPayload,
    PurchaseOrderPayload,
    check_decision,
    parse_action,
)
from nexus.domain.errors import Gone, NotFound, ValidationFailed
from nexus.domain.rbac import Role
from nexus.domain.simulation import minutes_to_datetime
from nexus.infra.models import ApprovalRequest, Ingredient, MenuItem, PurchaseOrder, SimulationRun

STALE_AFTER_BUSINESS_MINUTES = 60


@dataclass(frozen=True)
class DecisionActor:
    user_id: uuid.UUID
    label: str
    role: Role

    @property
    def audit(self) -> Actor:
        return Actor("user", str(self.user_id), self.label)


def decide(
    s: Session,
    *,
    restaurant_id: uuid.UUID,
    approval_id: uuid.UUID,
    actor: DecisionActor,
    decision: Decision,
    reason: str | None,
    request_id: str | None = None,
    now: datetime | None = None,
) -> ApprovalRequest:
    now = now or datetime.now(UTC)
    approval = s.scalars(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == approval_id, ApprovalRequest.restaurant_id == restaurant_id)
        .with_for_update()
    ).one_or_none()
    if approval is None:
        raise NotFound("Aprovação não encontrada.")
    if decision is Decision.REJECT and (not reason or len(reason.strip()) < 3):
        raise ValidationFailed("Informe uma justificativa para rejeitar.", code="reason_required")
    if approval.status == ApprovalStatus.PENDING and now >= approval.expires_at:
        _expire(s, approval, now)
        s.flush()
        raise Gone("Aprovação expirada; o agente precisa reavaliar a situação.", code="approval_expired")
    check = check_decision(
        status=ApprovalStatus(approval.status),
        expires_at=approval.expires_at,
        now=now,
        decision=decision,
        actor_role=actor.role,
        required_role=Role(approval.required_role),
    )
    approval.status = check.new_status.value
    approval.decided_by, approval.decided_at = actor.user_id, now
    approval.decision_reason = (reason or "").strip()[:500] or None
    approval.version += 1
    bt = business_now(s, restaurant_id)
    record_audit(
        s,
        restaurant_id=restaurant_id,
        actor=actor.audit,
        action=f"approval.{check.new_status.value}",
        target_type="approval",
        target_id=approval.id,
        details={"title": approval.title, "action_type": approval.action_type, "reason": approval.decision_reason},
        business_time=bt,
        request_id=request_id,
    )
    if check.new_status is ApprovalStatus.APPROVED:
        ok, result = execute_action(s, approval, actor=actor, now=now, business_time=bt)
        approval.status = ApprovalStatus.EXECUTED.value if ok else ApprovalStatus.FAILED.value
        approval.executed_at = now if ok else None
        approval.execution_result = result
        record_audit(
            s,
            restaurant_id=restaurant_id,
            actor=actor.audit,
            action="action.executed" if ok else "action.failed",
            target_type="approval",
            target_id=approval.id,
            details={"action_type": approval.action_type, **result},
            business_time=bt,
            request_id=request_id,
        )
    s.flush()
    maybe_resume_simulation(s, approval.simulation_run_id)
    return approval


def execute_action(
    s: Session, approval: ApprovalRequest, *, actor: DecisionActor, now: datetime, business_time: datetime
) -> tuple[bool, dict[str, Any]]:
    try:
        action = parse_action(approval.action_type, dict(approval.payload))
    except ValueError as exc:
        return False, {"error": "payload_invalid", "message": str(exc)[:200]}
    if approval.business_time is not None:
        age = (business_time - approval.business_time).total_seconds() / 60
        if age > STALE_AFTER_BUSINESS_MINUTES:
            return False, {
                "error": "stale_proposal",
                "message": f"Proposta feita há {age:.0f} min (horário do negócio); reavalie antes de executar.",
            }
    if isinstance(action, PauseMenuItemPayload):
        return _pause_menu_item(s, approval, action, actor, business_time)
    return _create_purchase_order(s, approval, action, business_time)


def _pause_menu_item(
    s: Session, approval: ApprovalRequest, action: PauseMenuItemPayload, actor: DecisionActor, business_time: datetime
) -> tuple[bool, dict[str, Any]]:
    item = s.scalars(
        select(MenuItem)
        .where(MenuItem.restaurant_id == approval.restaurant_id, MenuItem.key == action.item_key)
        .with_for_update()
    ).one_or_none()
    if item is None:
        return False, {"error": "item_not_found", "message": "Item não pertence a este restaurante."}
    if not item.is_available:
        return True, {"result": "no_op", "message": f"“{item.name}” já estava indisponível."}
    item.is_available = False
    item.unavailable_reason = action.reason
    item.updated_at = datetime.now(UTC)
    record_audit(
        s,
        restaurant_id=approval.restaurant_id,
        actor=actor.audit,
        action="menu_item.paused",
        target_type="menu_item",
        target_id=item.id,
        details={"item_key": item.key, "name": item.name, "reason": action.reason, "approval_id": str(approval.id)},
        business_time=business_time,
    )
    return True, {"result": "paused", "item_key": item.key, "message": f"“{item.name}” pausado no cardápio."}


def _create_purchase_order(
    s: Session, approval: ApprovalRequest, action: PurchaseOrderPayload, business_time: datetime
) -> tuple[bool, dict[str, Any]]:
    ing = s.scalars(
        select(Ingredient)
        .where(Ingredient.restaurant_id == approval.restaurant_id, Ingredient.key == action.ingredient_key)
        .with_for_update()
    ).one_or_none()
    if ing is None:
        return False, {"error": "ingredient_not_found", "message": "Ingrediente não pertence a este restaurante."}
    if action.unit != ing.unit:
        return False, {"error": "unit_mismatch", "message": f"Unidade {action.unit} difere de {ing.unit}."}
    cap = max(50 * float(ing.pack_size), 20 * float(ing.safety_stock))
    if action.quantity > cap:
        return False, {
            "error": "quantity_out_of_bounds",
            "message": f"Quantidade acima do limite de segurança ({cap:g} {ing.unit}).",
        }
    open_po = s.scalar(
        select(PurchaseOrder.id)
        .where(
            PurchaseOrder.restaurant_id == approval.restaurant_id,
            PurchaseOrder.ingredient_id == ing.id,
            PurchaseOrder.status == "ordered",
        )
        .limit(1)
    )
    if open_po is not None:
        return False, {
            "error": "duplicate_purchase_order",
            "message": "Já existe um pedido de compra em aberto para este ingrediente.",
        }
    sim = s.get(SimulationRun, approval.simulation_run_id) if approval.simulation_run_id else None
    expected_tick: int | None = None
    if sim is not None and sim.status in ("running", "paused"):
        expected_tick = sim.current_tick + math.ceil(action.expected_arrival_minutes)
        expected_at = minutes_to_datetime(sim.sim_start, expected_tick)
    else:
        expected_at = business_time + timedelta(minutes=action.expected_arrival_minutes)
    po = PurchaseOrder(
        restaurant_id=approval.restaurant_id,
        ingredient_id=ing.id,
        quantity=Decimal(str(action.quantity)),
        unit=ing.unit,
        status="ordered",
        estimated_cost_cents=action.estimated_cost_cents,
        expected_at=expected_at,
        expected_tick=expected_tick,
        approval_id=approval.id,
        simulation_run_id=sim.id if sim else None,
    )
    s.add(po)
    s.flush()
    record_audit(
        s,
        restaurant_id=approval.restaurant_id,
        actor=Actor.system("Compras (simulado)"),
        action="purchase_order.created",
        target_type="purchase_order",
        target_id=po.id,
        details={
            "ingredient": ing.name,
            "quantity": action.quantity,
            "unit": ing.unit,
            "expected_at": expected_at.isoformat(),
            "approval_id": str(approval.id),
            "note": "Pedido simulado. Nenhum fornecedor real é contatado.",
        },
        business_time=business_time,
    )
    return True, {
        "result": "purchase_order_created",
        "purchase_order_id": str(po.id),
        "expected_at": expected_at.isoformat(),
        "message": "Pedido de compra registrado. É uma simulação, nenhum fornecedor real é contatado.",
    }


def _expire(s: Session, approval: ApprovalRequest, now: datetime) -> None:
    approval.status = ApprovalStatus.EXPIRED.value
    approval.version += 1
    record_audit(
        s,
        restaurant_id=approval.restaurant_id,
        actor=Actor.system(),
        action="approval.expired",
        target_type="approval",
        target_id=approval.id,
        details={"title": approval.title},
    )


def expire_pending(
    s: Session, *, now: datetime | None = None, limit: int = 100, restaurant_id: uuid.UUID | None = None
) -> int:
    now = now or datetime.now(UTC)
    query = select(ApprovalRequest).where(ApprovalRequest.status == "pending", ApprovalRequest.expires_at <= now)
    if restaurant_id is not None:
        query = query.where(ApprovalRequest.restaurant_id == restaurant_id)
    rows = list(s.scalars(query.limit(limit).with_for_update(skip_locked=True)))
    sims = set()
    for approval in rows:
        _expire(s, approval, now)
        if approval.simulation_run_id:
            sims.add(approval.simulation_run_id)
    s.flush()
    for sim_id in sims:
        maybe_resume_simulation(s, sim_id)
    return len(rows)


def maybe_resume_simulation(s: Session, simulation_run_id: uuid.UUID | None) -> None:
    if simulation_run_id is None:
        return
    sim = s.get(SimulationRun, simulation_run_id, with_for_update=True)
    if sim is None or sim.status != "paused" or sim.pause_reason != "awaiting_approval":
        return
    pending = s.scalar(
        select(ApprovalRequest.id)
        .where(ApprovalRequest.simulation_run_id == sim.id, ApprovalRequest.status == "pending")
        .limit(1)
    )
    if pending is None:
        sim.status, sim.pause_reason, sim.updated_at = "running", None, datetime.now(UTC)
        record_audit(
            s,
            restaurant_id=sim.restaurant_id,
            actor=Actor.system(),
            action="simulation.resumed",
            target_type="simulation",
            target_id=sim.id,
            details={"reason": "approvals_decided"},
            business_time=minutes_to_datetime(sim.sim_start, sim.current_tick),
        )
