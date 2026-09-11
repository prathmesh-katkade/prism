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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from prism_api_contracts import (
    AtlasAdapterCapability,
    AtlasAdapterId,
    AtlasBaseModelVerification,
    AtlasBenchCategory,
    AtlasBenchCategoryCount,
    AtlasBenchCorpusSummary,
    AtlasBenchSuiteRun,
    AtlasBenchTaskResult,
    AtlasCandidateArtifact,
    AtlasCandidateKind,
    AtlasCandidateVerification,
    AtlasCombinedSftDatasetVersion,
    AtlasCombinedTrainingSourceSummary,
    AtlasFoundryCapability,
    AtlasFoundryPreflight,
    AtlasPreferenceDatasetVersion,
    AtlasPreferencePair,
    AtlasProductionPointer,
    AtlasProductionTrustStatus,
    AtlasPromotionDecision,
    AtlasSftTrainingRecord,
    AtlasSyntheticTeacherExample,
    AtlasSyntheticTeacherManifest,
    AtlasSystemSeedExample,
    AtlasSystemSeedManifest,
    AtlasTrainingDatasetVersion,
    AtlasTrainingExample,
    AtlasTrainingJob,
    AtlasTrainingRecipe,
    AtlasTrainingSplit,
    AtlasVerifiedBaseModelCandidate,
    AtlasVerifiedBaseModelRegistrationRequest,
)

from .atlas_adapter_foundation import report_adapter_capability, report_all_adapter_capabilities
from .atlas_base_model_trust import (
    DurableAtlasBaseModelVerificationStore,
    DurableAtlasVerifiedBaseModelRegistry,
    compute_base_model_candidate_id,
    is_base_model_verified,
    verify_base_model_candidate,
)
from .atlas_bench_corpus import CORPUS_VERSION, all_tasks, corpus_hash
from .atlas_bench_store import DurableAtlasBenchStore
from .atlas_candidate_runtime import (
    DurableAtlasCandidateRuntimeStore,
    activate_current_ollama_model,
    ensure_configured_production_baseline,
)
from .atlas_candidate_trust import (
    DurableAtlasCandidateVerificationStore,
    is_verified,
    verify_candidate,
)
from .atlas_combined_sft_dataset import (
    DurableAtlasCombinedSftStore,
    build_combined_records,
    export_alpaca_jsonl,
)
from .atlas_corpus_v2_synthetic import (
    DurableAtlasSyntheticTeacherStore,
    build_verified_synthetic_teacher_corpus,
)
from .atlas_corpus_v2_synthetic import build_manifest as build_synthetic_teacher_manifest
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
from .atlas_system_seed import (
    SEED_VERSION,
    DurableAtlasSystemSeedStore,
    build_manifest,
    build_system_seed_corpus,
    build_verified_system_seed_corpus,
)
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
_candidate_verification_store = DurableAtlasCandidateVerificationStore()
_base_model_registry = DurableAtlasVerifiedBaseModelRegistry()
_base_model_verification_store = DurableAtlasBaseModelVerificationStore()
_promotion_store = DurableAtlasPromotionStore()
_promotion_decision_store = DurableAtlasPromotionDecisionStore()
_system_seed_store = DurableAtlasSystemSeedStore()
_synthetic_teacher_store = DurableAtlasSyntheticTeacherStore()
_combined_sft_store = DurableAtlasCombinedSftStore()
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


@router.post("/combined-sft-datasets", response_model=AtlasCombinedSftDatasetVersion, status_code=status.HTTP_201_CREATED)
def build_combined_sft_dataset() -> AtlasCombinedSftDatasetVersion:
    """Release the reviewed seed and combine it with genuine eligible history.

    The historical run-only corpus remains available for inspection, but every
    ordinary SFT Foundry job is expected to use this immutable combined type.
    """
    seeds = build_verified_system_seed_corpus()
    seed_manifest = _system_seed_store.release(seeds, build_manifest(seeds, leakage_guard_passed=True))
    history, exclusions = AtlasTrainingDatasetBuilder(_run_store).build()
    history_manifest = _training_dataset_store.save(history, exclusions)
    synthetic_teacher = build_verified_synthetic_teacher_corpus()
    synthetic_teacher_manifest = _synthetic_teacher_store.release(
        synthetic_teacher,
        build_synthetic_teacher_manifest(
            synthetic_teacher, v1_leakage_guard_passed=True, v2_leakage_guard_passed=True, duplicate_guard_passed=True,
            license_validation_passed=True, secret_scan_passed=True
        ),
    )
    records = build_combined_records(
        seeds, history, history_version=history_manifest.version_id, synthetic_teacher=synthetic_teacher
    )
    return _combined_sft_store.save(
        records,
        seed_version=seed_manifest.seed_version,
        seed_hash=seed_manifest.aggregate_content_hash,
        history_version=history_manifest.version_id,
        history_hash=history_manifest.content_hash,
        synthetic_teacher_version=synthetic_teacher_manifest.generation_policy_version,
        synthetic_teacher_hash=synthetic_teacher_manifest.aggregate_content_hash,
    )


@router.get("/combined-sft-datasets", response_model=list[AtlasCombinedSftDatasetVersion])
def list_combined_sft_datasets(limit: int = Query(default=50, ge=1, le=200)) -> list[AtlasCombinedSftDatasetVersion]:
    return _combined_sft_store.list_versions(limit=limit)


@router.get("/combined-sft-datasets/{version_id}/preview", response_model=list[AtlasSftTrainingRecord])
def preview_combined_sft_dataset(version_id: str, split: Optional[AtlasTrainingSplit] = None, limit: int = Query(default=10, ge=1, le=100)) -> list[AtlasSftTrainingRecord]:
    if _combined_sft_store.get_version(version_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Combined SFT dataset version was not found.")
    return _combined_sft_store.records(version_id, split=split, limit=limit)


@router.post("/system-seed/release", response_model=AtlasSystemSeedManifest, status_code=status.HTTP_201_CREATED)
def release_system_seed_corpus() -> AtlasSystemSeedManifest:
    """Build, leakage-check, and durably release the current system-seed
    version. Idempotent: releasing an already-released version returns the
    existing immutable manifest rather than creating a second copy."""
    examples = build_verified_system_seed_corpus()  # raises on any AtlasBench leakage
    manifest = build_manifest(examples, leakage_guard_passed=True)
    return _system_seed_store.release(examples, manifest)


@router.get("/system-seed", response_model=list[AtlasSystemSeedManifest])
def list_system_seed_versions(limit: int = Query(default=50, ge=1, le=200)) -> list[AtlasSystemSeedManifest]:
    return _system_seed_store.list_manifests(limit=limit)


@router.get("/system-seed/{seed_version}/preview", response_model=list[AtlasSystemSeedExample])
def preview_system_seed_version(
    seed_version: str, limit: int = Query(default=10, ge=1, le=200)
) -> list[AtlasSystemSeedExample]:
    return _system_seed_store.examples(seed_version, limit=limit)


@router.post("/synthetic-teacher/release", response_model=AtlasSyntheticTeacherManifest, status_code=status.HTTP_201_CREATED)
def release_synthetic_teacher_corpus() -> AtlasSyntheticTeacherManifest:
    """Build, leakage-check (against both AtlasBench V1 and V2), and durably
    release the current synthetic-teacher version. Idempotent: releasing an
    already-released version returns the existing immutable manifest rather
    than creating a second copy."""
    examples = build_verified_synthetic_teacher_corpus()  # raises on any AtlasBench V1/V2 leakage or near-duplicate
    manifest = build_synthetic_teacher_manifest(
        examples, v1_leakage_guard_passed=True, v2_leakage_guard_passed=True, duplicate_guard_passed=True,
        license_validation_passed=True, secret_scan_passed=True,
    )
    return _synthetic_teacher_store.release(examples, manifest)


@router.get("/synthetic-teacher", response_model=list[AtlasSyntheticTeacherManifest])
def list_synthetic_teacher_versions(limit: int = Query(default=50, ge=1, le=200)) -> list[AtlasSyntheticTeacherManifest]:
    return _synthetic_teacher_store.list_manifests(limit=limit)


@router.get("/synthetic-teacher/{generation_policy_version}/preview", response_model=list[AtlasSyntheticTeacherExample])
def preview_synthetic_teacher_version(
    generation_policy_version: str, limit: int = Query(default=10, ge=1, le=200)
) -> list[AtlasSyntheticTeacherExample]:
    return _synthetic_teacher_store.examples(generation_policy_version, limit=limit)


@router.get("/training-datasets:combined-summary", response_model=AtlasCombinedTrainingSourceSummary)
def combined_training_source_summary() -> AtlasCombinedTrainingSourceSummary:
    """Real counts per SFT source class, kept separate rather than blended:
    system-seed examples, verified real Atlas-run history, real user
    corrections (DPO pairs), and synthetic-teacher examples. Never mixed
    into one indistinguishable pool -- see ``AtlasCombinedTrainingSourceSummary``."""
    system_seed_examples = len(build_system_seed_corpus())
    history_examples, _ = AtlasTrainingDatasetBuilder(_run_store).eligible_runs()
    correction_pairs, _ = AtlasPreferenceDatasetBuilder(_memory_store).eligible_pairs()
    synthetic_teacher_examples = len(build_verified_synthetic_teacher_corpus())
    return AtlasCombinedTrainingSourceSummary(
        seed_version=SEED_VERSION,
        system_seed_examples=system_seed_examples,
        verified_history_examples=len(history_examples),
        user_correction_examples=len(correction_pairs),
        synthetic_teacher_examples=synthetic_teacher_examples,
        total_eligible=system_seed_examples + len(history_examples) + len(correction_pairs) + synthetic_teacher_examples,
        computed_at=datetime.now(timezone.utc),
    )


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
    manifest = _combined_sft_store.get_version(dataset_version_id)
    if manifest is not None:
        records = _combined_sft_store.records(dataset_version_id, split=AtlasTrainingSplit.TRAIN, limit=100_000)
        if not records:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Combined SFT dataset version contains no TRAIN examples; Foundry refused to train on validation/test data.")
        export_path = _EXPORT_ROOT / dataset_version_id / f"{uuid.uuid4().hex}.jsonl"
        export_alpaca_jsonl(records, export_path)
        return start_training_job(governor, _job_store, _backend, recipe, dataset_path=export_path)

    # Compatibility-only route for pre-bridge run-only manifests. New SFT
    # callers use combined versions above, which always export explicit Alpaca.
    historical = _training_dataset_store.get_version(dataset_version_id)
    if historical is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Training dataset version was not found.")
    examples = _training_dataset_store.preview(dataset_version_id, split=AtlasTrainingSplit.TRAIN, limit=100_000)
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


@router.post("/candidates/{candidate_id}/verify", response_model=AtlasCandidateVerification, status_code=status.HTTP_201_CREATED)
def verify_candidate_artifact(candidate_id: str) -> AtlasCandidateVerification:
    """Real inspection of the registered candidate's files on disk.

    Never a rubber stamp: this appends a new VERIFIED or REJECTED record
    every call, and a prior REJECTED record is never silently erased.
    """
    candidate = _candidate_registry.get(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate artifact was not found.")
    recipe = _job_store.get_recipe(candidate.recipe_id)
    if recipe is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The candidate's original recipe is no longer available; cannot verify.")
    verification = verify_candidate(candidate, recipe)
    return _candidate_verification_store.save(verification)


@router.get("/candidates/{candidate_id}/verification", response_model=list[AtlasCandidateVerification])
def candidate_verification_history(
    candidate_id: str, limit: int = Query(default=50, ge=1, le=200)
) -> list[AtlasCandidateVerification]:
    return _candidate_verification_store.history(candidate_id, limit=limit)


base_model_router = APIRouter(prefix="/api/v1/atlas/base-model-candidates", tags=["atlas-base-model-candidates"])


@base_model_router.post("", response_model=AtlasVerifiedBaseModelCandidate, status_code=status.HTTP_201_CREATED)
def register_base_model_candidate(
    request: AtlasVerifiedBaseModelRegistrationRequest,
) -> AtlasVerifiedBaseModelCandidate:
    """Durably declare an off-the-shelf model's identity -- never a training
    provenance fabrication. Registration alone is not trust: it must still
    pass ``POST /base-model-candidates/{candidate_id}/verify`` against the
    live Ollama daemon before entering AtlasBench candidate evaluation or
    promotion. Idempotent: re-declaring the same real identity returns the
    existing durable row rather than creating a duplicate.
    """
    candidate_id = compute_base_model_candidate_id(
        upstream_model_id=request.upstream_model_id,
        upstream_revision=request.upstream_revision,
        runtime_model=request.runtime_model,
    )
    candidate = AtlasVerifiedBaseModelCandidate(
        candidate_id=candidate_id,
        upstream_model_id=request.upstream_model_id,
        upstream_revision=request.upstream_revision,
        license=request.license,
        official_source=request.official_source,
        runtime_model=request.runtime_model,
        declared_runtime_digest=request.declared_runtime_digest,
        quantization=request.quantization,
        declared_manifest_digest=request.declared_manifest_digest,
        declared_blob_digests=request.declared_blob_digests,
        parameter_count=request.parameter_count,
        created_at=datetime.now(timezone.utc),
    )
    return _base_model_registry.register(candidate)


@base_model_router.get("", response_model=list[AtlasVerifiedBaseModelCandidate])
def list_base_model_candidates(limit: int = Query(default=100, ge=1, le=500)) -> list[AtlasVerifiedBaseModelCandidate]:
    return _base_model_registry.list(limit=limit)


@base_model_router.get("/{candidate_id}", response_model=AtlasVerifiedBaseModelCandidate)
def get_base_model_candidate(candidate_id: str) -> AtlasVerifiedBaseModelCandidate:
    candidate = _base_model_registry.get(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Base-model candidate was not found.")
    return candidate


@base_model_router.post(
    "/{candidate_id}/verify", response_model=AtlasBaseModelVerification, status_code=status.HTTP_201_CREATED
)
def verify_base_model_candidate_route(candidate_id: str) -> AtlasBaseModelVerification:
    """Real, live inspection against the local Ollama daemon.

    Never a rubber stamp: this appends a new VERIFIED or REJECTED record
    every call, and a prior REJECTED record is never silently erased.
    """
    candidate = _base_model_registry.get(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Base-model candidate was not found.")
    verification = verify_base_model_candidate(candidate)
    return _base_model_verification_store.save(verification)


@base_model_router.get("/{candidate_id}/verification", response_model=list[AtlasBaseModelVerification])
def base_model_candidate_verification_history(
    candidate_id: str, limit: int = Query(default=50, ge=1, le=200)
) -> list[AtlasBaseModelVerification]:
    return _base_model_verification_store.history(candidate_id, limit=limit)


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


@bench_router.get("/runs-by-candidate/{candidate_id}", response_model=list[AtlasBenchSuiteRun])
def list_bench_runs_for_candidate(candidate_id: str, limit: int = Query(default=50, ge=1, le=200)) -> list[AtlasBenchSuiteRun]:
    """Every recorded AtlasBench run (any corpus -- V1, V2, or later) naming
    this candidate. Discovery only: it decides nothing about promotion and
    does not require the candidate to be verified or current production.
    This is what lets the GUI show AtlasBench V2 evidence for a candidate
    without the frontend ever hardcoding a run id or candidate id.
    """
    return _bench_store.list_runs_for_candidate(candidate_id, limit=limit)


promotion_router = APIRouter(prefix="/api/v1/atlas/promotion", tags=["atlas-promotion"])


def _require_verified_candidate(candidate_id: str) -> AtlasCandidateKind:
    """Source-neutral trust gate: a trained Foundry candidate verified by
    ``atlas_candidate_trust`` and a verified off-the-shelf base model
    verified by ``atlas_base_model_trust`` earn exactly the same gate here --
    neither kind is weaker than the other, and there is no third way in.
    """
    trained = _candidate_registry.get(candidate_id)
    if trained is not None:
        if not is_verified(_candidate_verification_store, candidate_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Candidate has no VERIFIED artifact-trust record; refusing to compute a promotion-eligibility decision. "
                "Run POST /candidates/{candidate_id}/verify first.",
            )
        return AtlasCandidateKind.TRAINED_ADAPTER
    base_model = _base_model_registry.get(candidate_id)
    if base_model is not None:
        if not is_base_model_verified(_base_model_verification_store, candidate_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Candidate has no VERIFIED base-model trust record; refusing to compute a promotion-eligibility decision. "
                "Run POST /base-model-candidates/{candidate_id}/verify first.",
            )
        return AtlasCandidateKind.VERIFIED_BASE_MODEL
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate artifact was not found.")


def _latest_verification_identity(
    candidate_id: str, kind: AtlasCandidateKind
) -> tuple[Optional[str], Optional[str]]:
    """Return (verification_id, aggregate_candidate_fingerprint) for
    whichever trust store this candidate's kind actually verified through."""
    verification = (
        _candidate_verification_store.latest(candidate_id)
        if kind is AtlasCandidateKind.TRAINED_ADAPTER
        else _base_model_verification_store.latest(candidate_id)
    )
    if verification is None:
        return None, None
    return verification.verification_id, verification.aggregate_candidate_fingerprint


@promotion_router.get("/current", response_model=Optional[AtlasProductionPointer])
def current_production() -> Optional[AtlasProductionPointer]:
    return _promotion_store.current_production()


@promotion_router.get("/history", response_model=list[AtlasProductionPointer])
def promotion_history(limit: int = Query(default=100, ge=1, le=500)) -> list[AtlasProductionPointer]:
    return _promotion_store.history(limit=limit)


@promotion_router.get("/current-status", response_model=AtlasProductionTrustStatus)
def current_production_trust_status() -> AtlasProductionTrustStatus:
    """Read-only aggregation for the GUI's model/trust panel.

    Decides nothing and verifies nothing new -- it only reads back whatever
    the promotion, trust, runtime-binding, AtlasBench, and Operational
    Certification stores already durably recorded, so the panel can never
    show a status this server did not already establish elsewhere.
    """
    production = _promotion_store.current_production()
    if production is None:
        return AtlasProductionTrustStatus()

    candidate_id = production.candidate_id
    candidate_kind: Optional[AtlasCandidateKind] = None
    trust_state = None
    if _candidate_registry.get(candidate_id) is not None:
        candidate_kind = AtlasCandidateKind.TRAINED_ADAPTER
        verification = _candidate_verification_store.latest(candidate_id)
        trust_state = verification.verification_state if verification else None
    elif _base_model_registry.get(candidate_id) is not None:
        candidate_kind = AtlasCandidateKind.VERIFIED_BASE_MODEL
        base_verification = _base_model_verification_store.latest(candidate_id)
        trust_state = base_verification.verification_state if base_verification else None

    binding = _candidate_runtime_store.latest(candidate_id)

    latest_v1_run_id = latest_v1_total_passed = latest_v1_total_tasks = None
    for run in _bench_store.list_runs_for_corpus(CORPUS_VERSION, corpus_hash()):
        if run.candidate_id == candidate_id and run.subject_kind in {"production", "candidate"}:
            latest_v1_run_id, latest_v1_total_passed, latest_v1_total_tasks = (
                run.run_id, run.total_passed, run.total_tasks,
            )
            break  # already ordered newest-first

    from .atlas_operational_cert import DurableAtlasOperationalCertStore

    opcert_runs = DurableAtlasOperationalCertStore().list_for_candidate(candidate_id, limit=1)
    opcert = opcert_runs[0] if opcert_runs else None

    return AtlasProductionTrustStatus(
        production=production,
        candidate_kind=candidate_kind,
        runtime_model=binding.runtime_model if binding else None,
        runtime_model_digest=binding.runtime_model_digest if binding else None,
        trust_verification_state=trust_state,
        latest_v1_run_id=latest_v1_run_id,
        latest_v1_total_passed=latest_v1_total_passed,
        latest_v1_total_tasks=latest_v1_total_tasks,
        latest_operational_cert_run_id=opcert.run_id if opcert else None,
        latest_operational_cert_total_passed=opcert.total_passed if opcert else None,
        latest_operational_cert_total_scenarios=opcert.total_scenarios if opcert else None,
        latest_operational_cert_critical_failures=opcert.critical_failure_count if opcert else None,
    )


@promotion_router.post("/decisions", response_model=AtlasPromotionDecision, status_code=status.HTTP_201_CREATED)
def compute_promotion_decision(
    candidate_id: str,
    production_run_id: str,
    candidate_run_id: str,
) -> AtlasPromotionDecision:
    candidate_kind = _require_verified_candidate(candidate_id)
    production_run = _bench_store.get_run(production_run_id)
    candidate_run = _bench_store.get_run(candidate_run_id)
    if production_run is None or candidate_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Both AtlasBench runs must exist before a decision can be computed.")
    if production_run.run_id == candidate_run.run_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Production and candidate AtlasBench runs must be distinct.")
    candidate_binding = _candidate_runtime_store.latest(candidate_id)
    verification_id, candidate_fingerprint = _latest_verification_identity(candidate_id, candidate_kind)
    if candidate_binding is None or verification_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Candidate has no current verified runtime binding.")
    if (
        candidate_run.subject_kind != "candidate"
        or candidate_run.candidate_id != candidate_id
        or candidate_run.runtime_model != candidate_binding.runtime_model
        or candidate_run.runtime_model_digest != candidate_binding.runtime_model_digest
        or candidate_run.trust_verification_id != verification_id
        or candidate_run.candidate_fingerprint != candidate_fingerprint
        or candidate_run.provider != candidate_binding.provider
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Candidate AtlasBench run is not server-bound to this exact verified candidate runtime.")
    production = _promotion_store.current_production()
    production_binding = _candidate_runtime_store.latest(production.candidate_id) if production else None
    if (
        production is None or production_binding is None
        or production_run.subject_kind != "production"
        or production_run.candidate_id != production.candidate_id
        or production_run.runtime_model != production_binding.runtime_model
        or production_run.runtime_model_digest != production_binding.runtime_model_digest
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Production AtlasBench run is not bound to the current durable production runtime.")
    if (
        production_run.corpus_version != candidate_run.corpus_version
        or production_run.corpus_hash != candidate_run.corpus_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Production and candidate must be evaluated against the identical AtlasBench corpus.",
        )
    production_categories = {score.category: score.total for score in production_run.category_scores}
    candidate_categories = {score.category: score.total for score in candidate_run.category_scores}
    if production_categories != candidate_categories or production_run.total_tasks != candidate_run.total_tasks:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Production and candidate must have identical complete AtlasBench category coverage "
                "and task totals; refusing an incomplete comparison."
            ),
        )
    if not production_run.evaluation_policy_id or not candidate_run.evaluation_policy_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Production and candidate AtlasBench runs must both carry an explicit evaluation-policy identity "
                "(e.g. a pinned context-token window). A run predating this field, or one that used an "
                "ambiguous/default inference policy, is legacy evidence and cannot be used for a promotion decision."
            ),
        )
    if production_run.evaluation_policy_id != candidate_run.evaluation_policy_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Production and candidate AtlasBench runs were evaluated under different evaluation policies "
                "(context window, temperature, output tokens, timeout, or prompt schema); refusing an "
                "incomparable promotion decision."
            ),
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
    trained = _candidate_registry.get(decision.candidate_id)
    if trained is not None:
        if not is_verified(_candidate_verification_store, decision.candidate_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Candidate has no VERIFIED artifact-trust record; refusing to promote.",
            )
    else:
        base_model = _base_model_registry.get(decision.candidate_id)
        if base_model is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The decision references a candidate artifact that is no longer available.")
        if not is_base_model_verified(_base_model_verification_store, decision.candidate_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Candidate has no VERIFIED base-model trust record; refusing to promote.",
            )
    binding = _candidate_runtime_store.latest(decision.candidate_id)
    if binding is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Candidate has no verified Ollama runtime binding; promotion cannot change Atlas safely.",
        )
    from .atlas_operational_cert import (
        latest_candidate_operational_run,
        operational_certification_failure_reason,
    )

    operational_failure = operational_certification_failure_reason(
        latest_candidate_operational_run(decision.candidate_id),
        candidate_id=decision.candidate_id,
        runtime_model_digest=binding.runtime_model_digest,
    )
    if operational_failure is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Operational Certification prerequisite not met: {operational_failure}",
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
