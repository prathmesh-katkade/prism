"""Compare one and two concurrent model-backed Atlas fixture requests locally.

The real API and Ollama run against a disposable backup copy. No pointer is
changed; numerical results are checked by the warm workflow driver.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx
from benchmark_atlas_warm_workflows import run_one, upload
from verify_atlas_disposable_startup import await_ready, sha256, stop


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


def measure_mode(client: httpx.Client, sql_id: str, stat_id: str, workers: int, offset: int) -> dict[str, object]:
    baseline = gpu_sample()
    readings: list[tuple[int, int]] = []
    done = threading.Event()

    def sample_resources() -> None:
        while not done.is_set():
            reading = gpu_sample()
            if reading is not None:
                readings.append(reading)
            done.wait(0.5)

    sampler = threading.Thread(target=sample_resources, daemon=True)
    sampler.start()
    tasks = [("sql", sql_id), ("stat", stat_id), ("sql", sql_id), ("stat", stat_id)]
    samples: list[dict[str, object]] = []
    errors: list[str] = []
    started = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="atlas-model-benchmark") as pool:
            futures = {}
            for index, (kind, dataset_id) in enumerate(tasks):
                submitted = time.perf_counter()

                def execute(kind: str = kind, dataset_id: str = dataset_id, index: int = index, submitted: float = submitted) -> dict[str, object]:
                    task_started = time.perf_counter()
                    sample = run_one(client, dataset_id, kind, offset + index)
                    sample["client_queue_ms"] = round((task_started - submitted) * 1000, 2)
                    run = client.get(f"/api/v1/atlas/runs/{sample['run_id']}").json()
                    plan = next((event for event in run["events"] if event["type"] == "plan_created"), None)
                    if plan is None:
                        raise AssertionError("Missing plan provenance")
                    sample["provider"] = plan["payload"].get("provider")
                    sample["model"] = plan["payload"].get("model")
                    sample["model_proposal"] = plan["payload"].get("model_proposal")
                    return sample

                futures[pool.submit(execute)] = index
            for future in as_completed(futures):
                try:
                    samples.append(future.result())
                except Exception as error:
                    errors.append(f"task {futures[future]}: {type(error).__name__}: {error}")
    finally:
        done.set()
        sampler.join(timeout=3)
    return {
        "workers": workers, "task_count": len(tasks), "success_count": len(samples), "errors": errors,
        "wall_ms": round((time.perf_counter() - started) * 1000, 2),
        "gpu_baseline_mib": baseline[0] if baseline else None,
        "gpu_peak_mib": max((item[0] for item in readings), default=None),
        "gpu_peak_utilization_pct": max((item[1] for item in readings), default=None),
        "gpu_sample_count": len(readings), "samples": sorted(samples, key=lambda item: str(item["run_id"])),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--port", type=int, default=8772)
    args = parser.parse_args()
    backup = args.backup.resolve(strict=True)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    original_hash = sha256(backup)
    with tempfile.TemporaryDirectory(prefix="prism-atlas-model-benchmark-", ignore_cleanup_errors=True) as directory:  # type: ignore[call-overload]
        temp = Path(directory)
        database = temp / "history.sqlite"
        shutil.copy2(backup, database)
        environment_file = temp / "api.env"
        environment_file.write_text(
            f"PRISM_ANALYTICAL_HISTORY_DATABASE_URL=sqlite:///{database.as_posix()}\n"
            f"PRISM_SQL_METADATA_PATH={str(temp / 'sql-lab.sqlite')}\n"
            "PRISM_REQUIRE_DURABLE_HISTORY=true\nPRISM_AI_PROVIDER=ollama\n",
            encoding="utf-8",
        )
        log: Any = (output_dir / "model-concurrency-api.log").open("wb")
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "prism_api.main:app", "--app-dir", "apps/api/src",
             "--env-file", str(environment_file), "--host", "127.0.0.1", "--port", str(args.port)],
            cwd=root, stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env={**os.environ, "PRISM_AI_PROVIDER": "ollama"},
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=45) as client:
                await_ready(client, process)
                pointer_before = client.get("/api/v1/atlas/promotion/current").json()
                sql = upload(client, "model-sql.csv", b"region,revenue\nwest,10\neast,7\nwest,5\n")
                stat = upload(client, "model-stat.csv", b"exposure,outcome\n1,2\n2,4\n3,6\n4,8\n5,10\n")
                warm = run_one(client, str(sql["dataset_id"]), "sql", 100)
                single = measure_mode(client, str(sql["dataset_id"]), str(stat["dataset_id"]), 1, 101)
                parallel = measure_mode(client, str(sql["dataset_id"]), str(stat["dataset_id"]), 2, 201)
                pointer_after = client.get("/api/v1/atlas/promotion/current").json()
        finally:
            stop(process, log)
            # A spawned statistical worker can release its Windows SQLite file
            # handle shortly after the API parent exits.
            time.sleep(1)
        result = {
            "model_source": "copied fast production pointer",
            "warmup_run_id": warm["run_id"], "single": single, "parallel": parallel,
            "backup_sha256_unchanged": sha256(backup) == original_hash,
            "promotion_pointer_unchanged": pointer_before == pointer_after,
        }
        path = output_dir / "model-concurrency-result.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({"single_wall_ms": single["wall_ms"], "parallel_wall_ms": parallel["wall_ms"],
                          "single_errors": single["errors"], "parallel_errors": parallel["errors"]}, sort_keys=True))
        if not result["backup_sha256_unchanged"] or not result["promotion_pointer_unchanged"]:
            raise AssertionError("Backup or promotion pointer changed")


if __name__ == "__main__":
    main()
