"""Reproducible measurements reported in docs/benchmarks/results.md.

Usage (needs a disposable PostgreSQL database):
    DATABASE_URL=postgresql+psycopg://nexus:nexus@localhost:5432/nexus_bench \
    JWT_SECRET=... uv run python scripts/run_benchmarks.py --seeds 10

What is measured (all on synthetic data):
1. Forecast backtest metrics per template (WAPE/MAE, interval coverage).
2. Simulator outcomes of the featured scenario under three decision policies,
   executed through the real service layer (events, detectors, agents, approvals):
   * approve_all: a manager approves every proposal immediately;
   * po_only: approves purchase orders, rejects menu pauses;
   * reject_all: rejects everything (counterfactual baseline).
3. Latencies of deterministic agent runs, tool calls and simulation ticks.
These numbers describe the simulator and the deterministic agents. They are not
evidence of real-world restaurant performance.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from nexus.application.agent_runs import execute_agent_run
from nexus.application.approvals import DecisionActor, decide
from nexus.application.audit import Actor
from nexus.application.sandbox import create_restaurant_from_template
from nexus.application.simulation import start_simulation, step_simulation
from nexus.config import get_settings
from nexus.domain.approvals import Decision
from nexus.domain.catalog import load_catalog
from nexus.domain.forecasting import backtest
from nexus.domain.rbac import Role
from nexus.infra.db import make_engine, session_scope
from nexus.infra.models import AgentRun, AgentStep, ApprovalRequest, Membership, Order, PurchaseOrder, User

POLICIES = ("approve_all", "po_only", "reject_all")


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    data = sorted(values)
    k = (len(data) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(data) - 1)
    return data[lo] + (data[hi] - data[lo]) * (k - lo)


def run_policy(factory, catalog, settings, seed: int, policy: str) -> dict[str, object]:
    with session_scope(factory) as s:
        user = User(email=f"bench-{uuid.uuid4().hex[:8]}@bench.invalid", display_name="Benchmark")
        s.add(user)
        s.flush()
        restaurant = create_restaurant_from_template(s, catalog.get("aurora_pinheiros"))
        s.add(Membership(user_id=user.id, restaurant_id=restaurant.id, role="manager"))
        run = start_simulation(
            s,
            restaurant=restaurant,
            catalog=catalog,
            settings=settings,
            scenario_key="rush_stockout",
            seed=seed,
            tick_interval_ms=200,
            auto_pause_on_approval=None,
            actor=Actor("user", str(user.id), "Benchmark"),
        )
        rid, run_id, uid = restaurant.id, run.id, user.id
    actor = DecisionActor(user_id=uid, label="Benchmark", role=Role.MANAGER)
    tick_ms: list[float] = []
    for _ in range(400):
        started = time.perf_counter()
        with session_scope(factory) as s:
            step = step_simulation(s, run_id=run_id, catalog=catalog, settings=settings)
        tick_ms.append((time.perf_counter() - started) * 1000)
        if step.agent_run_id:
            execute_agent_run(factory, settings, catalog, step.agent_run_id)
            with session_scope(factory) as s:
                pending = list(
                    s.scalars(
                        select(ApprovalRequest).where(
                            ApprovalRequest.restaurant_id == rid, ApprovalRequest.status == "pending"
                        )
                    )
                )
            for a in pending:
                approve = policy == "approve_all" or (policy == "po_only" and a.action_type == "create_purchase_order")
                with session_scope(factory) as s:
                    decide(
                        s,
                        restaurant_id=rid,
                        approval_id=a.id,
                        actor=actor,
                        decision=Decision.APPROVE if approve else Decision.REJECT,
                        reason=None if approve else f"benchmark policy {policy}",
                    )
        if step.status == "completed":
            break
    with session_scope(factory) as s:
        rows = dict(
            s.execute(select(Order.status, func.count()).where(Order.restaurant_id == rid).group_by(Order.status)).all()
        )
        lost_value = (
            s.scalar(
                select(func.coalesce(func.sum(Order.total_cents), 0)).where(
                    Order.restaurant_id == rid, Order.status == "rejected"
                )
            )
            or 0
        )
        runs = list(s.scalars(select(AgentRun).where(AgentRun.restaurant_id == rid)))
        run_ms = [(r.finished_at - r.started_at).total_seconds() * 1000 for r in runs if r.finished_at and r.started_at]
        tool_ms = [
            float(x)
            for x in s.scalars(
                select(AgentStep.latency_ms).where(
                    AgentStep.restaurant_id == rid, AgentStep.kind == "tool_call", AgentStep.latency_ms.is_not(None)
                )
            )
        ]
        pos = s.scalar(select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.restaurant_id == rid))
    return {
        "seed": seed,
        "policy": policy,
        "orders": sum(rows.values()),
        "lost_orders": rows.get("rejected", 0),
        "lost_revenue_cents": int(lost_value),
        "agent_runs": len(runs),
        "purchase_orders": pos,
        "agent_run_ms": run_ms,
        "tool_ms": tool_ms,
        "tick_ms": tick_ms,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[3] / "docs" / "benchmarks"))
    args = parser.parse_args()
    settings = get_settings()
    catalog = load_catalog()
    factory = sessionmaker(bind=make_engine(settings), expire_on_commit=False, autoflush=False)

    forecasting = {t.key: backtest(t).model_dump() for t in catalog.templates}
    results = []
    for seed in range(1, args.seeds + 1):
        for policy in POLICIES:
            results.append(run_policy(factory, catalog, settings, seed, policy))
            print(f"seed={seed} policy={policy} lost={results[-1]['lost_orders']}", flush=True)

    summary = {}
    for policy in POLICIES:
        rs = [r for r in results if r["policy"] == policy]
        summary[policy] = {
            "runs": len(rs),
            "lost_orders_mean": statistics.mean(r["lost_orders"] for r in rs),
            "lost_orders_min": min(r["lost_orders"] for r in rs),
            "lost_orders_max": max(r["lost_orders"] for r in rs),
            "lost_revenue_mean_brl": statistics.mean(r["lost_revenue_cents"] for r in rs) / 100,
            "orders_mean": statistics.mean(r["orders"] for r in rs),
        }
    all_runs = [x for r in results for x in r["agent_run_ms"]]
    all_tools = [x for r in results for x in r["tool_ms"]]
    all_ticks = [x for r in results for x in r["tick_ms"]]
    latency = {
        "agent_run_ms": {"n": len(all_runs), "p50": percentile(all_runs, 0.5), "p95": percentile(all_runs, 0.95)},
        "tool_call_ms": {"n": len(all_tools), "p50": percentile(all_tools, 0.5), "p95": percentile(all_tools, 0.95)},
        "simulation_tick_ms": {
            "n": len(all_ticks),
            "p50": percentile(all_ticks, 0.5),
            "p95": percentile(all_ticks, 0.95),
        },
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "seeds": args.seeds,
        "mode": "deterministic agents (no LLM)",
        "forecasting": forecasting,
        "policies": summary,
        "latency": latency,
        "runs": [{k: v for k, v in r.items() if not k.endswith("_ms")} for r in results],
    }
    (out / "results.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"policies": summary, "latency": latency}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
