from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from prism_api.atlas_foundry_backend import FoundryBackend, MockFoundryBackend
from prism_api.atlas_foundry_orchestration import (
    DurableAtlasCandidateRegistry,
    DurableAtlasFoundryJobStore,
    reconcile_foundry_jobs,
    start_training_job,
)
from prism_api.atlas_resources import AtlasResourceGovernor
from prism_api_contracts import (
    AtlasFoundryBackendName,
    AtlasFoundryCapability,
    AtlasFoundryPreflight,
    AtlasResourceLeaseRequest,
    AtlasResourcePriority,
    AtlasResourceWorkload,
    AtlasTrainingJob,
    AtlasTrainingJobState,
    AtlasTrainingRecipe,
    AtlasTrainingRecipeMethod,
)


def _recipe(**overrides) -> AtlasTrainingRecipe:  # type: ignore[no-untyped-def]
    defaults: dict[str, object] = dict(
        recipe_id="recipe_1",
        base_model="base/model",
        method=AtlasTrainingRecipeMethod.QLORA,
        task="sft",
        dataset_version_id="trainset_1",
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return AtlasTrainingRecipe.model_validate(defaults)


class _StubRunningBackend(FoundryBackend):
    """Test-only backend: starts RUNNING, moves to COMPLETED (with real
    adapter output written to disk) on its first poll() -- exercising the
    same reconciliation path SoupFoundryBackend's process-exit detection
    does, without spawning any real process."""

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace

    def capability(self) -> AtlasFoundryCapability:
        return AtlasFoundryCapability(
            backend=AtlasFoundryBackendName.SOUP, soup_available=True, can_train=True, can_cancel=True, detail="stub"
        )

    def preflight(self, recipe: AtlasTrainingRecipe) -> AtlasFoundryPreflight:
        return AtlasFoundryPreflight(compatible=True, detail="stub")

    def start(self, recipe: AtlasTrainingRecipe, *, dataset_path: Path) -> AtlasTrainingJob:
        now = datetime.now(timezone.utc)
        return AtlasTrainingJob(
            job_id=f"foundryjob_{recipe.recipe_id}",
            recipe_id=recipe.recipe_id,
            backend=AtlasFoundryBackendName.SOUP,
            state=AtlasTrainingJobState.RUNNING,
            workspace_path=str(self._workspace),
            started_at=now,
            created_at=now,
            updated_at=now,
        )

    def poll(self, job: AtlasTrainingJob) -> AtlasTrainingJob:
        if job.state is not AtlasTrainingJobState.RUNNING:
            return job
        output = self._workspace / "output"
        output.mkdir(parents=True, exist_ok=True)
        (output / "adapter_config.json").write_text("{}", encoding="utf-8")
        now = datetime.now(timezone.utc)
        return job.model_copy(update={"state": AtlasTrainingJobState.COMPLETED, "completed_at": now, "updated_at": now})

    def cancel(self, job: AtlasTrainingJob) -> AtlasTrainingJob:
        if job.state not in (AtlasTrainingJobState.RUNNING, AtlasTrainingJobState.QUEUED):
            return job
        return job.model_copy(update={"state": AtlasTrainingJobState.CANCELLED, "updated_at": datetime.now(timezone.utc)})

    def metrics(self, job: AtlasTrainingJob) -> list:  # type: ignore[type-arg]
        return []

    def checkpoints(self, job: AtlasTrainingJob) -> list:  # type: ignore[type-arg]
        return []


def _stores(tmp_path):  # type: ignore[no-untyped-def]
    url = f"sqlite:///{(tmp_path / 'foundry.sqlite').as_posix()}"
    return DurableAtlasFoundryJobStore(url), DurableAtlasCandidateRegistry(url)


def _dataset(tmp_path):  # type: ignore[no-untyped-def]
    path = tmp_path / "train.jsonl"
    path.write_text('{"messages": []}\n', encoding="utf-8")
    return path


def test_recipe_store_is_durable_and_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    job_store, _ = _stores(tmp_path)
    recipe = _recipe()
    job_store.save_recipe(recipe)
    job_store.save_recipe(recipe)  # idempotent
    fetched = job_store.get_recipe(recipe.recipe_id)
    assert fetched is not None and fetched.base_model == recipe.base_model
    assert job_store.get_recipe("does_not_exist") is None


def test_start_training_job_admits_through_the_resource_governor(tmp_path) -> None:  # type: ignore[no-untyped-def]
    job_store, _ = _stores(tmp_path)
    governor = AtlasResourceGovernor(max_active=4)
    backend = MockFoundryBackend()
    job = start_training_job(governor, job_store, backend, _recipe(), dataset_path=_dataset(tmp_path))
    assert job.resource_lease_id is not None
    assert any(lease.lease_id == job.resource_lease_id for lease in governor.snapshot().active_leases)
    stored = job_store.get(job.job_id)
    assert stored is not None and stored.state is job.state


def test_queued_job_starts_once_capacity_frees_up(tmp_path) -> None:  # type: ignore[no-untyped-def]
    job_store, candidates = _stores(tmp_path)
    governor = AtlasResourceGovernor(max_active=1)
    backend = MockFoundryBackend()

    blocker = governor.acquire(
        AtlasResourceLeaseRequest(
            workload=AtlasResourceWorkload(
                workload_id="blocker", priority=AtlasResourcePriority.FOUNDRY_TRAINING, cancellable=False, description="blocker"
            )
        )
    )
    assert blocker.state == "active"

    queued = start_training_job(governor, job_store, backend, _recipe(recipe_id="r2"), dataset_path=_dataset(tmp_path))
    assert queued.state is AtlasTrainingJobState.QUEUED

    governor.release(blocker.lease_id)  # governor auto-promotes the queued lease to active
    updated = reconcile_foundry_jobs(governor, job_store, backend, candidates)
    assert any(
        item.job_id == queued.job_id and item.state is AtlasTrainingJobState.COMPLETED for item in updated
    )


def test_preempted_lease_causes_the_running_job_to_be_cancelled(tmp_path) -> None:  # type: ignore[no-untyped-def]
    job_store, candidates = _stores(tmp_path)
    governor = AtlasResourceGovernor(max_active=1)
    backend = _StubRunningBackend(tmp_path / "job-workspace")

    job = start_training_job(governor, job_store, backend, _recipe(), dataset_path=_dataset(tmp_path))
    assert job.state is AtlasTrainingJobState.RUNNING

    interactive = governor.acquire(
        AtlasResourceLeaseRequest(
            workload=AtlasResourceWorkload(
                workload_id="chat", priority=AtlasResourcePriority.USER_INTERACTION, description="chat"
            )
        )
    )
    assert interactive.state == "active"  # preempted the lower-priority, cancellable Foundry lease

    updated = reconcile_foundry_jobs(governor, job_store, backend, candidates)
    assert any(item.job_id == job.job_id and item.state is AtlasTrainingJobState.CANCELLED for item in updated)


def test_completed_job_registers_exactly_one_candidate(tmp_path) -> None:  # type: ignore[no-untyped-def]
    job_store, candidates = _stores(tmp_path)
    governor = AtlasResourceGovernor(max_active=4)
    backend = _StubRunningBackend(tmp_path / "job-workspace-2")

    job = start_training_job(governor, job_store, backend, _recipe(recipe_id="r3"), dataset_path=_dataset(tmp_path))
    assert job.state is AtlasTrainingJobState.RUNNING

    reconcile_foundry_jobs(governor, job_store, backend, candidates)  # -> COMPLETED, registers a candidate
    reconcile_foundry_jobs(governor, job_store, backend, candidates)  # job is now terminal; no double-registration

    registered = candidates.list()
    assert len(registered) == 1
    assert registered[0].job_id == job.job_id
    assert registered[0].base_model == "base/model"
    assert registered[0].dataset_version_id == "trainset_1"


def test_candidate_registry_register_is_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, candidates = _stores(tmp_path)
    from prism_api_contracts import AtlasCandidateArtifact

    artifact = AtlasCandidateArtifact(
        candidate_id="candidate_1",
        job_id="job_1",
        recipe_id="recipe_1",
        base_model="base/model",
        method=AtlasTrainingRecipeMethod.LORA,
        adapter_path="/tmp/adapter",
        dataset_version_id="trainset_1",
        created_at=datetime.now(timezone.utc),
    )
    first = candidates.register(artifact)
    second = candidates.register(artifact)
    assert first.candidate_id == second.candidate_id
    assert len(candidates.list()) == 1
