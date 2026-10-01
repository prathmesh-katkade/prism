"""Phase 2: measure the frozen warm workflow through the real, verified
production model binding, with bounded specialist review enabled.

This intentionally does not reuse the qwen2.5:3b default-dev-model warm
benchmark (tools/benchmark_atlas_warm_workflows.py's own default run):
that number does not establish the production model's latency, and this
run also keeps specialist review turned on, which that earlier benchmark
predates. Review is run strictly sequentially; see the model-concurrency
benchmark for the separate decision to keep parallel dispatch disabled.

The production binding is resolved and live-verified against the Ollama
daemon *before* the API process is even launched, and the exact verified
tag is set as PRISM_ATLAS_OLLAMA_MODEL for that process, so every model
call this benchmark makes -- plan proposal and specialist review alike --
uses that one verified binding, never a silent fallback.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import cast

import httpx
from benchmark_atlas_warm_workflows import percentile, run_one, upload
from verify_atlas_disposable_startup import await_ready, launch, sha256, stop

WARMUP_COUNT = 2
SAMPLE_PAIRS = 10  # 10 SQL + 10 Pearson = 20 warm samples, matching the frozen fixture.
P95_TARGET_MS = 60_000


def resolve_and_verify_production_binding(expected_model: str) -> str:
    """Fail closed: never silently substitute another tag if this one is
    not actually present in the live Ollama daemon right now."""
    response = httpx.get("http://127.0.0.1:11434/api/tags", timeout=5)
    response.raise_for_status()
    models = response.json().get("models", [])
    match = next((item for item in models if expected_model in {item.get("name"), item.get("model")}), None)
    if match is None:
        raise RuntimeError(
            f"Production binding {expected_model!r} is not present in the live Ollama daemon; "
            "refusing to silently substitute another tag. Pull it or correct the pointer first."
        )
    digest = str(match.get("digest", "")).strip()
    if not digest:
        raise RuntimeError(f"Live Ollama manifest for {expected_model!r} carries no digest.")
    return digest


def gpu_sample() -> tuple[int, int] | None:
    try:
        process = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        used, utilization = process.stdout.strip().splitlines()[0].split(",")
        return int(used.strip()), int(utilization.strip())
    except (OSError, ValueError, subprocess.SubprocessError, IndexError):
        return None


def _review_breakdown(events: list[dict[str, object]]) -> dict[str, object]:
    review_events = [
        cast(dict[str, object], event["payload"]["specialist_review"])
        for event in events
        if event["type"] == "step_completed" and isinstance(event.get("payload"), dict)
        and isinstance(cast(dict[str, object], event["payload"]).get("specialist_review"), dict)
    ]
    synthesis = next((item for item in review_events if event_step_id(events, item) == "synthesis"), None)
    return {
        "review_call_count": len(review_events),
        "review_ms_total": round(sum(cast(float, item.get("duration_ms", 0.0)) for item in review_events), 2),
        "review_statuses": [item.get("status") for item in review_events],
        "synthesis_review_ms": synthesis.get("duration_ms") if synthesis else None,
        "synthesis_review_status": synthesis.get("status") if synthesis else None,
    }


def event_step_id(events: list[dict[str, object]], review_payload: dict[str, object]) -> str | None:
    for event in events:
        payload = cast(dict[str, object], event.get("payload") or {})
        if payload.get("specialist_review") is review_payload:
            return cast(str | None, event.get("step_id"))
    return None


def run_with_review_breakdown(client: httpx.Client, dataset_id: str, kind: str, index: int) -> dict[str, object]:
    sample = run_one(client, dataset_id, kind, index)
    run = client.get(f"/api/v1/atlas/runs/{sample['run_id']}").json()
    sample.update(_review_breakdown(run["events"]))
    sample["model_origin_message_count"] = sum(1 for message in run["messages"] if message["origin"] == "model")
    sample["review_unavailable_count"] = sum(1 for message in run["messages"] if message["kind"] == "review_unavailable")
    sample["model_bindings_used"] = sorted({
        message["model_binding"] for message in run["messages"] if message.get("model_binding")
    })
    plan_event = next((event for event in run["events"] if event["type"] == "plan_created"), None)
    sample["plan_proposal_model"] = plan_event["payload"].get("model") if plan_event else None
    return sample


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--port", type=int, default=8786)
    parser.add_argument("--model", default="qwen3:4b-instruct-2507-q4_K_M")
    args = parser.parse_args()
    backup = args.backup.resolve(strict=True)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    original_hash = sha256(backup)

    verified_digest = resolve_and_verify_production_binding(args.model)
    model_binding = f"{args.model}@{verified_digest}"
    print(json.dumps({"resolved_and_verified_binding": model_binding}))

    declaration = {
        "fixture": "10 SQL aggregation + 10 declared Pearson, sequential",
        "warmup_runs_excluded": WARMUP_COUNT,
        "sample_pairs": SAMPLE_PAIRS,
        "sample_count_declared": SAMPLE_PAIRS * 2,
        "specialist_review_enabled": True,
        "inference_policy": "sequential (one in-flight model call at a time; see model-concurrency benchmark)",
        "model_binding": model_binding,
        "p95_target_ms": P95_TARGET_MS,
        "cold_start_excluded_from_warm_p95": True,
        "human_wait_excluded": True,
    }

    with tempfile.TemporaryDirectory(prefix="prism-atlas-prod-benchmark-") as directory:
        temp = Path(directory)
        database = temp / "history.sqlite"
        shutil.copy2(backup, database)
        environment_file = temp / "api.env"
        environment_file.write_text(
            f"PRISM_ANALYTICAL_HISTORY_DATABASE_URL=sqlite:///{database.as_posix()}\n"
            f"PRISM_SQL_METADATA_PATH={str(temp / 'sql-lab.sqlite')}\n"
            f"PRISM_REQUIRE_DURABLE_HISTORY=true\nPRISM_AI_PROVIDER=ollama\n"
            f"PRISM_ATLAS_OLLAMA_MODEL={args.model}\n",
            encoding="utf-8",
        )

        cold_started = time.perf_counter()
        process, log = launch(root, environment_file, output_dir / "cold-start-api.log", args.port, provider="ollama")
        with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=15) as client:
            await_ready(client, process)
            cold_start_ms = round((time.perf_counter() - cold_started) * 1000, 2)
            pointer_before = client.get("/api/v1/atlas/promotion/current").json()

            gpu_baseline = gpu_sample()
            gpu_readings: list[tuple[int, int]] = []
            stop_sampling = threading.Event()

            def _sample_gpu() -> None:
                while not stop_sampling.is_set():
                    reading = gpu_sample()
                    if reading is not None:
                        gpu_readings.append(reading)
                    stop_sampling.wait(1.0)

            sampler = threading.Thread(target=_sample_gpu, daemon=True)
            sampler.start()
            try:
                sql_dataset = upload(client, "prod-warm-sql.csv", b"region,revenue\nwest,10\neast,7\nwest,5\n")
                stat_dataset = upload(client, "prod-warm-stat.csv", b"exposure,outcome\n1,2\n2,4\n3,6\n4,8\n5,10\n")
                for warmup in range(WARMUP_COUNT):
                    run_with_review_breakdown(client, str(sql_dataset["dataset_id"]), "sql", -1 - warmup)
                    run_with_review_breakdown(client, str(stat_dataset["dataset_id"]), "stat", -1 - warmup)
                samples = [
                    run_with_review_breakdown(
                        client, str(sql_dataset["dataset_id"] if kind == "sql" else stat_dataset["dataset_id"]), kind, i,
                    )
                    for i in range(1, SAMPLE_PAIRS + 1) for kind in ("sql", "stat")
                ]
            finally:
                stop_sampling.set()
                sampler.join(timeout=3)
            pointer_after = client.get("/api/v1/atlas/promotion/current").json()
        stop(process, log)

        final_hash = sha256(backup)
        if final_hash != original_hash:
            raise AssertionError("Supplied backup changed")
        if pointer_before != pointer_after:
            raise AssertionError("Promotion pointer changed during the benchmark")

        values = [cast(float, item["total_ms"]) for item in samples]
        models_used = {item.get("plan_proposal_model") for item in samples}
        bindings_used: set[str] = set()
        for item in samples:
            bindings_used.update(cast(list[str], item["model_bindings_used"]))
        result = {
            **declaration,
            "sample_count": len(samples),
            "models_used_for_plan_proposal": sorted(str(item) for item in models_used if item),
            "model_bindings_used_for_review": sorted(bindings_used),
            "total_p50_ms": percentile(values, 0.5),
            "total_p95_ms": percentile(values, 0.95),
            "total_max_ms": max(values),
            "total_mean_ms": round(statistics.fmean(values), 2),
            "p95_method": "nearest rank",
            "passed_target": percentile(values, 0.95) <= P95_TARGET_MS,
            "cold_start_ms": cold_start_ms,
            "correctness_failures": 0,  # run_one() itself raises AssertionError on any incorrect result.
            "review_ms_total_p50": percentile([cast(float, item["review_ms_total"]) for item in samples], 0.5),
            "review_ms_total_p95": percentile([cast(float, item["review_ms_total"]) for item in samples], 0.95),
            "model_origin_messages_total": sum(cast(int, item["model_origin_message_count"]) for item in samples),
            "review_unavailable_total": sum(cast(int, item["review_unavailable_count"]) for item in samples),
            "queue_ms_p50": percentile([cast(float, item["queue_ms"]) for item in samples if item["queue_ms"] is not None], 0.5),
            "planning_ms_p50": percentile([cast(float, item["planning_ms"]) for item in samples if item["planning_ms"] is not None], 0.5),
            "tool_ms_p50": percentile([cast(float, item["tool_ms"]) for item in samples if item["tool_ms"] is not None], 0.5),
            "gpu_baseline_mib": gpu_baseline[0] if gpu_baseline else None,
            "gpu_peak_mib": max((item[0] for item in gpu_readings), default=None),
            "gpu_peak_utilization_pct": max((item[1] for item in gpu_readings), default=None),
            "gpu_sample_count": len(gpu_readings),
            "backup_sha256_unchanged": True,
            "promotion_pointer_unchanged": True,
            "samples": samples,
        }
        path = output_dir / "production-warm-workflow-result.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({key: result[key] for key in (
            "sample_count", "total_p50_ms", "total_p95_ms", "total_max_ms", "passed_target",
            "cold_start_ms", "review_ms_total_p50", "review_ms_total_p95",
            "model_origin_messages_total", "review_unavailable_total",
            "gpu_peak_mib", "gpu_peak_utilization_pct",
        )}, sort_keys=True))


if __name__ == "__main__":
    main()
