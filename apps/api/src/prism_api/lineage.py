"""Phase 8B read-only analytical-object registry API."""

from fastapi import APIRouter, HTTPException, Query, status
from prism_analytical_schemas import AnalyticalObject, ObjectKind

from .analytical_objects import registry

router = APIRouter(prefix="/api/v1/lineage", tags=["lineage"])


@router.get("/objects/{object_id}", response_model=AnalyticalObject)
def get_object(object_id: str) -> AnalyticalObject:
    record = registry.get(object_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analytical object was not found.")
    return record


@router.get("/datasets/{dataset_id}/objects", response_model=list[AnalyticalObject])
def list_objects(
    dataset_id: str,
    revision: int | None = Query(default=None, ge=0),
    kind: ObjectKind | None = Query(default=None),
) -> list[AnalyticalObject]:
    return registry.list_for_dataset(dataset_id, revision=revision, kind=kind)
