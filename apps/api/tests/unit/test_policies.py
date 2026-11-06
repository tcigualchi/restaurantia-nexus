from datetime import timedelta

from nexus.domain.forecasting import forecast
from nexus.domain.metrics import IngredientRisk
from nexus.domain.policies import AffectedItem, IngredientContext, plan_inventory_actions
from nexus.domain.simulation import SIM_START

AS_OF = SIM_START + timedelta(minutes=23)


def _fc(aurora, observed=30):
    return forecast(
        aurora,
        as_of=AS_OF,
        horizon_minutes=120,
        observed_orders_in_window=observed,
        window_start=SIM_START,
        ingredient_keys=["ing_costela"],
    )


def _ctx(stock: float, risk: str = "high", items=None, open_po: float = 0.0) -> IngredientContext:
    return IngredientContext(
        risk=IngredientRisk(
            ingredient_key="ing_costela",
            name="Costela",
            unit="g",
            stock=stock,
            safety_stock=3000,
            consumption_per_hour=6000,
            eta_minutes=stock / 100,
            eta_to_safety_minutes=None,
            risk=risk,
        ),
        pack_size=1000,
        lead_time_minutes=40,
        unit_cost_cents=9,
        open_po_qty=open_po,
        affected_items=items
        if items is not None
        else [
            AffectedItem(
                item_key="item_burger_costela", name="Burger", price_cents=4490, usage_per_unit=180, available=True
            ),
            AffectedItem(
                item_key="item_bowl_costela", name="Bowl", price_cents=3990, usage_per_unit=150, available=True
            ),
            AffectedItem(
                item_key="item_pastel_costela", name="Pastel", price_cents=2490, usage_per_unit=120, available=True
            ),
        ],
    )


def test_purchase_order_rounded_to_pack_and_covers_p90(aurora) -> None:
    fc = _fc(aurora)
    cands, _, _ = plan_inventory_actions(as_of=AS_OF, ingredients=[_ctx(5300)], forecast=fc, evidence={})
    po = next(c for c in cands if c.action_type == "create_purchase_order")
    qty = po.payload["quantity"]
    p90 = next(i for i in fc.ingredients if i.ingredient_key == "ing_costela").adjusted.p90
    assert qty % 1000 == 0
    assert qty + 5300 >= p90 + 3000


def test_open_purchase_orders_reduce_the_new_order(aurora) -> None:
    fc = _fc(aurora)
    base, _, _ = plan_inventory_actions(as_of=AS_OF, ingredients=[_ctx(5300)], forecast=fc, evidence={})
    with_open, _, _ = plan_inventory_actions(
        as_of=AS_OF, ingredients=[_ctx(5300, open_po=10_000)], forecast=fc, evidence={}
    )
    q = lambda cs: next(c for c in cs if c.action_type == "create_purchase_order").payload["quantity"]  # noqa: E731
    assert q(with_open) == q(base) - 10_000


def test_pause_prefers_lowest_revenue_per_gram(aurora) -> None:
    cands, _, _ = plan_inventory_actions(as_of=AS_OF, ingredients=[_ctx(5300)], forecast=_fc(aurora), evidence={})
    pauses = [c for c in cands if c.action_type == "pause_menu_item"]
    assert pauses and pauses[0].payload["item_key"] == "item_pastel_costela"
    assert len(pauses) <= 2  # never pauses every affected item


def test_no_pause_when_stock_covers_lead_time(aurora) -> None:
    cands, _, _ = plan_inventory_actions(as_of=AS_OF, ingredients=[_ctx(40_000)], forecast=_fc(aurora), evidence={})
    assert not [c for c in cands if c.action_type == "pause_menu_item"]


def test_single_affected_item_is_never_paused_automatically(aurora) -> None:
    only = [
        AffectedItem(item_key="item_bowl_costela", name="Bowl", price_cents=3990, usage_per_unit=150, available=True)
    ]
    cands, recs, _ = plan_inventory_actions(
        as_of=AS_OF, ingredients=[_ctx(800, "critical", only)], forecast=_fc(aurora), evidence={}
    )
    assert not [c for c in cands if c.action_type == "pause_menu_item"]
    assert any("Monitorar" in r.title for r in recs)


def test_ok_ingredients_produce_no_actions(aurora) -> None:
    cands, recs, _ = plan_inventory_actions(
        as_of=AS_OF, ingredients=[_ctx(50_000, "ok")], forecast=_fc(aurora), evidence={}
    )
    assert cands == [] and recs == []
