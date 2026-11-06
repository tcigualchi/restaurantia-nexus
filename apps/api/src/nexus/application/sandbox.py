"""Create restaurants from synthetic templates and reset them deterministically."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from nexus.domain.catalog import Catalog, RestaurantTemplate
from nexus.infra.models import (
    AgentRun,
    ApprovalRequest,
    Event,
    Incident,
    Ingredient,
    MenuItem,
    Order,
    PurchaseOrder,
    RecipeLine,
    Restaurant,
    SimulationRun,
    StockMovement,
)


def create_restaurant_from_template(
    session: Session,
    template: RestaurantTemplate,
    *,
    name: str | None = None,
    is_demo: bool = False,
    demo_session_id: uuid.UUID | None = None,
) -> Restaurant:
    restaurant = Restaurant(
        name=name or template.name,
        template_key=template.key,
        timezone=template.timezone,
        kitchen_lines=template.kitchen_lines,
        kitchen_lines_available=template.kitchen_lines,
        prep_sla_minutes=template.prep_sla_minutes,
        is_demo=is_demo,
        demo_session_id=demo_session_id,
    )
    session.add(restaurant)
    session.flush()
    ingredients: dict[str, Ingredient] = {}
    for ing in template.ingredients:
        row = Ingredient(
            restaurant_id=restaurant.id,
            key=ing.key,
            name=ing.name,
            unit=ing.unit,
            stock=Decimal(str(ing.stock)),
            safety_stock=Decimal(str(ing.safety_stock)),
            unit_cost_cents=ing.unit_cost_cents,
            pack_size=Decimal(str(ing.pack_size)),
            lead_time_minutes=ing.lead_time_minutes,
        )
        session.add(row)
        ingredients[ing.key] = row
    session.flush()
    for item in template.menu_items:
        menu_item = MenuItem(
            restaurant_id=restaurant.id,
            key=item.key,
            name=item.name,
            category=item.category,
            course=item.course,
            price_cents=item.price_cents,
            prep_minutes=Decimal(str(item.prep_minutes)),
            popularity=Decimal(str(item.popularity)),
            is_available=True,
        )
        session.add(menu_item)
        session.flush()
        for ing_key, qty in item.recipe.items():
            session.add(
                RecipeLine(
                    menu_item_id=menu_item.id,
                    ingredient_id=ingredients[ing_key].id,
                    restaurant_id=restaurant.id,
                    qty_per_unit=Decimal(str(qty)),
                )
            )
    session.flush()
    return restaurant


@dataclass(frozen=True)
class ResetSummary:
    events: int
    orders: int
    incidents: int
    agent_runs: int
    approvals: int
    purchase_orders: int


def reset_operational_state(
    session: Session, restaurant: Restaurant, template: RestaurantTemplate, *, scenario_stock_override: str | None
) -> ResetSummary:
    """Delete operational data and restore catalog state. Audit logs are kept (append-only)."""
    rid = restaurant.id

    def _count_delete(model: type) -> int:
        result = session.execute(delete(model).where(model.restaurant_id == rid))  # type: ignore[attr-defined]
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    purchase_orders = _count_delete(PurchaseOrder)
    approvals = _count_delete(ApprovalRequest)
    agent_runs = _count_delete(AgentRun)
    incidents = _count_delete(Incident)
    _count_delete(StockMovement)
    orders = _count_delete(Order)
    events = _count_delete(Event)
    session.execute(
        update(SimulationRun)
        .where(SimulationRun.restaurant_id == rid, SimulationRun.status.in_(("running", "paused")))
        .values(status="cancelled", completed_at=datetime.now(UTC), pause_reason=None)
    )
    stock = template.initial_stock(scenario_stock_override)
    for ing in session.scalars(select(Ingredient).where(Ingredient.restaurant_id == rid)):
        ing.stock = Decimal(str(stock.get(ing.key, 0.0)))
        ing.updated_at = datetime.now(UTC)
    session.execute(
        update(MenuItem).where(MenuItem.restaurant_id == rid).values(is_available=True, unavailable_reason=None)
    )
    restaurant.kitchen_lines_available = restaurant.kitchen_lines
    session.flush()
    return ResetSummary(events, orders, incidents, agent_runs, approvals, purchase_orders)


def template_for(catalog: Catalog, restaurant: Restaurant) -> RestaurantTemplate:
    return catalog.get(restaurant.template_key)
