"""Role-based access control per restaurant (tenant)."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    MANAGER = "manager"
    OWNER = "owner"


ROLE_RANK: dict[Role, int] = {Role.VIEWER: 0, Role.OPERATOR: 1, Role.MANAGER: 2, Role.OWNER: 3}


class Permission(StrEnum):
    VIEW = "view"
    SIMULATION_CONTROL = "simulation.control"
    EVENTS_INGEST = "events.ingest"
    AGENTS_RUN = "agents.run"
    APPROVALS_DECIDE = "approvals.decide"
    MENU_UPDATE = "menu.update"
    SANDBOX_RESET = "sandbox.reset"


MIN_ROLE: dict[Permission, Role] = {
    Permission.VIEW: Role.VIEWER,
    Permission.SIMULATION_CONTROL: Role.OPERATOR,
    Permission.EVENTS_INGEST: Role.OPERATOR,
    Permission.AGENTS_RUN: Role.OPERATOR,
    Permission.APPROVALS_DECIDE: Role.MANAGER,
    Permission.MENU_UPDATE: Role.MANAGER,
    Permission.SANDBOX_RESET: Role.MANAGER,
}


def has_permission(role: Role | str, permission: Permission) -> bool:
    return ROLE_RANK[Role(role)] >= ROLE_RANK[MIN_ROLE[permission]]


def permissions_for(role: Role | str) -> list[str]:
    return sorted(p.value for p in Permission if has_permission(role, p))
