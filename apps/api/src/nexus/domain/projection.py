"""Reference (in-memory) projection of restaurant events.

This is the executable specification of how events change state. The SQL
projector in ``nexus.application.events`` implements the same rules against
PostgreSQL, and integration tests compare both for the same event stream
(differential testing).

Rules
-----
* ``order.created`` is idempotent on ``order_ref``. If any ingredient is short
  the whole order is *rejected* (lost revenue) and no stock is consumed, since
  restaurants do not sell half a burger.
* ``order.ready`` for an unknown order is *retryable* (events can arrive out of
  order); the queue retries it and eventually dead-letters it.
* ``inventory.received`` adds stock; ``inventory.adjusted`` applies a signed
  delta that can never make stock negative.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from nexus.domain.metrics import OrderRow, recipe_consumption


class ApplyOutcome(StrEnum):
    APPLIED = "applied"
    DUPLICATE = "duplicate"  # idempotent no-op
    REJECTED = "rejected"  # business rejection recorded as state (e.g. stockout)
    INVALID = "invalid"  # the event itself is unusable (e.g. unknown ingredient)
    RETRY = "retry"  # precondition not met yet


@dataclass(frozen=True)
class ApplyResult:
    outcome: ApplyOutcome
    detail: str = ""


def stock_shortages(stock: Mapping[str, float], needed: Mapping[str, float]) -> list[str]:
    return sorted(k for k, q in needed.items() if stock.get(k, 0.0) + 1e-9 < q)


@dataclass
class OrderState:
    order_ref: str
    channel: str
    created_at: datetime
    items: list[tuple[str, int]]
    total_cents: int
    status: str
    ready_at: datetime | None = None
    reject_reason: str | None = None
    customer_note: str | None = None


@dataclass
class RestaurantProjection:
    stock: dict[str, float]
    recipes: dict[str, dict[str, float]]
    prices: dict[str, int]
    available: dict[str, bool]
    lines_available: int
    orders: dict[str, OrderState] = field(default_factory=dict)
    consumption_log: list[tuple[datetime, str, float]] = field(default_factory=list)

    def apply(self, event_type: str, payload: Mapping[str, Any], occurred_at: datetime) -> ApplyResult:
        handler = getattr(self, "_on_" + event_type.replace(".", "_"), None)
        if handler is None:
            raise ValueError(f"unsupported event type {event_type}")
        result: ApplyResult = handler(payload, occurred_at)
        return result

    # --- handlers -----------------------------------------------------------------
    def _on_order_created(self, p: Mapping[str, Any], at: datetime) -> ApplyResult:
        ref = p["order_ref"]
        if ref in self.orders:
            return ApplyResult(ApplyOutcome.DUPLICATE)
        items = [(i["item_key"], int(i["qty"])) for i in p["items"]]
        unknown = [k for k, _ in items if k not in self.recipes]
        total = sum(self.prices.get(k, 0) * q for k, q in items)
        order = OrderState(ref, p["channel"], at, items, total, "received", customer_note=p.get("customer_note"))
        if unknown:
            order.status, order.reject_reason = "rejected", f"unknown_item:{unknown[0]}"
            self.orders[ref] = order
            return ApplyResult(ApplyOutcome.REJECTED, order.reject_reason)
        paused = [k for k, _ in items if not self.available.get(k, True)]
        if paused:
            order.status, order.reject_reason = "rejected", f"item_unavailable:{paused[0]}"
            self.orders[ref] = order
            return ApplyResult(ApplyOutcome.REJECTED, order.reject_reason)
        needed = recipe_consumption(items, self.recipes)
        short = stock_shortages(self.stock, needed)
        if short:
            order.status, order.reject_reason = "rejected", f"stockout:{short[0]}"
            self.orders[ref] = order
            return ApplyResult(ApplyOutcome.REJECTED, order.reject_reason)
        for ing, qty in needed.items():
            self.stock[ing] -= qty
            self.consumption_log.append((at, ing, qty))
        self.orders[ref] = order
        return ApplyResult(ApplyOutcome.APPLIED)

    def _on_order_ready(self, p: Mapping[str, Any], at: datetime) -> ApplyResult:
        order = self.orders.get(p["order_ref"])
        if order is None:
            return ApplyResult(ApplyOutcome.RETRY, "order_not_found")
        if order.status != "received":
            return ApplyResult(ApplyOutcome.DUPLICATE)
        order.status, order.ready_at = "ready", at
        return ApplyResult(ApplyOutcome.APPLIED)

    def _on_order_cancelled(self, p: Mapping[str, Any], at: datetime) -> ApplyResult:
        order = self.orders.get(p["order_ref"])
        if order is None:
            return ApplyResult(ApplyOutcome.RETRY, "order_not_found")
        if order.status in ("cancelled", "rejected"):
            return ApplyResult(ApplyOutcome.DUPLICATE)
        order.status = "cancelled"
        return ApplyResult(ApplyOutcome.APPLIED)

    def _on_inventory_received(self, p: Mapping[str, Any], at: datetime) -> ApplyResult:
        key = p["ingredient_key"]
        if key not in self.stock:
            return ApplyResult(ApplyOutcome.INVALID, f"unknown_ingredient:{key}")
        self.stock[key] += float(p["quantity"])
        return ApplyResult(ApplyOutcome.APPLIED)

    def _on_inventory_adjusted(self, p: Mapping[str, Any], at: datetime) -> ApplyResult:
        key = p["ingredient_key"]
        if key not in self.stock:
            return ApplyResult(ApplyOutcome.INVALID, f"unknown_ingredient:{key}")
        self.stock[key] = max(0.0, self.stock[key] + float(p["delta"]))
        return ApplyResult(ApplyOutcome.APPLIED)

    def _on_kitchen_capacity_changed(self, p: Mapping[str, Any], at: datetime) -> ApplyResult:
        self.lines_available = int(p["lines_available"])
        return ApplyResult(ApplyOutcome.APPLIED)

    # --- read helpers ---------------------------------------------------------------
    def order_rows(self) -> list[OrderRow]:
        return [
            OrderRow(o.order_ref, o.status, o.created_at, o.ready_at, o.total_cents, o.channel)
            for o in self.orders.values()
        ]

    def consumed_between(self, start: datetime, end: datetime) -> dict[str, float]:
        out: dict[str, float] = {}
        for at, ing, qty in self.consumption_log:
            if start <= at <= end:
                out[ing] = out.get(ing, 0.0) + qty
        return out
