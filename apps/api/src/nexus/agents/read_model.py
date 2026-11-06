"""Read-only data access port used by agent tools.

Tools depend on this protocol, not on SQL. Production uses the SQLAlchemy
implementation (``nexus.infra.read_model``); unit tests and offline evaluations
use :class:`ProjectionReadModel`, built on the reference in-memory projection.
Every method receives the tenant (``restaurant_id``) from the *server-side* run
context — model-supplied arguments can never change it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel

from nexus.domain.catalog import RestaurantTemplate
from nexus.domain.forecasting import ForecastResult, forecast
from nexus.domain.metrics import IngredientRisk, KitchenSnapshot, ingredient_risks, kitchen_snapshot
from nexus.domain.policies import AffectedItem, estimated_service_minutes
from nexus.domain.projection import RestaurantProjection


class DelayedOrder(BaseModel):
    order_ref: str
    channel: str
    age_minutes: float
    items_count: int
    customer_note: str | None = None


class IngredientDetails(BaseModel):
    ingredient_key: str
    name: str
    unit: str
    pack_size: float
    lead_time_minutes: int
    unit_cost_cents: int
    safety_stock: float
    open_po_qty: float
    affected_items: list[AffectedItem]


class KitchenCapacity(BaseModel):
    lines_total: int
    lines_available: int
    estimated_service_minutes: float
    sla_minutes: int


class ReadModel(Protocol):
    def kitchen_snapshot(self, restaurant_id: UUID, *, as_of: datetime, window_minutes: int) -> KitchenSnapshot: ...

    def delayed_orders(
        self, restaurant_id: UUID, *, as_of: datetime, min_age_minutes: int, limit: int
    ) -> list[DelayedOrder]: ...

    def kitchen_capacity(self, restaurant_id: UUID) -> KitchenCapacity: ...

    def inventory_risks(
        self, restaurant_id: UUID, *, as_of: datetime, window_minutes: int, horizon_minutes: int
    ) -> list[IngredientRisk]: ...

    def ingredient_details(self, restaurant_id: UUID, ingredient_key: str) -> IngredientDetails | None: ...

    def demand_forecast(
        self,
        restaurant_id: UUID,
        *,
        as_of: datetime,
        horizon_minutes: int,
        ingredient_keys: Sequence[str] | None,
    ) -> ForecastResult: ...


class ProjectionReadModel:
    """In-memory implementation backed by :class:`RestaurantProjection`."""

    def __init__(
        self,
        *,
        restaurant_id: UUID,
        template: RestaurantTemplate,
        projection: RestaurantProjection,
        sim_start: datetime,
        open_po_qty: dict[str, float] | None = None,
    ) -> None:
        self.restaurant_id = restaurant_id
        self.template = template
        self.projection = projection
        self.sim_start = sim_start
        self.open_po_qty = open_po_qty or {}

    def _check(self, restaurant_id: UUID) -> None:
        if restaurant_id != self.restaurant_id:
            raise PermissionError("cross-tenant access attempted")

    def kitchen_snapshot(self, restaurant_id: UUID, *, as_of: datetime, window_minutes: int) -> KitchenSnapshot:
        self._check(restaurant_id)
        return kitchen_snapshot(
            self.projection.order_rows(),
            as_of=as_of,
            window_minutes=window_minutes,
            sla_minutes=self.template.prep_sla_minutes,
        )

    def delayed_orders(
        self, restaurant_id: UUID, *, as_of: datetime, min_age_minutes: int, limit: int
    ) -> list[DelayedOrder]:
        self._check(restaurant_id)
        rows = []
        for o in self.projection.orders.values():
            if o.status != "received" or o.created_at > as_of or (o.ready_at and o.ready_at <= as_of):
                continue
            age = (as_of - o.created_at).total_seconds() / 60
            if age >= min_age_minutes:
                rows.append(
                    DelayedOrder(
                        order_ref=o.order_ref,
                        channel=o.channel,
                        age_minutes=round(age, 1),
                        items_count=sum(q for _, q in o.items),
                        customer_note=o.customer_note,
                    )
                )
        rows.sort(key=lambda r: -r.age_minutes)
        return rows[:limit]

    def kitchen_capacity(self, restaurant_id: UUID) -> KitchenCapacity:
        self._check(restaurant_id)
        return KitchenCapacity(
            lines_total=self.template.kitchen_lines,
            lines_available=self.projection.lines_available,
            estimated_service_minutes=estimated_service_minutes(self.template),
            sla_minutes=self.template.prep_sla_minutes,
        )

    def inventory_risks(
        self, restaurant_id: UUID, *, as_of: datetime, window_minutes: int, horizon_minutes: int
    ) -> list[IngredientRisk]:
        self._check(restaurant_id)
        meta = {i.key: (i.name, i.unit, i.safety_stock) for i in self.template.ingredients}
        consumed = self.projection.consumed_between(as_of - timedelta(minutes=window_minutes), as_of)
        return ingredient_risks(
            stock=dict(self.projection.stock),
            meta=meta,
            consumed_in_window=consumed,
            window_minutes=window_minutes,
            horizon_minutes=horizon_minutes,
        )

    def ingredient_details(self, restaurant_id: UUID, ingredient_key: str) -> IngredientDetails | None:
        self._check(restaurant_id)
        try:
            ing = self.template.ingredient(ingredient_key)
        except KeyError:
            return None
        affected = [
            AffectedItem(
                item_key=m.key,
                name=m.name,
                price_cents=m.price_cents,
                usage_per_unit=m.recipe[ingredient_key],
                available=self.projection.available.get(m.key, True),
            )
            for m in self.template.menu_items
            if ingredient_key in m.recipe
        ]
        return IngredientDetails(
            ingredient_key=ing.key,
            name=ing.name,
            unit=ing.unit,
            pack_size=ing.pack_size,
            lead_time_minutes=ing.lead_time_minutes,
            unit_cost_cents=ing.unit_cost_cents,
            safety_stock=ing.safety_stock,
            open_po_qty=self.open_po_qty.get(ing.key, 0.0),
            affected_items=affected,
        )

    def demand_forecast(
        self,
        restaurant_id: UUID,
        *,
        as_of: datetime,
        horizon_minutes: int,
        ingredient_keys: Sequence[str] | None,
    ) -> ForecastResult:
        self._check(restaurant_id)
        window_start = max(self.sim_start, as_of - timedelta(minutes=30))
        observed = sum(1 for o in self.projection.orders.values() if window_start <= o.created_at <= as_of)
        return forecast(
            self.template,
            as_of=as_of,
            horizon_minutes=horizon_minutes,
            observed_orders_in_window=observed,
            window_start=window_start,
            available_items=dict(self.projection.available),
            ingredient_keys=list(ingredient_keys) if ingredient_keys else None,
        )
