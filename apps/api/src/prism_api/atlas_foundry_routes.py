"""REST surface for the Phase 10 Foundry / Evolution system.

Security boundaries are intentional:

- AtlasBench tasks are never returned with their answer key.
- Promotion verdicts are computed server-side from stored AtlasBench runs.
- A promote request references a durable server-computed decision and a real
  candidate runtime binding; promotion changes Atlas's active runtime model.
"""

from __future__ import annotations

import os
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
    AtlasPromotionDecision,
    AtlasTrainingDatasetVersion,
    AtlasTrainingExample,
    AtlasTrainingJob,
    AtlasTrainingRecipe,
    AtlasTrainingSplit,
)

from .atlas_adapter_foundation import report_adapter_capability, report_all_adapter_capabilities
from .atlas_bench_corpus import CORPUS_VERSION, all_tasks, corpus_hash
from .atlas_bench_store import DurableAtlasBenchStore
from .atlas_candidate_runtime import (
    DurableAtlasCandidateRuntimeStore,
    activate_current_ollama_model,
    ensure_configured_production_baseline,
)
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
from .atlas_promotion import DurableAtlasPromotionStore, decide_promotion
from .atlas_promotion_decisions import DurableAtlasPromotionDecisionStore
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
_candidate_runtime_store = DurableAtlasCandidateRuntimeStore()
_promotion_store = DurableAtlasPromotionStore()
_promotion_decision_store = DurableAtlasPromotionDecisionStore()
_backend = SoupFoundryBackend()

_EXPORT_ROOT = Path(".prism/runtime/foundry-exports")

# On an Ollama deployment, persist the pre-Foundry configured model once as the
# rollback anchor and then rehydrate any previously promoted runtime pointer.
# Deterministic deployments are untouched.
if os.environ.get("PRISM_AI_PROVIDER", "deterministic").lower() == "ollama":
    ensure_configured_production_baseline()


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


@router.get("/capability", response_model=AtlasFoundryCapability)
def foundry_capability() -> AtlasFoundryCapability:
    return _backend.capability()


@router.post("/preflight", response_model=AtlasFoundryPreflight)
def foundry_preflight(recipe: AtlasTrainingRecipe) -> AtlasFoundryPreflight:
    return _backend.preflight(recipe)


@router.post("/jobs", response_model=AtlasTrainingJob, status_code=status.HTTP_202_ACCEPTED)
def start_foundry_job(recipe: AtlasTrainingRecipe, dataset_version_id: str) -> AtlasTrainingJob:
    """Export TRAIN only; validation/test examples never enter Foundry."""
    if recipe.dataset_version_id != dataset_version_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="recipe.dataset_version_id must match the dataset_version_id being trained on.",
        )
    manifest = _training_dataset_store.get_version(dataset_version_id)
    if manifest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training dataset version was not found.")
    examples = _training_dataset_store.preview(
        dataset_version_id,
        split=AtlasTrainingSplit.TRAIN,
        limit=100_000,
    )
    if not examples:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Training dataset version contains no TRAIN examples; Foundry refused to train on validation/test data.",
        )
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
    return reconcile_foundry_jobs(governor, _job_store, _backend, _candidate_registry)


@router.get("/candidates", response_model=list[AtlasCandidateArtifact])
def list_candidates(limit: int = Query(default=100, ge=1, le=500)) -> list[AtlasCandidateArtifact]:
    return _candidate_registry.list(limit=limit)


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


promotion_router = APIRouter(prefix="/api/v1/atlas/promotion", tags=["atlas-promotion"])


@promotion_router.get("/current", response_model=Optional[AtlasProductionPointer])
def current_production() -> Optional[AtlasProductionPointer]:
    return _promotion_store.current_production()


@promotion_router.get("/history", response_model=list[AtlasProductionPointer])
def promotion_history(limit: int = Query(default=100, ge=1, le=500)) -> list[AtlasProductionPointer]:
    return _promotion_store.history(limit=limit)


@promotion_router.post("/decisions", response_model=AtlasPromotionDecision, status_code=status.HTTP_201_CREATED)
def compute_promotion_decision(
    candidate_id: str,
    production_run_id: str,
    candidate_run_id: str,
) -> AtlasPromotionDecision:
    if _candidate_registry.get(candidate_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate artifact was not found.")
    production_run = _bench_store.get_run(production_run_id)
    candidate_run = _bench_store.get_run(candidate_run_id)
    if production_run is None or candidate_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Both AtlasBench runs must exist before a decision can be computed.")
    if production_run.run_id == candidate_run.run_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Production and candidate AtlasBench runs must be distinct.")
    if (
        production_run.corpus_version != candidate_run.corpus_version
        or production_run.corpus_hash != candidate_run.corpus_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Production and candidate must be evaluated against the identical AtlasBench corpus.",
        )
    decision = decide_promotion(candidate_id, production_run, candidate_run)
    return _promotion_decision_store.save(decision)


@promotion_router.get("/decisions/{candidate_id}", response_model=list[AtlasPromotionDecision])
def list_promotion_decisions(candidate_id: str, limit: int = Query(default=50, ge=1, le=200)) -> list[AtlasPromotionDecision]:
    return _promotion_decision_store.list_for_candidate(candidate_id, limit=limit)


@promotion_router.post("/promote", response_model=AtlasProductionPointer)
def promote_candidate(decision_id: str, reason: str) -> AtlasProductionPointer:
    """Promote only a benchmark-eligible candidate with a real runtime binding."""
    decision = _promotion_decision_store.get(decision_id)
    if decision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promotion decision was not found.")
    if _candidate_registry.get(decision.candidate_id) is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The decision references a candidate artifact that is no longer available.")
    if _candidate_runtime_store.latest(decision.candidate_id) is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Candidate has no verified Ollama runtime binding; promotion cannot change Atlas safely.",
        )
    try:
        pointer = _promotion_store.promote(decision, reason=reason)
        activate_current_ollama_model()
        return pointer
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@promotion_router.post("/rollback", response_model=AtlasProductionPointer)
def rollback_production(reason: str) -> AtlasProductionPointer:
    history = _promotion_store.history(limit=2)
    if len(history) < 2:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No prior production candidate to roll back to.")
    rollback_target = history[1].candidate_id
    if _candidate_runtime_store.latest(rollback_target) is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Rollback target has no durable runtime binding; production pointer was not changed.",
        )
    try:
        pointer = _promotion_store.rollback(reason=reason)
        activate_current_ollama_model()
        return pointer
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


adapter_router = APIRouter(prefix="/api/v1/atlas/adapters", tags=["atlas-adapters"])


@adapter_router.get("/capabilities", response_model=list[AtlasAdapterCapability])
def adapter_capabilities() -> list[AtlasAdapterCapability]:
    return report_all_adapter_capabilities()


@adapter_router.get("/capabilities/{adapter}", response_model=AtlasAdapterCapability)
def adapter_capability(adapter: AtlasAdapterId) -> AtlasAdapterCapability:
    return report_adapter_capability(adapter)
