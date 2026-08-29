from __future__ import annotations

import logging
import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prism_api_contracts import HealthResponse, ProviderReadiness, ReadinessResponse
from prism_config.settings import get_settings

from .ai_analyst import router as ai_analyst_router
from .clean import router as clean_router
from .forecasting import router as forecasting_router
from .migration import PHASE_1_MIGRATIONS
from .overview import router as overview_router
from .sql_lab import router as sql_lab_router
from .stats import router as stats_router
from .transport import phase_1_event_stream, sse_response
from .visualize import router as visualize_router

REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
logger = logging.getLogger("prism_api")


def _configure_logging() -> None:
    """Structured, greppable request logs on stdout — the default in a bare `uvicorn` process
    (no logging.basicConfig anywhere) is that INFO-level logs are silently dropped, which would
    leave a deployment with no request/duration/error visibility at all. Idempotent: safe to call
    from multiple create_app() invocations (tests included) without duplicating handlers."""
    target = logging.getLogger("prism_api")
    if target.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    target.addHandler(handler)
    target.setLevel(os.environ.get("PRISM_LOG_LEVEL", "INFO").upper())


def create_app() -> FastAPI:
    _configure_logging()
    settings = get_settings()
    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
    )
    if settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[str(origin) for origin in settings.allowed_origins],
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "X-Request-ID"],
        )
    app.include_router(overview_router)
    app.include_router(sql_lab_router)
    app.include_router(ai_analyst_router)
    app.include_router(clean_router)
    app.include_router(visualize_router)
    app.include_router(stats_router)
    app.include_router(forecasting_router)

    @app.middleware("http")
    async def trace_requests(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        supplied = request.headers.get("X-Request-ID", "")
        request_id = supplied if REQUEST_ID.fullmatch(supplied) else f"req_{uuid.uuid4().hex}"
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            logger.exception(
                "request_failed request_id=%s method=%s path=%s duration_ms=%s",
                request_id, request.method, request.url.path, duration_ms,
                extra={"request_id": request_id, "method": request.method, "path": request.url.path, "duration_ms": duration_ms},
            )
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_completed request_id=%s method=%s path=%s status=%s duration_ms=%s",
            request_id, request.method, request.url.path, response.status_code, duration_ms,
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response

    @app.get("/api/v1/platform/health", response_model=HealthResponse, tags=["platform"])
    def health() -> HealthResponse:
        """Liveness: the process is up and can respond. Never checks external dependencies."""
        return HealthResponse(
            generated_at=datetime.now(timezone.utc), migrations=PHASE_1_MIGRATIONS
        )

    @app.get("/api/v1/platform/ready", response_model=ReadinessResponse, tags=["platform"])
    def ready() -> ReadinessResponse:
        """Readiness: PRISM has no dependency it cannot function without, so this always reports
        ready — the deterministic path works with every optional provider unavailable. Provider
        entries are diagnostic only (configuration state, not a live network probe: a readiness
        check must stay fast and must not itself hang waiting on an optional external service)."""
        provider = os.environ.get("PRISM_AI_PROVIDER", "deterministic").lower()
        configured = provider == "ollama"
        providers = (
            ProviderReadiness(
                name="ollama",
                status="configured" if configured else "not_configured",
                detail=(
                    "PRISM_AI_PROVIDER=ollama; AI Analyst probes reachability per-request and falls "
                    "back deterministically on failure, never blocking startup or readiness."
                    if configured
                    else "PRISM_AI_PROVIDER is not set to 'ollama'; AI Analyst uses its deterministic path."
                ),
            ),
        )
        return ReadinessResponse(generated_at=datetime.now(timezone.utc), providers=providers)

    @app.get("/api/v1/platform/events", tags=["platform"])
    async def events():  # type: ignore[no-untyped-def]
        return sse_response(phase_1_event_stream())

    return app


app = create_app()
