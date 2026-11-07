"""Reproducible measurements reported in docs/benchmarks/results.md.

Usage (needs a disposable PostgreSQL database):
    DATABASE_URL=postgresql+psycopg://nexus:nexus@localhost:5432/nexus_bench \
    JWT_SECRET=... uv run python scripts/run_benchmarks.py --seeds 10

    # Same scenario, but the manager answers 5, 15 and 30 simulated minutes after each proposal:
    DATABASE_URL=... JWT_SECRET=... uv run python scripts/run_benchmarks.py --seeds 10 --approval-delays 5,15,30

What is measured (all on synthetic data):
1. Forecast backtest metrics per template (WAPE/MAE, interval coverage).
2. Simulator outcomes of the featured scenario under three decision policies,
   executed through the real service layer (events, detectors, agents, approvals):
   * approve_all: a manager approves every proposal immediately;
   * po_only: approves purchase orders, rejects menu pauses;
   * reject_all: rejects everything (counterfactual baseline).
   The run pauses while approvals are pending, so these decisions take no simulated time.
3. Latencies of deterministic agent runs, tool calls and simulation ticks.
4. Only with --approval-delays (writes approval_delay.json and leaves results.json alone):
   approve_all and po_only again, but the restaurant keeps operating while the manager has
   not answered. Each proposal is decided once N simulated minutes have passed since it was
   made, so a pause starts N minutes later and a purchase order also arrives N minutes later.
   A delay of 0 is always included as the control. reject_all runs once per seed as the
   reference: it executes nothing, so a delay cannot change it, and it is also the outcome
   when nobody answers before the approval expires.
These numbers describe the simulator and the deterministic agents. They are not
evidence of real-world restaurant performance.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import uuid
from collections import Counter
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
from nexus.domain.simulation import minutes_to_datetime
from nexus.infra.db import make_engine, session_scope
from nexus.infra.models import (
    AgentRun,
    AgentStep,
    ApprovalRequest,
    Membership,
    Order,
    PurchaseOrder,
    SimulationRun,
    User,
)

POLICIES = ("approve_all", "po_only", "reject_all")
# reject_all executes nothing, so answering late cannot change its outcome.
DELAY_POLICIES = ("approve_all", "po_only")


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    data = sorted(values)
    k = (len(data) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(data) - 1)
    return data[lo] + (data[hi] - data[lo]) * (k - lo)


def approves(policy: str, action_type: str) -> bool:
    return policy == "approve_all" or (policy == "po_only" and action_type == "create_purchase_order")


def decide_due_approvals(
    factory, *, restaurant_id: uuid.UUID, run_id: uuid.UUID, actor: DecisionActor, policy: str, delay_minutes: int
) -> list[dict[str, object]]:
    """Answer the pending approvals that have waited at least ``delay_minutes`` on the simulated clock.

    The wait is counted from the business time of the proposal to the current tick, so it does not
    depend on how fast this machine runs the simulation.
    """
    with session_scope(factory) as s:
        sim = s.get(SimulationRun, run_id)
        assert sim is not None
        now = minutes_to_datetime(sim.sim_start, sim.current_tick)
        pending = list(
            s.scalars(
                select(ApprovalRequest)
                .where(ApprovalRequest.restaurant_id == restaurant_id, ApprovalRequest.status == "pending")
                .order_by(ApprovalRequest.requested_at, ApprovalRequest.id)
            )
        )
    answered: list[dict[str, object]] = []
    for a in pending:
        waited = (now - (a.business_time or now)).total_seconds() / 60
        if waited < delay_minutes:
            continue
        approve = approves(policy, a.action_type)
        with session_scope(factory) as s:
            done = decide(
                s,
                restaurant_id=restaurant_id,
                approval_id=a.id,
                actor=actor,
                decision=Decision.APPROVE if approve else Decision.REJECT,
                reason=None if approve else f"benchmark policy {policy}",
            )
            answered.append({"status": done.status, "error": (done.execution_result or {}).get("error")})
    return answered


def run_policy(
    factory, catalog, settings, seed: int, policy: str, approval_delay_minutes: int | None = None
) -> dict[str, object]:
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
            # None: the run waits for the manager (scenario default), so a decision takes no simulated time.
            # A number: the run never waits, and the restaurant keeps operating until the manager answers.
            auto_pause_on_approval=None if approval_delay_minutes is None else False,
            actor=Actor("user", str(user.id), "Benchmark"),
        )
        rid, run_id, uid, sim_start = restaurant.id, run.id, user.id, run.sim_start
    actor = DecisionActor(user_id=uid, label="Benchmark", role=Role.MANAGER)
    tick_ms: list[float] = []
    answered: list[dict[str, object]] = []
    for _ in range(400):
        started = time.perf_counter()
        with session_scope(factory) as s:
            step = step_simulation(s, run_id=run_id, catalog=catalog, settings=settings)
        tick_ms.append((time.perf_counter() - started) * 1000)
        if step.agent_run_id:
            execute_agent_run(factory, settings, catalog, step.agent_run_id)
        answered += decide_due_approvals(
            factory,
            restaurant_id=rid,
            run_id=run_id,
            actor=actor,
            policy=policy,
            delay_minutes=approval_delay_minutes or 0,
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
        first_proposal = s.scalar(
            select(func.min(ApprovalRequest.business_time)).where(ApprovalRequest.restaurant_id == rid)
        )
        first_loss = s.scalar(
            select(func.min(Order.created_at)).where(Order.restaurant_id == rid, Order.status == "rejected")
        )
        po_arrivals = sorted(
            t
            for t in s.scalars(select(PurchaseOrder.expected_tick).where(PurchaseOrder.restaurant_id == rid))
            if t is not None
        )
        unanswered = s.scalar(
            select(func.count())
            .select_from(ApprovalRequest)
            .where(ApprovalRequest.restaurant_id == rid, ApprovalRequest.status == "pending")
        )

    def minute(at: datetime | None) -> float | None:
        return None if at is None else round((at - sim_start).total_seconds() / 60, 1)

    approvals = Counter(str(a["status"]) for a in answered)
    if unanswered:
        approvals["unanswered"] = unanswered  # still pending when the scenario ended
    return {
        "seed": seed,
        "policy": policy,
        "approval_delay_minutes": approval_delay_minutes,
        "orders": sum(rows.values()),
        "lost_orders": rows.get("rejected", 0),
        "lost_revenue_cents": int(lost_value),
        "agent_runs": len(runs),
        "purchase_orders": pos,
        # Simulated minutes since the start of the scenario (18:30).
        "first_proposal_minute": minute(first_proposal),
        "first_lost_order_minute": minute(first_loss),
        "purchase_order_arrival_minutes": po_arrivals,
        "approvals": dict(approvals),
        "failed_approvals": dict(Counter(str(a["error"]) for a in answered if a["status"] == "failed")),
        "agent_run_ms": run_ms,
        "tool_ms": tool_ms,
        "tick_ms": tick_ms,
    }


def summarize(rs: list[dict[str, object]]) -> dict[str, object]:
    return {
        "runs": len(rs),
        "lost_orders_mean": statistics.mean(r["lost_orders"] for r in rs),
        "lost_orders_min": min(r["lost_orders"] for r in rs),
        "lost_orders_max": max(r["lost_orders"] for r in rs),
        "lost_revenue_mean_brl": statistics.mean(r["lost_revenue_cents"] for r in rs) / 100,
        "orders_mean": statistics.mean(r["orders"] for r in rs),
    }


def parse_delays(value: str) -> list[int]:
    try:
        delays = {int(x) for x in value.split(",") if x.strip()}
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use whole minutes separated by commas, e.g. 5,15,30") from exc
    if any(d < 0 for d in delays):
        raise argparse.ArgumentTypeError("delays are minutes and cannot be negative")
    return sorted(delays | {0})


def run_delay_sweep(factory, catalog, settings, *, seeds: int, delays: list[int], out: Path) -> None:
    results: list[dict[str, object]] = []
    for seed in range(1, seeds + 1):
        results.append(run_policy(factory, catalog, settings, seed, "reject_all", approval_delay_minutes=0))
        print(f"seed={seed} policy=reject_all lost={results[-1]['lost_orders']}", flush=True)
        for delay in delays:
            for policy in DELAY_POLICIES:
                results.append(run_policy(factory, catalog, settings, seed, policy, approval_delay_minutes=delay))
                print(f"seed={seed} policy={policy} delay={delay} lost={results[-1]['lost_orders']}", flush=True)

    no_action = {r["seed"]: r["lost_orders"] for r in results if r["policy"] == "reject_all"}
    summary: dict[str, dict[str, object]] = {}
    for delay in delays:
        summary[str(delay)] = {}
        for policy in DELAY_POLICIES:
            rs = [r for r in results if r["policy"] == policy and r["approval_delay_minutes"] == delay]
            losses = [r["first_lost_order_minute"] for r in rs if r["first_lost_order_minute"] is not None]
            arrivals = [r["purchase_order_arrival_minutes"][0] for r in rs if r["purchase_order_arrival_minutes"]]
            # Same seed with no action at all: how much of that loss is still incurred.
            shares = [r["lost_orders"] / no_action[r["seed"]] for r in rs if no_action[r["seed"]]]
            summary[str(delay)][policy] = {
                **summarize(rs),
                "seeds_with_losses": sum(1 for r in rs if r["lost_orders"] > 0),
                "share_of_no_action_loss": statistics.mean(shares) if shares else None,
                "first_purchase_order_arrival_minute_mean": statistics.mean(arrivals) if arrivals else None,
                "first_lost_order_minute_mean": statistics.mean(losses) if losses else None,
                "approvals": dict(sum((Counter(r["approvals"]) for r in rs), Counter())),
                "failed_approvals": dict(sum((Counter(r["failed_approvals"]) for r in rs), Counter())),
            }
    reference = summarize([r for r in results if r["policy"] == "reject_all"])
    proposals = [r["first_proposal_minute"] for r in results if r["first_proposal_minute"] is not None]
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "seeds": seeds,
        "mode": "deterministic agents (no LLM)",
        "scenario": "rush_stockout",
        "template": "aurora_pinheiros",
        "delay": "simulated minutes from each proposal to the manager's answer; the restaurant keeps operating meanwhile",
        "approval_ttl_minutes": settings.approval_ttl_minutes,
        "first_proposal_minute_mean": statistics.mean(proposals) if proposals else None,
        "no_action_reference": {"reject_all": reference},
        "delays": summary,
        "runs": [{k: v for k, v in r.items() if not k.endswith("_ms")} for r in results],
    }
    (out / "approval_delay.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"no_action_reference": reference, "delays": summary}, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[3] / "docs" / "benchmarks"))
    parser.add_argument(
        "--approval-delays",
        type=parse_delays,
        default=None,
        metavar="MINUTES",
        help=(
            "comma-separated simulated minutes the manager takes to answer each proposal, e.g. 5,15,30 "
            "(0 is always added as the control); runs only this comparison and writes approval_delay.json"
        ),
    )
    args = parser.parse_args()
    settings = get_settings()
    catalog = load_catalog()
    factory = sessionmaker(bind=make_engine(settings), expire_on_commit=False, autoflush=False)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.approval_delays is not None:
        run_delay_sweep(factory, catalog, settings, seeds=args.seeds, delays=args.approval_delays, out=out)
        return

    forecasting = {t.key: backtest(t).model_dump() for t in catalog.templates}
    results = []
    for seed in range(1, args.seeds + 1):
        for policy in POLICIES:
            results.append(run_policy(factory, catalog, settings, seed, policy))
            print(f"seed={seed} policy={policy} lost={results[-1]['lost_orders']}", flush=True)

    summary = {policy: summarize([r for r in results if r["policy"] == policy]) for policy in POLICIES}
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
