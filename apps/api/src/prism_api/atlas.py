"""Phase 10 Atlas runtime API: typed plans, visible specialists, SSE, and Cortex data."""

from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException, Query, status
from prism_api_contracts import (
    AtlasKnowledgeChunk,
    AtlasKnowledgeSearchRequest,
    AtlasKnowledgeSourceRequest,
    AtlasMemoryClass,
    AtlasMemoryQuery,
    AtlasMemoryRecord,
    AtlasMemoryScope,
    AtlasMemoryWriteRequest,
    AtlasModelProviderCapabilities,
    AtlasResearchRequest,
    AtlasResearchResult,
    AtlasResourceLease,
    AtlasResourceLeaseRequest,
    AtlasResourceSnapshot,
    AtlasRunRequest,
    AtlasRunResponse,
    AtlasSandboxExecutionRequest,
    AtlasSandboxExecutionResult,
    AtlasSandboxWorkerHealth,
    AtlasSpecialistIdentity,
    CortexGraphState,
)

from .atlas_event_stream import durable_stream_events
from .atlas_memory import DurableAtlasMemoryStore
from .atlas_research import researcher
from .atlas_resources import governor
from .atlas_runtime import SPECIALISTS, cortex_graph, execute, providers, runs
from .atlas_sandbox import AtlasPythonSandbox
from .transport import sse_response

router = APIRouter(prefix="/api/v1/atlas", tags=["atlas"])
sandbox = AtlasPythonSandbox()
memory = DurableAtlasMemoryStore()


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


@router.get("/sandbox/health", response_model=AtlasSandboxWorkerHealth)
def sandbox_health() -> AtlasSandboxWorkerHealth:
    return sandbox.worker_health()


@router.post("/memories", response_model=AtlasMemoryRecord, status_code=status.HTTP_201_CREATED)
def write_memory(request: AtlasMemoryWriteRequest) -> AtlasMemoryRecord:
    return memory.create_or_reinforce(request)


@router.get("/memories", response_model=list[AtlasMemoryRecord])
def list_memories(
    scope: AtlasMemoryScope | None = None,
    knowledge_class: AtlasMemoryClass | None = None,
    project_id: str | None = None,
    workspace_id: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
) -> list[AtlasMemoryRecord]:
    return memory.query(AtlasMemoryQuery(scope=scope, knowledge_class=knowledge_class, project_id=project_id, workspace_id=workspace_id, limit=limit))


@router.post("/memories/{memory_id}/supersede", response_model=AtlasMemoryRecord)
def supersede_memory(memory_id: str, successor_id: str, contradiction: str) -> AtlasMemoryRecord:
    return memory.supersede(memory_id, successor_id, contradiction)


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_memory(memory_id: str) -> None:
    memory.delete_memory(memory_id)


@router.post("/knowledge/sources", response_model=list[AtlasKnowledgeChunk])
def index_project_knowledge(request: AtlasKnowledgeSourceRequest) -> list[AtlasKnowledgeChunk]:
    return memory.index_source(request)


@router.post("/knowledge/search", response_model=list[AtlasKnowledgeChunk])
def search_project_knowledge(request: AtlasKnowledgeSearchRequest) -> list[AtlasKnowledgeChunk]:
    return memory.search(request)


@router.delete("/knowledge/sources", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_project_knowledge(project_id: str, source_ref: str) -> None:
    memory.delete_source(project_id, source_ref)


@router.post("/research", response_model=AtlasResearchResult)
def run_research(request: AtlasResearchRequest) -> AtlasResearchResult:
    return researcher.research(request)


@router.post("/resources/leases", response_model=AtlasResourceLease, status_code=status.HTTP_201_CREATED)
def acquire_resource_lease(request: AtlasResourceLeaseRequest) -> AtlasResourceLease:
    return governor.acquire(request)


@router.delete("/resources/leases/{lease_id}", response_model=AtlasResourceLease)
def release_resource_lease(lease_id: str) -> AtlasResourceLease:
    try:
        return governor.release(lease_id)
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Atlas resource lease was not found.") from error


@router.get("/resources/snapshot", response_model=AtlasResourceSnapshot)
def resource_snapshot() -> AtlasResourceSnapshot:
    return governor.snapshot()


@router.get("/runs/{run_id}/events")
async def events(run_id: str):  # type: ignore[no-untyped-def]
    return sse_response(durable_stream_events(runs, run_id))


@router.get("/runs/{run_id}/cortex", response_model=CortexGraphState)
def get_cortex_graph(run_id: str) -> CortexGraphState:
    return cortex_graph(run_id)
