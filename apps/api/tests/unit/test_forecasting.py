from datetime import timedelta

import numpy as np

from nexus.domain.forecasting import NOWCAST_BOUNDS, backtest, forecast, nowcast, synthetic_history
from nexus.domain.simulation import SIM_START


def test_history_is_deterministic_and_closed_at_night(aurora) -> None:
    a, b = synthetic_history(aurora), synthetic_history(aurora)
    assert np.array_equal(a.items, b.items)
    for t in range(a.hours):
        if (a.start + timedelta(hours=t)).hour in (3, 4, 5):
            assert a.orders[t] == 0


def test_backtest_selects_on_validation_and_reports_test(aurora) -> None:
    report = backtest(aurora)
    val = {s.model: s.wape for s in report.validation}
    assert report.selected_model == min(val, key=val.get)
    test = {s.model: s for s in report.test}
    assert set(test) == {"naive_1d", "seasonal_naive_7d", "seasonal_mean_4w"}
    assert all(0 < s.wape < 1 and s.mae > 0 for s in test.values())
    assert report.validation_window[1] == report.test_window[0]  # no overlap


def test_interval_coverage_is_measured_not_assumed(aurora) -> None:
    report = backtest(aurora)
    assert 0.7 <= report.interval_coverage_test <= 0.98
    assert report.test_hours > 50


def test_nowcast_short_window_applies_no_adjustment(aurora) -> None:
    info = nowcast(aurora, as_of=SIM_START + timedelta(minutes=5), observed_orders=10, window_start=SIM_START)
    assert info.applied_ratio == 1.0 and info.raw_ratio is None


def test_nowcast_ratio_is_bounded(aurora) -> None:
    info = nowcast(aurora, as_of=SIM_START + timedelta(minutes=30), observed_orders=500, window_start=SIM_START)
    assert info.applied_ratio == NOWCAST_BOUNDS[1]
    assert info.raw_ratio is not None and info.raw_ratio > NOWCAST_BOUNDS[1]


def test_forecast_intervals_are_ordered_and_paused_items_zeroed(aurora) -> None:
    available = {m.key: True for m in aurora.menu_items}
    available["item_pastel_costela"] = False
    res = forecast(
        aurora,
        as_of=SIM_START + timedelta(minutes=20),
        horizon_minutes=120,
        observed_orders_in_window=14,
        window_start=SIM_START,
        available_items=available,
    )
    for item in res.items:
        assert item.baseline.p10 <= item.baseline.expected <= item.baseline.p90
    pastel = next(i for i in res.items if i.item_key == "item_pastel_costela")
    assert pastel.baseline.expected == 0
    costela = next(i for i in res.ingredients if i.ingredient_key == "ing_costela")
    assert costela.adjusted.expected > 0
    assert "sintético" in res.disclaimer
