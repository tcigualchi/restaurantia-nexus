"""End-to-end flow of the featured scenario against PostgreSQL (service layer)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from nexus.agents.harness import simulate_until_incident
from nexus.application.agent_runs import execute_agent_run
from nexus.application.approvals import DecisionActor, decide
from nexus.application.audit import Actor
from nexus.application.simulation import start_simulation, step_simulation
from nexus.domain.approvals import Decision
from nexus.domain.rbac import Role
from nexus.infra.db import session_scope
from nexus.infra.models import (
    AgentRun,
    AgentStep,
    ApprovalRequest,
    AuditLog,
    Event,
    Ingredient,
    MenuItem,
    Order,
    PurchaseOrder,
    Restaurant,
    SimulationRun,
)

pytestmark = pytest.mark.integration


def _start(factory, catalog, settings, tenant, seed=42, scenario="rush_stockout"):
    with session_scope(factory) as s:
        restaurant = s.get(Restaurant, tenant.restaurant_id)
        run = start_simulation(
            s,
            restaurant=restaurant,
            catalog=catalog,
            settings=settings,
            scenario_key=scenario,
            seed=seed,
            tick_interval_ms=200,
            auto_pause_on_approval=None,
            actor=Actor("user", str(tenant.user_id), "Teste"),
        )
        return run.id


def _run_until_agents(factory, catalog, settings, run_id, max_ticks=120):
    for _ in range(max_ticks):
        with session_scope(factory) as s:
            res = step_simulation(s, run_id=run_id, catalog=catalog, settings=settings)
        if res.agent_run_id:
            return res
        if res.skipped:
            return res
    raise AssertionError("no incident detected")


def test_db_pipeline_matches_reference_projection(factory, catalog, settings, make_tenant) -> None:
    tenant = make_tenant()
    run_id = _start(factory, catalog, settings, tenant)
    res = _run_until_agents(factory, catalog, settings, run_id)
    ref = simulate_until_incident(catalog, template_key="aurora_pinheiros", scenario_key="rush_stockout", seed=42)
    assert res.tick == ref.tick
    with session_scope(factory) as s:
        orders = {
            o.order_ref: (o.status, o.reject_reason)
            for o in s.scalars(select(Order).where(Order.restaurant_id == tenant.restaurant_id))
        }
        stock = {
            i.key: float(i.stock)
            for i in s.scalars(select(Ingredient).where(Ingredient.restaurant_id == tenant.restaurant_id))
        }
    assert orders == {r: (o.status, o.reject_reason) for r, o in ref.projection.orders.items()}
    assert all(abs(stock[k] - v) < 1e-6 for k, v in ref.projection.stock.items())


def test_featured_scenario_end_to_end(factory, catalog, settings, make_tenant) -> None:
    tenant = make_tenant()
    run_id = _start(factory, catalog, settings, tenant)
    res = _run_until_agents(factory, catalog, settings, run_id)
    with session_scope(factory) as s:
        sim = s.get(SimulationRun, run_id)
        assert (sim.status, sim.pause_reason) == ("paused", "agents_running")

    assert execute_agent_run(factory, settings, catalog, res.agent_run_id) == "awaiting_approval"
    with session_scope(factory) as s:
        sim = s.get(SimulationRun, run_id)
        assert (sim.status, sim.pause_reason) == ("paused", "awaiting_approval")
        run = s.get(AgentRun, res.agent_run_id)
        assert run.mode == "deterministic" and run.summary
        agents = {st.agent for st in s.scalars(select(AgentStep).where(AgentStep.run_id == run.id))}
        assert {"orchestrator", "operations", "inventory", "forecasting"} <= agents
        approvals = list(s.scalars(select(ApprovalRequest).where(ApprovalRequest.run_id == run.id)))
        assert {a.action_type for a in approvals} == {"create_purchase_order", "pause_menu_item"}
        # Nothing sensitive happened before a human decided.
        assert (
            s.scalar(
                select(func.count())
                .select_from(PurchaseOrder)
                .where(PurchaseOrder.restaurant_id == tenant.restaurant_id)
            )
            == 0
        )
        assert all(
            m.is_available for m in s.scalars(select(MenuItem).where(MenuItem.restaurant_id == tenant.restaurant_id))
        )

    actor = DecisionActor(user_id=tenant.user_id, label="Gerente", role=Role.MANAGER)
    for a in approvals:
        with session_scope(factory) as s:
            if a.payload.get("item_key") == "item_burger_costela":
                done = decide(
                    s,
                    restaurant_id=tenant.restaurant_id,
                    approval_id=a.id,
                    actor=actor,
                    decision=Decision.REJECT,
                    reason="Carro-chefe: manter no cardápio",
                )
                assert done.status == "rejected"
            else:
                done = decide(
                    s,
                    restaurant_id=tenant.restaurant_id,
                    approval_id=a.id,
                    actor=actor,
                    decision=Decision.APPROVE,
                    reason=None,
                )
                assert done.status == "executed", done.execution_result

    with session_scope(factory) as s:
        sim = s.get(SimulationRun, run_id)
        assert sim.status == "running"  # auto-resumed once nothing is pending
    for _ in range(200):
        with session_scope(factory) as s:
            step = step_simulation(s, run_id=run_id, catalog=catalog, settings=settings)
        if step.agent_run_id:
            execute_agent_run(factory, settings, catalog, step.agent_run_id)
            with session_scope(factory) as s:
                for pending in s.scalars(
                    select(ApprovalRequest).where(
                        ApprovalRequest.run_id == step.agent_run_id, ApprovalRequest.status == "pending"
                    )
                ):
                    decide(
                        s,
                        restaurant_id=tenant.restaurant_id,
                        approval_id=pending.id,
                        actor=actor,
                        decision=Decision.REJECT,
                        reason="Fora do escopo do teste",
                    )
        if step.status == "completed":
            break
    with session_scope(factory) as s:
        assert s.get(SimulationRun, run_id).status == "completed"
        po = s.scalars(select(PurchaseOrder).where(PurchaseOrder.restaurant_id == tenant.restaurant_id)).one()
        assert po.status == "received"
        pastel = s.scalars(
            select(MenuItem).where(
                MenuItem.restaurant_id == tenant.restaurant_id, MenuItem.key == "item_pastel_costela"
            )
        ).one()
        burger = s.scalars(
            select(MenuItem).where(
                MenuItem.restaurant_id == tenant.restaurant_id, MenuItem.key == "item_burger_costela"
            )
        ).one()
        assert not pastel.is_available and burger.is_available
        lost = s.scalar(
            select(func.count())
            .select_from(Order)
            .where(Order.restaurant_id == tenant.restaurant_id, Order.status == "rejected")
        )
        assert lost <= 10  # without action the same seed loses ~50 orders (see test below)
        # The second incident must not re-propose the action the manager rejected.
        later = list(
            s.scalars(
                select(ApprovalRequest).where(
                    ApprovalRequest.restaurant_id == tenant.restaurant_id, ApprovalRequest.run_id != res.agent_run_id
                )
            )
        )
        assert all(a.payload.get("item_key") != "item_burger_costela" for a in later)
        actions = [
            a
            for (a,) in s.execute(
                select(AuditLog.action).where(AuditLog.restaurant_id == tenant.restaurant_id).order_by(AuditLog.id)
            )
        ]
        for expected in (
            "simulation.started",
            "incident.opened",
            "approval.requested",
            "approval.approved",
            "approval.rejected",
            "action.executed",
            "menu_item.paused",
            "purchase_order.created",
            "simulation.completed",
        ):
            assert expected in actions, expected
        assert (
            s.scalar(
                select(func.count())
                .select_from(Event)
                .where(Event.restaurant_id == tenant.restaurant_id, Event.status != "processed")
            )
            == 0
        )


def test_rejecting_everything_loses_more_orders(factory, catalog, settings, make_tenant) -> None:
    tenant = make_tenant()
    run_id = _start(factory, catalog, settings, tenant)
    actor = DecisionActor(user_id=tenant.user_id, label="Gerente", role=Role.MANAGER)
    for _ in range(300):
        with session_scope(factory) as s:
            step = step_simulation(s, run_id=run_id, catalog=catalog, settings=settings)
        if step.agent_run_id:
            execute_agent_run(factory, settings, catalog, step.agent_run_id)
            with session_scope(factory) as s:
                for pending in s.scalars(
                    select(ApprovalRequest).where(
                        ApprovalRequest.restaurant_id == tenant.restaurant_id, ApprovalRequest.status == "pending"
                    )
                ):
                    decide(
                        s,
                        restaurant_id=tenant.restaurant_id,
                        approval_id=pending.id,
                        actor=actor,
                        decision=Decision.REJECT,
                        reason="Teste contrafactual",
                    )
        if step.status == "completed":
            break
    with session_scope(factory) as s:
        lost = s.scalar(
            select(func.count())
            .select_from(Order)
            .where(Order.restaurant_id == tenant.restaurant_id, Order.status == "rejected")
        )
        assert (
            s.scalar(
                select(func.count())
                .select_from(PurchaseOrder)
                .where(PurchaseOrder.restaurant_id == tenant.restaurant_id)
            )
            == 0
        )
    assert lost >= 30


def test_reset_replays_deterministically(factory, catalog, settings, make_tenant) -> None:
    tenant = make_tenant()
    signatures = []
    for _ in range(2):
        run_id = _start(factory, catalog, settings, tenant, seed=7)
        res = _run_until_agents(factory, catalog, settings, run_id)
        with session_scope(factory) as s:
            rows = s.execute(
                select(Event.type, Event.tick, Event.occurred_at, Event.payload)
                .where(Event.simulation_run_id == run_id)
                .order_by(Event.id)
            ).all()
        signatures.append((res.tick, [(t, k, o.isoformat(), p) for t, k, o, p in rows]))
    assert signatures[0] == signatures[1]
