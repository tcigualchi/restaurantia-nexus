"""Typed event contracts (shared by the simulator, the ingestion API and the worker)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter

from nexus.domain.catalog import KEY_PATTERN

ORDER_REF_PATTERN = r"^[A-Z0-9][A-Z0-9\-]{2,39}$"
IDEMPOTENCY_KEY_PATTERN = r"^[A-Za-z0-9:_\-\.]{8,200}$"


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OrderItemIn(_Payload):
    item_key: str = Field(pattern=KEY_PATTERN)
    qty: int = Field(ge=1, le=20)


class OrderCreated(_Payload):
    type: Literal["order.created"] = "order.created"
    order_ref: str = Field(pattern=ORDER_REF_PATTERN)
    channel: Literal["app_delivery", "dine_in", "takeout"]
    items: list[OrderItemIn] = Field(min_length=1, max_length=20)
    promised_prep_minutes: int = Field(default=18, ge=1, le=240)
    customer_note: str | None = Field(default=None, max_length=500)


class OrderReady(_Payload):
    type: Literal["order.ready"] = "order.ready"
    order_ref: str = Field(pattern=ORDER_REF_PATTERN)


class OrderCancelled(_Payload):
    type: Literal["order.cancelled"] = "order.cancelled"
    order_ref: str = Field(pattern=ORDER_REF_PATTERN)
    reason: str = Field(min_length=2, max_length=200)


class InventoryReceived(_Payload):
    type: Literal["inventory.received"] = "inventory.received"
    ingredient_key: str = Field(pattern=KEY_PATTERN)
    quantity: float = Field(gt=0, le=1_000_000)
    purchase_order_id: str | None = Field(default=None, max_length=64)


class InventoryAdjusted(_Payload):
    type: Literal["inventory.adjusted"] = "inventory.adjusted"
    ingredient_key: str = Field(pattern=KEY_PATTERN)
    delta: float = Field(ge=-1_000_000, le=1_000_000)
    reason: str = Field(min_length=2, max_length=200)


class KitchenCapacityChanged(_Payload):
    type: Literal["kitchen.capacity_changed"] = "kitchen.capacity_changed"
    lines_available: int = Field(ge=0, le=50)
    lines_total: int = Field(ge=1, le=50)
    reason: str = Field(min_length=2, max_length=200)


EventPayload = Annotated[
    OrderCreated | OrderReady | OrderCancelled | InventoryReceived | InventoryAdjusted | KitchenCapacityChanged,
    Field(discriminator="type"),
]
event_payload_adapter: TypeAdapter[
    OrderCreated | OrderReady | OrderCancelled | InventoryReceived | InventoryAdjusted | KitchenCapacityChanged
] = TypeAdapter(EventPayload)

EVENT_TYPES: tuple[str, ...] = (
    "order.created",
    "order.ready",
    "order.cancelled",
    "inventory.received",
    "inventory.adjusted",
    "kitchen.capacity_changed",
)


class EventIn(BaseModel):
    """External ingestion contract (e.g. a POS webhook)."""

    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(pattern=IDEMPOTENCY_KEY_PATTERN)
    occurred_at: AwareDatetime
    payload: EventPayload


def parse_payload(event_type: str, payload: dict[str, object]) -> _Payload:
    return event_payload_adapter.validate_python({**payload, "type": event_type})


def payload_dict(model: _Payload) -> dict[str, object]:
    data = model.model_dump(mode="json", exclude_none=True)
    data.pop("type", None)
    return data


def is_reserved_external_ref(order_ref: str) -> bool:
    """Simulation refs are reserved so external producers cannot collide with them."""
    return order_ref.startswith("SIM-")
