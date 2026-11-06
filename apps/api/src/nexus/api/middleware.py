"""HTTP middleware: request ids, access logs, security headers, body limits, rate limits."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from nexus.config import Settings
from nexus.logging_config import request_id_var

log = logging.getLogger("nexus.http")

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
LIVE_POLLS_PER_MINUTE = 150
API_ROOT = "/api/v1/"


class ServicePrefixMiddleware:
    """Serverless only: if a platform-generated service URL carries a path prefix, drop it.

    Vercel service bindings inject an absolute base URL; should that base include a path,
    ``<prefix>/api/v1/...`` is mapped back to ``/api/v1/...`` so routes still match.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._logged = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path: str = scope.get("path", "")
            index = path.find(API_ROOT)
            if index > 0:
                if not self._logged:
                    self._logged = True
                    log.warning("stripping service path prefix", extra={"prefix": path[:index][:80]})
                scope = {**scope, "path": path[index:], "raw_path": path[index:].encode()}
        await self.app(scope, receive, send)


class SlidingWindowLimiter:
    """In-process sliding-window limiter (per API instance).

    Good enough for a single container; a multi-instance deployment should move
    this to Redis or the database (see docs/adr/0005-security-baseline.md).
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, *, limit: int, window_seconds: float = 60.0) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > window_seconds:
                q.popleft()
            if len(q) >= limit:
                retry = int(window_seconds - (now - q[0])) + 1
                return False, retry
            q.append(now)
            if len(self._hits) > 50_000:  # bound memory
                for k in list(self._hits)[:10_000]:
                    if not self._hits[k]:
                        self._hits.pop(k, None)
            return True, 0


limiter = SlidingWindowLimiter()


def _error(status: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers=headers)


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, settings: Settings) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.settings = settings

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if 8 <= len(incoming) <= 64 and incoming.replace("-", "").isalnum() else uuid.uuid4().hex
        token = request_id_var.set(rid)
        started = time.perf_counter()
        try:
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > self.settings.max_ingest_body_bytes:
                return _error(413, "payload_too_large", "Corpo da requisição excede o limite.")
            path = request.url.path
            if path.startswith("/api/") and not path.endswith("/stream"):
                auth = request.headers.get("authorization", "")
                ip = request.client.host if request.client else "unknown"
                subject = f"auth:{hash(auth)}" if auth else f"ip:{ip}"
                if path.endswith("/live"):
                    # Dashboards poll /live about once per second: own budget, not the general one.
                    ok, retry = limiter.check(f"live:{subject}", limit=LIVE_POLLS_PER_MINUTE)
                else:
                    ok, retry = limiter.check(f"all:{subject}", limit=self.settings.rate_limit_per_minute)
                if ok and request.method in MUTATING:
                    ok, retry = limiter.check(f"mut:{subject}", limit=self.settings.rate_limit_mutations_per_minute)
                if not ok:
                    return _error(
                        429,
                        "rate_limited",
                        "Muitas requisições; tente novamente em instantes.",
                        {"Retry-After": str(retry)},
                    )
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        elapsed = int((time.perf_counter() - started) * 1000)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
        if not request.url.path.endswith(("/stream", "/live")):  # high-frequency feeds stay out of access logs
            log.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "ms": elapsed,
                    "request_id": rid,
                },
            )
        return response
