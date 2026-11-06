"""Read-side queries for the API. Every query is scoped by ``restaurant_id``."""

from __future__ import annotations

import base64
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from nexus.application.clock import business_now
from nexus.application.views import (
    AgentRunBrief,
    AgentRunDetail,
    ApprovalView,
    AuditView,
    EventView,
    IncidentView,
    IngredientView,
    InventoryView,
    Kpis,
    MenuItemView,
    OrderItemView,
    OrderView,
    Overview,
    Page,
    PurchaseOrderView,
    RestaurantView,
    SimulationView,
    StepView,
    Timeseries,
    TimeseriesPoint,
)
from nexus.domain.catalog import Catalog
from nexus.domain.metrics import kitchen_snapshot
from nexus.domain.rbac import Permission, Role, has_permission, permissions_for
from nexus.domain.simulation import SCENARIOS, minutes_to_datetime
from nexus.infra.models import (
    AgentRun,
    AgentStep,
    ApprovalRequest,
    AuditLog,
    Event,
    Incident,
    Ingredient,
    MenuItem,
    Order,
    PurchaseOrder,
    RecipeLine,
    Restaurant,
    StockMovement,
    User,
)
from nexus.infra.read_model import SqlReadModel, bound, latest_simulation, order_rows

DATA_LABEL = "Dados sintéticos gerados por simulação, sem integração com plataformas reais."


def restaurant_view(r: Restaurant, role: str) -> RestaurantView:
    return RestaurantView(
        id=r.id,
        name=r.name,
        template_key=r.template_key,
        timezone=r.timezone,
        kitchen_lines=r.kitchen_lines,
        kitchen_lines_available=r.kitchen_lines_available,
        prep_sla_minutes=r.prep_sla_minutes,
        is_demo=r.is_demo,
        role=role,
        permissions=permissions_for(role),
    )


def simulation_view(s: Session, restaurant_id: uuid.UUID) -> SimulationView | None:
    sim = latest_simulation(s, restaurant_id)
    if sim is None:
        return None
    scenario = SCENARIOS.get(sim.scenario_key)
    return SimulationView(
        id=sim.id,
        scenario_key=sim.scenario_key,
        scenario_name=scenario.name if scenario else sim.scenario_key,
        seed=sim.seed,
        status=sim.status,
        pause_reason=sim.pause_reason,
        current_tick=sim.current_tick,
        total_ticks=sim.total_ticks,
        tick_interval_ms=sim.tick_interval_ms,
        auto_pause_on_approval=sim.auto_pause_on_approval,
        sim_start=sim.sim_start,
        business_time=minutes_to_datetime(sim.sim_start, sim.current_tick),
        created_at=sim.created_at,
    )


def _run_brief(s: Session, run: AgentRun) -> AgentRunBrief:
    incident_title = s.scalar(select(Incident.title).where(Incident.id == run.incident_id)) if run.incident_id else None
    steps = s.scalar(select(func.count()).select_from(AgentStep).where(AgentStep.run_id == run.id)) or 0
    approvals = s.scalar(select(func.count()).select_from(ApprovalRequest).where(ApprovalRequest.run_id == run.id)) or 0
    return AgentRunBrief(
        id=run.id,
        status=run.status,
        mode=run.mode,
        provider=run.provider,
        model=run.model,
        trigger=run.trigger,
        incident_title=incident_title,
        summary=run.summary,
        as_of=run.as_of,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
        estimated_cost_usd=float(run.estimated_cost_usd) if run.estimated_cost_usd is not None else None,
        steps=int(steps),
        approvals=int(approvals),
        error=run.error,
    )


def overview(s: Session, catalog: Catalog, restaurant: Restaurant, role: str) -> Overview:
    rid = restaurant.id
    now = business_now(s, rid)
    sim = simulation_view(s, rid)
    rows = order_rows(s, rid, as_of=now, window_minutes=60)
    snap = kitchen_snapshot(rows, as_of=now, window_minutes=60, sla_minutes=restaurant.prep_sla_minutes)
    totals = s.execute(
        select(Order.status, func.count(), func.coalesce(func.sum(Order.total_cents), 0))
        .where(Order.restaurant_id == rid)
        .group_by(Order.status)
    ).all()
    lost_n = sum(int(n) for st, n, _ in totals if st == "rejected")
    lost_v = sum(int(v) for st, _, v in totals if st == "rejected")
    risks = SqlReadModel(bound(s), catalog).inventory_risks(rid, as_of=now, window_minutes=15, horizon_minutes=120)
    at_risk = [r for r in risks if r.risk in ("high", "critical", "out")]
    latest = s.scalars(
        select(AgentRun).where(AgentRun.restaurant_id == rid).order_by(AgentRun.created_at.desc()).limit(1)
    ).first()
    kpis = Kpis(
        orders_last_60=snap.orders_created + snap.orders_rejected,
        revenue_last_60_cents=snap.revenue_cents,
        queue_length=snap.queue_length,
        oldest_open_minutes=snap.oldest_open_minutes,
        avg_prep_minutes=snap.avg_prep_minutes,
        p90_prep_minutes=snap.p90_prep_minutes,
        sla_minutes=restaurant.prep_sla_minutes,
        sla_breach_rate=snap.sla_breach_rate,
        lost_orders_total=lost_n,
        lost_revenue_total_cents=lost_v,
        orders_total=sum(int(n) for _, n, _ in totals),
        revenue_total_cents=sum(int(v) for st, _, v in totals if st != "rejected"),
        kitchen_lines=restaurant.kitchen_lines,
        kitchen_lines_available=restaurant.kitchen_lines_available,
        open_incidents=int(
            s.scalar(
                select(func.count())
                .select_from(Incident)
                .where(Incident.restaurant_id == rid, Incident.status != "resolved")
            )
            or 0
        ),
        pending_approvals=int(
            s.scalar(
                select(func.count())
                .select_from(ApprovalRequest)
                .where(ApprovalRequest.restaurant_id == rid, ApprovalRequest.status == "pending")
            )
            or 0
        ),
        ingredients_at_risk=len(at_risk),
    )
    return Overview(
        restaurant=restaurant_view(restaurant, role),
        business_time=now,
        clock_mode="simulation" if sim else "live",
        data_label=DATA_LABEL,
        simulation=sim,
        kpis=kpis,
        ingredients_at_risk=at_risk[:6],
        latest_agent_run=_run_brief(s, latest) if latest else None,
    )


def timeseries(
    s: Session, catalog: Catalog, restaurant: Restaurant, *, bucket_minutes: int, ingredient_keys: list[str]
) -> Timeseries:
    rid = restaurant.id
    end = business_now(s, rid)
    sim = latest_simulation(s, rid)
    start = sim.sim_start if sim else end - timedelta(hours=2)
    if end <= start:
        end = start + timedelta(minutes=bucket_minutes)
    orders = s.execute(
        select(Order.status, Order.created_at, Order.ready_at).where(
            Order.restaurant_id == rid, Order.created_at >= start, Order.created_at <= end
        )
    ).all()
    ingredients = list(
        s.scalars(select(Ingredient).where(Ingredient.restaurant_id == rid, Ingredient.key.in_(ingredient_keys)))
    )
    movements: list[Any] = []
    if ingredients:
        movements = list(
            s.execute(
                select(StockMovement.ingredient_id, StockMovement.delta, StockMovement.occurred_at).where(
                    StockMovement.restaurant_id == rid, StockMovement.ingredient_id.in_([i.id for i in ingredients])
                )
            ).all()
        )
    points: list[TimeseriesPoint] = []
    t = start + timedelta(minutes=bucket_minutes)
    while t <= end + timedelta(minutes=bucket_minutes - 1e-6):
        b0 = t - timedelta(minutes=bucket_minutes)
        in_bucket = [o for o in orders if b0 <= o.created_at < t]
        preps = [
            (o.ready_at - o.created_at).total_seconds() / 60
            for o in orders
            if o.ready_at is not None and b0 <= o.ready_at < t
        ]
        queue = sum(
            1
            for o in orders
            if o.status in ("received", "ready") and o.created_at < t and (o.ready_at is None or o.ready_at >= t)
        )
        stock_at = {}
        for ing in ingredients:
            later = sum(float(d) for ing_id, d, occ in movements if ing_id == ing.id and occ >= t)
            stock_at[ing.key] = round(max(0.0, float(ing.stock) - later), 2)
        points.append(
            TimeseriesPoint(
                t=min(t, end),
                orders=len(in_bucket),
                rejected=sum(1 for o in in_bucket if o.status == "rejected"),
                avg_prep_minutes=round(sum(preps) / len(preps), 2) if preps else None,
                queue_length=queue,
                stock=stock_at,
            )
        )
        t += timedelta(minutes=bucket_minutes)
    return Timeseries(
        bucket_minutes=bucket_minutes,
        start=start,
        end=end,
        ingredients={i.key: i.name for i in ingredients},
        units={i.key: i.unit for i in ingredients},
        points=points,
    )


def _encode_cursor(dt: datetime, ref: str) -> str:
    return base64.urlsafe_b64encode(f"{dt.isoformat()}|{ref}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    ts, ref = raw.split("|", 1)
    return datetime.fromisoformat(ts), ref


def list_orders(
    s: Session, restaurant_id: uuid.UUID, *, status: str | None, channel: str | None, limit: int, cursor: str | None
) -> Page[OrderView]:
    q = select(Order).options(selectinload(Order.items)).where(Order.restaurant_id == restaurant_id)
    if status:
        q = q.where(Order.status == status)
    if channel:
        q = q.where(Order.channel == channel)
    if cursor:
        ts, ref = _decode_cursor(cursor)
        q = q.where((Order.created_at < ts) | ((Order.created_at == ts) & (Order.order_ref < ref)))
    rows = list(s.scalars(q.order_by(Order.created_at.desc(), Order.order_ref.desc()).limit(limit + 1)))
    names = dict(s.execute(select(MenuItem.key, MenuItem.name).where(MenuItem.restaurant_id == restaurant_id)).all())
    items = [
        OrderView(
            id=o.id,
            order_ref=o.order_ref,
            channel=o.channel,
            status=o.status,
            created_at=o.created_at,
            ready_at=o.ready_at,
            prep_minutes=round((o.ready_at - o.created_at).total_seconds() / 60, 1) if o.ready_at else None,
            total_cents=o.total_cents,
            reject_reason=o.reject_reason,
            customer_note=o.customer_note,
            note_flags=list(o.note_flags or []),
            items=[
                OrderItemView(
                    item_key=i.item_key,
                    name=names.get(i.item_key, i.item_key),
                    qty=i.qty,
                    unit_price_cents=i.unit_price_cents,
                )
                for i in o.items
            ],
        )
        for o in rows[:limit]
    ]
    nxt = _encode_cursor(rows[limit - 1].created_at, rows[limit - 1].order_ref) if len(rows) > limit else None
    total = s.scalar(select(func.count()).select_from(Order).where(Order.restaurant_id == restaurant_id))
    return Page[OrderView](items=items, next_cursor=nxt, total=int(total or 0))


def inventory(s: Session, catalog: Catalog, restaurant: Restaurant) -> InventoryView:
    rid = restaurant.id
    now = business_now(s, rid)
    risks = {
        r.ingredient_key: r
        for r in SqlReadModel(bound(s), catalog).inventory_risks(rid, as_of=now, window_minutes=15, horizon_minutes=120)
    }
    ingredients = list(s.scalars(select(Ingredient).where(Ingredient.restaurant_id == rid).order_by(Ingredient.name)))
    open_po = dict(
        s.execute(
            select(PurchaseOrder.ingredient_id, func.sum(PurchaseOrder.quantity))
            .where(PurchaseOrder.restaurant_id == rid, PurchaseOrder.status == "ordered")
            .group_by(PurchaseOrder.ingredient_id)
        ).all()
    )
    recipe_rows = s.execute(
        select(RecipeLine.ingredient_id, MenuItem.key, MenuItem.name, RecipeLine.qty_per_unit, Ingredient.key)
        .join(MenuItem, MenuItem.id == RecipeLine.menu_item_id)
        .join(Ingredient, Ingredient.id == RecipeLine.ingredient_id)
        .where(RecipeLine.restaurant_id == rid)
    ).all()
    used_by: dict[uuid.UUID, list[str]] = {}
    recipes: dict[str, dict[str, float]] = {}
    for ing_id, item_key, item_name, qty, ing_key in recipe_rows:
        used_by.setdefault(ing_id, []).append(item_name)
        recipes.setdefault(item_key, {})[ing_key] = float(qty)
    ing_views = []
    for i in ingredients:
        r = risks.get(i.key)
        ing_views.append(
            IngredientView(
                id=i.id,
                key=i.key,
                name=i.name,
                unit=i.unit,
                stock=float(i.stock),
                safety_stock=float(i.safety_stock),
                consumption_per_hour=r.consumption_per_hour if r else 0.0,
                eta_minutes=r.eta_minutes if r else None,
                risk=r.risk if r else "ok",
                pack_size=float(i.pack_size),
                lead_time_minutes=i.lead_time_minutes,
                unit_cost_cents=i.unit_cost_cents,
                open_po_qty=float(open_po.get(i.id, 0) or 0),
                used_by=sorted(used_by.get(i.id, [])),
            )
        )
    order = {"out": 0, "critical": 1, "high": 2, "watch": 3, "ok": 4}
    ing_views.sort(key=lambda v: (order.get(v.risk, 5), v.name))
    menu = [
        MenuItemView(
            id=m.id,
            key=m.key,
            name=m.name,
            category=m.category,
            course=m.course,
            price_cents=m.price_cents,
            is_available=m.is_available,
            unavailable_reason=m.unavailable_reason,
            recipe=recipes.get(m.key, {}),
        )
        for m in s.scalars(
            select(MenuItem).where(MenuItem.restaurant_id == rid).order_by(MenuItem.course, MenuItem.name)
        )
    ]
    names = {i.id: (i.key, i.name) for i in ingredients}
    pos = [
        PurchaseOrderView(
            id=p.id,
            ingredient_key=names[p.ingredient_id][0],
            ingredient_name=names[p.ingredient_id][1],
            quantity=float(p.quantity),
            unit=p.unit,
            status=p.status,
            estimated_cost_cents=p.estimated_cost_cents,
            expected_at=p.expected_at,
            received_at=p.received_at,
            approval_id=p.approval_id,
            created_at=p.created_at,
        )
        for p in s.scalars(
            select(PurchaseOrder).where(PurchaseOrder.restaurant_id == rid).order_by(PurchaseOrder.created_at.desc())
        )
    ]
    return InventoryView(business_time=now, ingredients=ing_views, menu_items=menu, purchase_orders=pos)


def list_events(
    s: Session,
    restaurant_id: uuid.UUID,
    *,
    event_type: str | None,
    status: str | None,
    after_id: int | None,
    before_id: int | None,
    limit: int,
) -> list[EventView]:
    q = select(Event).where(Event.restaurant_id == restaurant_id)
    if event_type:
        q = q.where(Event.type == event_type)
    if status:
        q = q.where(Event.status == status)
    if after_id is not None:
        q = q.where(Event.id > after_id).order_by(Event.id.asc())
    else:
        if before_id is not None:
            q = q.where(Event.id < before_id)
        q = q.order_by(Event.id.desc())
    return [_event_view(e) for e in s.scalars(q.limit(limit))]


def _event_view(e: Event) -> EventView:
    return EventView(
        id=e.id,
        type=e.type,
        source=e.source,
        status=e.status,
        tick=e.tick,
        occurred_at=e.occurred_at,
        received_at=e.received_at,
        attempts=e.attempts,
        outcome=e.outcome,
        last_error=e.last_error,
        payload=e.payload,
    )


def incident_view(i: Incident) -> IncidentView:
    return IncidentView(
        id=i.id,
        title=i.title,
        severity=i.severity,
        status=i.status,
        detected_at=i.detected_at,
        tick=i.tick,
        signals=list(i.signals),
    )


def list_incidents(s: Session, restaurant_id: uuid.UUID, *, limit: int = 50) -> list[IncidentView]:
    q = (
        select(Incident)
        .where(Incident.restaurant_id == restaurant_id)
        .order_by(Incident.detected_at.desc())
        .limit(limit)
    )
    return [incident_view(i) for i in s.scalars(q)]


def list_agent_runs(s: Session, restaurant_id: uuid.UUID, *, limit: int = 50) -> list[AgentRunBrief]:
    runs = s.scalars(
        select(AgentRun)
        .where(AgentRun.restaurant_id == restaurant_id)
        .order_by(AgentRun.created_at.desc())
        .limit(limit)
    )
    return [_run_brief(s, r) for r in runs]


def _users(s: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return dict(s.execute(select(User.id, User.display_name).where(User.id.in_(ids))).all())


def approval_view(a: ApprovalRequest, users: dict[uuid.UUID, str], role: str) -> ApprovalView:
    return ApprovalView(
        id=a.id,
        run_id=a.run_id,
        incident_id=a.incident_id,
        action_type=a.action_type,
        title=a.title,
        rationale=a.rationale,
        expected_impact=a.expected_impact,
        risk_level=a.risk_level,
        payload=a.payload,
        evidence=list(a.evidence or []),
        required_role=a.required_role,
        status=a.status,
        version=a.version,
        requested_at=a.requested_at,
        business_time=a.business_time,
        expires_at=a.expires_at,
        decided_by_label=users.get(a.decided_by) if a.decided_by else None,
        decided_at=a.decided_at,
        decision_reason=a.decision_reason,
        executed_at=a.executed_at,
        execution_result=a.execution_result,
        can_decide=a.status == "pending" and has_permission(Role(role), Permission.APPROVALS_DECIDE),
    )


def list_approvals(
    s: Session, restaurant_id: uuid.UUID, *, status: str | None, role: str, limit: int = 100
) -> list[ApprovalView]:
    q = select(ApprovalRequest).where(ApprovalRequest.restaurant_id == restaurant_id)
    if status:
        q = q.where(ApprovalRequest.status == status)
    rows = list(s.scalars(q.order_by(ApprovalRequest.requested_at.desc()).limit(limit)))
    users = _users(s, {a.decided_by for a in rows if a.decided_by})
    return [approval_view(a, users, role) for a in rows]


def agent_run_detail(s: Session, restaurant_id: uuid.UUID, run_id: uuid.UUID, role: str) -> AgentRunDetail | None:
    run = s.scalars(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.restaurant_id == restaurant_id)
    ).one_or_none()
    if run is None:
        return None
    brief = _run_brief(s, run)
    steps = [
        StepView(
            id=f"S{st.seq:02d}",
            seq=st.seq,
            agent=st.agent,
            kind=st.kind,
            title=st.title,
            tool_name=st.tool_name,
            input=st.input,
            output=st.output,
            status=st.status,
            latency_ms=st.latency_ms,
            flags=list(st.flags or []),
            created_at=st.created_at,
        )
        for st in s.scalars(select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.seq))
    ]
    approvals = list(
        s.scalars(
            select(ApprovalRequest).where(ApprovalRequest.run_id == run.id).order_by(ApprovalRequest.requested_at)
        )
    )
    users = _users(s, {a.decided_by for a in approvals if a.decided_by})
    incident = s.get(Incident, run.incident_id) if run.incident_id else None
    return AgentRunDetail(
        **brief.model_dump(),
        plan=run.plan,
        outcomes=run.outcomes,
        incident=incident_view(incident) if incident else None,
        step_list=steps,
        approval_list=[approval_view(a, users, role) for a in approvals],
    )


def list_audit(
    s: Session,
    restaurant_id: uuid.UUID,
    *,
    action: str | None,
    actor_type: str | None,
    before_id: int | None,
    after_id: int | None,
    limit: int,
) -> list[AuditView]:
    q = select(AuditLog).where(AuditLog.restaurant_id == restaurant_id)
    if action:
        q = q.where(AuditLog.action.startswith(action))
    if actor_type:
        q = q.where(AuditLog.actor_type == actor_type)
    if after_id is not None:
        q = q.where(AuditLog.id > after_id).order_by(AuditLog.id.asc())
    else:
        if before_id is not None:
            q = q.where(AuditLog.id < before_id)
        q = q.order_by(AuditLog.id.desc())
    return [
        AuditView(
            id=a.id,
            actor_type=a.actor_type,
            actor_label=a.actor_label,
            action=a.action,
            target_type=a.target_type,
            target_id=a.target_id,
            details=a.details,
            business_time=a.business_time,
            created_at=a.created_at,
        )
        for a in s.scalars(q.limit(limit))
    ]


def default_chart_ingredients(s: Session, catalog: Catalog, restaurant_id: uuid.UUID, limit: int = 2) -> list[str]:
    """Ingredients worth charting: those named in this run's incidents, then the ones at risk now."""
    keys: list[str] = []
    sim = latest_simulation(s, restaurant_id)
    if sim is not None:
        for signals in s.scalars(
            select(Incident.signals).where(Incident.simulation_run_id == sim.id).order_by(Incident.detected_at)
        ):
            for sig in signals:
                if sig.get("kind") == "stockout_risk" and sig.get("subject") not in keys:
                    keys.append(sig["subject"])
    risks = SqlReadModel(bound(s), catalog).inventory_risks(
        restaurant_id, as_of=business_now(s, restaurant_id), window_minutes=15, horizon_minutes=120
    )
    for r in risks:
        if r.risk != "ok" and r.ingredient_key not in keys:
            keys.append(r.ingredient_key)
    if not keys and risks:
        keys.append(risks[0].ingredient_key)
    return keys[:limit]
