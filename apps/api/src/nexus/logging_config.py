"""Structured JSON logging with secret redaction."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

from nexus.domain.guardrails import redact_secrets

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact_secrets(record.getMessage()),
        }
        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid
        for key, value in record.__dict__.items():
            if key not in self.RESERVED and not key.startswith("_"):
                payload[key] = redact_secrets(str(value)) if isinstance(value, str) else value
        if record.exc_info:
            payload["exc"] = redact_secrets(self.formatException(record.exc_info))[-2000:]
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
