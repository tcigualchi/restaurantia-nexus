from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from nexus.api.deps import DbDep, SettingsDep
from nexus.application.views import ScenarioView
from nexus.domain.simulation import SCENARIOS

router = APIRouter(tags=["system"])


@router.get("/healthz", summary="Liveness probe")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", summary="Readiness probe (database reachable and migrated)")
def readyz(db: DbDep) -> JSONResponse:
    try:
        db.execute(text("SELECT 1"))
        version = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except Exception:
        return JSONResponse({"status": "unavailable", "database": "unreachable"}, status_code=503)
    if version is None:
        return JSONResponse({"status": "unavailable", "database": "not_migrated"}, status_code=503)
    return JSONResponse({"status": "ready", "database": "ok", "migration": version})


@router.get("/api/v1/system/info", summary="Public runtime information (no secrets)")
def system_info(settings: SettingsDep) -> dict[str, object]:
    llm = settings.llm
    return {
        "name": "RestaurantIA Nexus",
        "version": settings.app_version,
        "environment": settings.app_env,
        "agents": {
            "mode": "llm" if llm.enabled else "deterministic",
            "provider": llm.provider if llm.enabled else "deterministic",
            "model": llm.model if llm.enabled else None,
            "label": (
                f"LLM configurado ({llm.model})"
                if llm.enabled
                else "Modo determinístico (sem LLM): agentes seguem planos de ferramentas e resumos por template."
            ),
            "cost_tracking": llm.price_input_per_mtok_usd is not None,
        },
        "demo": {"enabled": settings.demo_enabled, "session_ttl_minutes": settings.demo_session_ttl_minutes},
        "data_notice": "Todos os dados são sintéticos. Sem vínculo com iFood ou outras plataformas.",
    }


@router.get("/api/v1/scenarios", response_model=list[ScenarioView], summary="Available simulation scenarios")
def scenarios() -> list[ScenarioView]:
    return [
        ScenarioView(
            key=s.key,
            name=s.name,
            description=s.description,
            total_ticks=s.total_ticks,
            featured=s.featured,
            tags=list(s.tags),
            auto_pause_on_approval=s.auto_pause_on_approval,
        )
        for s in SCENARIOS.values()
    ]
