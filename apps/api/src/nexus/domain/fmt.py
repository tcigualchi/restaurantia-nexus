"""pt-BR formatting helpers for human-facing strings produced by deterministic code."""

from __future__ import annotations


def num(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "—"
    text = f"{value:,.{digits}f}"
    return text.replace(",", "§").replace(".", ",").replace("§", ".")


def qty(value: float, unit: str) -> str:
    if unit == "g" and abs(value) >= 1000:
        return f"{num(value / 1000, 1)} kg"
    if unit == "ml" and abs(value) >= 1000:
        return f"{num(value / 1000, 1)} L"
    return f"{num(value, 0)} {unit}"


def brl(cents: int | float) -> str:
    return f"R$ {num(cents / 100, 2)}"


def pct(ratio: float, digits: int = 0) -> str:
    return f"{num(ratio * 100, digits)}%"


def lower_first(text: str) -> str:
    """Lower-cases the first letter so a catalog name reads naturally mid-sentence."""
    return text[:1].lower() + text[1:]
