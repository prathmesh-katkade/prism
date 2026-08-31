"""Phase 8B/8C read-only analytical-object registry and lineage-traversal API.

Phase 8C adds deterministic graph traversal (parents/children/ancestors/descendants/
graph/path) on top of Phase 8B's read-only object retrieval - all still read-only,
still built only from the direct `parent_refs` links producers already record, never
AI-inferred. No write route exists, or may be added, under this router.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from prism_analytical_schemas import (
    AnalyticalObject,
    LineageDirection,
    LineagePath,
    LineageTraversal,
    ObjectKind,
)

from . import lineage_service
from .analytical_objects import registry

router = APIRouter(prefix="/api/v1/lineage", tags=["lineage"])

# Bounded traversal: an unbounded max_depth is fine by default (BFS is already
# cycle-safe and the registry is process-local, so pathological size is not a
# realistic risk) - this only caps what a caller may explicitly request.
MAX_LINEAGE_DEPTH = 100

_NOT_FOUND = "Analytical object was not found."


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
