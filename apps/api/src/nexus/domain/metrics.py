"""Pure operational metrics shared by the read model, detectors and agent tools.

The persistence layer only *fetches* rows (always filtered by tenant and time
window); every number shown to users or agents is computed here so that tests,
API and agents agree on definitions.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import BaseModel


@dataclass(frozen=True)
class OrderRow:
    order_ref: str
    status: str  # received | ready | rejected | cancelled
    created_at: datetime
    ready_at: datetime | None
    total_cents: int
    channel: str


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile (numpy 'linear' method); None for empty input."""
    if not values:
        return None
    data = sorted(values)
    if len(data) == 1:
        return float(data[0])
    pos = (len(data) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return float(data[lo])
    return float(data[lo] + (data[hi] - data[lo]) * (pos - lo))


class KitchenSnapshot(BaseModel):
    as_of: datetime
    window_minutes: int
    sla_minutes: int
    orders_created: int
    orders_completed: int
    orders_rejected: int
    queue_length: int
    oldest_open_minutes: float | None
    avg_prep_minutes: float | None
    p90_prep_minutes: float | None
    sla_breach_rate: float | None
    throughput_per_hour: float
    revenue_cents: int
    lost_revenue_cents: int


def kitchen_snapshot(
    orders: Iterable[OrderRow], *, as_of: datetime, window_minutes: int, sla_minutes: int
) -> KitchenSnapshot:
    start = as_of - timedelta(minutes=window_minutes)
    created = completed = rejected = 0
    queue = 0
    oldest: float | None = None
    preps: list[float] = []
    revenue = lost = 0
    for o in orders:
        if o.created_at > as_of:
            continue
        in_window = o.created_at >= start
        if o.status == "rejected":
            if in_window:
                rejected += 1
                lost += o.total_cents
            continue
        if o.status == "cancelled":
            continue
        if in_window:
            created += 1
            revenue += o.total_cents
        is_open = o.ready_at is None or o.ready_at > as_of
        if is_open:
            queue += 1
            age = (as_of - o.created_at).total_seconds() / 60
            oldest = age if oldest is None else max(oldest, age)
        elif o.ready_at is not None and o.ready_at >= start:
            completed += 1
            preps.append((o.ready_at - o.created_at).total_seconds() / 60)
    avg = sum(preps) / len(preps) if preps else None
    breach = sum(1 for p in preps if p > sla_minutes) / len(preps) if preps else None
    return KitchenSnapshot(
        as_of=as_of,
        window_minutes=window_minutes,
        sla_minutes=sla_minutes,
        orders_created=created,
        orders_completed=completed,
        orders_rejected=rejected,
        queue_length=queue,
        oldest_open_minutes=round(oldest, 2) if oldest is not None else None,
        avg_prep_minutes=round(avg, 2) if avg is not None else None,
        p90_prep_minutes=round(p, 2) if (p := percentile(preps, 0.9)) is not None else None,
        sla_breach_rate=round(breach, 4) if breach is not None else None,
        throughput_per_hour=round(completed * 60 / window_minutes, 2),
        revenue_cents=revenue,
        lost_revenue_cents=lost,
    )


class IngredientRisk(BaseModel):
    ingredient_key: str
    name: str
    unit: str
    stock: float
    safety_stock: float
    consumption_per_hour: float
    eta_minutes: float | None  # None when there is no consumption
    eta_to_safety_minutes: float | None
    risk: str  # ok | watch | high | critical | out


def classify_risk(stock: float, safety: float, eta: float | None, horizon_minutes: float) -> str:
    if stock <= 0:
        return "out"
    if eta is not None and eta <= horizon_minutes * 0.25:
        return "critical"
    if stock <= safety or (eta is not None and eta <= horizon_minutes * 0.5):
        return "high"
    if eta is not None and eta <= horizon_minutes:
        return "watch"
    return "ok"


def ingredient_risks(
    *,
    stock: Mapping[str, float],
    meta: Mapping[str, tuple[str, str, float]],  # key -> (name, unit, safety)
    consumed_in_window: Mapping[str, float],
    window_minutes: int,
    horizon_minutes: int,
) -> list[IngredientRisk]:
    risks: list[IngredientRisk] = []
    for key, qty in stock.items():
        name, unit, safety = meta[key]
        rate_per_min = consumed_in_window.get(key, 0.0) / window_minutes
        eta = qty / rate_per_min if rate_per_min > 0 else None
        eta_safety = max(0.0, (qty - safety) / rate_per_min) if rate_per_min > 0 else None
        risks.append(
            IngredientRisk(
                ingredient_key=key,
                name=name,
                unit=unit,
                stock=round(qty, 2),
                safety_stock=safety,
                consumption_per_hour=round(rate_per_min * 60, 2),
                eta_minutes=round(eta, 1) if eta is not None else None,
                eta_to_safety_minutes=round(eta_safety, 1) if eta_safety is not None else None,
                risk=classify_risk(qty, safety, eta, horizon_minutes),
            )
        )
    order = {"out": 0, "critical": 1, "high": 2, "watch": 3, "ok": 4}
    risks.sort(key=lambda r: (order[r.risk], r.eta_minutes if r.eta_minutes is not None else 1e9))
    return risks


def recipe_consumption(
    items: Iterable[tuple[str, int]], recipes: Mapping[str, Mapping[str, float]]
) -> dict[str, float]:
    """Ingredient quantities consumed by a list of (item_key, qty)."""
    total: dict[str, float] = {}
    for item_key, qty in items:
        for ing_key, per_unit in recipes[item_key].items():
            total[ing_key] = total.get(ing_key, 0.0) + per_unit * qty
    return total
