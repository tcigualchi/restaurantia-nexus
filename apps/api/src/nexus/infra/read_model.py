"""SQL implementation of the agent ``ReadModel`` and shared read helpers.

Rows are fetched with explicit tenant filters; numbers are computed by the pure
functions in ``nexus.domain.metrics`` so API, detectors and agents agree.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager, nullcontext
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from nexus.agents.read_model import DelayedOrder, IngredientDetails, KitchenCapacity
from nexus.domain.catalog import Catalog
from nexus.domain.forecasting import ForecastResult, forecast
from nexus.domain.metrics import IngredientRisk, KitchenSnapshot, OrderRow, ingredient_risks, kitchen_snapshot
from nexus.domain.policies import AffectedItem, estimated_service_minutes
from nexus.infra.models import (
    Ingredient,
    MenuItem,
    Order,
    PurchaseOrder,
    RecipeLine,
    Restaurant,
    SimulationRun,
    StockMovement,
)

SessionProvider = Callable[[], AbstractContextManager[Session]]


def bound(session: Session) -> SessionProvider:
    """Use an existing session (sees uncommitted work of the current transaction)."""
    return lambda: nullcontext(session)


def from_factory(factory: sessionmaker[Session]) -> SessionProvider:
    @contextmanager
    def _scope() -> Iterator[Session]:
        with factory() as s:
            yield s
            s.rollback()  # read-only

    return _scope


def stock_as_of(session: Session, restaurant_id: uuid.UUID, as_of: datetime) -> dict[uuid.UUID, float]:
    """Current stock minus movements that happened after ``as_of`` (business time)."""
    current = {
        i.id: float(i.stock)
        for i in session.scalars(select(Ingredient).where(Ingredient.restaurant_id == restaurant_id))
    }
    later = session.execute(
        select(StockMovement.ingredient_id, func.sum(StockMovement.delta))
        .where(StockMovement.restaurant_id == restaurant_id, StockMovement.occurred_at > as_of)
        .group_by(StockMovement.ingredient_id)
    ).all()
    for ing_id, delta in later:
        current[ing_id] = current.get(ing_id, 0.0) - float(delta or 0)
    return current


def consumption_between(
    session: Session, restaurant_id: uuid.UUID, start: datetime, end: datetime
) -> dict[uuid.UUID, float]:
    rows = session.execute(
        select(StockMovement.ingredient_id, func.sum(StockMovement.delta))
        .where(
            StockMovement.restaurant_id == restaurant_id,
            StockMovement.reason == "order_consumption",
            StockMovement.occurred_at > start,
            StockMovement.occurred_at <= end,
        )
        .group_by(StockMovement.ingredient_id)
    ).all()
    return {ing_id: -float(total or 0) for ing_id, total in rows}


def order_rows(session: Session, restaurant_id: uuid.UUID, *, as_of: datetime, window_minutes: int) -> list[OrderRow]:
    start = as_of - timedelta(minutes=window_minutes)
    rows = session.execute(
        select(Order.order_ref, Order.status, Order.created_at, Order.ready_at, Order.total_cents, Order.channel).where(
            Order.restaurant_id == restaurant_id,
            Order.created_at <= as_of,
            or_(Order.created_at >= start, Order.status == "received", Order.ready_at >= start),
        )
    ).all()
    return [OrderRow(*r) for r in rows]


def latest_simulation(session: Session, restaurant_id: uuid.UUID) -> SimulationRun | None:
    return session.scalars(
        select(SimulationRun)
        .where(SimulationRun.restaurant_id == restaurant_id)
        .order_by(SimulationRun.created_at.desc())
        .limit(1)
    ).first()


class SqlReadModel:
    def __init__(self, sessions: SessionProvider, catalog: Catalog):
        self.sessions = sessions
        self.catalog = catalog

    def _restaurant(self, s: Session, restaurant_id: uuid.UUID) -> Restaurant:
        restaurant = s.get(Restaurant, restaurant_id)
        if restaurant is None:
            raise LookupError("restaurante não encontrado")
        return restaurant

    def kitchen_snapshot(self, restaurant_id: uuid.UUID, *, as_of: datetime, window_minutes: int) -> KitchenSnapshot:
        with self.sessions() as s:
            restaurant = self._restaurant(s, restaurant_id)
            rows = order_rows(s, restaurant_id, as_of=as_of, window_minutes=window_minutes)
            return kitchen_snapshot(
                rows, as_of=as_of, window_minutes=window_minutes, sla_minutes=restaurant.prep_sla_minutes
            )

    def delayed_orders(
        self, restaurant_id: uuid.UUID, *, as_of: datetime, min_age_minutes: int, limit: int
    ) -> list[DelayedOrder]:
        with self.sessions() as s:
            q = (
                select(Order)
                .where(
                    Order.restaurant_id == restaurant_id,
                    Order.created_at <= as_of - timedelta(minutes=min_age_minutes),
                    or_(Order.status == "received", (Order.status == "ready") & (Order.ready_at > as_of)),
                )
                .order_by(Order.created_at.asc())
                .limit(limit)
            )
            out = []
            for o in s.scalars(q):
                out.append(
                    DelayedOrder(
                        order_ref=o.order_ref,
                        channel=o.channel,
                        age_minutes=round((as_of - o.created_at).total_seconds() / 60, 1),
                        items_count=sum(i.qty for i in o.items),
                        customer_note=o.customer_note,
                    )
                )
            return out

    def kitchen_capacity(self, restaurant_id: uuid.UUID) -> KitchenCapacity:
        with self.sessions() as s:
            r = self._restaurant(s, restaurant_id)
            template = self.catalog.get(r.template_key)
            return KitchenCapacity(
                lines_total=r.kitchen_lines,
                lines_available=r.kitchen_lines_available,
                estimated_service_minutes=estimated_service_minutes(template),
                sla_minutes=r.prep_sla_minutes,
            )

    def inventory_risks(
        self, restaurant_id: uuid.UUID, *, as_of: datetime, window_minutes: int, horizon_minutes: int
    ) -> list[IngredientRisk]:
        with self.sessions() as s:
            ingredients = list(s.scalars(select(Ingredient).where(Ingredient.restaurant_id == restaurant_id)))
            stock = stock_as_of(s, restaurant_id, as_of)
            consumed = consumption_between(s, restaurant_id, as_of - timedelta(minutes=window_minutes), as_of)
            by_id = {i.id: i for i in ingredients}
            return ingredient_risks(
                stock={by_id[k].key: max(0.0, v) for k, v in stock.items() if k in by_id},
                meta={i.key: (i.name, i.unit, float(i.safety_stock)) for i in ingredients},
                consumed_in_window={by_id[k].key: v for k, v in consumed.items() if k in by_id},
                window_minutes=window_minutes,
                horizon_minutes=horizon_minutes,
            )

    def ingredient_details(self, restaurant_id: uuid.UUID, ingredient_key: str) -> IngredientDetails | None:
        with self.sessions() as s:
            ing = s.scalars(
                select(Ingredient).where(Ingredient.restaurant_id == restaurant_id, Ingredient.key == ingredient_key)
            ).one_or_none()
            if ing is None:
                return None
            rows = s.execute(
                select(MenuItem, RecipeLine.qty_per_unit)
                .join(RecipeLine, RecipeLine.menu_item_id == MenuItem.id)
                .where(RecipeLine.restaurant_id == restaurant_id, RecipeLine.ingredient_id == ing.id)
                .order_by(MenuItem.name)
            ).all()
            open_po = s.scalar(
                select(func.coalesce(func.sum(PurchaseOrder.quantity), 0)).where(
                    PurchaseOrder.restaurant_id == restaurant_id,
                    PurchaseOrder.ingredient_id == ing.id,
                    PurchaseOrder.status == "ordered",
                )
            )
            return IngredientDetails(
                ingredient_key=ing.key,
                name=ing.name,
                unit=ing.unit,
                pack_size=float(ing.pack_size),
                lead_time_minutes=ing.lead_time_minutes,
                unit_cost_cents=ing.unit_cost_cents,
                safety_stock=float(ing.safety_stock),
                open_po_qty=float(open_po or 0),
                affected_items=[
                    AffectedItem(
                        item_key=m.key,
                        name=m.name,
                        price_cents=m.price_cents,
                        usage_per_unit=float(q),
                        available=m.is_available,
                    )
                    for m, q in rows
                ],
            )

    def demand_forecast(
        self, restaurant_id: uuid.UUID, *, as_of: datetime, horizon_minutes: int, ingredient_keys: Sequence[str] | None
    ) -> ForecastResult:
        with self.sessions() as s:
            r = self._restaurant(s, restaurant_id)
            template = self.catalog.get(r.template_key)
            sim = latest_simulation(s, restaurant_id)
            window_start = as_of - timedelta(minutes=30)
            if sim is not None and sim.sim_start > window_start:
                window_start = sim.sim_start
            observed = (
                s.scalar(
                    select(func.count())
                    .select_from(Order)
                    .where(
                        Order.restaurant_id == restaurant_id,
                        Order.created_at >= window_start,
                        Order.created_at <= as_of,
                    )
                )
                or 0
            )
            available = {
                m.key: m.is_available
                for m in s.scalars(select(MenuItem).where(MenuItem.restaurant_id == restaurant_id))
            }
            return forecast(
                template,
                as_of=as_of,
                horizon_minutes=horizon_minutes,
                observed_orders_in_window=int(observed),
                window_start=window_start,
                available_items=available,
                ingredient_keys=list(ingredient_keys) if ingredient_keys else None,
            )
