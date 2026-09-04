"""REST surface for the 10M-10Q Foundry wave.

Deliberately narrower than the full backend surface those modules expose:

- AtlasBench tasks are never returned with their answer key. Only
  ``AtlasBenchCorpusSummary`` (counts, no ``correct_choice``/``rationale``)
  is public; browsing full task content over HTTP would hand any client --
  including a candidate under evaluation -- its own judge's answer key.
- There is no "promote" endpoint. A promotion decision must come from a
  real server-side ``decide_promotion()`` call over a real suite run, never
  from a client-supplied ``AtlasPromotionDecision`` -- accepting one over
  HTTP would let any caller fabricate a PROMOTE_ELIGIBLE verdict and force
  a promotion. Only read-only history/current-production and the
  no-client-input ``rollback`` action are exposed until a live subject and
  a real end-to-end promotion flow exist to drive this safely.
- There is no "run the benchmark suite" endpoint yet: no AtlasBenchSubject
  wraps a live Atlas provider yet (see the Foundry-wave ledger), so the
  only subjects available are reference/mock ones not worth exposing as a
  production action.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from prism_api_contracts import (
    AtlasAdapterCapability,
    AtlasAdapterId,
    AtlasBenchCategory,
    AtlasBenchCategoryCount,
    AtlasBenchCorpusSummary,
    AtlasBenchSuiteRun,
    AtlasBenchTaskResult,
    AtlasCandidateArtifact,
    AtlasFoundryCapability,
    AtlasFoundryPreflight,
    AtlasPreferenceDatasetVersion,
    AtlasPreferencePair,
    AtlasProductionPointer,
    AtlasTrainingDatasetVersion,
    AtlasTrainingExample,
    AtlasTrainingJob,
    AtlasTrainingRecipe,
    AtlasTrainingSplit,
)

from .atlas_adapter_foundation import report_adapter_capability, report_all_adapter_capabilities
from .atlas_bench_corpus import CORPUS_VERSION, all_tasks, corpus_hash
from .atlas_bench_store import DurableAtlasBenchStore
from .atlas_foundry_backend import SoupFoundryBackend
from .atlas_foundry_dataset import (
    AtlasTrainingDatasetBuilder,
    DurableAtlasTrainingDatasetStore,
    export_jsonl,
)
from .atlas_foundry_orchestration import (
    DurableAtlasCandidateRegistry,
    DurableAtlasFoundryJobStore,
    reconcile_foundry_jobs,
    start_training_job,
)
from .atlas_foundry_preference import (
    AtlasPreferenceDatasetBuilder,
    DurableAtlasPreferenceDatasetStore,
)
from .atlas_memory import DurableAtlasMemoryStore
from .atlas_promotion import DurableAtlasPromotionStore
from .atlas_resources import governor
from .durable_atlas_store import DurableAtlasRunStore

router = APIRouter(prefix="/api/v1/atlas/foundry", tags=["atlas-foundry"])

_run_store = DurableAtlasRunStore()
_memory_store = DurableAtlasMemoryStore()
_training_dataset_store = DurableAtlasTrainingDatasetStore()
_preference_dataset_store = DurableAtlasPreferenceDatasetStore()
_bench_store = DurableAtlasBenchStore()
_job_store = DurableAtlasFoundryJobStore()
_candidate_registry = DurableAtlasCandidateRegistry()
_promotion_store = DurableAtlasPromotionStore()
_backend = SoupFoundryBackend()

_EXPORT_ROOT = Path(".prism/runtime/foundry-exports")


# --- 10N: verified training datasets --------------------------------------


@router.post("/training-datasets", response_model=AtlasTrainingDatasetVersion, status_code=status.HTTP_201_CREATED)
def build_training_dataset() -> AtlasTrainingDatasetVersion:
    examples, exclusions = AtlasTrainingDatasetBuilder(_run_store).build()
    return _training_dataset_store.save(examples, exclusions)


@router.get("/training-datasets", response_model=list[AtlasTrainingDatasetVersion])
def list_training_datasets(limit: int = Query(default=50, ge=1, le=200)) -> list[AtlasTrainingDatasetVersion]:
    return _training_dataset_store.list_versions(limit=limit)


@router.get("/training-datasets/{version_id}/preview", response_model=list[AtlasTrainingExample])
def preview_training_dataset(
    version_id: str,
    split: Optional[AtlasTrainingSplit] = None,
    limit: int = Query(default=10, ge=1, le=100),
) -> list[AtlasTrainingExample]:
    return _training_dataset_store.preview(version_id, split=split, limit=limit)


# --- 10O: DPO preference datasets ------------------------------------------


@router.post("/preference-datasets", response_model=AtlasPreferenceDatasetVersion, status_code=status.HTTP_201_CREATED)
def build_preference_dataset() -> AtlasPreferenceDatasetVersion:
    pairs, exclusions = AtlasPreferenceDatasetBuilder(_memory_store).build()
    return _preference_dataset_store.save(pairs, exclusions)


@router.get("/preference-datasets", response_model=list[AtlasPreferenceDatasetVersion])
def list_preference_datasets(limit: int = Query(default=50, ge=1, le=200)) -> list[AtlasPreferenceDatasetVersion]:
    return _preference_dataset_store.list_versions(limit=limit)


@router.get("/preference-datasets/{version_id}/preview", response_model=list[AtlasPreferencePair])
def preview_preference_dataset(
    version_id: str,
    split: Optional[AtlasTrainingSplit] = None,
    limit: int = Query(default=10, ge=1, le=100),
) -> list[AtlasPreferencePair]:
    return _preference_dataset_store.preview(version_id, split=split, limit=limit)


# --- 10M: Foundry backend + jobs -------------------------------------------


@router.get("/capability", response_model=AtlasFoundryCapability)
def foundry_capability() -> AtlasFoundryCapability:
    return _backend.capability()


@router.post("/preflight", response_model=AtlasFoundryPreflight)
def foundry_preflight(recipe: AtlasTrainingRecipe) -> AtlasFoundryPreflight:
    return _backend.preflight(recipe)


@router.post("/jobs", response_model=AtlasTrainingJob, status_code=status.HTTP_202_ACCEPTED)
def start_foundry_job(recipe: AtlasTrainingRecipe, dataset_version_id: str) -> AtlasTrainingJob:
    """Exports the named training-dataset version to JSONL, then admits and
    starts (or durably queues) a job through the Resource Governor."""
    if recipe.dataset_version_id != dataset_version_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="recipe.dataset_version_id must match the dataset_version_id being trained on.",
        )
    manifest = _training_dataset_store.get_version(dataset_version_id)
    if manifest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training dataset version was not found.")
    examples = _training_dataset_store.preview(dataset_version_id, limit=100_000)
    export_path = _EXPORT_ROOT / dataset_version_id / f"{uuid.uuid4().hex}.jsonl"
    export_jsonl(examples, export_path)
    return start_training_job(governor, _job_store, _backend, recipe, dataset_path=export_path)


@router.get("/jobs", response_model=list[AtlasTrainingJob])
def list_active_foundry_jobs(limit: int = Query(default=200, ge=1, le=500)) -> list[AtlasTrainingJob]:
    return _job_store.list_active(limit=limit)


@router.get("/jobs/{job_id}", response_model=AtlasTrainingJob)
def get_foundry_job(job_id: str) -> AtlasTrainingJob:
    job = _job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Foundry job was not found.")
    return job


@router.post("/jobs/{job_id}/cancel", response_model=AtlasTrainingJob)
def cancel_foundry_job(job_id: str) -> AtlasTrainingJob:
    job = _job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Foundry job was not found.")
    cancelled = _backend.cancel(job)
    return _job_store.save(cancelled)


@router.post("/jobs:reconcile", response_model=list[AtlasTrainingJob])
def reconcile_jobs() -> list[AtlasTrainingJob]:
    """Advance every non-terminal job by one step (see
    ``atlas_foundry_orchestration.reconcile_foundry_jobs``) -- there is no
    background daemon in this wave, so a caller (a scheduled poll, an
    operator action) must call this periodically for jobs to progress."""
    return reconcile_foundry_jobs(governor, _job_store, _backend, _candidate_registry)


@router.get("/candidates", response_model=list[AtlasCandidateArtifact])
def list_candidates(limit: int = Query(default=100, ge=1, le=500)) -> list[AtlasCandidateArtifact]:
    return _candidate_registry.list(limit=limit)


# --- 10P: AtlasBench (read-only; never exposes the answer key) -------------

bench_router = APIRouter(prefix="/api/v1/atlas/bench", tags=["atlas-bench"])


@bench_router.get("/corpus/summary", response_model=AtlasBenchCorpusSummary)
def bench_corpus_summary() -> AtlasBenchCorpusSummary:
    tasks = all_tasks()
    counts: dict[AtlasBenchCategory, int] = {}
    for task in tasks:
        counts[task.category] = counts.get(task.category, 0) + 1
    return AtlasBenchCorpusSummary(
        corpus_version=CORPUS_VERSION,
        corpus_hash=corpus_hash(),
        total_tasks=len(tasks),
        category_counts=[
            AtlasBenchCategoryCount(category=category, task_count=count)
            for category, count in sorted(counts.items(), key=lambda item: item[0].value)
        ],
    )


@bench_router.get("/runs/{subject_id}", response_model=list[AtlasBenchSuiteRun])
def list_bench_runs(subject_id: str, limit: int = Query(default=50, ge=1, le=200)) -> list[AtlasBenchSuiteRun]:
    return _bench_store.list_runs_for_subject(subject_id, limit=limit)


@bench_router.get("/runs/detail/{run_id}", response_model=AtlasBenchSuiteRun)
def get_bench_run(run_id: str) -> AtlasBenchSuiteRun:
    suite_run = _bench_store.get_run(run_id)
    if suite_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AtlasBench run was not found.")
    return suite_run


@bench_router.get("/runs/detail/{run_id}/failures", response_model=list[AtlasBenchTaskResult])
def get_bench_run_failures(run_id: str, limit: int = Query(default=200, ge=1, le=500)) -> list[AtlasBenchTaskResult]:
    return _bench_store.failed_tasks(run_id, limit=limit)


# --- 10Q: promotion history / rollback (never accepts a client decision) --

promotion_router = APIRouter(prefix="/api/v1/atlas/promotion", tags=["atlas-promotion"])


@promotion_router.get("/current", response_model=Optional[AtlasProductionPointer])
def current_production() -> Optional[AtlasProductionPointer]:
    return _promotion_store.current_production()


@promotion_router.get("/history", response_model=list[AtlasProductionPointer])
def promotion_history(limit: int = Query(default=100, ge=1, le=500)) -> list[AtlasProductionPointer]:
    return _promotion_store.history(limit=limit)


@promotion_router.post("/rollback", response_model=AtlasProductionPointer)
def rollback_production(reason: str) -> AtlasProductionPointer:
    try:
        return _promotion_store.rollback(reason=reason)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


# --- Adapter foundation ------------------------------------------------

adapter_router = APIRouter(prefix="/api/v1/atlas/adapters", tags=["atlas-adapters"])


@adapter_router.get("/capabilities", response_model=list[AtlasAdapterCapability])
def adapter_capabilities() -> list[AtlasAdapterCapability]:
    return report_all_adapter_capabilities()


@adapter_router.get("/capabilities/{adapter}", response_model=AtlasAdapterCapability)
def adapter_capability(adapter: AtlasAdapterId) -> AtlasAdapterCapability:
    return report_adapter_capability(adapter)
