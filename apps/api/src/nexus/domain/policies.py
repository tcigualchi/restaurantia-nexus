"""Deterministic planning policies.

The orchestrator never lets a language model invent actions. Candidate actions
are generated here from tool outputs with explicit formulas; a model (when one
is configured) may only *prioritise and explain* these candidates. Every
candidate is validated again by the action executor right before execution.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from nexus.domain.catalog import RestaurantTemplate
from nexus.domain.demand import to_local
from nexus.domain.fmt import brl, lower_first, num, qty
from nexus.domain.forecasting import ForecastResult
from nexus.domain.metrics import IngredientRisk, KitchenSnapshot
from nexus.domain.order_mix import EXPECTED_MAINS_PER_ORDER

ActionType = Literal["create_purchase_order", "pause_menu_item"]
SENSITIVE_ACTIONS: frozenset[str] = frozenset({"create_purchase_order", "pause_menu_item"})


class AffectedItem(BaseModel):
    item_key: str
    name: str
    price_cents: int
    usage_per_unit: float
    available: bool


class IngredientContext(BaseModel):
    risk: IngredientRisk
    pack_size: float
    lead_time_minutes: int
    unit_cost_cents: int
    open_po_qty: float = 0.0
    affected_items: list[AffectedItem] = Field(default_factory=list)


class CandidateAction(BaseModel):
    candidate_id: str
    action_type: ActionType
    title: str
    payload: dict[str, object]
    rationale: str
    expected_impact: str
    risk_level: Literal["low", "medium", "high"]
    requires_approval: bool = True
    evidence: list[str] = Field(default_factory=list)


class Recommendation(BaseModel):
    title: str
    detail: str
    category: Literal["operations", "inventory", "communication"]
    evidence: list[str] = Field(default_factory=list)


class CapacityAnalysis(BaseModel):
    lines_available: int
    estimated_service_minutes: float
    capacity_orders_per_hour: float
    projected_orders_per_hour: float
    projected_utilization: float
    queue_length: int
    risk: Literal["ok", "watch", "high"]


class PlanProposal(BaseModel):
    candidates: list[CandidateAction]
    recommendations: list[Recommendation]
    capacity: CapacityAnalysis | None
    assumptions: list[str]


# Used to explain why the cheapest items (by revenue per unit of ingredient) are paused first.
ORDINALS = {1: "segundo ", 2: "terceiro ", 3: "quarto "}


@dataclass(frozen=True)
class PolicyConfig:
    max_items_to_pause_per_ingredient: int = 2
    po_cap_multiplier: float = 3.0
    pause_buffer: float = 1.05
    utilization_watch: float = 0.9
    utilization_high: float = 1.05


def estimated_service_minutes(template: RestaurantTemplate) -> float:
    """Expected kitchen service time per order (matches the simulator's model)."""
    mains = [m for m in template.menu_items if m.course == "main"]
    weighted = sum(m.prep_minutes * m.popularity for m in mains) / sum(m.popularity for m in mains)
    # assembly (1.5) + ~2 extra units (0.35 each) + mean jitter (0.2), plus max() effect of several items
    return round(weighted + 1.5 + 0.35 * (EXPECTED_MAINS_PER_ORDER + 0.6) + 0.2 + 0.4, 2)


def capacity_analysis(
    *,
    snapshot: KitchenSnapshot,
    lines_available: int,
    service_minutes: float,
    forecast: ForecastResult,
    cfg: PolicyConfig = PolicyConfig(),
) -> CapacityAnalysis:
    capacity = lines_available * 60.0 / service_minutes
    projected = forecast.orders_adjusted.expected * 60.0 / forecast.horizon_minutes
    utilization = projected / capacity if capacity else math.inf
    risk: Literal["ok", "watch", "high"] = (
        "high" if utilization >= cfg.utilization_high else "watch" if utilization >= cfg.utilization_watch else "ok"
    )
    return CapacityAnalysis(
        lines_available=lines_available,
        estimated_service_minutes=service_minutes,
        capacity_orders_per_hour=round(capacity, 1),
        projected_orders_per_hour=round(projected, 1),
        projected_utilization=round(utilization, 3),
        queue_length=snapshot.queue_length,
        risk=risk,
    )


def plan_inventory_actions(
    *,
    as_of: datetime,
    ingredients: Sequence[IngredientContext],
    forecast: ForecastResult,
    evidence: Mapping[str, str],
    cfg: PolicyConfig = PolicyConfig(),
) -> tuple[list[CandidateAction], list[Recommendation], list[str]]:
    """Purchase-order and menu-pause candidates for at-risk ingredients."""
    by_ing = {f.ingredient_key: f for f in forecast.ingredients}
    by_item = {f.item_key: f for f in forecast.items}
    horizon = forecast.horizon_minutes
    candidates: list[CandidateAction] = []
    recs: list[Recommendation] = []
    assumptions: list[str] = []
    for ctx in ingredients:
        r = ctx.risk
        if r.risk not in ("high", "critical", "out"):
            continue
        fc = by_ing.get(r.ingredient_key)
        if fc is None:
            assumptions.append(f"Sem previsão para {r.name}, nenhuma ação foi sugerida.")
            continue
        ev = [e for e in (evidence.get("inventory"), evidence.get("forecast")) if e]
        rate_p50 = fc.adjusted.expected / horizon  # per minute
        rate_p90 = fc.adjusted.p90 / horizon
        need_p90 = fc.adjusted.p90 + r.safety_stock
        deficit = need_p90 - r.stock - ctx.open_po_qty
        arrival = as_of + timedelta(minutes=ctx.lead_time_minutes)
        if deficit > 0:
            order_qty = math.ceil(deficit / ctx.pack_size) * ctx.pack_size
            order_qty = min(order_qty, math.ceil(cfg.po_cap_multiplier * need_p90 / ctx.pack_size) * ctx.pack_size)
            cost = round(order_qty * ctx.unit_cost_cents)
            candidates.append(
                CandidateAction(
                    candidate_id=f"po:{r.ingredient_key}",
                    action_type="create_purchase_order",
                    title=f"Pedido de compra emergencial: {qty(order_qty, r.unit)} de {r.name}",
                    payload={
                        "ingredient_key": r.ingredient_key,
                        "quantity": order_qty,
                        "unit": r.unit,
                        "expected_arrival_minutes": ctx.lead_time_minutes,
                        "estimated_cost_cents": cost,
                    },
                    rationale=(
                        f"No cenário pessimista (P90, já ajustado ao ritmo atual), o consumo das próximas "
                        f"{horizon // 60}h chega a {qty(fc.adjusted.p90, r.unit)}. Somando o estoque de segurança "
                        f"de {qty(r.safety_stock, r.unit)}, isso passa do estoque atual ({qty(r.stock, r.unit)})"
                        + (
                            f" mais o que já foi pedido ({qty(ctx.open_po_qty, r.unit)})"
                            if ctx.open_po_qty > 0
                            else ", e não há outra compra a caminho"
                        )
                        + f". A quantidade foi arredondada para embalagens de {qty(ctx.pack_size, r.unit)}."
                    ),
                    expected_impact=(
                        f"Deve chegar às {to_local(arrival).strftime('%H:%M')} (o fornecedor leva "
                        f"{ctx.lead_time_minutes} min). Custo estimado de {brl(cost)}."
                    ),
                    risk_level="medium" if cost < 200_000 else "high",
                    evidence=ev,
                )
            )
        # Will we run out before the purchase arrives?
        consumption_until_arrival = rate_p50 * ctx.lead_time_minutes
        gap = consumption_until_arrival * cfg.pause_buffer - r.stock
        if gap <= 0:
            continue
        options = sorted(
            (i for i in ctx.affected_items if i.available and i.usage_per_unit > 0),
            key=lambda i: (i.price_cents / i.usage_per_unit, i.item_key),
        )
        if len(options) <= 1:
            recs.append(
                Recommendation(
                    title=f"Monitorar {r.name}",
                    detail=(
                        "Pode faltar antes da reposição, mas só resta um item à venda que usa esse ingrediente, "
                        "e tirá-lo do cardápio não é sugerido automaticamente."
                    ),
                    category="inventory",
                    evidence=ev,
                )
            )
            continue
        saved = 0.0
        for rank, item in enumerate(options[: min(cfg.max_items_to_pause_per_ingredient, len(options) - 1)]):
            if saved >= gap:
                break
            ifc = by_item.get(item.item_key)
            item_rate = (ifc.adjusted.expected / horizon) if ifc else 0.0
            saving = item_rate * item.usage_per_unit * ctx.lead_time_minutes
            if saving <= 0:
                continue
            saved += saving
            candidates.append(
                CandidateAction(
                    candidate_id=f"pause:{item.item_key}",
                    action_type="pause_menu_item",
                    title=f"Pausar temporariamente “{item.name}” no cardápio",
                    payload={
                        "item_key": item.item_key,
                        "reason": f"Poupar {lower_first(r.name)} até a reposição",
                        "ingredient_key": r.ingredient_key,
                    },
                    rationale=(
                        f"Pelo consumo previsto, o estoque de {lower_first(r.name)} acaba em "
                        f"~{num(r.stock / rate_p50)} min, antes de a reposição chegar ({ctx.lead_time_minutes} min). "
                        f"Entre os itens que usam esse ingrediente, “{item.name}” é o {ORDINALS.get(rank, '')}que "
                        f"menos fatura por {r.unit} usado ({brl(item.price_cents)} para "
                        f"{num(item.usage_per_unit)} {r.unit})."
                    ),
                    expected_impact=(
                        f"Poupa ~{qty(saving, r.unit)} até a reposição chegar. Os clientes passam a pedir outros "
                        "itens em vez de terem o pedido cancelado por falta de ingrediente."
                    ),
                    risk_level="medium",
                    evidence=ev,
                )
            )
        if rate_p90 > 0 and saved < gap:
            assumptions.append(
                f"Mesmo com as pausas propostas, {r.name} pode faltar por alguns minutos antes da reposição."
            )
    return candidates, recs, assumptions


def plan_kitchen_recommendations(
    *, capacity: CapacityAnalysis, delayed_refs: Sequence[str], evidence: Mapping[str, str]
) -> list[Recommendation]:
    ev = [e for e in (evidence.get("operations"), evidence.get("forecast")) if e]
    recs: list[Recommendation] = []
    if capacity.risk in ("watch", "high"):
        recs.append(
            Recommendation(
                title="Demanda projetada acima da capacidade da cozinha"
                if capacity.risk == "high"
                else "Cozinha próxima do limite de capacidade",
                detail=(
                    f"A previsão é de ~{num(capacity.projected_orders_per_hour)} pedidos/h para uma capacidade de "
                    f"~{num(capacity.capacity_orders_per_hour)} pedidos/h ({capacity.lines_available} linhas, "
                    f"~{num(capacity.estimated_service_minutes, 1)} min por pedido). Reforce a chapa e "
                    "priorize os pedidos pelo horário prometido."
                ),
                category="operations",
                evidence=ev,
            )
        )
    if delayed_refs:
        recs.append(
            Recommendation(
                title=f"Priorizar {len(delayed_refs)} pedidos mais antigos",
                detail="Pedidos com maior espera: " + ", ".join(delayed_refs[:8]) + ".",
                category="operations",
                evidence=ev,
            )
        )
    if capacity.risk == "high":
        recs.append(
            Recommendation(
                title="Avisar os clientes sobre o tempo de espera",
                detail=(
                    "Atualize o prazo de entrega mostrado nos aplicativos para evitar reclamações. "
                    "Nesta versão, isso é feito à mão."
                ),
                category="communication",
                evidence=ev,
            )
        )
    return recs
