"""10M-3 + Candidate Registry: Resource Governor integration and durable
Foundry job/candidate persistence.

Foundry training never starts unmanaged: every job is admitted through
``AtlasResourceGovernor`` at ``AtlasResourcePriority.FOUNDRY_TRAINING`` --
the lowest interactive-relevant priority -- so a real user interaction can
preempt it. No backend in this wave implements a graceful pause/resume
handshake, so "yield" here is an honest hard-cancel of the training
subprocess on preemption, not a fabricated pause capability.

``AtlasCandidateArtifact`` here is intentionally just the durable fact of
what a completed job produced (adapter path, base model, recipe, dataset
lineage) -- not a promotion state machine. DISCOVERED/VERIFIED/PROMOTED/...
lifecycle status is 10Q's concern (Shadow Brain / Promotion), which is
explicitly sequenced after AtlasBench; recording it here before that
machinery exists would be a status this project cannot yet honor.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from prism_api_contracts import (
    AtlasCandidateArtifact,
    AtlasResourceLeaseRequest,
    AtlasResourcePriority,
    AtlasResourceWorkload,
    AtlasTrainingJob,
    AtlasTrainingJobState,
    AtlasTrainingRecipe,
)
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine

from .atlas_foundry_backend import FoundryBackend
from .atlas_resources import AtlasResourceGovernor
from .atlas_schema_utils import ensure_index
from .durable_registry import history_database_url

_metadata = MetaData()
_recipes = Table(
    "prism_atlas_foundry_recipes",
    _metadata,
    Column("recipe_id", String(120), primary_key=True),
    Column("payload", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
)
_jobs = Table(
    "prism_atlas_foundry_jobs",
    _metadata,
    Column("job_id", String(120), primary_key=True),
    Column("recipe_id", String(120), nullable=False, index=True),
    Column("backend", String(16), nullable=False),
    Column("state", String(16), nullable=False, index=True),
    Column("resource_lease_id", String(120), nullable=True, index=True),
    Column("process_id", Integer, nullable=True),
    Column("workspace_path", String(2_000), nullable=True),
    Column("error", Text, nullable=True),
    # Set only while state == QUEUED: what to (re)start once the lease this
    # job is waiting on goes active. Cleared once the job actually starts.
    Column("pending_recipe_payload", Text, nullable=True),
    Column("pending_dataset_path", String(2_000), nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
_candidates = Table(
    "prism_atlas_candidate_artifacts",
    _metadata,
    Column("candidate_id", String(120), primary_key=True),
    Column("job_id", String(120), nullable=False, index=True),
    Column("recipe_id", String(120), nullable=False, index=True),
    Column("base_model", String(300), nullable=False),
    Column("method", String(16), nullable=False),
    Column("adapter_path", String(2_000), nullable=False),
    Column("dataset_version_id", String(120), nullable=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
)


class DurableAtlasFoundryJobStore:
    def __init__(self, database_url: Optional[str] = None) -> None:
        url = database_url or history_database_url()
        self.engine: Engine = create_engine(
            url,
            future=True,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        )
        _metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            ensure_index(
                connection,
                "prism_atlas_foundry_jobs",
                "ix_prism_atlas_foundry_jobs_lease",
                "CREATE INDEX ix_prism_atlas_foundry_jobs_lease "
                "ON prism_atlas_foundry_jobs (resource_lease_id)",
            )

    def save_recipe(self, recipe: AtlasTrainingRecipe) -> AtlasTrainingRecipe:
        """Durably record every recipe a job was started from -- training
        provenance (base model, method, dataset lineage, hyperparameters)
        must survive independently of any single job's transient state.
        Idempotent: saving the same recipe_id twice is a no-op.
        """
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(_recipes.c.recipe_id).where(_recipes.c.recipe_id == recipe.recipe_id)
            ).scalar_one_or_none()
            if existing is None:
                connection.execute(
                    insert(_recipes).values(
                        recipe_id=recipe.recipe_id,
                        payload=json.dumps(recipe.model_dump(mode="json"), sort_keys=True),
                        created_at=recipe.created_at,
                    )
                )
        return recipe

    def get_recipe(self, recipe_id: str) -> Optional[AtlasTrainingRecipe]:
        row = (
            self.engine.connect()
            .execute(select(_recipes.c.payload).where(_recipes.c.recipe_id == recipe_id))
            .scalar_one_or_none()
        )
        return None if row is None else AtlasTrainingRecipe.model_validate(json.loads(row))

    def save(
        self,
        job: AtlasTrainingJob,
        *,
        pending_recipe: Optional[AtlasTrainingRecipe] = None,
        pending_dataset_path: Optional[Path] = None,
    ) -> AtlasTrainingJob:
        values = {
            "job_id": job.job_id,
            "recipe_id": job.recipe_id,
            "backend": job.backend.value,
            "state": job.state.value,
            "resource_lease_id": job.resource_lease_id,
            "process_id": job.process_id,
            "workspace_path": job.workspace_path,
            "error": job.error,
            "pending_recipe_payload": (
                json.dumps(pending_recipe.model_dump(mode="json"), sort_keys=True)
                if pending_recipe is not None
                else None
            ),
            "pending_dataset_path": str(pending_dataset_path) if pending_dataset_path is not None else None,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        }
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(_jobs.c.job_id).where(_jobs.c.job_id == job.job_id)
            ).scalar_one_or_none()
            if existing is None:
                connection.execute(insert(_jobs).values(**values))
            else:
                connection.execute(update(_jobs).where(_jobs.c.job_id == job.job_id).values(**values))
        return job

    @staticmethod
    def _record(row: object) -> AtlasTrainingJob:
        return AtlasTrainingJob.model_validate(
            {
                "job_id": row["job_id"],  # type: ignore[index]
                "recipe_id": row["recipe_id"],  # type: ignore[index]
                "backend": row["backend"],  # type: ignore[index]
                "state": row["state"],  # type: ignore[index]
                "resource_lease_id": row["resource_lease_id"],  # type: ignore[index]
                "process_id": row["process_id"],  # type: ignore[index]
                "workspace_path": row["workspace_path"],  # type: ignore[index]
                "error": row["error"],  # type: ignore[index]
                "started_at": row["started_at"],  # type: ignore[index]
                "completed_at": row["completed_at"],  # type: ignore[index]
                "created_at": row["created_at"],  # type: ignore[index]
                "updated_at": row["updated_at"],  # type: ignore[index]
            }
        )

    def get(self, job_id: str) -> Optional[AtlasTrainingJob]:
        row = self.engine.connect().execute(select(_jobs).where(_jobs.c.job_id == job_id)).mappings().first()
        return None if row is None else self._record(row)

    def pending_start(self, job_id: str) -> tuple[Optional[AtlasTrainingRecipe], Optional[Path]]:
        row = (
            self.engine.connect()
            .execute(select(_jobs.c.pending_recipe_payload, _jobs.c.pending_dataset_path).where(_jobs.c.job_id == job_id))
            .mappings()
            .first()
        )
        if row is None or row["pending_recipe_payload"] is None:
            return None, None
        recipe = AtlasTrainingRecipe.model_validate(json.loads(row["pending_recipe_payload"]))
        dataset_path = Path(row["pending_dataset_path"]) if row["pending_dataset_path"] else None
        return recipe, dataset_path

    def list_active(self, *, limit: int = 200) -> list[AtlasTrainingJob]:
        statement = (
            select(_jobs)
            .where(_jobs.c.state.in_([AtlasTrainingJobState.QUEUED.value, AtlasTrainingJobState.RUNNING.value]))
            .order_by(_jobs.c.created_at)
            .limit(limit)
        )
        return [self._record(row) for row in self.engine.connect().execute(statement).mappings().all()]

    def list_by_state(self, state: AtlasTrainingJobState, *, limit: int = 200) -> list[AtlasTrainingJob]:
        statement = select(_jobs).where(_jobs.c.state == state.value).order_by(_jobs.c.created_at.desc()).limit(limit)
        return [self._record(row) for row in self.engine.connect().execute(statement).mappings().all()]


class DurableAtlasCandidateRegistry:
    def __init__(self, database_url: Optional[str] = None) -> None:
        url = database_url or history_database_url()
        self.engine: Engine = create_engine(
            url,
            future=True,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        )
        _metadata.create_all(self.engine)

    def register(self, candidate: AtlasCandidateArtifact) -> AtlasCandidateArtifact:
        existing = self.get(candidate.candidate_id)
        if existing is not None:
            return existing  # idempotent: registering the same candidate twice is a no-op
        with self.engine.begin() as connection:
            connection.execute(
                insert(_candidates).values(
                    candidate_id=candidate.candidate_id,
                    job_id=candidate.job_id,
                    recipe_id=candidate.recipe_id,
                    base_model=candidate.base_model,
                    method=candidate.method.value,
                    adapter_path=candidate.adapter_path,
                    dataset_version_id=candidate.dataset_version_id,
                    created_at=candidate.created_at,
                )
            )
        return candidate

    def get(self, candidate_id: str) -> Optional[AtlasCandidateArtifact]:
        row = (
            self.engine.connect()
            .execute(select(_candidates).where(_candidates.c.candidate_id == candidate_id))
            .mappings()
            .first()
        )
        return None if row is None else AtlasCandidateArtifact.model_validate(dict(row))

    def list(self, *, limit: int = 100) -> list[AtlasCandidateArtifact]:
        statement = select(_candidates).order_by(_candidates.c.created_at.desc()).limit(limit)
        rows = self.engine.connect().execute(statement).mappings().all()
        return [AtlasCandidateArtifact.model_validate(dict(row)) for row in rows]


def _lease_description(recipe: AtlasTrainingRecipe) -> str:
    return f"Foundry training: {recipe.base_model} ({recipe.method.value}, {recipe.task})"[:500]


def start_training_job(
    governor: AtlasResourceGovernor,
    job_store: DurableAtlasFoundryJobStore,
    backend: FoundryBackend,
    recipe: AtlasTrainingRecipe,
    *,
    dataset_path: Path,
) -> AtlasTrainingJob:
    """Admit a job through the Resource Governor before touching the backend
    at all. If capacity is unavailable, the job is durably QUEUED (with
    enough state to start it later) rather than either blocking or bypassing
    admission control.
    """
    job_store.save_recipe(recipe)
    capability = backend.capability()
    lease = governor.acquire(
        AtlasResourceLeaseRequest(
            workload=AtlasResourceWorkload(
                workload_id=f"foundry_{recipe.recipe_id}_{uuid.uuid4().hex[:8]}",
                priority=AtlasResourcePriority.FOUNDRY_TRAINING,
                cancellable=True,
                description=_lease_description(recipe),
            )
        )
    )
    now = datetime.now(timezone.utc)
    if lease.state != "active":
        job = AtlasTrainingJob(
            job_id=f"foundryjob_{uuid.uuid4().hex}",
            recipe_id=recipe.recipe_id,
            backend=capability.backend,
            state=AtlasTrainingJobState.QUEUED,
            resource_lease_id=lease.lease_id,
            created_at=now,
            updated_at=now,
        )
        return job_store.save(job, pending_recipe=recipe, pending_dataset_path=dataset_path)
    job = backend.start(recipe, dataset_path=dataset_path).model_copy(update={"resource_lease_id": lease.lease_id})
    return job_store.save(job)


def reconcile_foundry_jobs(
    governor: AtlasResourceGovernor,
    job_store: DurableAtlasFoundryJobStore,
    backend: FoundryBackend,
    candidate_registry: DurableAtlasCandidateRegistry,
) -> list[AtlasTrainingJob]:
    """Advance every non-terminal job by one step. Call this periodically
    (a REST poll, a scheduled Routine -- there is no background daemon in
    this wave) rather than expecting jobs to advance themselves.

    Order matters: a preempted lease is honored before anything else, so an
    interactive workload that just won admission actually gets the GPU back
    this tick, not next tick.
    """
    leases_by_id = {lease.lease_id: lease for lease in governor.snapshot().active_leases}
    updated: list[AtlasTrainingJob] = []
    for job in job_store.list_active():
        lease = leases_by_id.get(job.resource_lease_id) if job.resource_lease_id else None
        if lease is not None and lease.state == "preempted":
            cancelled = backend.cancel(job) if job.state is AtlasTrainingJobState.RUNNING else job.model_copy(
                update={"state": AtlasTrainingJobState.CANCELLED, "updated_at": datetime.now(timezone.utc)}
            )
            updated.append(job_store.save(cancelled))
            continue
        if job.state is AtlasTrainingJobState.QUEUED:
            if lease is None or lease.state != "active":
                continue  # still waiting for capacity
            recipe, dataset_path = job_store.pending_start(job.job_id)
            if recipe is None or dataset_path is None:
                continue  # nothing durably recorded to start; leave as-is
            started = backend.start(recipe, dataset_path=dataset_path).model_copy(
                update={"job_id": job.job_id, "resource_lease_id": job.resource_lease_id}
            )
            updated.append(job_store.save(started))
            continue
        # RUNNING: ask the backend whether it finished.
        polled = backend.poll(job)
        if polled.state is not job.state:
            updated.append(job_store.save(polled))
            if polled.state is AtlasTrainingJobState.COMPLETED and polled.workspace_path:
                _register_candidate_if_present(candidate_registry, job_store, polled)
            if job.resource_lease_id and polled.state in (
                AtlasTrainingJobState.COMPLETED,
                AtlasTrainingJobState.FAILED,
                AtlasTrainingJobState.CANCELLED,
            ):
                try:
                    governor.release(job.resource_lease_id)
                except KeyError:
                    pass
    return updated


def _register_candidate_if_present(
    registry: DurableAtlasCandidateRegistry, job_store: DurableAtlasFoundryJobStore, job: AtlasTrainingJob
) -> None:
    """A completed job becomes a registered candidate artifact -- a durable
    fact, not a promotion decision. Requires the job's original recipe (for
    base_model/method/dataset lineage) and real adapter output on disk;
    either missing means this is not yet a candidate worth registering.
    """
    if not job.workspace_path:
        return
    adapter_path = Path(job.workspace_path) / "output"
    if not adapter_path.exists():
        return
    recipe = job_store.get_recipe(job.recipe_id)
    if recipe is None:
        return
    registry.register(
        AtlasCandidateArtifact(
            candidate_id=f"candidate_{job.job_id}",
            job_id=job.job_id,
            recipe_id=job.recipe_id,
            base_model=recipe.base_model,
            method=recipe.method,
            adapter_path=str(adapter_path),
            dataset_version_id=recipe.dataset_version_id,
            created_at=job.completed_at or datetime.now(timezone.utc),
        )
    )
