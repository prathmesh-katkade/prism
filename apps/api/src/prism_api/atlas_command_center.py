"""Bounded, read-only dashboard composition; no model calls or eligibility scans."""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Annotated, Optional, TypeVar

from fastapi import APIRouter, Depends, Query, Response
from prism_api_contracts import (
    AtlasBenchSuiteRun,
    AtlasCommandCenterSummary,
    AtlasFeedbackEvent,
    AtlasMemoryQuery,
    AtlasMemoryRecord,
    AtlasProductionPointer,
    AtlasRecentRunSummary,
    AtlasSectionAvailability,
)

from . import atlas, atlas_feedback
from . import atlas_foundry_routes as foundry
from .atlas_authorization import Principal, require_local_owner
from .atlas_operational_cert import DurableAtlasOperationalCertStore
from .atlas_runtime import SPECIALISTS
from .atlas_runtime import runs as run_store

router = APIRouter(prefix="/api/v1/atlas", tags=["atlas"])
logger = logging.getLogger("prism_api.command_center")
T = TypeVar("T")


@router.get("/command-center", response_model=AtlasCommandCenterSummary)
def command_center(response: Response, principal: Annotated[Principal, Depends(require_local_owner)], dataset_id: Optional[str] = Query(default=None, max_length=255)) -> AtlasCommandCenterSummary:
    response.headers["Cache-Control"] = "no-store"
    now = datetime.now(timezone.utc)
    sections: dict[str, AtlasSectionAvailability] = {}

    def read(name: str, operation: Callable[[], T], fallback: T) -> T:
        try:
            value = operation()
            sections[name] = AtlasSectionAvailability(state="available" if value is not None else "unavailable",
                observed_at=now, detail="Read from durable records; observation is not a live model verification." if value is not None else "No record available.")
            return value
        except Exception:
            logger.exception("command_center_section_failed section=%s", name)
            sections[name] = AtlasSectionAvailability(state="error", observed_at=now, detail="Section could not be read. Retry to recover.")
            return fallback

    status = read("trust", foundry.current_production_trust_status, None)
    candidate_id = status.production.candidate_id if status and status.production else None
    candidate = read("candidate", lambda: foundry._base_model_registry.get(candidate_id) if candidate_id else None, None)
    verification = read("verification", lambda: foundry._base_model_verification_store.latest(candidate_id) if candidate_id else None, None)
    bench: list[AtlasBenchSuiteRun] = read("bench", lambda: foundry._bench_store.list_runs_for_candidate(candidate_id, limit=20) if candidate_id else [], [])
    operational = read("operational", lambda: DurableAtlasOperationalCertStore().get(status.latest_operational_cert_run_id) if status and status.latest_operational_cert_run_id else None, None)
    seed = read("system_seed", lambda: next(iter(foundry.list_system_seed_versions(limit=1)), None), None)
    teacher = read("synthetic_teacher", lambda: next(iter(foundry.list_synthetic_teacher_versions(limit=1)), None), None)
    sft = read("combined_sft", lambda: next(iter(foundry.list_combined_sft_datasets(limit=1)), None), None)
    runs: list[AtlasRecentRunSummary] = read("runs", lambda: run_store.recent_summaries(dataset_id=dataset_id, limit=8), [])
    history: list[AtlasProductionPointer] = read("promotion_history", lambda: foundry.promotion_history(limit=20), [])
    memories: list[AtlasMemoryRecord] = read("memory", lambda: atlas.memory.query(AtlasMemoryQuery(limit=50)), [])
    feedback: list[AtlasFeedbackEvent] = read("feedback", lambda: atlas_feedback.list_recent_feedback(limit=20), [])
    retrieval = read("retrieval", atlas.retrieval_capability, None)
    sections["project"] = AtlasSectionAvailability(state="unavailable", observed_at=now,
        detail="No authenticated project ownership source is integrated. Local workspace only.")
    sections["training_eligibility"] = AtlasSectionAvailability(state="unavailable", observed_at=now,
        detail="Current eligibility requires the explicit training summary drill-down. Released corpus provenance is shown here.")
    return AtlasCommandCenterSummary(generated_at=now, sections=sections, status=status, candidate=candidate,
        verification=verification, bench_runs=bench, operational_run=operational, promotion_history=history,
        system_seed=seed, synthetic_teacher=teacher, combined_sft=sft, recent_runs=runs,
        specialists=list(SPECIALISTS), memories=memories, feedback=feedback, retrieval=retrieval, dataset_id=dataset_id)
