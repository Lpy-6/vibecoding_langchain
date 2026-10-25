"""FastAPI application entrypoint (local, no-Docker deployment)."""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin, auth, chat, documents, health, kbs
from app.core.config import PROJECT_ROOT, settings
from app.core.metrics import HTTP_LATENCY, HTTP_REQUESTS
from app.db.session import init_db
from app.ingest.tasks import task_runner
from app.seed import seed_initial_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("jieba").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    await seed_initial_data()
    logger.info(
        "startup complete | llm_mode=%s | embedding=%s | data_dir=%s",
        settings.effective_llm_mode,
        settings.embedding_model if settings.use_dashscope else "offline-hashing-v1",
        settings.data_dir,
    )
    if settings.effective_llm_mode == "mock":
        logger.warning("未配置 DASHSCOPE_API_KEY：当前使用离线检索 + 抽取式回答模式")
    yield
    task_runner.shutdown()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="基于 LangChain 的电商商品知识库 RAG 问答系统（本地 SQLite + 混合检索）",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed = time.perf_counter() - started
        HTTP_REQUESTS.labels(request.method, request.url.path, "500").inc()
        HTTP_LATENCY.labels(request.method, request.url.path).observe(elapsed)
        logger.exception("unhandled error request_id=%s path=%s", request_id, request.url.path)
        raise
    elapsed = time.perf_counter() - started
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
    HTTP_LATENCY.labels(request.method, path).observe(elapsed)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = f"{elapsed * 1000:.1f}"
    return response


app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(kbs.router, prefix=settings.api_prefix)
app.include_router(chat.router, prefix=settings.api_prefix)
app.include_router(documents.router, prefix=settings.api_prefix)
app.include_router(admin.router, prefix=settings.api_prefix)
app.include_router(health.router)


dist_dir = PROJECT_ROOT / "frontend" / "dist"
if dist_dir.is_dir():
    assets_dir = dist_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        if full_path.startswith(settings.api_prefix.lstrip("/")) or full_path in {"metrics", "docs", "openapi.json"}:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = dist_dir / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist_dir / "index.html")
else:

    @app.get("/")
    async def root():
        return {
            "name": settings.app_name,
            "docs": "/docs",
            "health": "/healthz",
            "llm_mode": settings.effective_llm_mode,
            "frontend": "run `npm run dev` in frontend/ or build to frontend/dist",
        }
