"""Phase 3 Overview vertical slice: server-held datasets and typed evidence responses."""

from __future__ import annotations

import hashlib
import io
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pandas as pd
from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from prism_api_contracts import (
    AtlasEvidence,
    AtlasOverviewAction,
    AtlasOverviewRequest,
    AtlasOverviewResponse,
    DatasetRowsResponse,
    OverviewDataset,
    OverviewProfileResponse,
    OverviewProvenance,
)
from prism_overview_analytics import ANALYTICS_SERVICE_VERSION, build_overview

from .durable_dataset_store import DurableDatasetStore
from .durable_dataset_store import StoredDataset as DurableStoredDataset

StoredDataset = DurableStoredDataset

router = APIRouter(prefix="/api/v1/overview", tags=["overview"])
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_PROFILE_ROWS = 500_000


class DatasetStore:
    """Deliberately process-local for Phase 3; no browser receives the full dataset.

    Phase 6 (Clean) adds revision history on top of the same store: applying a
    transformation does not mutate a dataset in place, it appends a new revision
    under the same ``dataset_id``. Every existing consumer (Overview, SQL Lab,
    AI Analyst) reads through ``get()``/``latest()``, which always resolve to the
    current revision, so a Clean transformation is immediately visible everywhere
    without those modules needing to know revisions exist.
    """

    def __init__(self) -> None:
        self._datasets: dict[str, StoredDataset] = {}
        self._history: dict[str, list[StoredDataset]] = {}

    def put(self, frame: pd.DataFrame, source_name: str, source_fingerprint: str) -> OverviewDataset:
        dataset = OverviewDataset(
            dataset_id=f"ds_{uuid.uuid4().hex}", revision=0, source_name=source_name,
            source_fingerprint=source_fingerprint, row_count=len(frame), column_count=len(frame.columns),
        )
        stored = StoredDataset(dataset, frame, source_fingerprint)
        self._datasets[dataset.dataset_id] = stored
        self._history[dataset.dataset_id] = [stored]
        return dataset

    def get(self, dataset_id: str) -> StoredDataset:
        dataset = self._datasets.get(dataset_id)
        if dataset is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Overview dataset was not found.")
        return dataset

    def latest(self) -> StoredDataset | None:
        """The current process has one active research context in Phase 3/4."""
        return next(reversed(self._datasets.values()), None) if self._datasets else None

    def revisions(self, dataset_id: str) -> list[StoredDataset]:
        self.get(dataset_id)
        return list(self._history.get(dataset_id, []))

    def add_revision(self, dataset_id: str, frame: pd.DataFrame, fingerprint: str) -> OverviewDataset:
        """Append a new revision of ``dataset_id`` (e.g. after a Clean transformation)."""
        current = self.get(dataset_id)
        dataset = OverviewDataset(
            dataset_id=dataset_id, revision=current.dataset.revision + 1, source_name=current.dataset.source_name,
            source_fingerprint=fingerprint, row_count=len(frame), column_count=len(frame.columns),
        )
        stored = StoredDataset(dataset, frame, fingerprint)
        self._datasets[dataset_id] = stored
        self._history.setdefault(dataset_id, []).append(stored)
        return dataset

    def revert(self, dataset_id: str, revision: int) -> OverviewDataset:
        """Undo: make ``revision`` current again and drop any later revisions.

        This is a linear undo stack, not a branching version tree: reverting then
        applying a new transformation starts a fresh path from ``revision`` rather
        than colliding with the revision numbers of the discarded branch.
        """
        history = self._history.get(dataset_id) or []
        target = next((item for item in history if item.dataset.revision == revision), None)
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Revision {revision} was not found for this dataset.")
        self._datasets[dataset_id] = target
        self._history[dataset_id] = [item for item in history if item.dataset.revision <= revision]
        return target.dataset


# Phase 9 preserves DatasetStore's authority and public API, while making its
# revision payloads restart-safe alongside durable analytical history.
store: DatasetStore = cast(DatasetStore, DurableDatasetStore())


def _read_upload(contents: bytes, source_name: str) -> pd.DataFrame:
    suffix = Path(source_name).suffix.lower()
    try:
        if suffix in {".xlsx", ".xls"}:
            frame = pd.read_excel(io.BytesIO(contents))
        else:
            last_error: Exception | None = None
            frame = None
            for encoding in ("utf-8-sig", "cp1252", "latin-1"):
                try:
                    frame = pd.read_csv(io.BytesIO(contents), encoding=encoding)
                    break
                except (UnicodeDecodeError, pd.errors.ParserError) as error:
                    last_error = error
            if frame is None:
                raise last_error or ValueError("The file could not be decoded as CSV.")
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Could not read dataset: {error}") from error
    frame = frame.dropna(how="all")
    if frame.empty or not len(frame.columns):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The dataset has no usable rows or columns.")
    if len(frame) > MAX_PROFILE_ROWS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Overview accepts up to {MAX_PROFILE_ROWS:,} rows in Phase 3.",
        )
    return frame


def _provenance(stored: StoredDataset) -> OverviewProvenance:
    return OverviewProvenance(
        source_fingerprint=stored.source_fingerprint,
        dataset_revision=stored.dataset.revision,
        parameters={"outlier_method": "iqr_tukey_1.5", "correlation": "pearson", "max_profile_rows": MAX_PROFILE_ROWS},
        service_version=ANALYTICS_SERVICE_VERSION,
        computed_at=datetime.now(timezone.utc),
    )


def _json_value(value: Any) -> object | None:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, (pd.Timestamp, datetime)):
        return str(value.isoformat())
    return None if bool(pd.isna(value)) else str(value)


def _atlas_response(profile: OverviewProfileResponse, request: AtlasOverviewRequest) -> AtlasOverviewResponse:
    quality, health = profile.quality, profile.health
    evidence = [
        AtlasEvidence(label="Dataset", value=f"{quality.n_rows:,} rows × {quality.n_cols} columns"),
        AtlasEvidence(label="Health score", value=f"{health.total}/100"),
    ]
    uncertainty = "This is a deterministic profile, not a causal conclusion; inspect the affected rows before changing data."
    if request.action is AtlasOverviewAction.EXPLAIN_DATASET:
        summary = f"{profile.dataset.source_name} has {quality.n_rows:,} rows and {quality.n_cols} columns. Its health score is {health.total}/100."
    elif request.action is AtlasOverviewAction.DIAGNOSE_QUALITY:
        summary = f"Quality evidence: {quality.total_missing_pct}% missing cells, {quality.duplicate_rows:,} duplicate rows, and {len(quality.all_null_columns)} fully empty columns."
    elif request.action is AtlasOverviewAction.INSPECT_ANOMALY:
        total = sum(item.count for item in quality.outliers.values())
        summary = f"IQR screening flagged {total:,} value-level outliers across {len(quality.outliers)} numeric columns; this is a screening signal, not proof of bad data."
    elif request.action is AtlasOverviewAction.SUGGEST_NEXT_ANALYSIS:
        summary = profile.suggestions[0].reason if profile.suggestions else "No deterministic next analysis is available yet."
    elif request.action is AtlasOverviewAction.TRACE_SOURCE:
        summary = f"This profile is derived from {profile.dataset.source_name}, revision {profile.dataset.revision}, fingerprint {profile.provenance.source_fingerprint[:12]}… using {profile.provenance.service_version}."
    elif request.action is AtlasOverviewAction.COMPARE_COLUMNS:
        if not request.column or not request.comparison_column:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Two columns are required for comparison.")
        pair = next((item for item in profile.correlations if {item.left, item.right} == {request.column, request.comparison_column}), None)
        summary = f"{request.column} and {request.comparison_column} have Pearson r={pair.coefficient:.2f}." if pair else f"No comparable numeric relationship was computed for {request.column} and {request.comparison_column}."
    else:
        risks = [f"{quality.total_missing_pct}% missingness", f"{quality.duplicate_rows:,} duplicate rows"]
        if quality.all_null_columns:
            risks.append(f"{len(quality.all_null_columns)} empty column(s)")
        summary = "Key risks: " + ", ".join(risks) + "."
    return AtlasOverviewResponse(action=request.action, summary=summary, uncertainty=uncertainty, evidence=evidence, provenance=profile.provenance)


@router.post("/datasets", response_model=OverviewDataset, status_code=status.HTTP_201_CREATED)
async def upload_dataset(file: UploadFile = File(...)) -> OverviewDataset:  # noqa: B008
    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Dataset exceeds the 64 MB Phase 3 upload limit.")
    source_name = file.filename or "uploaded-dataset.csv"
    frame = _read_upload(contents, source_name)
    return store.put(frame, source_name, hashlib.sha256(contents).hexdigest())


@router.get("/datasets/{dataset_id}/profile", response_model=OverviewProfileResponse)
def get_profile(dataset_id: str) -> OverviewProfileResponse:
    stored = store.get(dataset_id)
    payload = build_overview(stored.frame)
    return OverviewProfileResponse(dataset=stored.dataset, provenance=_provenance(stored), **payload)


@router.get("/datasets/{dataset_id}/rows", response_model=DatasetRowsResponse)
def get_rows(dataset_id: str, offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100)) -> DatasetRowsResponse:
    stored = store.get(dataset_id)
    frame = stored.frame.iloc[offset : offset + limit]
    return DatasetRowsResponse(
        dataset=stored.dataset, offset=offset, limit=limit, total_rows=len(stored.frame),
        rows=[{str(key): _json_value(value) for key, value in row.items()} for row in frame.to_dict(orient="records")],
        provenance=_provenance(stored),
    )


@router.post("/datasets/{dataset_id}/atlas", response_model=AtlasOverviewResponse)
def atlas_action(dataset_id: str, request: AtlasOverviewRequest) -> AtlasOverviewResponse:
    stored = store.get(dataset_id)
    profile = OverviewProfileResponse(dataset=stored.dataset, provenance=_provenance(stored), **build_overview(stored.frame))
    return _atlas_response(profile, request)
