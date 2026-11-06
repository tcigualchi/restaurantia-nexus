"""Incident orchestrator built on a LangGraph state graph.

Graph::

    START → triage ─┬─▶ operations ─▶ inventory ─▶ forecasting ─▶ plan ─▶ request_approvals → END
                    └─(kitchen-only incident skips inventory)──────┘

* ``triage`` routes deterministically from the detector signals.
* Specialist nodes run the agents (LLM or deterministic mode) through the
  permissioned tool executor; every step is recorded.
* ``plan`` derives candidate actions with deterministic policies; a model, if
  configured, may only write the executive summary and order the candidates.
* ``request_approvals`` turns sensitive candidates into *pending* approval
  requests. Nothing is executed here: execution happens only after a human
  decision, with revalidation, in the approval service.

The routing function :func:`next_node` is shared by the LangGraph wiring and by
:meth:`Orchestrator.run_sequential` (a dependency-free harness used by unit
tests), so both follow exactly the same edges.
"""

from __future__ import annotations

import json
import operator
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Protocol, TypedDict

from pydantic import BaseModel, Field, ValidationError

from nexus.agents.llm import LLMError, LLMProvider, Usage
from nexus.agents.specialists import SPECIALISTS, AgentOutcome, AgentRunner, AgentTask
from nexus.agents.tools import FORECASTING, INVENTORY, OPERATIONS, StepRecorder, ToolContext
from nexus.domain.demand import to_local
from nexus.domain.detectors import Signal
from nexus.domain.fmt import num, pct
from nexus.domain.forecasting import ForecastResult
from nexus.domain.guardrails import validate_model_text
from nexus.domain.metrics import IngredientRisk, KitchenSnapshot
from nexus.domain.policies import (
    AffectedItem,
    CandidateAction,
    IngredientContext,
    PlanProposal,
    PolicyConfig,
    Recommendation,
    capacity_analysis,
    plan_inventory_actions,
    plan_kitchen_recommendations,
)


class IncidentInfo(BaseModel):
    incident_id: str
    title: str
    severity: str
    signals: list[Signal]


class ApprovalSink(Protocol):
    def request(self, candidate: CandidateAction, *, summary: str) -> str: ...


@dataclass
class MemoryApprovalSink:
    requested: list[CandidateAction] = field(default_factory=list)

    def request(self, candidate: CandidateAction, *, summary: str) -> str:
        self.requested.append(candidate)
        return f"approval-{len(self.requested)}"


def _merge(a: dict[str, Any] | None, b: dict[str, Any] | None) -> dict[str, Any]:
    return {**(a or {}), **(b or {})}


class OrchestratorState(TypedDict, total=False):
    incident: dict[str, Any]
    route: list[str]
    outcomes: Annotated[dict[str, Any], _merge]
    plan: dict[str, Any]
    priority: list[str]
    summary: str
    approvals: Annotated[list[str], operator.add]
    status: str


class OrchestratorResult(BaseModel):
    status: Literal["completed", "awaiting_approval"]
    summary: str
    outcomes: dict[str, AgentOutcome]
    plan: PlanProposal
    priority: list[str]
    approvals: list[str]
    mode: str
    usage: Usage = Field(default_factory=Usage)


NODE_ORDER = (OPERATIONS, INVENTORY, FORECASTING)


def next_node(state: OrchestratorState, current: str) -> str:
    """Shared routing: next specialist in the triaged route, then ``plan``."""
    route = state.get("route", [])
    if current == "triage":
        return route[0] if route else "plan"
    idx = route.index(current) if current in route else len(route)
    return route[idx + 1] if idx + 1 < len(route) else "plan"


class _Narrative(BaseModel):
    summary: str = Field(min_length=20, max_length=1500)
    priority: list[str] = Field(default_factory=list, max_length=10)


@dataclass
class Orchestrator:
    runner: AgentRunner
    recorder: StepRecorder
    sink: ApprovalSink
    ctx: ToolContext
    provider: LLMProvider | None = None
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    checkpointer: Any = None
    # Candidate ids a human already rejected in this context: never re-proposed automatically.
    excluded_candidates: frozenset[str] = frozenset()

    # --- nodes ---------------------------------------------------------------------------
    def triage(self, state: OrchestratorState) -> dict[str, Any]:
        incident = IncidentInfo.model_validate(state["incident"])
        kinds = {s.kind for s in incident.signals}
        route = [OPERATIONS]
        if "stockout_risk" in kinds:
            route.append(INVENTORY)
        route.append(FORECASTING)
        names = {OPERATIONS: "operação", INVENTORY: "estoque", FORECASTING: "previsão"}
        reason = (
            "O agente de operação avalia a capacidade da cozinha, o de estoque entra quando há risco de faltar "
            "ingrediente e o de previsão estima a demanda das próximas horas."
        )
        self.recorder.record(
            agent="orchestrator",
            kind="decision",
            title="Triagem do incidente",
            output={"signals": sorted(kinds), "route": [names[r] for r in route], "reason": reason},
        )
        return {"route": route}

    def _specialist(
        self, name: str, state: OrchestratorState, objective: str, focus: list[str] | None = None
    ) -> dict[str, Any]:
        incident = IncidentInfo.model_validate(state["incident"])
        task = AgentTask(objective=objective, signals=incident.signals, focus_ingredients=focus or [])
        outcome = self.runner.run(SPECIALISTS[name], task, self.ctx)
        return {"outcomes": {name: outcome.model_dump(mode="json")}}

    def operations(self, state: OrchestratorState) -> dict[str, Any]:
        return self._specialist(
            OPERATIONS, state, "Avalie fila, tempos de preparo e risco de atraso nas próximas horas."
        )

    def inventory(self, state: OrchestratorState) -> dict[str, Any]:
        incident = IncidentInfo.model_validate(state["incident"])
        focus = [s.subject for s in incident.signals if s.kind == "stockout_risk"]
        return self._specialist(
            INVENTORY, state, "Identifique ingredientes críticos e itens do cardápio afetados.", focus
        )

    def forecasting(self, state: OrchestratorState) -> dict[str, Any]:
        outcomes = state.get("outcomes", {})
        inv = outcomes.get(INVENTORY)
        focus: list[str] = []
        if inv:
            status = (inv.get("data") or {}).get("get_inventory_status") or {}
            focus = [
                r["ingredient_key"] for r in status.get("ingredients", []) if r["risk"] in ("high", "critical", "out")
            ]
        return self._specialist(
            FORECASTING, state, "Projete a demanda e o consumo de ingredientes nas próximas 2 horas.", focus
        )

    def plan(self, state: OrchestratorState) -> dict[str, Any]:
        outcomes = {k: AgentOutcome.model_validate(v) for k, v in (state.get("outcomes") or {}).items()}
        ops, inv, fc = outcomes.get(OPERATIONS), outcomes.get(INVENTORY), outcomes.get(FORECASTING)
        forecast = (
            ForecastResult.model_validate(fc.data["get_demand_forecast"])
            if fc and "get_demand_forecast" in fc.data
            else None
        )
        evidence = {
            "operations": (ops.evidence.get("get_kitchen_snapshot") if ops else None) or "",
            "inventory": (inv.evidence.get("get_inventory_status") if inv else None) or "",
            "forecast": (fc.evidence.get("get_demand_forecast") if fc else None) or "",
        }
        candidates: list[CandidateAction] = []
        recs: list[Recommendation] = []
        assumptions: list[str] = []
        if inv and forecast:
            contexts = self._ingredient_contexts(inv)
            c, r, a = plan_inventory_actions(
                as_of=self.ctx.as_of, ingredients=contexts, forecast=forecast, evidence=evidence, cfg=self.policy
            )
            candidates, recs, assumptions = c, r, a
        capacity = None
        ops_forecast = (
            ForecastResult.model_validate(ops.data["get_demand_forecast"])
            if ops and "get_demand_forecast" in ops.data
            else forecast
        )
        if ops and ops_forecast and "get_kitchen_snapshot" in ops.data and "get_kitchen_capacity" in ops.data:
            cap = ops.data["get_kitchen_capacity"]
            capacity = capacity_analysis(
                snapshot=KitchenSnapshot.model_validate(ops.data["get_kitchen_snapshot"]),
                lines_available=cap["lines_available"],
                service_minutes=cap["estimated_service_minutes"],
                forecast=ops_forecast,
                cfg=self.policy,
            )
            delayed = [o["order_ref"] for o in (ops.data.get("list_open_orders") or {}).get("orders", [])]
            recs = plan_kitchen_recommendations(capacity=capacity, delayed_refs=delayed, evidence=evidence) + recs
        if forecast is None:
            assumptions.append("Sem previsão disponível, nenhuma ação de estoque foi sugerida.")
        skipped = [c for c in candidates if c.candidate_id in self.excluded_candidates]
        if skipped:
            candidates = [c for c in candidates if c.candidate_id not in self.excluded_candidates]
            assumptions += [
                f"“{c.title}” já foi rejeitada pelo gerente nesta simulação e não foi sugerida de novo."
                for c in skipped
            ]
        proposal = PlanProposal(candidates=candidates, recommendations=recs, capacity=capacity, assumptions=assumptions)
        priority = [c.candidate_id for c in candidates]
        summary = self._deterministic_summary(outcomes, proposal)
        narrative_mode = "deterministic"
        if self.provider is not None:
            try:
                summary, priority = self._narrative(outcomes, proposal, priority)
                narrative_mode = "llm"
            except (LLMError, ValidationError, ValueError) as exc:
                self.recorder.record(
                    agent="orchestrator",
                    kind="fallback",
                    title="Falha no modelo, resumo do plano feito por regras",
                    status="error",
                    output={"reason": str(exc)[:200]},
                )
        self.recorder.record(
            agent="orchestrator",
            kind="decision",
            title="Plano proposto",
            output={
                "summary": summary,
                "summary_mode": narrative_mode,
                "candidates": [
                    {"id": c.candidate_id, "title": c.title, "requires_approval": c.requires_approval}
                    for c in candidates
                ],
                "priority": priority,
                "recommendations": [r.title for r in recs],
                "capacity": capacity.model_dump() if capacity else None,
                "assumptions": assumptions,
            },
        )
        return {"plan": proposal.model_dump(mode="json"), "priority": priority, "summary": summary}

    def request_approvals(self, state: OrchestratorState) -> dict[str, Any]:
        proposal = PlanProposal.model_validate(state["plan"])
        by_id = {c.candidate_id: c for c in proposal.candidates}
        ids: list[str] = []
        for cid in state.get("priority", []):
            candidate = by_id.get(cid)
            if candidate is None or not candidate.requires_approval:
                continue
            approval_id = self.sink.request(candidate, summary=state.get("summary", ""))
            ids.append(approval_id)
            self.recorder.record(
                agent="orchestrator",
                kind="approval_request",
                title=f"Aprovação solicitada: {candidate.title}",
                output={"approval_id": approval_id, "action_type": candidate.action_type, "candidate_id": cid},
            )
        status = "awaiting_approval" if ids else "completed"
        return {"approvals": ids, "status": status}

    # --- helpers --------------------------------------------------------------------------
    @staticmethod
    def _ingredient_contexts(inv: AgentOutcome) -> list[IngredientContext]:
        status = inv.data.get("get_inventory_status") or {"ingredients": []}
        details = inv.data.get("_details", {})
        contexts: list[IngredientContext] = []
        for row in status["ingredients"]:
            d = details.get(row["ingredient_key"])
            if not d:
                continue
            contexts.append(
                IngredientContext(
                    risk=IngredientRisk.model_validate(row),
                    pack_size=d["pack_size"],
                    lead_time_minutes=d["lead_time_minutes"],
                    unit_cost_cents=d["unit_cost_cents"],
                    open_po_qty=d["open_po_qty"],
                    affected_items=[AffectedItem.model_validate(i) for i in d["affected_items"]],
                )
            )
        return contexts

    def _deterministic_summary(self, outcomes: dict[str, AgentOutcome], proposal: PlanProposal) -> str:
        clock = to_local(self.ctx.as_of).strftime("%H:%M")
        parts = [f"Análise às {clock} (horário simulado)."]
        inv = outcomes.get(INVENTORY)
        if inv:
            parts.append(inv.summary.split(". Itens afetados")[0].rstrip(".") + ".")
        if proposal.capacity:
            c = proposal.capacity
            parts.append(
                f"Cozinha: utilização projetada de {pct(c.projected_utilization)} "
                f"(~{num(c.projected_orders_per_hour)} pedidos/h para uma capacidade de ~{num(c.capacity_orders_per_hour)}/h)."
            )
        if proposal.candidates:
            listed = "; ".join(f"({i}) {c.title}" for i, c in enumerate(proposal.candidates, 1))
            n = len(proposal.candidates)
            parts.append(f"{n} {'ação' if n == 1 else 'ações'} aguardando aprovação do gerente: {listed}.")
        else:
            parts.append("Nenhuma ação precisa de aprovação agora.")
        if proposal.recommendations:
            parts.append("Recomendações: " + "; ".join(r.title for r in proposal.recommendations[:3]) + ".")
        return " ".join(parts)

    def _narrative(
        self, outcomes: dict[str, AgentOutcome], proposal: PlanProposal, default_priority: list[str]
    ) -> tuple[str, list[str]]:
        assert self.provider is not None
        payload = {
            "achados": {
                k: {"resumo": v.summary, "fatos": [f.model_dump() for f in v.facts]} for k, v in outcomes.items()
            },
            "acoes_candidatas": [
                {"id": c.candidate_id, "titulo": c.title, "justificativa": c.rationale, "impacto": c.expected_impact}
                for c in proposal.candidates
            ],
            "recomendacoes": [r.title for r in proposal.recommendations],
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "Você é o orquestrador de agentes de um restaurante. Escreva um resumo executivo (até 120 palavras) "
                    "do incidente e ordene as ações candidatas por prioridade. Use somente os dados fornecidos, não crie "
                    'ações novas e não prometa resultados. Responda apenas JSON: {"summary": str, "priority": [ids]}.'
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        resp = self.provider.chat(messages, json_mode=True, max_tokens=500)
        self.recorder.record(
            agent="orchestrator",
            kind="model_call",
            title=f"Resumo do plano pelo modelo {resp.model}",
            latency_ms=resp.latency_ms,
            output={"prompt_tokens": resp.usage.prompt_tokens, "completion_tokens": resp.usage.completion_tokens},
        )
        text = resp.content or ""
        start, end = text.find("{"), text.rfind("}")
        parsed = _Narrative.model_validate_json(text[start : end + 1] if start >= 0 else text)
        valid = [p for p in parsed.priority if p in default_priority]
        priority = list(dict.fromkeys(valid + default_priority))  # model may reorder, never drop or invent
        return validate_model_text(parsed.summary), priority

    # --- execution ------------------------------------------------------------------------
    def build_graph(self) -> Any:
        # Imported lazily so node-level unit tests do not require LangGraph.
        from langgraph.graph import END, START, StateGraph

        graph = StateGraph(OrchestratorState)
        for name in ("triage", OPERATIONS, INVENTORY, FORECASTING, "plan", "request_approvals"):
            graph.add_node(name, getattr(self, name))
        graph.add_edge(START, "triage")
        targets = [OPERATIONS, INVENTORY, FORECASTING, "plan"]
        for node in ("triage", OPERATIONS, INVENTORY, FORECASTING):
            graph.add_conditional_edges(node, lambda s, _n=node: next_node(s, _n), targets)
        graph.add_edge("plan", "request_approvals")
        graph.add_edge("request_approvals", END)
        return graph.compile(checkpointer=self.checkpointer)

    def run_sequential(self, state: OrchestratorState) -> OrchestratorState:
        """Dependency-free execution following :func:`next_node` (unit-test harness)."""
        current = "triage"
        while True:
            update = getattr(self, current)(state)
            state = _apply(state, update)
            if current in ("plan", "request_approvals"):
                if current == "request_approvals":
                    return state
                current = "request_approvals"
                continue
            current = next_node(state, current)

    def run(
        self,
        incident: IncidentInfo,
        *,
        engine: Literal["langgraph", "sequential"] = "langgraph",
        thread_id: str | None = None,
    ) -> OrchestratorResult:
        initial: OrchestratorState = {"incident": incident.model_dump(mode="json"), "outcomes": {}, "approvals": []}
        if engine == "langgraph":
            config = {"configurable": {"thread_id": thread_id or incident.incident_id}}
            final: OrchestratorState = self.build_graph().invoke(initial, config=config)
        else:
            final = self.run_sequential(initial)
        outcomes = {k: AgentOutcome.model_validate(v) for k, v in (final.get("outcomes") or {}).items()}
        usage = Usage(
            prompt_tokens=sum(o.usage.prompt_tokens for o in outcomes.values()),
            completion_tokens=sum(o.usage.completion_tokens for o in outcomes.values()),
        )
        modes = {o.mode for o in outcomes.values()}
        mode = modes.pop() if len(modes) == 1 else "mixed"
        return OrchestratorResult(
            status="awaiting_approval" if final.get("approvals") else "completed",
            summary=final.get("summary", ""),
            outcomes=outcomes,
            plan=PlanProposal.model_validate(final["plan"]),
            priority=final.get("priority", []),
            approvals=list(final.get("approvals", [])),
            mode=mode,
            usage=usage,
        )


def _apply(state: OrchestratorState, update: dict[str, Any]) -> OrchestratorState:
    new: dict[str, Any] = dict(state)
    for key, value in update.items():
        if key == "outcomes":
            new[key] = _merge(new.get(key), value)
        elif key == "approvals":
            new[key] = list(new.get(key, [])) + list(value)
        else:
            new[key] = value
    return new  # type: ignore[return-value]
