"""Order composition model shared by the simulator and the synthetic history generator.

Keeping these constants in one place guarantees that the demand history used to
train the forecasting baseline has the same item mix as the live simulation.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Mapping, Sequence

from nexus.domain.catalog import MenuItemTemplate

EXTRA_MAIN_PROBS: tuple[float, ...] = (0.45, 0.15)  # P(2nd main), P(3rd main)
SIDE_PROB = 0.55
DRINK_PROB = 0.65
DRINK_QTY_CHOICES: tuple[int, ...] = (1, 1, 1, 2)
DESSERT_PROB = 0.12

CHANNELS: tuple[str, ...] = ("app_delivery", "dine_in", "takeout")
CHANNEL_WEIGHTS: tuple[float, ...] = (0.60, 0.25, 0.15)

EXPECTED_MAINS_PER_ORDER = 1.0 + sum(EXTRA_MAIN_PROBS)
EXPECTED_DRINK_QTY = sum(DRINK_QTY_CHOICES) / len(DRINK_QTY_CHOICES)


def _by_course(items: Sequence[MenuItemTemplate], course: str) -> list[MenuItemTemplate]:
    return [i for i in items if i.course == course]


def draw_order_items(
    rng: random.Random,
    menu: Sequence[MenuItemTemplate],
    available: Mapping[str, bool],
) -> Counter[str]:
    """Draw the items of one order. Unavailable items are never chosen.

    Returns an empty counter when no main course is available (customer leaves).
    """
    usable = [m for m in menu if available.get(m.key, True)]
    mains = _by_course(usable, "main")
    # Always consume the same number of random draws for the "shape" of the order
    # so that availability changes do not shift unrelated decisions.
    extra_draws = [rng.random() for _ in EXTRA_MAIN_PROBS]
    side_draw, drink_draw, dessert_draw = rng.random(), rng.random(), rng.random()
    drink_qty = rng.choice(DRINK_QTY_CHOICES)
    items: Counter[str] = Counter()
    if not mains:
        return items
    n_mains = 1 + sum(1 for d, p in zip(extra_draws, EXTRA_MAIN_PROBS, strict=True) if d < p)
    weights = [m.popularity for m in mains]
    for chosen in rng.choices(mains, weights=weights, k=n_mains):
        items[chosen.key] += 1
    sides = _by_course(usable, "side")
    if sides and side_draw < SIDE_PROB:
        items[rng.choices(sides, weights=[s.popularity for s in sides])[0].key] += 1
    drinks = _by_course(usable, "drink")
    if drinks and drink_draw < DRINK_PROB:
        items[rng.choices(drinks, weights=[d.popularity for d in drinks])[0].key] += drink_qty
    desserts = _by_course(usable, "dessert")
    if desserts and dessert_draw < DESSERT_PROB:
        items[rng.choices(desserts, weights=[d.popularity for d in desserts])[0].key] += 1
    return items


def expected_item_qty_per_order(menu: Sequence[MenuItemTemplate]) -> dict[str, float]:
    """Analytical expectation of units of each item per order (all items available)."""
    expected: dict[str, float] = {}
    for course, factor in (
        ("main", EXPECTED_MAINS_PER_ORDER),
        ("side", SIDE_PROB),
        ("drink", DRINK_PROB * EXPECTED_DRINK_QTY),
        ("dessert", DESSERT_PROB),
    ):
        group = _by_course(menu, course)
        total = sum(i.popularity for i in group)
        for item in group:
            expected[item.key] = factor * item.popularity / total if total else 0.0
    return expected
