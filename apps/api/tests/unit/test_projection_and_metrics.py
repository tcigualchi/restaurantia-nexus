from datetime import datetime, timedelta, timezone

from nexus.domain.metrics import classify_risk, ingredient_risks, kitchen_snapshot, percentile
from nexus.domain.projection import ApplyOutcome, RestaurantProjection

T0 = datetime(2026, 3, 13, 18, 30, tzinfo=timezone(timedelta(hours=-3)))


def _projection(stock=None) -> RestaurantProjection:
    return RestaurantProjection(
        stock=stock or {"ing_a": 1000.0, "ing_b": 10.0},
        recipes={"item_x": {"ing_a": 100.0}, "item_y": {"ing_a": 50.0, "ing_b": 1.0}},
        prices={"item_x": 2000, "item_y": 1500},
        available={"item_x": True, "item_y": True},
        lines_available=4,
    )


def _created(ref: str, items):
    return {"order_ref": ref, "channel": "dine_in", "items": [{"item_key": k, "qty": q} for k, q in items]}


def test_order_created_is_idempotent() -> None:
    p = _projection()
    assert p.apply("order.created", _created("A-001", [("item_x", 2)]), T0).outcome is ApplyOutcome.APPLIED
    assert p.apply("order.created", _created("A-001", [("item_x", 2)]), T0).outcome is ApplyOutcome.DUPLICATE
    assert p.stock["ing_a"] == 800.0


def test_stockout_rejects_whole_order_without_consuming() -> None:
    p = _projection({"ing_a": 120.0, "ing_b": 10.0})
    res = p.apply("order.created", _created("A-002", [("item_x", 1), ("item_y", 1)]), T0)
    assert res.outcome is ApplyOutcome.REJECTED and res.detail == "stockout:ing_a"
    assert p.stock["ing_a"] == 120.0
    assert p.orders["A-002"].status == "rejected"


def test_ready_before_created_is_retryable() -> None:
    p = _projection()
    assert p.apply("order.ready", {"order_ref": "A-404"}, T0).outcome is ApplyOutcome.RETRY


def test_paused_item_is_rejected() -> None:
    p = _projection()
    p.available["item_x"] = False
    assert p.apply("order.created", _created("A-003", [("item_x", 1)]), T0).detail == "item_unavailable:item_x"


def test_percentile_matches_linear_interpolation() -> None:
    assert percentile([], 0.9) is None
    assert percentile([10.0], 0.9) == 10.0
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.9) == 9.1


def test_kitchen_snapshot_counts_queue_and_prep_times() -> None:
    p = _projection()
    for i in range(4):
        p.apply("order.created", _created(f"A-10{i}", [("item_x", 1)]), T0 + timedelta(minutes=i))
    p.apply("order.ready", {"order_ref": "A-100"}, T0 + timedelta(minutes=10))
    p.apply("order.ready", {"order_ref": "A-101"}, T0 + timedelta(minutes=21))
    snap = kitchen_snapshot(p.order_rows(), as_of=T0 + timedelta(minutes=25), window_minutes=30, sla_minutes=18)
    assert snap.queue_length == 2
    assert snap.orders_completed == 2
    assert snap.avg_prep_minutes == 15.0
    assert snap.sla_breach_rate == 0.5
    assert snap.oldest_open_minutes == 23.0


def test_risk_classification_thresholds() -> None:
    assert classify_risk(0, 10, None, 120) == "out"
    assert classify_risk(100, 10, 25, 120) == "critical"
    assert classify_risk(100, 10, 50, 120) == "high"
    assert classify_risk(5, 10, None, 120) == "high"
    assert classify_risk(100, 10, 100, 120) == "watch"
    assert classify_risk(100, 10, 500, 120) == "ok"


def test_ingredient_risk_eta_uses_window_rate() -> None:
    risks = ingredient_risks(
        stock={"ing_a": 600.0},
        meta={"ing_a": ("A", "g", 100.0)},
        consumed_in_window={"ing_a": 300.0},
        window_minutes=15,
        horizon_minutes=120,
    )
    assert risks[0].consumption_per_hour == 1200.0
    assert risks[0].eta_minutes == 30.0
    assert risks[0].risk == "critical"  # eta <= 25% of the 120-min horizon
