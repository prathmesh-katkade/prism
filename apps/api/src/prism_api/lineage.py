"""Phase 8B/8C/8D/8F read-only analytical-object registry, lineage-traversal,
freshness, and reproduction API.

Phase 8C adds deterministic graph traversal (parents/children/ancestors/descendants/
graph/path) on top of Phase 8B's read-only object retrieval. Phase 8D adds contextual
freshness (current/stale/superseded/unknown) computed live against DatasetStore's
active identity - never stored on the object. Phase 8F adds one controlled write
route, `/rerun`: it never overwrites an existing object, only ever creates a new one
from an existing object's own recorded configuration - everything else here stays
strictly read-only, built only from links producers already record, never AI-inferred.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from prism_analytical_schemas import (
    AnalyticalObject,
    FreshnessAssessment,
    LineageDirection,
    LineagePath,
    LineageTraversal,
    ObjectKind,
    ReproductionMode,
    ReproductionResponse,
)
from prism_api_contracts import AtlasLineageRequest, AtlasLineageResponse
from pydantic import BaseModel

from . import atlas_lineage, freshness_service, lineage_service, reproduction_service
from .analytical_objects import registry
from .overview import store as overview_store

router = APIRouter(prefix="/api/v1/lineage", tags=["lineage"])

# Bounded traversal: an unbounded max_depth is fine by default (BFS is already
# cycle-safe and the registry is process-local, so pathological size is not a
# realistic risk) - this only caps what a caller may explicitly request.
MAX_LINEAGE_DEPTH = 100

_NOT_FOUND = "Analytical object was not found."


class RerunRequest(BaseModel):
    """The only field a rerun caller may supply - every other configuration value is
    derived from the original object's own recorded provenance, never from the client."""

    mode: ReproductionMode


@router.get("/objects/{object_id}", response_model=AnalyticalObject)
def get_object(object_id: str) -> AnalyticalObject:
    record = registry.get(object_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return record


@router.get("/datasets/{dataset_id}/objects", response_model=list[AnalyticalObject])
def list_objects(
    dataset_id: str,
    revision: int | None = Query(None, ge=0),
    kind: ObjectKind | None = None,
) -> list[AnalyticalObject]:
    return registry.list_for_dataset(dataset_id, revision=revision, kind=kind)


@router.get("/history", response_model=list[AnalyticalObject])
def list_history(limit: int = Query(100, ge=1, le=500), kind: ObjectKind | None = None) -> list[AnalyticalObject]:
    """Bounded global analytical history, ordered newest-first.

    This is intentionally read-only. It is a research-history feed, not a
    generic lineage administration or mutation API.
    """
    return registry.list_recent(limit=limit, kind=kind)


@router.get("/objects/{object_id}/parents", response_model=list[AnalyticalObject])
def get_object_parents(object_id: str) -> list[AnalyticalObject]:
    """Direct parents only - never transitive. Use `/ancestors` for the full chain."""
    result = registry.get_parents(object_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return result


@router.get("/objects/{object_id}/children", response_model=list[AnalyticalObject])
def get_object_children(object_id: str) -> list[AnalyticalObject]:
    """Direct children only - never transitive. Use `/descendants` for the full chain."""
    result = registry.get_children(object_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return result


@router.get("/objects/{object_id}/ancestors", response_model=LineageTraversal)
def get_object_ancestors(object_id: str, max_depth: int | None = Query(None, ge=1, le=MAX_LINEAGE_DEPTH)) -> LineageTraversal:
    """Transitive upstream traversal: everything this object depends on."""
    result = lineage_service.build_ancestors(registry, object_id, max_depth)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return result


@router.get("/objects/{object_id}/descendants", response_model=LineageTraversal)
def get_object_descendants(object_id: str, max_depth: int | None = Query(None, ge=1, le=MAX_LINEAGE_DEPTH)) -> LineageTraversal:
    """Transitive downstream traversal: everything that depends on this object."""
    result = lineage_service.build_descendants(registry, object_id, max_depth)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return result


@router.get("/objects/{object_id}/graph", response_model=LineageTraversal)
def get_object_graph(
    object_id: str,
    direction: LineageDirection = LineageDirection.BOTH,
    max_depth: int | None = Query(None, ge=1, le=MAX_LINEAGE_DEPTH),
) -> LineageTraversal:
    """A compact single-call graph: root (at depth 0) plus its ancestors and/or
    descendants, already merged into one node/edge set. A thin composition of the
    same traversal used by `/ancestors` and `/descendants` - not a separate engine."""
    result = lineage_service.build_graph(registry, object_id, direction, max_depth)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return result


@router.get("/path", response_model=LineagePath)
def get_path(from_object_id: str, to_object_id: str) -> LineagePath:
    """Deterministic shortest path connecting two analytical objects, if one exists."""
    result = lineage_service.build_path(registry, from_object_id, to_object_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="One or both analytical objects were not found.")
    return result


@router.get("/objects/{object_id}/freshness", response_model=FreshnessAssessment)
def get_object_freshness(object_id: str) -> FreshnessAssessment:
    """Contextual freshness for one object, computed live - never stored, never
    changes the object it describes."""
    result = freshness_service.assess_object(registry, overview_store, object_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return result


@router.get("/datasets/{dataset_id}/freshness", response_model=list[FreshnessAssessment])
def get_dataset_freshness(dataset_id: str) -> list[FreshnessAssessment]:
    """Freshness for every registered object of ``dataset_id``, newest-first. An
    unknown or never-touched dataset returns an empty list, matching
    `/datasets/{dataset_id}/objects`'s own behavior - never a 404."""
    return freshness_service.assess_dataset(registry, overview_store, dataset_id)


@router.post("/objects/{object_id}/rerun", response_model=ReproductionResponse)
def rerun_object(object_id: str, request: RerunRequest) -> ReproductionResponse:
    """Reproduce one analytical object's original configuration as a brand-new object.

    The only route under `/lineage` that writes anything - and even this one never
    overwrites: it only ever creates a new `AnalyticalObject`. The request supplies only
    `mode`; every other configuration value (columns, test, target, horizon, ...) is
    derived from the original object's own recorded provenance, never from the client.
    """
    result = reproduction_service.reproduce(registry, overview_store, object_id, request.mode)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return result


@router.post("/objects/{object_id}/atlas", response_model=AtlasLineageResponse)
def atlas_lineage_action(object_id: str, request: AtlasLineageRequest) -> AtlasLineageResponse:
    """Atlas lineage awareness: deterministic explanations grounded entirely in Phase
    8A-8F's own recorded provenance/freshness/reproducibility data - see
    `atlas_lineage.py`'s module docstring for why this is structurally incapable of
    inventing a dependency, version, or stale reason."""
    result = atlas_lineage.explain(registry, overview_store, object_id, request.action, request.compare_to_object_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return result
