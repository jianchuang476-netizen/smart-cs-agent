from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from redis.asyncio import Redis

from app.api.health import router as health_router
from app.api.v1.router import api_router
from app.config import PROJECT_ROOT, get_settings
from app.core.agent import AgentRuntime
from app.db.seed import seed_database
from app.db.session import dispose_db, init_db
from app.logging_config import configure_logging, request_id_ctx

settings = get_settings()
configure_logging("DEBUG" if settings.app_debug else "INFO")

REQUEST_COUNT = Counter(
    "smart_cs_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "smart_cs_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.settings = settings
    if settings.auto_create_tables:
        await init_db()
    if settings.auto_seed:
        await seed_database()

    redis: Redis | None = None
    try:
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        await redis.ping()
    except Exception:
        if redis is not None:
            await redis.aclose()
        redis = None
    app.state.redis = redis

    runtime = AgentRuntime(settings)
    await runtime.startup()
    app.state.agent = runtime

    try:
        yield
    finally:
        await runtime.shutdown()
        if redis is not None:
            await redis.aclose()
        await dispose_db()


app = FastAPI(
    title=settings.app_name,
    description="基于 LangGraph、RAG 与人工审批的电商售后 Agent",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

app.mount(
    "/static",
    StaticFiles(directory=PROJECT_ROOT / "app" / "static"),
    name="static",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    request.state.trace_id = request_id
    token = request_id_ctx.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        REQUEST_COUNT.labels(request.method, request.url.path, "500").inc()
        raise
    finally:
        request_id_ctx.reset(token)
    elapsed = time.perf_counter() - started
    REQUEST_LATENCY.labels(request.method, request.url.path).observe(elapsed)
    REQUEST_COUNT.labels(request.method, request.url.path, str(response.status_code)).inc()
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "trace_id", None)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "服务内部错误",
            "code": "internal_error",
            "request_id": request_id,
        },
    )


@app.get("/docs", include_in_schema=False)
async def custom_docs():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url or "/openapi.json",
        title=f"{app.title} - Swagger UI",
        swagger_js_url="/static/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui.css",
        swagger_favicon_url="",
    )


@app.get("/redoc", include_in_schema=False)
async def redoc_redirect() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


app.include_router(health_router)
app.include_router(api_router, prefix=settings.api_v1_prefix)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
