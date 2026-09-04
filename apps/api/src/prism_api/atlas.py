"""Phase 10 Atlas runtime API: typed plans, visible specialists, SSE, and Cortex data."""

from __future__ import annotations

import threading

from fastapi import APIRouter, status
from prism_api_contracts import (
    AtlasModelProviderCapabilities,
    AtlasRunRequest,
    AtlasRunResponse,
    AtlasSandboxExecutionRequest,
    AtlasSandboxExecutionResult,
    AtlasSpecialistIdentity,
    CortexGraphState,
)

from .atlas_runtime import SPECIALISTS, cortex_graph, execute, providers, runs, stream_events
from .atlas_sandbox import AtlasPythonSandbox
from .transport import sse_response

router = APIRouter(prefix="/api/v1/atlas", tags=["atlas"])
sandbox = AtlasPythonSandbox()


@router.get("/providers", response_model=list[AtlasModelProviderCapabilities])
def list_providers() -> list[AtlasModelProviderCapabilities]:
    return providers.capabilities()


@router.get("/specialists", response_model=list[AtlasSpecialistIdentity])
def list_specialists() -> list[AtlasSpecialistIdentity]:
    return list(SPECIALISTS)


@router.post("/runs", response_model=AtlasRunResponse, status_code=status.HTTP_202_ACCEPTED)
def start_run(request: AtlasRunRequest) -> AtlasRunResponse:
    run = runs.create(request, providers.select())
    thread = threading.Thread(
        target=execute, args=(run.run_id,), name=f"atlas-{run.run_id[-8:]}", daemon=True
    )
    thread.start()
    return run


@router.get("/runs/{run_id}", response_model=AtlasRunResponse)
def get_run(run_id: str) -> AtlasRunResponse:
    return runs.get(run_id)


@router.post("/runs/{run_id}/cancel", response_model=AtlasRunResponse)
def cancel_run(run_id: str) -> AtlasRunResponse:
    return runs.request_cancel(run_id)


@router.post("/sandbox/executions", response_model=AtlasSandboxExecutionResult)
def execute_sandbox(request: AtlasSandboxExecutionRequest) -> AtlasSandboxExecutionResult:
    """Explicit, constrained analysis endpoint; there is no host shell endpoint."""
    return sandbox.execute(request)


@router.get("/runs/{run_id}/events")
async def events(run_id: str):  # type: ignore[no-untyped-def]
    return sse_response(stream_events(run_id))


@router.get("/runs/{run_id}/cortex", response_model=CortexGraphState)
def get_cortex_graph(run_id: str) -> CortexGraphState:
    return cortex_graph(run_id)
