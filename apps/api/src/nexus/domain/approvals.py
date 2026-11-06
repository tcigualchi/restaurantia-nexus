"""Approval state machine and sensitive-action payload schemas (pure).

States::

    pending ──approve──▶ approved ──execute──▶ executed
       │                     └──────────────▶ failed   (revalidation/execution error)
       ├──reject──▶ rejected
       ├──(time)──▶ expired
       └──reset───▶ cancelled

Only ``pending`` can be decided, and only once. The persistence layer enforces
this with a row lock plus an optimistic ``version`` check, so concurrent clicks
or replayed requests can never execute an action twice.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from nexus.domain.catalog import KEY_PATTERN
from nexus.domain.errors import Conflict, Forbidden, Gone
from nexus.domain.rbac import ROLE_RANK, Permission, Role, has_permission


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTED = "executed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL = frozenset(
    {
        ApprovalStatus.REJECTED,
        ApprovalStatus.EXPIRED,
        ApprovalStatus.EXECUTED,
        ApprovalStatus.FAILED,
        ApprovalStatus.CANCELLED,
    }
)


class Decision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PurchaseOrderPayload(_Payload):
    action_type: Literal["create_purchase_order"] = "create_purchase_order"
    ingredient_key: str = Field(pattern=KEY_PATTERN)
    quantity: float = Field(gt=0, le=1_000_000)
    unit: Literal["un", "g", "ml"]
    expected_arrival_minutes: int = Field(ge=5, le=24 * 60)
    estimated_cost_cents: int = Field(ge=0, le=10_000_000)


class PauseMenuItemPayload(_Payload):
    action_type: Literal["pause_menu_item"] = "pause_menu_item"
    item_key: str = Field(pattern=KEY_PATTERN)
    reason: str = Field(min_length=3, max_length=200)
    ingredient_key: str | None = Field(default=None, pattern=KEY_PATTERN)


ActionPayload = Annotated[PurchaseOrderPayload | PauseMenuItemPayload, Field(discriminator="action_type")]
action_payload_adapter: TypeAdapter[PurchaseOrderPayload | PauseMenuItemPayload] = TypeAdapter(ActionPayload)


def parse_action(action_type: str, payload: dict[str, object]) -> PurchaseOrderPayload | PauseMenuItemPayload:
    return action_payload_adapter.validate_python({**payload, "action_type": action_type})


def required_role_for(action_type: str) -> Role:
    # Both sensitive actions require a manager in this version; kept explicit per action
    # so a future refund/discount action can require OWNER.
    return {"create_purchase_order": Role.MANAGER, "pause_menu_item": Role.MANAGER}[action_type]


class DecisionCheck(BaseModel):
    new_status: ApprovalStatus


def check_decision(
    *,
    status: ApprovalStatus,
    expires_at: datetime,
    now: datetime,
    decision: Decision,
    actor_role: Role,
    required_role: Role,
) -> DecisionCheck:
    """Validate a human decision. Raises Forbidden/Conflict/Gone."""
    if not has_permission(actor_role, Permission.APPROVALS_DECIDE):
        raise Forbidden(
            "Seu papel não permite decidir aprovações.",
            code="role_insufficient",
            details={"required_role": required_role.value, "actor_role": actor_role.value},
        )
    if ROLE_RANK[actor_role] < ROLE_RANK[required_role]:
        raise Forbidden(
            "Esta ação exige um papel superior.",
            code="role_insufficient",
            details={"required_role": required_role.value, "actor_role": actor_role.value},
        )
    if status != ApprovalStatus.PENDING:
        raise Conflict(
            f"Aprovação já está em estado '{status.value}'.", code="already_decided", details={"status": status.value}
        )
    if now >= expires_at:
        raise Gone("Aprovação expirada; o agente precisa reavaliar a situação.", code="approval_expired")
    return DecisionCheck(
        new_status=ApprovalStatus.APPROVED if decision == Decision.APPROVE else ApprovalStatus.REJECTED
    )
