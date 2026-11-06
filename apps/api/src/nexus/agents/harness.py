"""Offline harness: run a scenario in memory until the detectors open an incident.

Used by unit tests and by the evaluation runner to exercise agents without a
database. The live system follows the same sequence (tick → project events →
detect) against PostgreSQL in ``nexus.application.simulation``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from nexus.agents.read_model import ProjectionReadModel
from nexus.domain.catalog import Catalog, RestaurantTemplate
from nexus.domain.detectors import Signal, kitchen_signals, stock_signals
from nexus.domain.metrics import ingredient_risks, kitchen_snapshot
from nexus.domain.projection import RestaurantProjection
from nexus.domain.simulation import SCENARIOS, SIM_START, SimState, run_tick, tick_time

DETECTION_WINDOW_MINUTES = 15
DETECTION_HORIZON_MINUTES = 120


@dataclass
class HarnessResult:
    template: RestaurantTemplate
    projection: RestaurantProjection
    tick: int | None
    as_of: datetime
    signals: list[Signal]
    state: SimState
    restaurant_id: UUID

    def read_model(self) -> ProjectionReadModel:
        return ProjectionReadModel(
            restaurant_id=self.restaurant_id, template=self.template, projection=self.projection, sim_start=SIM_START
        )


def new_projection(template: RestaurantTemplate, scenario_key: str) -> RestaurantProjection:
    scenario = SCENARIOS[scenario_key]
    return RestaurantProjection(
        stock=template.initial_stock(scenario.stock_override),
        recipes={m.key: dict(m.recipe) for m in template.menu_items},
        prices={m.key: m.price_cents for m in template.menu_items},
        available={m.key: True for m in template.menu_items},
        lines_available=template.kitchen_lines,
    )


def detect(template: RestaurantTemplate, projection: RestaurantProjection, as_of: datetime) -> list[Signal]:
    snap = kitchen_snapshot(
        projection.order_rows(),
        as_of=as_of,
        window_minutes=DETECTION_WINDOW_MINUTES,
        sla_minutes=template.prep_sla_minutes,
    )
    meta = {i.key: (i.name, i.unit, i.safety_stock) for i in template.ingredients}
    consumed = projection.consumed_between(as_of - timedelta(minutes=DETECTION_WINDOW_MINUTES), as_of)
    risks = ingredient_risks(
        stock=dict(projection.stock),
        meta=meta,
        consumed_in_window=consumed,
        window_minutes=DETECTION_WINDOW_MINUTES,
        horizon_minutes=DETECTION_HORIZON_MINUTES,
    )
    return kitchen_signals(snap) + stock_signals(risks)


def simulate_until_incident(
    catalog: Catalog, *, template_key: str, scenario_key: str, seed: int, max_ticks: int | None = None
) -> HarnessResult:
    template = catalog.get(template_key)
    scenario = SCENARIOS[scenario_key]
    projection = new_projection(template, scenario_key)
    state = SimState.initial(template)
    last = scenario.total_ticks if max_ticks is None else min(max_ticks, scenario.total_ticks)
    for tick in range(last):
        out = run_tick(
            scenario=scenario,
            template=template,
            seed=seed,
            tick=tick,
            state=state,
            availability=projection.available,
            stock=projection.stock,
        )
        state = out.state
        for event in out.events:
            projection.apply(event.type, event.payload, event.occurred_at)
        as_of = tick_time(tick)
        signals = detect(template, projection, as_of)
        if signals:
            return HarnessResult(template, projection, tick, as_of, signals, state, uuid4())
    return HarnessResult(template, projection, None, tick_time(last - 1), [], state, uuid4())
