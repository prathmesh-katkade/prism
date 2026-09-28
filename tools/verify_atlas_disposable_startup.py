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


def launch(root: Path, environment_file: Path, log_path: Path, port: int) -> tuple[subprocess.Popen[bytes], object]:
    log = log_path.open("wb")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "prism_api.main:app", "--app-dir", "apps/api/src",
         "--env-file", str(environment_file), "--host", "127.0.0.1", "--port", str(port)],
        cwd=root, stdout=log, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env={**os.environ, "PRISM_AI_PROVIDER": "deterministic"},
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
                    else:
                        run_id = str(result["run_id"])
                        response = client.get(f"/api/v1/atlas/runs/{run_id}")
                        response.raise_for_status()
                        result["run_after_restart"] = response.json()
                        response = client.get(f"/api/v1/overview/datasets/{result['dataset']['dataset_id']}/profile")  # type: ignore[index]
                        response.raise_for_status()
                        result["dataset_revision_after_restart"] = response.json()["dataset"]["revision"]
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
