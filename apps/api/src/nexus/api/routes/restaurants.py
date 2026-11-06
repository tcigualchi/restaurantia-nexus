"""Tenant-scoped read endpoints plus menu availability and event ingestion."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from nexus.api.deps import CatalogDep, DbDep, SettingsDep, TenantDep, UserDep, request_id
from nexus.application import queries
from nexus.application.audit import record_audit
from nexus.application.clock import business_now
from nexus.application.events import ingest_event, process_pending_events, requeue_dead_letter
from nexus.application.views import (
    AuditView,
    EventView,
    IncidentView,
    InventoryView,
    MenuItemView,
    OrderView,
    Overview,
    Page,
    RestaurantView,
    Timeseries,
)
from nexus.domain.errors import Conflict, NotFound, ValidationFailed
from nexus.domain.events import EventIn, is_reserved_external_ref, payload_dict
from nexus.domain.forecasting import ForecastResult, hourly_orders_series
from nexus.domain.rbac import Permission
from nexus.infra.models import Membership, MenuItem, Restaurant
from nexus.infra.read_model import SqlReadModel, bound

router = APIRouter(prefix="/api/v1/restaurants", tags=["restaurants"])


@router.get("", response_model=list[RestaurantView], summary="Restaurants the caller can access")
def list_restaurants(user: UserDep, db: DbDep) -> list[RestaurantView]:
    rows = db.execute(
        select(Restaurant, Membership.role)
        .join(Membership, Membership.restaurant_id == Restaurant.id)
        .where(Membership.user_id == user.id)
        .order_by(Restaurant.name)
    ).all()
    return [queries.restaurant_view(r, role) for r, role in rows]


@router.get("/{restaurant_id}", response_model=RestaurantView)
def get_restaurant(ctx: TenantDep) -> RestaurantView:
    return queries.restaurant_view(ctx.restaurant, ctx.role.value)


@router.get("/{restaurant_id}/overview", response_model=Overview, summary="Overview KPIs (Visão geral)")
def overview(ctx: TenantDep, db: DbDep, catalog: CatalogDep) -> Overview:
    return queries.overview(db, catalog, ctx.restaurant, ctx.role.value)


@router.get("/{restaurant_id}/timeseries", response_model=Timeseries)
def timeseries(
    ctx: TenantDep,
    db: DbDep,
    catalog: CatalogDep,
    bucket_minutes: Annotated[int, Query(ge=1, le=60)] = 5,
    ingredients: Annotated[list[str] | None, Query(max_length=5)] = None,
) -> Timeseries:
    keys = ingredients or queries.default_chart_ingredients(db, catalog, ctx.restaurant_id)
    return queries.timeseries(db, catalog, ctx.restaurant, bucket_minutes=bucket_minutes, ingredient_keys=keys)


@router.get("/{restaurant_id}/orders", response_model=Page[OrderView])
def orders(
    ctx: TenantDep,
    db: DbDep,
    status: Literal["received", "ready", "rejected", "cancelled"] | None = None,
    channel: Literal["app_delivery", "dine_in", "takeout"] | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> Page[OrderView]:
    try:
        return queries.list_orders(db, ctx.restaurant_id, status=status, channel=channel, limit=limit, cursor=cursor)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationFailed("Cursor inválido.", code="invalid_cursor") from exc


@router.get("/{restaurant_id}/inventory", response_model=InventoryView)
def inventory(ctx: TenantDep, db: DbDep, catalog: CatalogDep) -> InventoryView:
    return queries.inventory(db, catalog, ctx.restaurant)


class AvailabilityIn(BaseModel):
    available: bool
    reason: str | None = Field(default=None, max_length=200)


@router.post(
    "/{restaurant_id}/menu-items/{item_key}/availability",
    response_model=MenuItemView,
    summary="Manually pause or resume a menu item (manager; audited)",
)
def set_availability(item_key: str, body: AvailabilityIn, ctx: TenantDep, db: DbDep) -> MenuItemView:
    ctx.require(Permission.MENU_UPDATE)
    item = db.scalars(
        select(MenuItem).where(MenuItem.restaurant_id == ctx.restaurant_id, MenuItem.key == item_key).with_for_update()
    ).one_or_none()
    if item is None:
        raise NotFound("Item não encontrado.")
    if not body.available and not (body.reason and len(body.reason.strip()) >= 3):
        raise ValidationFailed("Informe o motivo da pausa.", code="reason_required")
    item.is_available = body.available
    item.unavailable_reason = None if body.available else body.reason
    record_audit(
        db,
        restaurant_id=ctx.restaurant_id,
        actor=ctx.actor,
        action="menu_item.resumed" if body.available else "menu_item.paused",
        target_type="menu_item",
        target_id=item.id,
        details={"item_key": item.key, "name": item.name, "reason": body.reason, "manual": True},
        business_time=business_now(db, ctx.restaurant_id),
        request_id=request_id(),
    )
    db.flush()
    return MenuItemView(
        id=item.id,
        key=item.key,
        name=item.name,
        category=item.category,
        course=item.course,
        price_cents=item.price_cents,
        is_available=item.is_available,
        unavailable_reason=item.unavailable_reason,
        recipe={},
    )


class IngestOut(BaseModel):
    event_id: int
    created: bool
    status: str
    outcome: str | None


@router.post(
    "/{restaurant_id}/events",
    response_model=IngestOut,
    status_code=202,
    summary="Ingest an external event (idempotent by idempotency_key)",
)
def ingest(body: EventIn, ctx: TenantDep, db: DbDep, settings: SettingsDep) -> IngestOut:
    ctx.require(Permission.EVENTS_INGEST)
    order_ref = getattr(body.payload, "order_ref", None)
    if order_ref and is_reserved_external_ref(order_ref):
        raise ValidationFailed("Prefixo SIM- é reservado ao simulador.", code="reserved_ref")
    result = ingest_event(
        db,
        restaurant_id=ctx.restaurant_id,
        event_type=body.payload.type,
        payload=payload_dict(body.payload),
        idempotency_key=body.idempotency_key,
        occurred_at=body.occurred_at,
        source="api",
    )
    if result.created:
        process_pending_events(db, ctx.restaurant_id, max_attempts=settings.event_max_attempts)
        record_audit(
            db,
            restaurant_id=ctx.restaurant_id,
            actor=ctx.actor,
            action="event.ingested",
            target_type="event",
            target_id=str(result.event_id),
            details={"type": body.payload.type, "idempotency_key": body.idempotency_key},
            request_id=request_id(),
        )
    db.flush()
    ev = queries.list_events(
        db, ctx.restaurant_id, event_type=None, status=None, after_id=result.event_id - 1, before_id=None, limit=1
    )
    status, outcome = (ev[0].status, ev[0].outcome) if ev else ("pending", None)
    return IngestOut(event_id=result.event_id, created=result.created, status=status, outcome=outcome)


@router.get("/{restaurant_id}/events", response_model=list[EventView])
def events(
    ctx: TenantDep,
    db: DbDep,
    type: Annotated[str | None, Query(max_length=40)] = None,
    status: Literal["pending", "processed", "rejected", "dead_letter"] | None = None,
    after_id: int | None = None,
    before_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[EventView]:
    return queries.list_events(
        db, ctx.restaurant_id, event_type=type, status=status, after_id=after_id, before_id=before_id, limit=limit
    )


@router.post(
    "/{restaurant_id}/events/{event_id}/requeue",
    response_model=EventView,
    summary="Re-queue a dead-lettered event (manager)",
)
def requeue(event_id: int, ctx: TenantDep, db: DbDep) -> EventView:
    ctx.require(Permission.APPROVALS_DECIDE)
    ev = requeue_dead_letter(db, ctx.restaurant_id, event_id)
    if ev is None:
        raise NotFound("Evento não encontrado.")
    if ev.status != "pending":
        raise Conflict("Somente eventos em dead-letter podem ser reprocessados.", code="not_dead_letter")
    record_audit(
        db,
        restaurant_id=ctx.restaurant_id,
        actor=ctx.actor,
        action="event.requeued",
        target_type="event",
        target_id=str(ev.id),
        request_id=request_id(),
    )
    db.flush()
    return queries._event_view(ev)


@router.get("/{restaurant_id}/incidents", response_model=list[IncidentView])
def incidents(ctx: TenantDep, db: DbDep) -> list[IncidentView]:
    return queries.list_incidents(db, ctx.restaurant_id)


class ForecastOut(BaseModel):
    forecast: ForecastResult
    history: list[dict[str, object]]
    data_label: str


@router.get("/{restaurant_id}/forecast", response_model=ForecastOut, summary="Demand forecast, backtest and history")
def forecast_view(
    ctx: TenantDep,
    db: DbDep,
    catalog: CatalogDep,
    horizon_minutes: Annotated[int, Query(ge=30, le=360)] = 120,
) -> ForecastOut:
    as_of = business_now(db, ctx.restaurant_id)
    result = SqlReadModel(bound(db), catalog).demand_forecast(
        ctx.restaurant_id, as_of=as_of, horizon_minutes=horizon_minutes, ingredient_keys=None
    )
    template = catalog.get(ctx.restaurant.template_key)
    history = [h for h in hourly_orders_series(template, days=14)]
    return ForecastOut(
        forecast=result,
        history=history,
        data_label="Histórico de vendas sintético, gerado de forma determinística a partir do perfil do restaurante.",
    )


@router.get("/{restaurant_id}/audit", response_model=list[AuditView])
def audit(
    ctx: TenantDep,
    db: DbDep,
    action: Annotated[str | None, Query(max_length=60)] = None,
    actor_type: Literal["user", "agent", "system"] | None = None,
    before_id: int | None = None,
    after_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditView]:
    return queries.list_audit(
        db, ctx.restaurant_id, action=action, actor_type=actor_type, before_id=before_id, after_id=after_id, limit=limit
    )
