"""Read DTOs returned by the API (also define the OpenAPI response schemas)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from nexus.domain.metrics import IngredientRisk


class RestaurantView(BaseModel):
    id: uuid.UUID
    name: str
    template_key: str
    timezone: str
    kitchen_lines: int
    kitchen_lines_available: int
    prep_sla_minutes: int
    is_demo: bool
    role: str
    permissions: list[str]


class SimulationView(BaseModel):
    id: uuid.UUID
    scenario_key: str
    scenario_name: str
    seed: int
    status: str
    pause_reason: str | None
    current_tick: int
    total_ticks: int
    tick_interval_ms: int
    auto_pause_on_approval: bool
    sim_start: datetime
    business_time: datetime
    created_at: datetime


class Kpis(BaseModel):
    orders_last_60: int
    revenue_last_60_cents: int
    queue_length: int
    oldest_open_minutes: float | None
    avg_prep_minutes: float | None
    p90_prep_minutes: float | None
    sla_minutes: int
    sla_breach_rate: float | None
    lost_orders_total: int
    lost_revenue_total_cents: int
    orders_total: int
    revenue_total_cents: int
    kitchen_lines: int
    kitchen_lines_available: int
    open_incidents: int
    pending_approvals: int
    ingredients_at_risk: int


class AgentRunBrief(BaseModel):
    id: uuid.UUID
    status: str
    mode: str | None
    provider: str
    model: str | None
    trigger: str
    incident_title: str | None
    summary: str | None
    as_of: datetime
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float | None
    steps: int
    approvals: int
    error: str | None


class Overview(BaseModel):
    restaurant: RestaurantView
    business_time: datetime
    clock_mode: str
    data_label: str
    simulation: SimulationView | None
    kpis: Kpis
    ingredients_at_risk: list[IngredientRisk]
    latest_agent_run: AgentRunBrief | None


class TimeseriesPoint(BaseModel):
    t: datetime
    orders: int
    rejected: int
    avg_prep_minutes: float | None
    queue_length: int
    stock: dict[str, float] = Field(default_factory=dict)


class Timeseries(BaseModel):
    bucket_minutes: int
    start: datetime
    end: datetime
    ingredients: dict[str, str]
    points: list[TimeseriesPoint]


class OrderItemView(BaseModel):
    item_key: str
    name: str
    qty: int
    unit_price_cents: int


class OrderView(BaseModel):
    id: uuid.UUID
    order_ref: str
    channel: str
    status: str
    created_at: datetime
    ready_at: datetime | None
    prep_minutes: float | None
    total_cents: int
    reject_reason: str | None
    customer_note: str | None
    note_flags: list[str]
    items: list[OrderItemView]


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    total: int | None = None


class IngredientView(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    unit: str
    stock: float
    safety_stock: float
    consumption_per_hour: float
    eta_minutes: float | None
    risk: str
    pack_size: float
    lead_time_minutes: int
    unit_cost_cents: int
    open_po_qty: float
    used_by: list[str]


class MenuItemView(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    category: str
    course: str
    price_cents: int
    is_available: bool
    unavailable_reason: str | None
    recipe: dict[str, float]


class PurchaseOrderView(BaseModel):
    id: uuid.UUID
    ingredient_key: str
    ingredient_name: str
    quantity: float
    unit: str
    status: str
    estimated_cost_cents: int
    expected_at: datetime
    received_at: datetime | None
    approval_id: uuid.UUID | None
    created_at: datetime


class InventoryView(BaseModel):
    business_time: datetime
    ingredients: list[IngredientView]
    menu_items: list[MenuItemView]
    purchase_orders: list[PurchaseOrderView]


class EventView(BaseModel):
    id: int
    type: str
    source: str
    status: str
    tick: int | None
    occurred_at: datetime
    received_at: datetime
    attempts: int
    outcome: str | None
    last_error: str | None
    payload: dict[str, Any]


class IncidentView(BaseModel):
    id: uuid.UUID
    title: str
    severity: str
    status: str
    detected_at: datetime
    tick: int | None
    signals: list[dict[str, Any]]


class StepView(BaseModel):
    id: str
    seq: int
    agent: str
    kind: str
    title: str
    tool_name: str | None
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    status: str
    latency_ms: int | None
    flags: list[str]
    created_at: datetime


class ApprovalView(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID | None
    incident_id: uuid.UUID | None
    action_type: str
    title: str
    rationale: str
    expected_impact: str
    risk_level: str
    payload: dict[str, Any]
    evidence: list[Any]
    required_role: str
    status: str
    version: int
    requested_at: datetime
    business_time: datetime | None
    expires_at: datetime
    decided_by_label: str | None
    decided_at: datetime | None
    decision_reason: str | None
    executed_at: datetime | None
    execution_result: dict[str, Any] | None
    can_decide: bool = False


class AgentRunDetail(AgentRunBrief):
    plan: dict[str, Any] | None
    outcomes: dict[str, Any] | None
    incident: IncidentView | None
    step_list: list[StepView]
    approval_list: list[ApprovalView]


class AuditView(BaseModel):
    id: int
    actor_type: str
    actor_label: str
    action: str
    target_type: str | None
    target_id: str | None
    details: dict[str, Any]
    business_time: datetime | None
    created_at: datetime


class ScenarioView(BaseModel):
    key: str
    name: str
    description: str
    total_ticks: int
    featured: bool
    tags: list[str]
    auto_pause_on_approval: bool
