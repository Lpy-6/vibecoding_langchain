"""Health, readiness and Prometheus metrics."""
from __future__ import annotations

import shutil

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.core.config import settings
from app.db.session import async_engine
from app.ingest.vector_index import vector_index_manager

router = APIRouter(tags=["ops"])


@router.get("/healthz")
async def healthz():
    return {"status": "ok", "app": settings.app_name}


@router.get("/readyz")
async def readyz():
    components: dict[str, str] = {}
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        components["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        components["database"] = f"error: {exc}"
    try:
        usage = shutil.disk_usage(settings.data_dir)
        components["storage"] = f"ok ({usage.free // (1024 * 1024)} MB free)"
    except Exception as exc:  # noqa: BLE001
        components["storage"] = f"error: {exc}"
    components["llm_mode"] = settings.effective_llm_mode
    components["vector_index"] = str(vector_index_manager.stats())
    status = "ok" if components["database"] == "ok" else "degraded"
    return {"status": status, "components": components}


@router.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
