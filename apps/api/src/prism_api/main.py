from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prism_api_contracts import HealthResponse
from prism_config.settings import get_settings

from .ai_analyst import router as ai_analyst_router
from .clean import router as clean_router
from .migration import PHASE_1_MIGRATIONS
from .overview import router as overview_router
from .sql_lab import router as sql_lab_router
from .transport import phase_1_event_stream, sse_response
from .visualize import router as visualize_router

REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def create_app() -> FastAPI:
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

    @app.middleware("http")
    async def trace_requests(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        supplied = request.headers.get("X-Request-ID", "")
        request_id = supplied if REQUEST_ID.fullmatch(supplied) else f"req_{uuid.uuid4().hex}"
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.get("/api/v1/platform/health", response_model=HealthResponse, tags=["platform"])
    def health() -> HealthResponse:
        return HealthResponse(
            generated_at=datetime.now(timezone.utc), migrations=PHASE_1_MIGRATIONS
        )

    @app.get("/api/v1/platform/events", tags=["platform"])
    async def events():  # type: ignore[no-untyped-def]
        return sse_response(phase_1_event_stream())

    return app


app = create_app()
