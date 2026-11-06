"""Guardrails for untrusted text and model output.

Defence in depth against prompt injection:

1. **Architecture first** — tools are read-only or "propose-only"; tenant and
   time scope are injected by the server, never taken from model arguments;
   sensitive actions require human approval and are revalidated at execution.
2. **Untrusted data marking** — free text that originates outside the system
   (order notes, documents, complaints) is wrapped and labelled before it reaches
   a model, and suspicious instructions are neutralised.
3. **Output checks** — model output is scanned for secrets and length limits
   before being stored or displayed.

Pattern matching alone is not a complete defence; it is one layer and makes
attempts visible in traces and audit logs.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

MAX_UNTRUSTED_CHARS = 500

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(rx, re.IGNORECASE))
    for name, rx in (
        (
            "override_instructions",
            r"\b(ignore|ignora|ignorar|desconsidere|esque[cç]a)\b.{0,40}\b(instru|instruction|regras|rules|prompt)",
        ),
        ("role_hijack", r"\b(you are now|voc[eê] agora [ée]|act as|aja como|finja ser)\b"),
        (
            "system_prompt_exfiltration",
            r"\b(system prompt|prompt do sistema|revele|reveal|mostre).{0,30}(prompt|instru|segredo|secret|chave|key)",
        ),
        (
            "approval_manipulation",
            r"\b(aprove|approve|autorize|authori[sz]e)\b.{0,60}\b(reembolso|refund|desconto|discount|pagamento|payment)",
        ),
        (
            "excessive_discount",
            r"(100\s*%|cem por cento).{0,20}\b(desconto|discount|off)\b|\b(desconto|discount)\b.{0,20}100\s*%",
        ),
        (
            "tool_injection",
            r"(\bcall\b|\bchame\b|\bexecute\b|\bexecutar\b).{0,30}\b(tool|ferramenta|function|fun[cç][aã]o)",
        ),
        ("markup_injection", r"<\s*/?\s*(script|system|assistant|tool)\b|```\s*(system|tool)"),
    )
)

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9\-_.=]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
    re.compile(r"postgres(?:ql)?(?:\+\w+)?://[^\s]+:[^\s]+@"),
)


@dataclass(frozen=True)
class SanitizedText:
    text: str
    flags: tuple[str, ...] = field(default_factory=tuple)
    truncated: bool = False

    @property
    def suspicious(self) -> bool:
        return bool(self.flags)


def detect_injection(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", text)
    return tuple(name for name, rx in _INJECTION_PATTERNS if rx.search(normalized))


def sanitize_untrusted(text: str, *, max_chars: int = MAX_UNTRUSTED_CHARS) -> SanitizedText:
    """Normalise, strip control characters, truncate and flag injection attempts.

    Suspicious content is not deleted (operators need to see it) but it is
    neutralised: the text is quoted and prefixed with a warning so a model reads
    it as data.
    """
    normalized = unicodedata.normalize("NFKC", text)
    cleaned = "".join(ch for ch in normalized if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    truncated = len(cleaned) > max_chars
    cleaned = cleaned[:max_chars]
    flags = detect_injection(cleaned)
    if flags:
        cleaned = "[CONTEÚDO NÃO CONFIÁVEL — instruções ignoradas] " + cleaned.replace("```", "'''")
    return SanitizedText(text=cleaned, flags=flags, truncated=truncated)


def wrap_untrusted(text: str, *, source: str) -> dict[str, object]:
    """Representation used inside tool results sent to a model."""
    s = sanitize_untrusted(text)
    return {
        "untrusted": True,
        "source": source,
        "text": s.text,
        "injection_flags": list(s.flags),
        "truncated": s.truncated,
    }


def redact_secrets(text: str) -> str:
    for rx in _SECRET_PATTERNS:
        text = rx.sub("[REDACTED]", text)
    return text


def validate_model_text(text: str, *, max_chars: int = 2000) -> str:
    """Post-process model prose before storing/displaying it."""
    text = redact_secrets(text.strip())
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text
