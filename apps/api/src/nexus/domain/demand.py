"""Shared demand profile: used by the simulator *and* the synthetic sales history.

Using a single definition keeps the forecasting baseline honest: a "normal"
simulated Friday matches what the model expects, so the nowcast ratio measures
the scenario's anomaly (e.g. the rush) rather than a modelling mismatch.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from nexus.domain.catalog import RestaurantTemplate

# São Paulo has had no DST since 2019; a fixed offset avoids a tzdata dependency.
BRT = timezone(timedelta(hours=-3), name="BRT")


def to_local(dt: datetime) -> datetime:
    """Restaurant-local time (all synthetic restaurants are in America/Sao_Paulo)."""
    return dt.astimezone(BRT)


# Relative volume per local hour (restaurant closed when absent).
HOURLY_PROFILE: dict[int, float] = {
    11: 0.6,
    12: 1.4,
    13: 1.3,
    14: 0.6,
    15: 0.2,
    18: 0.9,
    19: 1.6,
    20: 1.8,
    21: 1.4,
    22: 0.8,
    23: 0.3,
}
# Monday=0 ... Sunday=6
DOW_PROFILE: dict[int, float] = {0: 0.75, 1: 0.8, 2: 0.9, 3: 1.0, 4: 1.35, 5: 1.45, 6: 1.1}
REFERENCE_HOUR = 20  # peak_orders_per_hour refers to Friday 20h
REFERENCE_DOW = 4


def hour_factor(dt: datetime) -> float:
    local_dt = to_local(dt)
    h = HOURLY_PROFILE.get(local_dt.hour, 0.0)
    return (h / HOURLY_PROFILE[REFERENCE_HOUR]) * (DOW_PROFILE[local_dt.weekday()] / DOW_PROFILE[REFERENCE_DOW])


def expected_orders_per_hour(template: RestaurantTemplate, local_dt: datetime) -> float:
    return template.peak_orders_per_hour * hour_factor(local_dt)


def expected_orders_per_minute(template: RestaurantTemplate, local_dt: datetime) -> float:
    return expected_orders_per_hour(template, local_dt) / 60.0
