"""Event ingestion and processing (PostgreSQL-backed queue).

* **Idempotent ingestion** — ``UNIQUE (restaurant_id, idempotency_key)`` with
  ``ON CONFLICT DO NOTHING``: replays return the original event, never a copy.
* **Ordered, per-tenant processing** — a transaction-scoped advisory lock per
  restaurant serialises processing; events are claimed in id order with
  ``FOR UPDATE SKIP LOCKED`` so several workers can share the queue.
* **Retries and dead-letter** — each event is applied inside a SAVEPOINT. A
  retryable failure (e.g. ``order.ready`` arriving before ``order.created``) or an
  unexpected error rolls back only that event and schedules a retry with
  exponential backoff; after ``max_attempts`` it is moved to ``dead_letter``.
* **Idempotent effects** — handlers are no-ops for already-applied facts (same
  order ref, order already ready), so even a re-delivered event cannot double
  count stock or revenue.

The projection rules mirror ``nexus.domain.projection.RestaurantProjection``
(the executable specification); integration tests compare both.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from nexus.domain.errors import RetryableError
from nexus.domain.events import parse_payload
from nexus.domain.guardrails import detect_injection
from nexus.domain.metrics import recipe_consumption
from nexus.domain.projection import ApplyOutcome, ApplyResult, stock_shortages
from nexus.infra.models import (
    Event,
    Ingredient,
    MenuItem,
    Order,
    OrderItem,
    PurchaseOrder,
    RecipeLine,
    Restaurant,
    StockMovement,
)


@dataclass(frozen=True)
class IngestResult:
    event_id: int
    created: bool


def ingest_event(
    session: Session,
    *,
    restaurant_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
    occurred_at: datetime,
    source: str,
    simulation_run_id: uuid.UUID | None = None,
    tick: int | None = None,
) -> IngestResult:
    stmt = (
        pg_insert(Event)
        .values(
            restaurant_id=restaurant_id,
            type=event_type,
            idempotency_key=idempotency_key,
            source=source,
            simulation_run_id=simulation_run_id,
            tick=tick,
            occurred_at=occurred_at,
            payload=payload,
        )
        .on_conflict_do_nothing(constraint="uq_event_idempotency")
        .returning(Event.id)
    )
    new_id = session.execute(stmt).scalar_one_or_none()
    if new_id is not None:
        return IngestResult(int(new_id), True)
    existing = session.scalar(
        select(Event.id).where(Event.restaurant_id == restaurant_id, Event.idempotency_key == idempotency_key)
    )
    assert existing is not None
    return IngestResult(int(existing), False)


class SqlProjector:
    """Applies one event to the relational state of a single restaurant."""

    def __init__(self, session: Session, restaurant_id: uuid.UUID):
        self.s = session
        self.rid = restaurant_id
        self._recipes: dict[str, dict[str, float]] | None = None
        self._ingredient_ids: dict[str, uuid.UUID] | None = None

    def _load_catalog(self) -> None:
        rows = self.s.execute(
            select(MenuItem.key, Ingredient.key, Ingredient.id, RecipeLine.qty_per_unit)
            .join(RecipeLine, RecipeLine.menu_item_id == MenuItem.id)
            .join(Ingredient, Ingredient.id == RecipeLine.ingredient_id)
            .where(MenuItem.restaurant_id == self.rid)
        ).all()
        recipes: dict[str, dict[str, float]] = {}
        ids: dict[str, uuid.UUID] = {}
        for item_key, ing_key, ing_id, qty in rows:
            recipes.setdefault(item_key, {})[ing_key] = float(qty)
            ids[ing_key] = ing_id
        for ing_key, ing_id in self.s.execute(
            select(Ingredient.key, Ingredient.id).where(Ingredient.restaurant_id == self.rid)
        ):
            ids[ing_key] = ing_id
        self._recipes, self._ingredient_ids = recipes, ids

    @property
    def recipes(self) -> dict[str, dict[str, float]]:
        if self._recipes is None:
            self._load_catalog()
        assert self._recipes is not None
        return self._recipes

    @property
    def ingredient_ids(self) -> dict[str, uuid.UUID]:
        if self._ingredient_ids is None:
            self._load_catalog()
        assert self._ingredient_ids is not None
        return self._ingredient_ids

    def apply(self, event: Event) -> ApplyResult:
        model = parse_payload(event.type, event.payload)  # re-validated on every delivery
        data = model.model_dump(mode="python", exclude_none=True)
        handler = getattr(self, "_on_" + event.type.replace(".", "_"))
        result: ApplyResult = handler(data, event)
        return result

    def _lock_ingredients(self, keys: list[str]) -> dict[str, Ingredient]:
        ids = [self.ingredient_ids[k] for k in keys if k in self.ingredient_ids]
        rows = self.s.scalars(
            select(Ingredient).where(Ingredient.id.in_(ids)).order_by(Ingredient.id).with_for_update()
        )
        return {r.key: r for r in rows}

    def _on_order_created(self, p: dict[str, Any], ev: Event) -> ApplyResult:
        ref = p["order_ref"]
        exists = self.s.scalar(select(Order.id).where(Order.restaurant_id == self.rid, Order.order_ref == ref))
        if exists is not None:
            return ApplyResult(ApplyOutcome.DUPLICATE)
        items = [(i["item_key"], int(i["qty"])) for i in p["items"]]
        menu = {
            m.key: m
            for m in self.s.scalars(
                select(MenuItem).where(MenuItem.restaurant_id == self.rid, MenuItem.key.in_([k for k, _ in items]))
            )
        }
        total = sum(menu[k].price_cents * q for k, q in items if k in menu)
        note = p.get("customer_note")
        order = Order(
            restaurant_id=self.rid,
            order_ref=ref,
            channel=p["channel"],
            status="received",
            created_at=ev.occurred_at,
            total_cents=total,
            customer_note=note,
            note_flags=list(detect_injection(note)) if note else [],
            event_id=ev.id,
        )
        unknown = [k for k, _ in items if k not in menu or k not in self.recipes]
        paused = [k for k, _ in items if k in menu and not menu[k].is_available]
        needed: dict[str, float] = {}
        locked: dict[str, Ingredient] = {}
        result: ApplyResult
        if unknown:
            order.status, order.reject_reason = "rejected", f"unknown_item:{unknown[0]}"
            result = ApplyResult(ApplyOutcome.REJECTED, order.reject_reason)
        elif paused:
            order.status, order.reject_reason = "rejected", f"item_unavailable:{paused[0]}"
            result = ApplyResult(ApplyOutcome.REJECTED, order.reject_reason)
        else:
            needed = recipe_consumption(items, self.recipes)
            locked = self._lock_ingredients(sorted(needed))
            short = stock_shortages({k: float(v.stock) for k, v in locked.items()}, needed)
            if short:
                order.status, order.reject_reason = "rejected", f"stockout:{short[0]}"
                result = ApplyResult(ApplyOutcome.REJECTED, order.reject_reason)
            else:
                result = ApplyResult(ApplyOutcome.APPLIED)
        self.s.add(order)
        self.s.flush()
        for k, q in items:
            self.s.add(
                OrderItem(
                    order_id=order.id,
                    item_key=k,
                    menu_item_id=menu[k].id if k in menu else None,
                    qty=q,
                    unit_price_cents=menu[k].price_cents if k in menu else 0,
                )
            )
        if result.outcome is ApplyOutcome.APPLIED:
            for ing_key, qty in needed.items():
                ing = locked[ing_key]
                ing.stock = ing.stock - Decimal(str(qty))
                ing.updated_at = datetime.now(UTC)
                self.s.add(
                    StockMovement(
                        restaurant_id=self.rid,
                        ingredient_id=ing.id,
                        delta=-Decimal(str(qty)),
                        reason="order_consumption",
                        occurred_at=ev.occurred_at,
                        event_id=ev.id,
                        order_id=order.id,
                    )
                )
        return result

    def _order_for_update(self, ref: str) -> Order | None:
        return self.s.scalars(
            select(Order).where(Order.restaurant_id == self.rid, Order.order_ref == ref).with_for_update()
        ).one_or_none()

    def _on_order_ready(self, p: dict[str, Any], ev: Event) -> ApplyResult:
        order = self._order_for_update(p["order_ref"])
        if order is None:
            raise RetryableError("order_not_found")
        if order.status != "received":
            return ApplyResult(ApplyOutcome.DUPLICATE)
        order.status, order.ready_at = "ready", ev.occurred_at
        return ApplyResult(ApplyOutcome.APPLIED)

    def _on_order_cancelled(self, p: dict[str, Any], ev: Event) -> ApplyResult:
        order = self._order_for_update(p["order_ref"])
        if order is None:
            raise RetryableError("order_not_found")
        if order.status in ("cancelled", "rejected"):
            return ApplyResult(ApplyOutcome.DUPLICATE)
        order.status = "cancelled"
        order.reject_reason = p.get("reason", "cancelled")[:120]
        return ApplyResult(ApplyOutcome.APPLIED)

    def _on_inventory_received(self, p: dict[str, Any], ev: Event) -> ApplyResult:
        locked = self._lock_ingredients([p["ingredient_key"]])
        ing = locked.get(p["ingredient_key"])
        if ing is None:
            return ApplyResult(ApplyOutcome.INVALID, f"unknown_ingredient:{p['ingredient_key']}")
        qty = Decimal(str(p["quantity"]))
        ing.stock = ing.stock + qty
        ing.updated_at = datetime.now(UTC)
        self.s.add(
            StockMovement(
                restaurant_id=self.rid,
                ingredient_id=ing.id,
                delta=qty,
                reason="purchase_received",
                occurred_at=ev.occurred_at,
                event_id=ev.id,
            )
        )
        po_id = p.get("purchase_order_id")
        if po_id:
            po = self.s.scalars(
                select(PurchaseOrder)
                .where(PurchaseOrder.restaurant_id == self.rid, PurchaseOrder.id == uuid.UUID(po_id))
                .with_for_update()
            ).one_or_none()
            if po is not None and po.status == "ordered":
                po.status, po.received_at = "received", ev.occurred_at
        return ApplyResult(ApplyOutcome.APPLIED)

    def _on_inventory_adjusted(self, p: dict[str, Any], ev: Event) -> ApplyResult:
        locked = self._lock_ingredients([p["ingredient_key"]])
        ing = locked.get(p["ingredient_key"])
        if ing is None:
            return ApplyResult(ApplyOutcome.INVALID, f"unknown_ingredient:{p['ingredient_key']}")
        new_stock = max(Decimal("0"), ing.stock + Decimal(str(p["delta"])))
        applied = new_stock - ing.stock
        ing.stock = new_stock
        ing.updated_at = datetime.now(UTC)
        self.s.add(
            StockMovement(
                restaurant_id=self.rid,
                ingredient_id=ing.id,
                delta=applied,
                reason="adjustment",
                occurred_at=ev.occurred_at,
                event_id=ev.id,
            )
        )
        return ApplyResult(ApplyOutcome.APPLIED)

    def _on_kitchen_capacity_changed(self, p: dict[str, Any], ev: Event) -> ApplyResult:
        restaurant = self.s.get(Restaurant, self.rid, with_for_update=True)
        assert restaurant is not None
        restaurant.kitchen_lines_available = min(int(p["lines_available"]), restaurant.kitchen_lines)
        return ApplyResult(ApplyOutcome.APPLIED)


@dataclass
class ProcessStats:
    processed: int = 0
    rejected: int = 0
    retried: int = 0
    dead_lettered: int = 0
    skipped_locked: bool = False
    last_tick: int | None = None
    outcomes: dict[str, int] = field(default_factory=dict)


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(60, 2**attempts))


def process_pending_events(
    session: Session,
    restaurant_id: uuid.UUID,
    *,
    limit: int = 1000,
    max_attempts: int = 5,
    wait_for_lock: bool = False,
    now: datetime | None = None,
) -> ProcessStats:
    """Apply pending events of one restaurant in order (caller commits)."""
    now = now or datetime.now(UTC)
    stats = ProcessStats()
    session.flush()  # make pending changes of this transaction visible to the claim query
    lock_key = func.hashtextextended(str(restaurant_id), 0)
    if wait_for_lock:
        session.execute(select(func.pg_advisory_xact_lock(lock_key)))
    elif not session.execute(select(func.pg_try_advisory_xact_lock(lock_key))).scalar_one():
        stats.skipped_locked = True
        return stats
    events = session.scalars(
        select(Event)
        .where(Event.restaurant_id == restaurant_id, Event.status == "pending", Event.next_attempt_at <= now)
        .order_by(Event.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    projector = SqlProjector(session, restaurant_id)
    for ev in events:
        savepoint = session.begin_nested()
        try:
            result = projector.apply(ev)
            savepoint.commit()
        except RetryableError as exc:
            savepoint.rollback()
            _schedule_retry(ev, str(exc), now, max_attempts, stats)
            continue
        except Exception as exc:
            savepoint.rollback()
            _schedule_retry(ev, f"{type(exc).__name__}: {str(exc)[:300]}", now, max_attempts, stats)
            continue
        ev.status = "rejected" if result.outcome is ApplyOutcome.INVALID else "processed"
        ev.outcome = (result.outcome.value + (f":{result.detail}" if result.detail else ""))[:80]
        ev.processed_at = now
        ev.attempts += 1
        stats.outcomes[result.outcome.value] = stats.outcomes.get(result.outcome.value, 0) + 1
        if ev.status == "rejected":
            stats.rejected += 1
        else:
            stats.processed += 1
        if ev.tick is not None:
            stats.last_tick = ev.tick
    session.flush()
    return stats


def _schedule_retry(ev: Event, error: str, now: datetime, max_attempts: int, stats: ProcessStats) -> None:
    ev.attempts += 1
    ev.last_error = error[:500]
    if ev.attempts >= max_attempts:
        ev.status = "dead_letter"
        stats.dead_lettered += 1
    else:
        ev.next_attempt_at = now + _backoff(ev.attempts)
        stats.retried += 1


def requeue_dead_letter(session: Session, restaurant_id: uuid.UUID, event_id: int) -> Event | None:
    ev = session.scalars(
        select(Event).where(Event.restaurant_id == restaurant_id, Event.id == event_id).with_for_update()
    ).one_or_none()
    if ev is None or ev.status != "dead_letter":
        return ev
    ev.status, ev.attempts, ev.next_attempt_at, ev.last_error = "pending", 0, datetime.now(UTC), None
    session.flush()
    return ev
