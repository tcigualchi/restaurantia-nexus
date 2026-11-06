from nexus.domain.simulation import ADVERSARIAL_NOTE, SCENARIOS, SimState, run_tick


def _run(template, scenario_key: str, seed: int, ticks: int, stock=None):
    scenario = SCENARIOS[scenario_key]
    state = SimState.initial(template)
    stock = dict(stock or template.initial_stock(scenario.stock_override))
    availability = {m.key: True for m in template.menu_items}
    events = []
    for t in range(ticks):
        out = run_tick(
            scenario=scenario, template=template, seed=seed, tick=t, state=state, availability=availability, stock=stock
        )
        state = out.state
        events.extend(out.events)
    return events, state


def _signature(events):
    return [(e.type, e.tick, e.seq, e.occurred_at.isoformat(), e.payload) for e in events]


def test_same_seed_produces_identical_event_stream(aurora) -> None:
    a, _ = _run(aurora, "rush_stockout", 42, 40)
    b, _ = _run(aurora, "rush_stockout", 42, 40)
    assert _signature(a) == _signature(b)
    assert len(a) > 50


def test_different_seed_changes_the_stream(aurora) -> None:
    a, _ = _run(aurora, "rush_stockout", 42, 30)
    b, _ = _run(aurora, "rush_stockout", 43, 30)
    assert _signature(a) != _signature(b)


def test_tick_replay_from_persisted_state_is_identical(aurora) -> None:
    scenario = SCENARIOS["rush_stockout"]
    _events, state = _run(aurora, "rush_stockout", 7, 20)
    saved = SimState.from_json(state.to_json())
    kwargs = dict(
        scenario=scenario,
        template=aurora,
        seed=7,
        tick=20,
        availability={m.key: True for m in aurora.menu_items},
        stock=aurora.initial_stock(scenario.stock_override),
    )
    first = run_tick(state=saved, **kwargs)
    again = run_tick(state=SimState.from_json(state.to_json()), **kwargs)
    assert _signature(first.events) == _signature(again.events)


def test_ready_events_only_reference_created_orders(aurora) -> None:
    events, _ = _run(aurora, "rush_hour", 3, 60)
    created = set()
    for e in events:
        if e.type == "order.created":
            created.add(e.payload["order_ref"])
        if e.type == "order.ready":
            assert e.payload["order_ref"] in created


def test_unfulfillable_orders_never_occupy_the_kitchen(aurora) -> None:
    empty = {k: 0.0 for k in aurora.initial_stock()}
    events, state = _run(aurora, "rush_hour", 5, 30, stock=empty)
    assert any(e.type == "order.created" for e in events)
    assert not any(e.type == "order.ready" for e in events)
    assert state.pending_ready == []


def test_paused_items_are_never_ordered(aurora) -> None:
    scenario = SCENARIOS["rush_hour"]
    availability = {m.key: True for m in aurora.menu_items}
    availability["item_burger_costela"] = False
    state = SimState.initial(aurora)
    for t in range(40):
        out = run_tick(
            scenario=scenario,
            template=aurora,
            seed=11,
            tick=t,
            state=state,
            availability=availability,
            stock=aurora.initial_stock(),
        )
        state = out.state
        for e in out.events:
            if e.type == "order.created":
                assert all(i["item_key"] != "item_burger_costela" for i in e.payload["items"])


def test_kitchen_outage_emits_capacity_events(aurora) -> None:
    events, _ = _run(aurora, "kitchen_delay", 1, 60)
    changes = [e for e in events if e.type == "kitchen.capacity_changed"]
    assert [c.payload["lines_available"] for c in changes] == [aurora.kitchen_lines - 4, aurora.kitchen_lines]


def test_featured_scenario_contains_adversarial_note(aurora) -> None:
    events, _ = _run(aurora, "rush_stockout", 42, 20)
    notes = [e.payload.get("customer_note") for e in events if e.type == "order.created"]
    assert ADVERSARIAL_NOTE in notes
