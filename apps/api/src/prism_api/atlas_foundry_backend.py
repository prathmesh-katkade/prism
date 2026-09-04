"""10M: Atlas Foundry -- typed, backend-agnostic training-job orchestration.

Soup (https://github.com/MakazhanAlpamys/Soup) is a training *backend*, not
Atlas's runtime: normal Atlas inference has no import-time or runtime
dependency on this module, and everything here works with Soup absent (via
``MockFoundryBackend``). A candidate produced here is never production Atlas
by itself -- promotion is a separate, AtlasBench-gated decision (10P/10Q).

Soup invocation is deliberately narrow: exactly one constant argv shape per
operation (``["soup", "train", "--config", path]``, etc.), and every value an
LLM or user could influence flows only through a validated
``AtlasTrainingRecipe`` rendered to a YAML config file -- never through
string-built shell commands.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from prism_api_contracts import (
    AtlasFoundryBackendName,
    AtlasFoundryCapability,
    AtlasFoundryPreflight,
    AtlasTrainingCheckpoint,
    AtlasTrainingJob,
    AtlasTrainingJobState,
    AtlasTrainingMetric,
    AtlasTrainingRecipe,
)

from .atlas_platform import new_process_group_flag, process_alive, terminate_process_tree

# --- recipe -> Soup config rendering -----------------------------------------


def _recipe_to_soup_config(
    recipe: AtlasTrainingRecipe, *, dataset_path: Path, output_dir: Path
) -> dict[str, object]:
    return {
        "base": recipe.base_model,
        "task": recipe.task,
        "backend": "transformers",
        "data": {
            "train": str(dataset_path),
            "format": "dpo" if recipe.task == "dpo" else "auto",
            "max_length": recipe.max_length,
        },
        "training": {
            "epochs": recipe.epochs,
            "lr": recipe.learning_rate,
            "batch_size": recipe.batch_size,
            "gradient_accumulation_steps": recipe.gradient_accumulation_steps,
            "quantization": recipe.quantization,
            "seed": recipe.seed,
            "stream_layers": recipe.stream_layers,
            "lora": {
                "r": recipe.lora_r,
                "alpha": recipe.lora_alpha,
                "dropout": recipe.lora_dropout,
                "target_modules": list(recipe.target_modules),
            },
        },
        "output": str(output_dir),
    }


def write_recipe_config(
    recipe: AtlasTrainingRecipe, *, dataset_path: Path, output_dir: Path, config_path: Path
) -> Path:
    """Deterministically render a validated recipe to a Soup-compatible YAML
    config -- the only path recipe content takes to reach Soup."""
    config = _recipe_to_soup_config(recipe, dataset_path=dataset_path, output_dir=output_dir)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config, sort_keys=True, default_flow_style=False), encoding="utf-8")
    return config_path


def _has_adapter_output(output_dir: Path) -> bool:
    if not output_dir.exists():
        return False
    return any(output_dir.rglob("adapter_model.safetensors")) or any(output_dir.rglob("adapter_config.json"))


# --- backend contract ---------------------------------------------------


class FoundryBackend(ABC):
    """Backend-agnostic training-job contract.

    Methods take and return ``AtlasTrainingJob`` snapshots rather than owning
    their own state store: a backend is a stateless operator over durable
    state a caller (the orchestration layer, ``DurableAtlasFoundryJobStore``)
    persists between calls -- exactly like ``DurableAtlasRunStore`` /
    ``AtlasPythonSandbox`` keep execution and persistence separate.
    """

    @abstractmethod
    def capability(self) -> AtlasFoundryCapability: ...

    @abstractmethod
    def preflight(self, recipe: AtlasTrainingRecipe) -> AtlasFoundryPreflight: ...

    @abstractmethod
    def start(self, recipe: AtlasTrainingRecipe, *, dataset_path: Path) -> AtlasTrainingJob: ...

    @abstractmethod
    def poll(self, job: AtlasTrainingJob) -> AtlasTrainingJob: ...

    @abstractmethod
    def cancel(self, job: AtlasTrainingJob) -> AtlasTrainingJob: ...

    @abstractmethod
    def metrics(self, job: AtlasTrainingJob) -> list[AtlasTrainingMetric]: ...

    @abstractmethod
    def checkpoints(self, job: AtlasTrainingJob) -> list[AtlasTrainingCheckpoint]: ...


# --- mock backend ---------------------------------------------------------


class MockFoundryBackend(FoundryBackend):
    """Deterministic, fast, in-memory backend for tests and for any
    environment without a real GPU or a Soup install.

    Every job it returns carries ``backend=AtlasFoundryBackendName.MOCK`` --
    nothing here is presented as a real trained model, and its metrics are
    clearly synthetic placeholders, not fabricated training evidence.
    """

    def capability(self) -> AtlasFoundryCapability:
        return AtlasFoundryCapability(
            backend=AtlasFoundryBackendName.MOCK,
            soup_available=False,
            can_train=True,
            can_cancel=True,
            can_pause=False,
            detail="Mock backend: deterministic, completes synchronously, needs no GPU or Soup install.",
        )

    def preflight(self, recipe: AtlasTrainingRecipe) -> AtlasFoundryPreflight:
        return AtlasFoundryPreflight(
            compatible=True, detail="Mock backend does not estimate real resource usage."
        )

    def start(self, recipe: AtlasTrainingRecipe, *, dataset_path: Path) -> AtlasTrainingJob:
        now = datetime.now(timezone.utc)
        job_id = f"foundryjob_{uuid.uuid4().hex}"
        workspace = dataset_path.parent / f"mock-{job_id}"
        adapter_dir = workspace / "output"
        adapter_dir.mkdir(parents=True, exist_ok=True)
        (adapter_dir / "adapter_config.json").write_text(
            json.dumps({"mock": True, "recipe_id": recipe.recipe_id}), encoding="utf-8"
        )
        return AtlasTrainingJob(
            job_id=job_id,
            recipe_id=recipe.recipe_id,
            backend=AtlasFoundryBackendName.MOCK,
            state=AtlasTrainingJobState.COMPLETED,
            workspace_path=str(workspace),
            started_at=now,
            completed_at=now,
            created_at=now,
            updated_at=now,
        )

    def poll(self, job: AtlasTrainingJob) -> AtlasTrainingJob:
        return job  # mock jobs finish synchronously inside start()

    def cancel(self, job: AtlasTrainingJob) -> AtlasTrainingJob:
        if job.state in (
            AtlasTrainingJobState.COMPLETED,
            AtlasTrainingJobState.FAILED,
            AtlasTrainingJobState.CANCELLED,
        ):
            return job
        return job.model_copy(
            update={"state": AtlasTrainingJobState.CANCELLED, "updated_at": datetime.now(timezone.utc)}
        )

    def metrics(self, job: AtlasTrainingJob) -> list[AtlasTrainingMetric]:
        if job.state is not AtlasTrainingJobState.COMPLETED:
            return []
        return [
            AtlasTrainingMetric(
                job_id=job.job_id,
                step=1,
                loss=0.42,
                learning_rate=2e-4,
                recorded_at=job.completed_at or datetime.now(timezone.utc),
            )
        ]

    def checkpoints(self, job: AtlasTrainingJob) -> list[AtlasTrainingCheckpoint]:
        if job.state is not AtlasTrainingJobState.COMPLETED or not job.workspace_path:
            return []
        return [
            AtlasTrainingCheckpoint(
                checkpoint_id=f"{job.job_id}_final",
                job_id=job.job_id,
                step=1,
                path=str(Path(job.workspace_path) / "output"),
                created_at=job.completed_at or datetime.now(timezone.utc),
            )
        ]


# --- real Soup backend -----------------------------------------------------


class SoupFoundryBackend(FoundryBackend):
    """Shells out to the real ``soup`` CLI (https://github.com/MakazhanAlpamys/Soup).

    ``shell=False`` with a fixed argv list is the actual injection defense --
    recipe content only ever reaches Soup through a YAML file this module
    renders from validated Pydantic fields (``write_recipe_config``), never
    through string interpolation into a command line.
    """

    def __init__(self, *, workspace_root: Optional[Path] = None) -> None:
        self.workspace_root = (workspace_root or Path(".prism/runtime/foundry-jobs")).resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _soup_path() -> Optional[str]:
        return shutil.which("soup")

    def capability(self) -> AtlasFoundryCapability:
        soup = self._soup_path()
        if soup is None:
            return AtlasFoundryCapability(
                backend=AtlasFoundryBackendName.SOUP,
                soup_available=False,
                can_train=False,
                can_cancel=False,
                can_pause=False,
                detail="The `soup` CLI is not installed in this environment; Foundry training is unavailable until it is.",
            )
        version = None
        try:
            result = subprocess.run([soup, "version"], capture_output=True, text=True, timeout=10, check=False)
            lines = result.stdout.strip().splitlines()
            version = lines[0][:64] if lines else None
        except (OSError, subprocess.TimeoutExpired):
            pass
        return AtlasFoundryCapability(
            backend=AtlasFoundryBackendName.SOUP,
            soup_available=True,
            soup_version=version,
            can_train=True,
            can_cancel=True,
            can_pause=False,
            detail="Soup CLI available. Training subprocesses can be started and hard-cancelled; graceful pause/resume is not implemented.",
        )

    def preflight(self, recipe: AtlasTrainingRecipe) -> AtlasFoundryPreflight:
        """Read-only: ``soup profile`` only estimates, it never trains."""
        soup = self._soup_path()
        if soup is None:
            return AtlasFoundryPreflight(compatible=False, detail="The `soup` CLI is not installed; cannot preflight.")
        workspace = self.workspace_root / f"preflight_{uuid.uuid4().hex}"
        try:
            config_path = write_recipe_config(
                recipe,
                dataset_path=Path("dataset.jsonl"),
                output_dir=workspace / "output",
                config_path=workspace / "config.yaml",
            )
            result = subprocess.run(
                [soup, "profile", "--config", str(config_path), "--json"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if result.returncode != 0:
                return AtlasFoundryPreflight(
                    compatible=False,
                    detail=f"soup profile exited {result.returncode}: {result.stderr.strip()[:500]}",
                )
            payload = json.loads(result.stdout)
            return AtlasFoundryPreflight(
                compatible=True,
                estimated_total_memory_gb=payload.get("total_memory_gb"),
                estimated_tokens_per_sec=payload.get("tokens_per_sec"),
                recommended_batch_size=payload.get("recommended_batch_size"),
                detail="Estimate from `soup profile --json`; no training occurred.",
            )
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError) as error:
            return AtlasFoundryPreflight(compatible=False, detail=f"Preflight failed: {error}")
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def start(self, recipe: AtlasTrainingRecipe, *, dataset_path: Path) -> AtlasTrainingJob:
        now = datetime.now(timezone.utc)
        job_id = f"foundryjob_{uuid.uuid4().hex}"
        soup = self._soup_path()
        if soup is None:
            return AtlasTrainingJob(
                job_id=job_id,
                recipe_id=recipe.recipe_id,
                backend=AtlasFoundryBackendName.SOUP,
                state=AtlasTrainingJobState.FAILED,
                error="The `soup` CLI is not installed in this environment.",
                created_at=now,
                updated_at=now,
            )
        workspace = self.workspace_root / job_id
        output_dir = workspace / "output"
        config_path = write_recipe_config(
            recipe, dataset_path=dataset_path, output_dir=output_dir, config_path=workspace / "config.yaml"
        )
        log_path = workspace / "soup.log"
        with log_path.open("w", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                [soup, "train", "--config", str(config_path)],
                cwd=str(workspace),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=new_process_group_flag(),
                start_new_session=os.name != "nt",
            )
        return AtlasTrainingJob(
            job_id=job_id,
            recipe_id=recipe.recipe_id,
            backend=AtlasFoundryBackendName.SOUP,
            state=AtlasTrainingJobState.RUNNING,
            process_id=process.pid,
            workspace_path=str(workspace),
            started_at=now,
            created_at=now,
            updated_at=now,
        )

    def poll(self, job: AtlasTrainingJob) -> AtlasTrainingJob:
        if job.state is not AtlasTrainingJobState.RUNNING or job.process_id is None:
            return job
        if process_alive(job.process_id):
            return job
        now = datetime.now(timezone.utc)
        succeeded = bool(job.workspace_path and _has_adapter_output(Path(job.workspace_path) / "output"))
        return job.model_copy(
            update={
                "state": AtlasTrainingJobState.COMPLETED if succeeded else AtlasTrainingJobState.FAILED,
                "completed_at": now,
                "updated_at": now,
                "error": None
                if succeeded
                else "soup train exited without producing adapter output; see the job's soup.log.",
            }
        )

    def cancel(self, job: AtlasTrainingJob) -> AtlasTrainingJob:
        if job.state not in (AtlasTrainingJobState.RUNNING, AtlasTrainingJobState.QUEUED):
            return job
        if job.process_id is not None:
            terminate_process_tree(job.process_id, new_session=os.name != "nt")
        now = datetime.now(timezone.utc)
        return job.model_copy(update={"state": AtlasTrainingJobState.CANCELLED, "completed_at": now, "updated_at": now})

    def metrics(self, job: AtlasTrainingJob) -> list[AtlasTrainingMetric]:
        if not job.workspace_path:
            return []
        output_dir = Path(job.workspace_path) / "output"
        found: list[AtlasTrainingMetric] = []
        for state_path in sorted(output_dir.glob("checkpoint-*/trainer_state.json")):
            try:
                payload = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for entry in payload.get("log_history", []):
                if "step" not in entry:
                    continue
                found.append(
                    AtlasTrainingMetric(
                        job_id=job.job_id,
                        step=int(entry["step"]),
                        loss=entry.get("loss"),
                        learning_rate=entry.get("learning_rate"),
                        recorded_at=job.updated_at,
                    )
                )
        return found

    def checkpoints(self, job: AtlasTrainingJob) -> list[AtlasTrainingCheckpoint]:
        if not job.workspace_path:
            return []
        output_dir = Path(job.workspace_path) / "output"
        found: list[AtlasTrainingCheckpoint] = []
        for path in sorted(output_dir.glob("checkpoint-*")):
            if not path.is_dir():
                continue
            try:
                step = int(path.name.split("-", 1)[1])
            except (IndexError, ValueError):
                continue
            found.append(
                AtlasTrainingCheckpoint(
                    checkpoint_id=f"{job.job_id}_{path.name}",
                    job_id=job.job_id,
                    step=step,
                    path=str(path),
                    created_at=job.updated_at,
                )
            )
        return found
