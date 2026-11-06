"""Business clock: simulated time for sandboxes, wall-clock otherwise."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from nexus.domain.simulation import minutes_to_datetime
from nexus.infra.read_model import latest_simulation


def business_now(s: Session, restaurant_id: uuid.UUID) -> datetime:
    sim = latest_simulation(s, restaurant_id)
    if sim is None:
        return datetime.now(UTC)
    return minutes_to_datetime(sim.sim_start, sim.current_tick)
