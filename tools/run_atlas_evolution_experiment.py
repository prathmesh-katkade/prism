"""Run PRISM's first real local Atlas evolution experiment.

This is deliberately an orchestration script over the existing Phase 10
boundaries, not a second training/runtime implementation. It:

1. verifies the real local Ollama production model and records AtlasBench;
2. persists that verified model as the rollback anchor when needed;
3. builds a versioned verified training corpus and exports TRAIN split only;
4. installs/pins Soup in an isolated local venv when requested;
5. runs a Resource-Governor-admitted QLoRA/LoRA smoke job;
6. exports/deploys the real adapter to Ollama under a candidate-only name;
7. runs the identical frozen AtlasBench corpus against that candidate;
8. stores the locked server-owned promotion verdict; and
9. only when PROMOTE_ELIGIBLE, performs a real promotion/runtime-switch and
   rollback drill, ending back on the exact production model that started the
   experiment.

HOLD and REJECT are valid experiment outcomes. Hidden chain-of-thought is never
exported, validation/test training examples are never passed to Soup, and a
candidate never controls its benchmark answer key, thresholds, or verdict.

Run from repository root with Python 3.10-3.12:
    python tools/run_atlas_evolution_experiment.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

ROOT = Path(__file__).resolve().parents[1]
for relative in (
    "apps/api/src",
    "packages/api-contracts/python",
    "packages/config/python",
    "packages/overview-analytics/python",
    "packages/sql-lab-runtime/python",
    "packages/analytical-schemas/python",
):
    path = str(ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)

import httpx  # noqa: E402
from prism_api.atlas_bench_live import (  # noqa: E402
    AtlasBenchSubjectUnavailable,
    AtlasProviderBenchSubject,
    run_candidate_benchmark,  # noqa: E402
    run_live_benchmark,
)
from prism_api.atlas_candidate_runtime import (  # noqa: E402
    DurableAtlasCandidateRuntimeStore,
    activate_current_ollama_model,
    ensure_configured_production_baseline,
)
from prism_api.atlas_candidate_trust import (  # noqa: E402
    DurableAtlasCandidateVerificationStore,
    verify_candidate,
)
from prism_api.atlas_combined_sft_dataset import (  # noqa: E402
    DurableAtlasCombinedSftStore,
    build_combined_records,
    export_alpaca_jsonl,
)
from prism_api.atlas_foundry_backend import SoupFoundryBackend  # noqa: E402
from prism_api.atlas_foundry_dataset import (  # noqa: E402
    AtlasTrainingDatasetBuilder,
    DurableAtlasTrainingDatasetStore,
)
from prism_api.atlas_foundry_orchestration import (  # noqa: E402
    DurableAtlasCandidateRegistry,
    DurableAtlasFoundryJobStore,
    reconcile_foundry_jobs,
    start_training_job,
)
from prism_api.atlas_foundry_routes import (  # noqa: E402
    compute_promotion_decision,
    promote_candidate,
    rollback_production,
)
from prism_api.atlas_promotion import DurableAtlasPromotionStore  # noqa: E402
from prism_api.atlas_resources import governor  # noqa: E402
from prism_api.atlas_system_seed import (  # noqa: E402
    DurableAtlasSystemSeedStore,
    build_manifest,
    build_verified_system_seed_corpus,
)
from prism_api.durable_atlas_store import DurableAtlasRunStore  # noqa: E402
from prism_api_contracts import (  # noqa: E402
    AtlasModelProviderName,
    AtlasPromotionVerdict,
    AtlasTrainingJobState,
    AtlasTrainingRecipe,
    AtlasTrainingRecipeMethod,
    AtlasTrainingSplit,
)

PINNED_SOUP_VERSION = "0.74.0"
DEFAULT_BASE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
RUNTIME_ROOT = ROOT / ".prism" / "runtime"
EXPERIMENT_ROOT = RUNTIME_ROOT / "evolution-experiments"
SOUP_VENV = RUNTIME_ROOT / f"soup-{PINNED_SOUP_VERSION}-venv"


class ExperimentBlocked(RuntimeError):
    pass


@contextmanager
def temporary_environment(updates: dict[str, Optional[str]]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _venv_executable(name: str) -> Path:
    scripts = SOUP_VENV / ("Scripts" if os.name == "nt" else "bin")
    suffix = ".exe" if os.name == "nt" else ""
    return scripts / f"{name}{suffix}"


def ensure_soup(*, install: bool) -> str:
    existing = shutil.which("soup")
    if existing:
        return existing
    soup = _venv_executable("soup")
    if soup.exists():
        os.environ["PATH"] = f"{soup.parent}{os.pathsep}{os.environ.get('PATH', '')}"
        return str(soup)
    if not install:
        raise ExperimentBlocked(
            f"Soup is not installed. Re-run without --no-install-soup to create {SOUP_VENV}."
        )
    if not ((3, 10) <= sys.version_info[:2] < (3, 13)):
        raise ExperimentBlocked("Soup 0.74.0 requires Python >=3.10,<3.13.")
    SOUP_VENV.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "venv", str(SOUP_VENV)], check=True)
    pip = _venv_executable("pip")
    subprocess.run(
        [str(pip), "install", f"soup-cli[train]=={PINNED_SOUP_VERSION}"],
        check=True,
    )
    if not soup.exists():
        raise ExperimentBlocked("Soup installation completed without a soup executable.")
    os.environ["PATH"] = f"{soup.parent}{os.pathsep}{os.environ.get('PATH', '')}"
    return str(soup)


def hardware_snapshot() -> dict[str, object]:
    snapshot = governor.snapshot()
    return {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "cpu_count": snapshot.cpu_count,
        "memory_total_mb": snapshot.memory_total_mb,
        "memory_available_mb": snapshot.memory_available_mb,
        "storage_free_mb": snapshot.storage_free_mb,
        "gpu_available": snapshot.gpu_available,
        "gpu_name": snapshot.gpu_name,
        "vram_total_mb": snapshot.vram_total_mb,
        "gpu_detail": snapshot.gpu_telemetry_detail,
    }


def run_live_suite(*, candidate_model: Optional[str] = None):  # type: ignore[no-untyped-def]
    updates = {"PRISM_AI_PROVIDER": "ollama"}
    if candidate_model is not None:
        updates["PRISM_ATLAS_OLLAMA_MODEL"] = candidate_model
    with temporary_environment(updates):
        suite = run_live_benchmark(AtlasModelProviderName.OLLAMA)
        subject = AtlasProviderBenchSubject(AtlasModelProviderName.OLLAMA)
        if (
            suite.subject_kind != "production"
            or suite.runtime_model != subject.model
            or suite.runtime_model_digest != subject.model_digest
            or suite.provider != "ollama"
        ):
            raise ExperimentBlocked(
                "Production AtlasBench run lacks the required durable Ollama runtime binding."
            )
        return suite, subject


def build_training_dataset() -> tuple[object, Path, int, str, str]:
    history_store = DurableAtlasTrainingDatasetStore()
    history, exclusions = AtlasTrainingDatasetBuilder(DurableAtlasRunStore()).build()
    history_version = history_store.save(history, exclusions)
    seeds = build_verified_system_seed_corpus()
    seed_manifest = DurableAtlasSystemSeedStore().release(
        seeds, build_manifest(seeds, leakage_guard_passed=True)
    )
    records = build_combined_records(seeds, history, history_version=history_version.version_id)
    version = DurableAtlasCombinedSftStore().save(
        records,
        seed_version=seed_manifest.seed_version,
        seed_hash=seed_manifest.aggregate_content_hash,
        history_version=history_version.version_id,
        history_hash=history_version.content_hash,
    )
    train_records = [record for record in records if record.split is AtlasTrainingSplit.TRAIN]
    if not train_records:
        raise ExperimentBlocked(
            "Combined SFT corpus contains zero TRAIN records; refusing Soup execution."
        )
    export_path = EXPERIMENT_ROOT / version.version_id / "train.jsonl"
    train_sha256, provenance_sha256 = export_alpaca_jsonl(train_records, export_path)
    return version, export_path, len(train_records), train_sha256, provenance_sha256


def make_recipe(
    version_id: str, base_model: str, method: AtlasTrainingRecipeMethod
) -> AtlasTrainingRecipe:
    method_quant = "4bit" if method is AtlasTrainingRecipeMethod.QLORA else "none"
    return AtlasTrainingRecipe(
        recipe_id=f"evolution_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        base_model=base_model,
        method=method,
        task="sft",
        dataset_version_id=version_id,
        quantization=method_quant,
        lora_r=8,
        lora_alpha=16,
        lora_dropout=0.05,
        target_modules=["q_proj", "v_proj"],
        epochs=1,
        learning_rate=2e-4,
        batch_size=1,
        gradient_accumulation_steps=4,
        max_length=512,
        seed=7,
        stream_layers=True,
        created_at=datetime.now(timezone.utc),
    )


def wait_for_training(
    backend: SoupFoundryBackend,
    recipe: AtlasTrainingRecipe,
    dataset_path: Path,
    *,
    timeout_seconds: int,
    poll_seconds: float,
):  # type: ignore[no-untyped-def]
    job_store = DurableAtlasFoundryJobStore()
    candidates = DurableAtlasCandidateRegistry()
    job = start_training_job(governor, job_store, backend, recipe, dataset_path=dataset_path)
    deadline = time.monotonic() + timeout_seconds
    while job.state in {AtlasTrainingJobState.QUEUED, AtlasTrainingJobState.RUNNING}:
        if time.monotonic() >= deadline:
            backend.cancel(job)
            raise ExperimentBlocked(f"Training exceeded {timeout_seconds}s and was cancelled.")
        time.sleep(poll_seconds)
        reconcile_foundry_jobs(governor, job_store, backend, candidates, job_ids={job.job_id})
        stored = job_store.get(job.job_id)
        if stored is None:
            raise ExperimentBlocked("Foundry job disappeared from durable storage.")
        job = stored
    if job.state is not AtlasTrainingJobState.COMPLETED:
        raise ExperimentBlocked(
            f"Soup training ended in {job.state.value}: {job.error or 'no error detail'}"
        )
    candidate = candidates.get(f"candidate_{job.job_id}")
    if candidate is None:
        reconcile_foundry_jobs(governor, job_store, backend, candidates, job_ids={job.job_id})
        candidate = candidates.get(f"candidate_{job.job_id}")
    if candidate is None:
        raise ExperimentBlocked("Training completed but no real adapter candidate was registered.")
    return job, candidate, backend.metrics(job), backend.checkpoints(job)


def deploy_candidate_to_ollama(
    soup: str,
    candidate,  # type: ignore[no-untyped-def]
    *,
    timeout_seconds: int,
) -> tuple[str, str, str, str]:
    adapter_path = Path(candidate.adapter_path)
    if not adapter_path.exists():
        raise ExperimentBlocked(f"Candidate adapter path does not exist: {adapter_path}")
    runtime_name = (
        f"atlas-candidate-{hashlib.sha256(candidate.candidate_id.encode()).hexdigest()[:16]}"
    )
    gguf_path = adapter_path.parent / f"{runtime_name}.q4_k_m.gguf"
    export_log = adapter_path.parent / f"{runtime_name}.export.log"
    command = [
        soup,
        "export",
        "--model",
        str(adapter_path),
        "--format",
        "gguf",
        "--quant",
        "q4_k_m",
        "--output",
        str(gguf_path),
        "--base",
        candidate.base_model,
        "--deploy",
        "ollama",
        "--deploy-name",
        runtime_name,
    ]
    with export_log.open("wb") as output:
        result = subprocess.run(
            # Soup's Rich progress renderer succeeds with a real stream on
            # Windows but can terminate early when its merge is captured through
            # a pipe. Preserve the full exporter output as local evidence.
            command,
            stdout=output,
            stderr=subprocess.STDOUT,
            # The GGUF exporter starts Python helpers, which must retain UTF-8
            # mode on Windows even when the parent console uses CP-1252.
            env={**os.environ, "PYTHONUTF8": "1"},
            timeout=timeout_seconds,
            check=False,
        )
    if result.returncode != 0:
        detail = export_log.read_text(encoding="utf-8", errors="replace").strip()[-2_000:]
        raise ExperimentBlocked(f"Soup export/deploy failed ({result.returncode}): {detail}")

    base_url = os.environ.get("PRISM_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    response = httpx.get(f"{base_url}/api/tags", timeout=5.0)
    response.raise_for_status()
    models = response.json().get("models", [])
    digest = "digest-unavailable"
    runtime_model = runtime_name
    runtime_aliases = {runtime_name, f"{runtime_name}:latest"}
    for item in models:
        if isinstance(item, dict) and runtime_aliases.intersection({
            str(item.get("name", "")),
            str(item.get("model", "")),
        }):
            digest = str(item.get("digest", "")) or digest
            # Persist the daemon's canonical tag.  Ollama returns a deployed
            # nameless model as ``name:latest``; storing the pre-deploy alias
            # makes the later, independently constructed benchmark subject
            # fail its exact /api/tags trust probe.
            runtime_model = str(item.get("name", "")).strip() or str(
                item.get("model", "")
            ).strip()
            break
    else:
        raise ExperimentBlocked(
            "Soup reported successful Ollama deployment but the candidate is absent from /api/tags."
        )

    DurableAtlasCandidateRuntimeStore().bind_ollama(
        candidate.candidate_id,
        runtime_model,
        runtime_model_digest=digest,
    )
    return runtime_model, digest, str(gguf_path), str(export_log)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the first real local Atlas evolution experiment."
    )
    parser.add_argument("--base-model", default=DEFAULT_BASE_MODEL)
    parser.add_argument("--method", choices=("lora", "qlora"), default="qlora")
    parser.add_argument("--install-soup", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--training-timeout", type=int, default=3_600)
    parser.add_argument("--export-timeout", type=int, default=3_600)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()

    EXPERIMENT_ROOT.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "hardware": hardware_snapshot(),
        "soup_pin": PINNED_SOUP_VERSION,
        "base_model": args.base_model,
        "status": "running",
    }
    try:
        if args.base_model != DEFAULT_BASE_MODEL:
            raise ExperimentBlocked(
                f"This first smoke experiment is trust-locked to {DEFAULT_BASE_MODEL}. "
                "Extend the Model Trust Registry before selecting another base model."
            )
        os.environ.setdefault("PRISM_AI_PROVIDER", "ollama")

        promotion_store = DurableAtlasPromotionStore()
        if promotion_store.current_production() is not None:
            activate_current_ollama_model()

        baseline, baseline_subject = run_live_suite()
        report["production_baseline"] = baseline.model_dump(mode="json")
        report["production_model"] = baseline_subject.model
        report["production_model_digest"] = baseline_subject.model_digest

        if promotion_store.current_production() is None:
            ensure_configured_production_baseline(
                runtime_model_digest=baseline_subject.model_digest,
            )
        baseline_pointer = promotion_store.current_production()
        if baseline_pointer is None:
            raise ExperimentBlocked(
                "A durable production rollback anchor could not be established."
            )
        active_baseline_model = activate_current_ollama_model()
        if active_baseline_model != baseline_subject.model:
            raise ExperimentBlocked(
                "Durable production pointer does not resolve to the model that was benchmarked as production."
            )
        report["production_pointer_before"] = baseline_pointer.model_dump(mode="json")

        version, dataset_path, train_count, train_sha256, provenance_sha256 = (
            build_training_dataset()
        )
        report["training_dataset"] = version.model_dump(mode="json")
        report["training_examples_used"] = train_count
        report["training_export"] = str(dataset_path)
        report["training_export_sha256"] = train_sha256
        report["training_provenance_sha256"] = provenance_sha256

        soup = ensure_soup(install=args.install_soup)
        backend = SoupFoundryBackend()
        capability = backend.capability()
        report["foundry_capability"] = capability.model_dump(mode="json")
        if not capability.soup_available or not capability.can_train:
            raise ExperimentBlocked(capability.detail)

        method = AtlasTrainingRecipeMethod(args.method)
        recipe = make_recipe(version.version_id, args.base_model, method)
        preflight = backend.preflight(recipe)
        report["preflight"] = preflight.model_dump(mode="json")
        if not preflight.compatible:
            raise ExperimentBlocked(preflight.detail)

        job, candidate, metrics, checkpoints = wait_for_training(
            backend,
            recipe,
            dataset_path,
            timeout_seconds=args.training_timeout,
            poll_seconds=args.poll_seconds,
        )
        report["training_job"] = job.model_dump(mode="json")
        report["training_metrics"] = [item.model_dump(mode="json") for item in metrics]
        report["training_checkpoints"] = [item.model_dump(mode="json") for item in checkpoints]
        report["candidate"] = candidate.model_dump(mode="json")

        verification = DurableAtlasCandidateVerificationStore().save(
            verify_candidate(candidate, recipe)
        )
        report["candidate_verification"] = verification.model_dump(mode="json")
        if verification.verification_state.value != "verified":
            raise ExperimentBlocked(
                "Candidate artifact verification failed; refusing deploy and benchmark."
            )

        runtime_name, digest, gguf, export_log = deploy_candidate_to_ollama(
            soup,
            candidate,
            timeout_seconds=args.export_timeout,
        )
        report["candidate_runtime"] = {
            "provider": "ollama",
            "model": runtime_name,
            "digest": digest,
            "gguf": gguf,
            "export_log": export_log,
        }

        candidate_run = run_candidate_benchmark(candidate.candidate_id)
        report["candidate_benchmark"] = candidate_run.model_dump(mode="json")

        if (
            baseline.corpus_version != candidate_run.corpus_version
            or baseline.corpus_hash != candidate_run.corpus_hash
        ):
            raise ExperimentBlocked(
                "Production and candidate AtlasBench runs did not use the identical frozen corpus."
            )

        decision = compute_promotion_decision(
            candidate.candidate_id, baseline.run_id, candidate_run.run_id
        )
        report["promotion_decision"] = decision.model_dump(mode="json")

        if decision.verdict is AtlasPromotionVerdict.PROMOTE_ELIGIBLE:
            promoted = promote_candidate(
                decision.decision_id,
                reason="First real Atlas evolution experiment: promotion drill.",
            )
            report["promotion_pointer"] = promoted.model_dump(mode="json")
            promoted_model = activate_current_ollama_model()
            report["promoted_runtime_model"] = promoted_model
            if promoted_model != runtime_name:
                raise ExperimentBlocked(
                    "Promotion pointer was recorded but Atlas did not resolve to the candidate runtime model."
                )

            rollback = rollback_production(
                reason="First real Atlas evolution experiment: mandatory rollback drill.",
            )
            report["rollback_pointer"] = rollback.model_dump(mode="json")
            restored_model = activate_current_ollama_model()
            report["restored_runtime_model"] = restored_model
            if restored_model != baseline_subject.model:
                raise ExperimentBlocked(
                    "Rollback pointer was recorded but Atlas did not restore the exact pre-experiment production model."
                )
            report["promotion_performed"] = True
            report["rollback_drill"] = "done"
            report["promotion_note"] = (
                "Candidate earned PROMOTE_ELIGIBLE, was activated as Atlas production, then the mandatory rollback "
                "drill restored the exact starting production model."
            )
        else:
            report["promotion_performed"] = False
            report["rollback_drill"] = "not_required"
            report["promotion_note"] = (
                f"Candidate verdict was {decision.verdict.value}; production remained unchanged."
            )

        final_pointer = promotion_store.current_production()
        report["production_pointer_after"] = (
            final_pointer.model_dump(mode="json") if final_pointer is not None else None
        )
        report["production_model_after"] = activate_current_ollama_model()
        report["status"] = "complete"
        exit_code = 0
    except (
        ExperimentBlocked,
        AtlasBenchSubjectUnavailable,
        httpx.HTTPError,
        subprocess.SubprocessError,
    ) as error:
        report["status"] = "blocked"
        report["blocker"] = str(error)
        exit_code = 2
    except Exception as error:  # keep an inspectable report for unexpected local-runtime failures
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        exit_code = 1

    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = EXPERIMENT_ROOT / f"experiment-{stamp}.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"report": str(output), **report}, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
