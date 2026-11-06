"""FastAPI application factory."""

from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from nexus.api.middleware import RequestContextMiddleware, ServicePrefixMiddleware
from nexus.api.routes import auth, operations, restaurants, stream, system
from nexus.config import Settings, get_settings
from nexus.domain.errors import DomainError, RateLimited
from nexus.logging_config import configure_logging, request_id_var

log = logging.getLogger("nexus.app")

DESCRIPTION = """
API do RestaurantIA Nexus, um projeto de portfólio sobre agentes de IA na operação de restaurantes.

* Todos os dados são sintéticos. Não há integração com iFood nem com outras plataformas.
* Os agentes sugerem ações, e as ações sensíveis só são executadas depois de aprovadas por uma pessoa e conferidas de novo.
* Cada restaurante é um tenant isolado: toda rota sob `/restaurants/{restaurant_id}` exige associação.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        stop = threading.Event()
        thread = None
        if settings.embedded_worker:
            from nexus.worker.main import run_worker

            thread = threading.Thread(
                target=run_worker, kwargs={"stop": stop, "settings": settings}, name="embedded-worker", daemon=True
            )
            thread.start()
            log.info("embedded worker started")
        yield
        stop.set()
        if thread is not None:
            thread.join(timeout=5)

    app = FastAPI(
        title="RestaurantIA Nexus API",
        version=settings.app_version,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings = settings  # route dependencies (SettingsDep) read these, not a global
    app.add_middleware(RequestContextMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Last-Event-ID"],
        max_age=600,
    )
    if settings.serverless:
        app.add_middleware(ServicePrefixMiddleware)  # outermost: fixes the path before anything routes it

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        headers = {"Retry-After": str(exc.retry_after_seconds)} if isinstance(exc, RateLimited) else None
        return JSONResponse(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": request_id_var.get(),
                }
            },
            status_code=exc.status_code,
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()][
            :20
        ]
        return JSONResponse(
            {
                "error": {
                    "code": "validation_failed",
                    "message": "Requisição inválida.",
                    "details": {"errors": errors},
                    "request_id": request_id_var.get(),
                }
            },
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return JSONResponse(
            {"error": {"code": "internal_error", "message": "Erro interno.", "request_id": request_id_var.get()}},
            status_code=500,
        )

    for module in (system, auth, restaurants, operations, stream):
        app.include_router(module.router)
    return app


app = create_app()
