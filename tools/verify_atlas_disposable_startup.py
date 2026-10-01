"""Exercise the real API launch twice on a disposable SQLite backup copy.

This script never opens the supplied backup for writing. It creates a temporary
copy, points all durable stores at that copy, and removes the copy on exit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def await_ready(client: httpx.Client, process: subprocess.Popen[bytes]) -> None:
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError(f"API process exited early with {process.returncode}")
        try:
            response = client.get("/api/v1/platform/ready")
            if response.status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.2)
    raise TimeoutError("API did not become ready within 20 seconds")


def launch(root: Path, environment_file: Path, log_path: Path, port: int, *, provider: str = "deterministic") -> tuple[subprocess.Popen[bytes], object]:
    log = log_path.open("wb")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "prism_api.main:app", "--app-dir", "apps/api/src",
         "--env-file", str(environment_file), "--host", "127.0.0.1", "--port", str(port)],
        cwd=root, stdout=log, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env={**os.environ, "PRISM_AI_PROVIDER": provider},
    )
    return process, log


def stop(process: subprocess.Popen[bytes], log: object) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    log.close()  # type: ignore[attr-defined]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--port", type=int, default=8769)
    args = parser.parse_args()
    backup = args.backup.resolve(strict=True)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    original_hash = sha256(backup)
    with tempfile.TemporaryDirectory(prefix="prism-atlas-disposable-") as directory:
        temp = Path(directory)
        database = temp / "history.sqlite"
        shutil.copy2(backup, database)
        environment_file = temp / "api.env"
        environment_file.write_text(
            f"PRISM_ANALYTICAL_HISTORY_DATABASE_URL=sqlite:///{database.as_posix()}\n"
            f"PRISM_SQL_METADATA_PATH={str(temp / 'sql-lab.sqlite')}\n"
            "PRISM_AI_PROVIDER=deterministic\n",
            encoding="utf-8",
        )
        result: dict[str, object] = {"backup_sha256_before": original_hash}
        with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=10) as client:
            for iteration in (1, 2):
                process, log = launch(root, environment_file, output_dir / f"startup-{iteration}.log", args.port)
                try:
                    await_ready(client, process)
                    response = client.get("/api/v1/atlas/promotion/current")
                    response.raise_for_status()
                    result[f"pointer_after_start_{iteration}"] = response.json()
                    if iteration == 1:
                        upload = client.post("/api/v1/overview/datasets", files={
                            "file": ("atlas-fixture.csv", b"region,revenue\nwest,10\neast,7\nwest,5\n", "text/csv")
                        })
                        upload.raise_for_status()
                        dataset = upload.json()
                        result["dataset"] = dataset
                        started = client.post("/api/v1/atlas/runs", json={
                            "dataset_id": dataset["dataset_id"], "objective": "Sum revenue by region using SQL",
                            "sql_analysis": {"aggregate": "sum", "measure": "revenue", "group_by": "region"},
                        })
                        started.raise_for_status()
                        run_id = started.json()["run_id"]
                        result["run_id"] = run_id
                        for _ in range(120):
                            run = client.get(f"/api/v1/atlas/runs/{run_id}").json()
                            if run["plan"]["state"] in {"completed", "failed", "cancelled"}:
                                break
                            time.sleep(0.1)
                        result["run_after_execution"] = run
                        if run["plan"]["state"] != "completed":
                            raise RuntimeError(f"Atlas run did not complete: {run['plan']['state']}")
                        stat_upload = client.post("/api/v1/overview/datasets", files={
                            "file": ("atlas-stat-fixture.csv", b"exposure,outcome\n1,2\n2,4\n3,6\n4,8\n5,10\n", "text/csv")
                        })
                        stat_upload.raise_for_status()
                        stat_dataset = stat_upload.json()
                        result["stat_dataset"] = stat_dataset
                        started_stat = client.post("/api/v1/atlas/runs", json={
                            "dataset_id": stat_dataset["dataset_id"], "objective": "Test correlation significance",
                        })
                        started_stat.raise_for_status()
                        stat_run_id = started_stat.json()["run_id"]
                        result["stat_run_id"] = stat_run_id
                        for _ in range(120):
                            waiting = client.get(f"/api/v1/atlas/runs/{stat_run_id}").json()
                            if waiting["plan"]["state"] == "waiting":
                                break
                            time.sleep(0.1)
                        if waiting["plan"]["state"] != "waiting":
                            raise RuntimeError(f"Statistical run did not wait: {waiting['plan']['state']}")
                        result["stat_waiting_before_restart"] = waiting
                    else:
                        run_id = str(result["run_id"])
                        response = client.get(f"/api/v1/atlas/runs/{run_id}")
                        response.raise_for_status()
                        result["run_after_restart"] = response.json()
                        response = client.get(f"/api/v1/overview/datasets/{result['dataset']['dataset_id']}/profile")  # type: ignore[index]
                        response.raise_for_status()
                        result["dataset_revision_after_restart"] = response.json()["dataset"]["revision"]
                        stat_run_id = str(result["stat_run_id"])
                        waiting_response = client.get(f"/api/v1/atlas/runs/{stat_run_id}")
                        waiting_response.raise_for_status()
                        result["stat_waiting_after_restart"] = waiting_response.json()
                        if result["stat_waiting_after_restart"] != result["stat_waiting_before_restart"]:
                            raise AssertionError("Waiting question changed across restart")
                        question_id = result["stat_waiting_after_restart"]["clarifications"][0]["question_id"]  # type: ignore[index]
                        answered = client.post(f"/api/v1/atlas/runs/{stat_run_id}/clarifications/{question_id}", json={
                            "test": "pearson", "col_a": "exposure", "col_b": "outcome", "design": "linear_association",
                        })
                        answered.raise_for_status()
                        for _ in range(120):
                            stat_completed = client.get(f"/api/v1/atlas/runs/{stat_run_id}").json()
                            if stat_completed["plan"]["state"] in {"completed", "failed"}:
                                break
                            time.sleep(0.1)
                        if stat_completed["plan"]["state"] != "completed":
                            raise RuntimeError(f"Statistical run did not complete: {stat_completed['plan']['state']}")
                        result["stat_run_after_resume"] = stat_completed
                finally:
                    stop(process, log)
        result["backup_sha256_after"] = sha256(backup)
        if result["backup_sha256_after"] != original_hash:
            raise AssertionError("Supplied backup changed")
        if result["pointer_after_start_1"] != result["pointer_after_start_2"]:
            raise AssertionError("Promotion pointer changed across disposable restart")
        if result["run_after_execution"] != result["run_after_restart"]:
            raise AssertionError("Atlas run changed across disposable restart")
        output = output_dir / "disposable-startup-result.json"
        output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({"result_file": str(output), "run_id": result["run_id"],
                          "dataset_revision_after_restart": result["dataset_revision_after_restart"],
                          "backup_sha256_unchanged": True}, sort_keys=True))


if __name__ == "__main__":
    main()
