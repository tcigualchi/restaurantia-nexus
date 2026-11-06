"""Deterministic risk detectors.

Detectors are cheap threshold rules evaluated after every simulated minute. They
decide *when* the agents are called; they never decide *what* to do. Thresholds
are explicit and documented so that an operator can audit why an incident opened.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from nexus.domain.fmt import num, qty
from nexus.domain.metrics import IngredientRisk, KitchenSnapshot


@dataclass(frozen=True)
class DetectorConfig:
    kitchen_queue_threshold: int = 10
    kitchen_oldest_fraction_of_sla: float = 0.5
    kitchen_p90_fraction_of_sla: float = 1.0
    stock_risk_levels: tuple[str, ...] = ("high", "critical", "out")


class Signal(BaseModel):
    kind: str  # kitchen_delay_risk | stockout_risk
    severity: str  # medium | high | critical
    subject: str  # e.g. ingredient key or "kitchen"
    message: str
    metrics: dict[str, float | int | str | None]


def kitchen_signals(snapshot: KitchenSnapshot, cfg: DetectorConfig = DetectorConfig()) -> list[Signal]:
    sla = snapshot.sla_minutes
    oldest = snapshot.oldest_open_minutes or 0.0
    p90 = snapshot.p90_prep_minutes or 0.0
    queue_pressure = (
        snapshot.queue_length >= cfg.kitchen_queue_threshold and oldest >= cfg.kitchen_oldest_fraction_of_sla * sla
    )
    sla_pressure = p90 >= cfg.kitchen_p90_fraction_of_sla * sla
    if not (queue_pressure or sla_pressure):
        return []
    severity = "critical" if p90 >= 1.3 * sla else "high" if sla_pressure else "medium"
    reasons = []
    if queue_pressure:
        reasons.append(f"fila com {snapshot.queue_length} pedidos e o mais antigo há {num(oldest)} min")
    if sla_pressure:
        reasons.append(f"p90 de preparo em {num(p90)} min (SLA {sla} min)")
    return [
        Signal(
            kind="kitchen_delay_risk",
            severity=severity,
            subject="kitchen",
            message="Risco de atraso na cozinha: " + "; ".join(reasons) + ".",
            metrics={
                "queue_length": snapshot.queue_length,
                "oldest_open_minutes": snapshot.oldest_open_minutes,
                "p90_prep_minutes": snapshot.p90_prep_minutes,
                "sla_minutes": sla,
            },
        )
    ]


def stock_signals(risks: Sequence[IngredientRisk], cfg: DetectorConfig = DetectorConfig()) -> list[Signal]:
    signals: list[Signal] = []
    for r in risks:
        if r.risk not in cfg.stock_risk_levels:
            continue
        severity = "critical" if r.risk in ("critical", "out") else "high"
        eta = f"{num(r.eta_minutes)} min" if r.eta_minutes is not None else "indeterminado"
        signals.append(
            Signal(
                kind="stockout_risk",
                severity=severity,
                subject=r.ingredient_key,
                message=(
                    f"Risco de ruptura de {r.name}: {qty(r.stock, r.unit)} em estoque, "
                    f"consumo de {qty(r.consumption_per_hour, r.unit)}/h, esgota em ~{eta}."
                ),
                metrics={
                    "name": r.name,
                    "stock": r.stock,
                    "safety_stock": r.safety_stock,
                    "consumption_per_hour": r.consumption_per_hour,
                    "eta_minutes": r.eta_minutes,
                    "risk": r.risk,
                },
            )
        )
    return signals


SEVERITY_ORDER = {"medium": 1, "high": 2, "critical": 3}


def incident_title(signals: Sequence[Signal]) -> str:
    kinds = {s.kind for s in signals}
    if kinds == {"kitchen_delay_risk", "stockout_risk"}:
        return "Risco combinado: atraso na cozinha e ruptura de estoque"
    if "stockout_risk" in kinds:
        names = ", ".join(
            sorted({str(s.metrics.get("name") or s.subject) for s in signals if s.kind == "stockout_risk"})
        )
        return f"Risco de ruptura de estoque ({names})"
    return "Risco de atraso na cozinha"


def max_severity(signals: Sequence[Signal]) -> str:
    return max((s.severity for s in signals), key=lambda s: SEVERITY_ORDER[s], default="medium")
