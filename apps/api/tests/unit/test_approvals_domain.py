from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from nexus.domain.approvals import ApprovalStatus, Decision, check_decision, parse_action
from nexus.domain.errors import Conflict, Forbidden, Gone
from nexus.domain.rbac import Permission, Role, has_permission, permissions_for

NOW = datetime(2026, 3, 13, 22, 0, tzinfo=UTC)


def _check(**overrides):
    params = dict(
        status=ApprovalStatus.PENDING,
        expires_at=NOW + timedelta(minutes=10),
        now=NOW,
        decision=Decision.APPROVE,
        actor_role=Role.MANAGER,
        required_role=Role.MANAGER,
    )
    params.update(overrides)
    return check_decision(**params)


def test_manager_can_approve_and_reject() -> None:
    assert _check().new_status is ApprovalStatus.APPROVED
    assert _check(decision=Decision.REJECT).new_status is ApprovalStatus.REJECTED


@pytest.mark.parametrize("role", [Role.VIEWER, Role.OPERATOR])
def test_lower_roles_cannot_decide(role: Role) -> None:
    with pytest.raises(Forbidden):
        _check(actor_role=role)


def test_owner_required_blocks_manager() -> None:
    with pytest.raises(Forbidden):
        _check(required_role=Role.OWNER)


@pytest.mark.parametrize("status", [s for s in ApprovalStatus if s is not ApprovalStatus.PENDING])
def test_only_pending_can_be_decided(status: ApprovalStatus) -> None:
    with pytest.raises(Conflict):
        _check(status=status)


def test_expired_approval_cannot_be_approved() -> None:
    with pytest.raises(Gone):
        _check(expires_at=NOW)


def test_action_payloads_are_strict() -> None:
    ok = parse_action("pause_menu_item", {"item_key": "item_x", "reason": "preservar estoque"})
    assert ok.action_type == "pause_menu_item"
    with pytest.raises(ValidationError):
        parse_action("pause_menu_item", {"item_key": "item_x", "reason": "ok!", "discount": 100})
    with pytest.raises(ValidationError):
        parse_action(
            "create_purchase_order",
            {
                "ingredient_key": "ing_a",
                "quantity": -5,
                "unit": "g",
                "expected_arrival_minutes": 40,
                "estimated_cost_cents": 1,
            },
        )
    with pytest.raises(ValidationError):
        parse_action("issue_refund", {"amount": 1000})


def test_rbac_matrix() -> None:
    assert has_permission(Role.OPERATOR, Permission.SIMULATION_CONTROL)
    assert not has_permission(Role.OPERATOR, Permission.APPROVALS_DECIDE)
    assert not has_permission(Role.VIEWER, Permission.SIMULATION_CONTROL)
    assert "approvals.decide" in permissions_for(Role.MANAGER)
