"""Demand forecasting baseline with an honest, reproducible evaluation.

What this module does
---------------------
1. Generates a *synthetic* hourly sales history (8 weeks) per item from the
   template seed, using the same demand profile as the simulator. Nothing here is
   real sales data.
2. Evaluates three simple seasonal models with day-ahead backtests:
   ``naive_1d`` (same hour yesterday), ``seasonal_naive_7d`` (same hour last week)
   and ``seasonal_mean_4w`` (mean of the same hour over the last four weeks).
   The model is **selected on a validation week** and **reported on a held-out
   test week** (no peeking).
3. Builds 80% prediction intervals from a Poisson variance inflated by a
   dispersion factor estimated on the validation week, and reports the
   *empirical coverage* of those intervals on the test week.
4. Applies an explicit, bounded **nowcast** factor (observed vs expected orders
   in the last 30 minutes) so that an ongoing rush is reflected in the next hours.

Numbers produced here are statistics, never LLM output.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from pydantic import BaseModel

from nexus.domain.catalog import RestaurantTemplate
from nexus.domain.demand import hour_factor
from nexus.domain.fmt import num
from nexus.domain.order_mix import expected_item_qty_per_order
from nexus.domain.simulation import BRT, SIM_START

HISTORY_DAYS = 56
Z80 = 1.2815515655446004  # standard normal quantile for a central 80% interval
NOWCAST_WINDOW_MINUTES = 30
NOWCAST_MIN_MINUTES = 10
NOWCAST_BOUNDS = (0.5, 3.0)
MODELS = ("naive_1d", "seasonal_naive_7d", "seasonal_mean_4w")


@dataclass(frozen=True)
class History:
    start: datetime  # first hour (local, BRT)
    hours: int
    item_keys: tuple[str, ...]
    items: np.ndarray  # shape (n_items, hours)
    orders: np.ndarray  # shape (hours,)
    expected_orders: np.ndarray  # deterministic mean (hours,)

    def index_of(self, local_hour: datetime) -> int:
        return int((local_hour - self.start).total_seconds() // 3600)


def _hour_factor(dt: datetime) -> float:
    return hour_factor(dt)  # converts to restaurant-local time


_HISTORY_CACHE: dict[tuple[str, int, float, str], History] = {}
_BACKTEST_CACHE: dict[tuple[str, int, float], BacktestReport] = {}


def synthetic_history(template: RestaurantTemplate, end: datetime = SIM_START) -> History:
    """Hourly synthetic history ending at the hour boundary before ``end`` (cached)."""
    key = (template.key, template.history_seed, template.peak_orders_per_hour, end.isoformat())
    cached = _HISTORY_CACHE.get(key)
    if cached is None:
        cached = _HISTORY_CACHE[key] = _generate_history(template, end)
    return cached


def _generate_history(template: RestaurantTemplate, end: datetime) -> History:
    end_hour = end.astimezone(BRT).replace(minute=0, second=0, microsecond=0)
    start = end_hour - timedelta(days=HISTORY_DAYS)
    hours = HISTORY_DAYS * 24
    rs = np.random.RandomState(template.history_seed)  # legacy RNG: stream-stable across numpy versions
    day_shock = rs.gamma(shape=25.0, scale=1 / 25.0, size=HISTORY_DAYS + 1)  # mean 1, sd 0.2
    per_order = expected_item_qty_per_order(template.menu_items)
    keys = tuple(m.key for m in template.menu_items)
    mix = np.array([per_order[k] for k in keys])
    expected = np.zeros(hours)
    lam = np.zeros(hours)
    for i in range(hours):
        ts = start + timedelta(hours=i)
        week = i // (24 * 7)
        trend = 1.0 + 0.004 * week
        expected[i] = template.peak_orders_per_hour * _hour_factor(ts) * trend
        lam[i] = expected[i] * day_shock[i // 24]
    orders = rs.poisson(lam)
    items = rs.poisson(np.outer(mix, lam))
    return History(start=start, hours=hours, item_keys=keys, items=items, orders=orders, expected_orders=expected)


def predict_hour(history: History, model: str, target_index: int) -> np.ndarray:
    """Item-level prediction for an hour index (may be beyond the history end).

    Lags never reach into the future relative to a day-ahead forecast origin
    because every lag is >= 24h.
    """
    out = np.zeros(len(history.item_keys))
    for j in range(len(history.item_keys)):
        series = history.items[j]
        if model == "naive_1d":
            lag = target_index - 24
            out[j] = series[lag] if 0 <= lag < history.hours else _fallback(series, target_index, history.hours)
        elif model == "seasonal_naive_7d":
            lag = target_index - 168
            out[j] = series[lag] if 0 <= lag < history.hours else _fallback(series, target_index, history.hours)
        else:
            lags = [target_index - 168 * k for k in range(1, 5)]
            vals = [series[lag] for lag in lags if 0 <= lag < history.hours]
            out[j] = float(np.mean(vals)) if vals else 0.0
    return out


def _fallback(series: np.ndarray, target_index: int, hours: int) -> float:
    lag = target_index - 168
    while lag >= hours:
        lag -= 168
    return float(series[lag]) if lag >= 0 else 0.0


class ModelScore(BaseModel):
    model: str
    mae: float
    wape: float


class BacktestReport(BaseModel):
    method: str
    granularity: str
    validation_window: tuple[str, str]
    test_window: tuple[str, str]
    validation: list[ModelScore]
    test: list[ModelScore]
    selected_model: str
    dispersion: float
    interval_level: float
    interval_coverage_test: float
    test_hours: int


def _scores(history: History, start_idx: int, end_idx: int) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    open_hours = [t for t in range(start_idx, end_idx) if _hour_factor(history.start + timedelta(hours=t)) > 0]
    result: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for model in MODELS:
        preds = np.stack([predict_hour(history, model, t) for t in open_hours], axis=1)
        actual = history.items[:, open_hours]
        result[model] = (actual, preds)
    return result


def _mae_wape(actual: np.ndarray, pred: np.ndarray) -> tuple[float, float]:
    err = np.abs(actual - pred)
    denom = float(np.sum(np.abs(actual)))
    return float(np.mean(err)), float(np.sum(err) / denom) if denom else math.nan


def backtest(template: RestaurantTemplate) -> BacktestReport:
    key = (template.key, template.history_seed, template.peak_orders_per_hour)
    cached = _BACKTEST_CACHE.get(key)
    if cached is None:
        cached = _BACKTEST_CACHE[key] = _run_backtest(template)
    return cached


def _run_backtest(template: RestaurantTemplate) -> BacktestReport:
    history = synthetic_history(template)
    test_start = history.hours - 7 * 24
    val_start = history.hours - 14 * 24
    val = _scores(history, val_start, test_start)
    test = _scores(history, test_start, history.hours)
    val_scores = [
        ModelScore(model=m, mae=round(a, 4), wape=round(w, 4)) for m in MODELS for a, w in [_mae_wape(*val[m])]
    ]
    test_scores = [
        ModelScore(model=m, mae=round(a, 4), wape=round(w, 4)) for m in MODELS for a, w in [_mae_wape(*test[m])]
    ]
    selected = min(val_scores, key=lambda s: s.wape).model
    actual_v, pred_v = val[selected]
    # Over-dispersion relative to Poisson: phi = E[(y - yhat)^2 / max(yhat, 1)].
    phi = float(np.mean((actual_v - pred_v) ** 2 / np.maximum(pred_v, 1.0)))
    actual_t, pred_t = test[selected]
    sigma = np.sqrt(phi * np.maximum(pred_t, 1.0))
    lo, hi = np.maximum(pred_t - Z80 * sigma, 0.0), pred_t + Z80 * sigma
    coverage = float(np.mean((actual_t >= np.floor(lo)) & (actual_t <= np.ceil(hi))))

    def window(a: int, b: int) -> tuple[str, str]:
        return ((history.start + timedelta(hours=a)).isoformat(), (history.start + timedelta(hours=b)).isoformat())

    return BacktestReport(
        method=(
            "backtest com previsão do dia seguinte; modelo escolhido na semana de validação e métricas "
            "reportadas na semana de teste, fora da amostra"
        ),
        granularity="item × hora (somente horas de funcionamento)",
        validation_window=window(val_start, test_start),
        test_window=window(test_start, history.hours),
        validation=val_scores,
        test=test_scores,
        selected_model=selected,
        dispersion=round(phi, 4),
        interval_level=0.8,
        interval_coverage_test=round(coverage, 4),
        test_hours=int(actual_t.shape[1]),
    )


class Interval(BaseModel):
    expected: float
    p10: float
    p90: float


class NowcastInfo(BaseModel):
    window_minutes: float
    observed_orders: int
    expected_orders: float
    raw_ratio: float | None
    applied_ratio: float
    note: str


class IngredientForecast(BaseModel):
    ingredient_key: str
    name: str
    unit: str
    baseline: Interval
    adjusted: Interval


class ItemForecast(BaseModel):
    item_key: str
    name: str
    baseline: Interval
    adjusted: Interval


class ForecastResult(BaseModel):
    as_of: datetime
    horizon_minutes: int
    model: str
    orders: Interval
    orders_adjusted: Interval
    items: list[ItemForecast]
    ingredients: list[IngredientForecast]
    nowcast: NowcastInfo
    backtest: BacktestReport
    disclaimer: str


def _interval(mean: float, var: float) -> Interval:
    sd = math.sqrt(max(var, 0.0))
    return Interval(expected=round(mean, 2), p10=round(max(0.0, mean - Z80 * sd), 2), p90=round(mean + Z80 * sd, 2))


def _hour_slices(as_of: datetime, horizon_minutes: int) -> list[tuple[datetime, float]]:
    """(hour_start_local, fraction_of_hour) pieces covering [as_of, as_of + horizon)."""
    pieces: list[tuple[datetime, float]] = []
    cursor = as_of.astimezone(BRT)
    end = cursor + timedelta(minutes=horizon_minutes)
    while cursor < end:
        hour_start = cursor.replace(minute=0, second=0, microsecond=0)
        nxt = min(hour_start + timedelta(hours=1), end)
        pieces.append((hour_start, (nxt - cursor).total_seconds() / 3600))
        cursor = nxt
    return pieces


def expected_orders_between(template: RestaurantTemplate, start: datetime, end: datetime) -> float:
    """Model-free expectation from the demand profile (used for the nowcast)."""
    total = 0.0
    minutes = max(0.0, (end - start).total_seconds() / 60)
    for hour_start, frac in _hour_slices(start, math.ceil(minutes)):
        total += template.peak_orders_per_hour * _hour_factor(hour_start) * frac
    return total


def nowcast(
    template: RestaurantTemplate, *, as_of: datetime, observed_orders: int, window_start: datetime
) -> NowcastInfo:
    window_minutes = (as_of - window_start).total_seconds() / 60
    expected = expected_orders_between(template, window_start, as_of)
    if window_minutes < NOWCAST_MIN_MINUTES or expected < 1.0:
        return NowcastInfo(
            window_minutes=round(window_minutes, 1),
            observed_orders=observed_orders,
            expected_orders=round(expected, 2),
            raw_ratio=None,
            applied_ratio=1.0,
            note="Ainda há pouco tempo de observação, então nenhum ajuste foi aplicado.",
        )
    raw = observed_orders / expected
    applied = min(max(raw, NOWCAST_BOUNDS[0]), NOWCAST_BOUNDS[1])
    note = (
        f"Nos últimos {num(window_minutes)} min, o ritmo foi {num(raw, 2)}× o esperado. O ajuste aplicado foi de "
        f"{num(applied, 2)}× (limite entre {num(NOWCAST_BOUNDS[0], 1)}× e {num(NOWCAST_BOUNDS[1], 1)}×)."
    )
    return NowcastInfo(
        window_minutes=round(window_minutes, 1),
        observed_orders=observed_orders,
        expected_orders=round(expected, 2),
        raw_ratio=round(raw, 3),
        applied_ratio=round(applied, 3),
        note=note,
    )


def forecast(
    template: RestaurantTemplate,
    *,
    as_of: datetime,
    horizon_minutes: int,
    observed_orders_in_window: int,
    window_start: datetime,
    available_items: Mapping[str, bool] | None = None,
    ingredient_keys: list[str] | None = None,
) -> ForecastResult:
    history = synthetic_history(template)
    report = backtest(template)
    model = report.selected_model
    phi = report.dispersion
    nc = nowcast(template, as_of=as_of, observed_orders=observed_orders_in_window, window_start=window_start)
    ratio = nc.applied_ratio

    item_mean = np.zeros(len(history.item_keys))
    orders_mean = 0.0
    for hour_start, frac in _hour_slices(as_of, horizon_minutes):
        idx = history.index_of(hour_start)
        item_mean += predict_hour(history, model, idx) * frac
        orders_mean += template.peak_orders_per_hour * _hour_factor(hour_start) * frac
    if available_items is not None:
        mask = np.array([1.0 if available_items.get(k, True) else 0.0 for k in history.item_keys])
        item_mean = item_mean * mask

    items: list[ItemForecast] = []
    for j, key in enumerate(history.item_keys):
        mean = float(item_mean[j])
        var = phi * max(mean, 1.0 if mean > 0 else 0.0)
        items.append(
            ItemForecast(
                item_key=key,
                name=template.menu_item(key).name,
                baseline=_interval(mean, var),
                adjusted=_interval(mean * ratio, var * ratio**2),
            )
        )

    wanted = set(ingredient_keys) if ingredient_keys else {i.key for i in template.ingredients}
    ingredients: list[IngredientForecast] = []
    for ing in template.ingredients:
        if ing.key not in wanted:
            continue
        mean = var = 0.0
        for j, key in enumerate(history.item_keys):
            per_unit = template.menu_item(key).recipe.get(ing.key, 0.0)
            if per_unit:
                m = float(item_mean[j])
                mean += per_unit * m
                var += per_unit**2 * phi * max(m, 1.0 if m > 0 else 0.0)
        ingredients.append(
            IngredientForecast(
                ingredient_key=ing.key,
                name=ing.name,
                unit=ing.unit,
                baseline=_interval(mean, var),
                adjusted=_interval(mean * ratio, var * ratio**2),
            )
        )

    orders_var = phi * max(orders_mean, 1.0)
    return ForecastResult(
        as_of=as_of,
        horizon_minutes=horizon_minutes,
        model=model,
        orders=_interval(orders_mean, orders_var),
        orders_adjusted=_interval(orders_mean * ratio, orders_var * ratio**2),
        items=items,
        ingredients=ingredients,
        nowcast=nc,
        backtest=report,
        disclaimer=(
            "A previsão usa só o histórico sintético. Os intervalos de 80% supõem variância de Poisson "
            "com sobredispersão estimada. O ajuste pelo ritmo observado é uma heurística simples e não "
            "antecipa eventos que nunca aconteceram no histórico."
        ),
    )


def hourly_orders_series(template: RestaurantTemplate, days: int = 14) -> list[dict[str, object]]:
    """History of orders per hour for charts (open hours only)."""
    history = synthetic_history(template)
    out: list[dict[str, object]] = []
    for t in range(history.hours - days * 24, history.hours):
        ts = history.start + timedelta(hours=t)
        if _hour_factor(ts) > 0:
            out.append(
                {
                    "hour": ts.isoformat(),
                    "orders": int(history.orders[t]),
                    "expected": round(float(history.expected_orders[t]), 2),
                }
            )
    return out
