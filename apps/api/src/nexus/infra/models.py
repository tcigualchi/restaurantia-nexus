"""Relational model. Every tenant-owned table carries ``restaurant_id``.

Business timestamps (``created_at`` of orders, ``occurred_at`` of events, …) use
the restaurant's business clock, which is the simulation clock for sandboxes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSONB, list[Any]: JSONB}


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


def _tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(200))
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = _now()


class DemoSession(Base):
    __tablename__ = "demo_sessions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    ip_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    persona: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class Restaurant(Base):
    __tablename__ = "restaurants"
    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    kitchen_lines: Mapped[int] = mapped_column(Integer, nullable=False)
    kitchen_lines_available: Mapped[int] = mapped_column(Integer, nullable=False)
    prep_sla_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    demo_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("demo_sessions.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = _now()


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (CheckConstraint("role IN ('viewer','operator','manager','owner')", name="ck_membership_role"),)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = _now()


class Ingredient(Base):
    __tablename__ = "ingredients"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "key", name="uq_ingredient_key"),
        CheckConstraint("stock >= 0", name="ck_ingredient_stock_non_negative"),
        CheckConstraint("unit IN ('un','g','ml')", name="ck_ingredient_unit"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    restaurant_id: Mapped[uuid.UUID] = _tenant_fk()
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    unit: Mapped[str] = mapped_column(String(4), nullable=False)
    stock: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    safety_stock: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_cost_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    pack_size: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    lead_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MenuItem(Base):
    __tablename__ = "menu_items"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "key", name="uq_menu_item_key"),
        CheckConstraint("price_cents > 0", name="ck_menu_item_price"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    restaurant_id: Mapped[uuid.UUID] = _tenant_fk()
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    course: Mapped[str] = mapped_column(String(10), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    prep_minutes: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    popularity: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    unavailable_reason: Mapped[str | None] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    recipe: Mapped[list[RecipeLine]] = relationship(back_populates="menu_item", cascade="all, delete-orphan")


class RecipeLine(Base):
    __tablename__ = "recipe_lines"
    __table_args__ = (CheckConstraint("qty_per_unit > 0", name="ck_recipe_qty_positive"),)
    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="CASCADE"), primary_key=True
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    restaurant_id: Mapped[uuid.UUID] = _tenant_fk()
    qty_per_unit: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    menu_item: Mapped[MenuItem] = relationship(back_populates="recipe")
    ingredient: Mapped[Ingredient] = relationship()


class SimulationRun(Base):
    __tablename__ = "simulation_runs"
    __table_args__ = (
        CheckConstraint("status IN ('running','paused','completed','cancelled')", name="ck_sim_status"),
        Index(
            "uq_sim_active_per_restaurant",
            "restaurant_id",
            unique=True,
            postgresql_where=text("status IN ('running','paused')"),
        ),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    restaurant_id: Mapped[uuid.UUID] = _tenant_fk()
    scenario_key: Mapped[str] = mapped_column(String(64), nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    pause_reason: Mapped[str | None] = mapped_column(String(40))
    current_tick: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    total_ticks: Mapped[int] = mapped_column(Integer, nullable=False)
    tick_interval_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    auto_pause_on_approval: Mapped[bool] = mapped_column(Boolean, nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    sim_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_tick_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "idempotency_key", name="uq_event_idempotency"),
        CheckConstraint("status IN ('pending','processed','rejected','dead_letter')", name="ck_event_status"),
        CheckConstraint("source IN ('simulator','api','system')", name="ck_event_source"),
        Index("ix_events_pending", "restaurant_id", "id", postgresql_where=text("status = 'pending'")),
        Index("ix_events_restaurant_recent", "restaurant_id", text("id DESC")),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    simulation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="CASCADE")
    )
    tick: Mapped[int | None] = mapped_column(Integer)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = _now()
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(String(500))
    outcome: Mapped[str | None] = mapped_column(String(80))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "order_ref", name="uq_order_ref"),
        CheckConstraint("status IN ('received','ready','rejected','cancelled')", name="ck_order_status"),
        Index("ix_orders_restaurant_created", "restaurant_id", "created_at"),
        Index("ix_orders_open", "restaurant_id", "created_at", postgresql_where=text("status = 'received'")),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False
    )
    order_ref: Mapped[str] = mapped_column(String(40), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    reject_reason: Mapped[str | None] = mapped_column(String(120))
    customer_note: Mapped[str | None] = mapped_column(String(500))
    note_flags: Mapped[list[str]] = mapped_column(ARRAY(String(40)), nullable=False, server_default=text("'{}'"))
    event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("events.id", ondelete="SET NULL"))
    items: Mapped[list[OrderItem]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (CheckConstraint("qty > 0", name="ck_order_item_qty"),)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), primary_key=True
    )
    item_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    menu_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="SET NULL")
    )
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    order: Mapped[Order] = relationship(back_populates="items")


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint("reason IN ('order_consumption','purchase_received','adjustment')", name="ck_stock_reason"),
        Index("ix_stock_movements_time", "restaurant_id", "occurred_at"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False
    )
    delta: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    reason: Mapped[str] = mapped_column(String(24), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("events.id", ondelete="SET NULL"))
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = _now()


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "dedupe_key", name="uq_incident_dedupe"),
        CheckConstraint("status IN ('open','mitigating','resolved')", name="ck_incident_status"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    restaurant_id: Mapped[uuid.UUID] = _tenant_fk()
    simulation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'open'"))
    signals: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tick: Mapped[int | None] = mapped_column(Integer)
    dedupe_key: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = _now()


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','awaiting_approval','completed','failed')", name="ck_agent_run_status"
        ),
        Index("ix_agent_runs_queued", "created_at", postgresql_where=text("status = 'queued'")),
        Index("ix_agent_runs_restaurant", "restaurant_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE")
    )
    simulation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="CASCADE")
    )
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str | None] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str | None] = mapped_column(String(120))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    outcomes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(String(500))
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _now()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    steps: Mapped[list[AgentStep]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AgentStep.seq"
    )


class AgentStep(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_agent_step_seq"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    agent: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(60))
    input: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    flags: Mapped[list[str]] = mapped_column(ARRAY(String(60)), nullable=False, server_default=text("'{}'"))
    created_at: Mapped[datetime] = _now()
    run: Mapped[AgentRun] = relationship(back_populates="steps")


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "idempotency_key", name="uq_approval_idempotency"),
        CheckConstraint(
            "status IN ('pending','approved','rejected','expired','executed','failed','cancelled')",
            name="ck_approval_status",
        ),
        CheckConstraint("required_role IN ('viewer','operator','manager','owner')", name="ck_approval_role"),
        Index("ix_approvals_pending", "restaurant_id", "requested_at", postgresql_where=text("status = 'pending'")),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    restaurant_id: Mapped[uuid.UUID] = _tenant_fk()
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="SET NULL")
    )
    simulation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="CASCADE")
    )
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    expected_impact: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False)
    evidence: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    required_role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'pending'"))
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    requested_at: Mapped[datetime] = _now()
    business_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(String(500))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (CheckConstraint("status IN ('ordered','received','cancelled')", name="ck_po_status"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    restaurant_id: Mapped[uuid.UUID] = _tenant_fk()
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    estimated_cost_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_tick: Mapped[int | None] = mapped_column(Integer)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="SET NULL")
    )
    simulation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = _now()


class AuditLog(Base):
    """Append-only (enforced by a trigger). Deliberately no FK to restaurants."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint("actor_type IN ('user','agent','system')", name="ck_audit_actor_type"),
        Index("ix_audit_restaurant", "restaurant_id", text("id DESC")),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    restaurant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_type: Mapped[str] = mapped_column(String(10), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64))
    actor_label: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    business_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _now()
