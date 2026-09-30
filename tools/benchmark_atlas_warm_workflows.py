"""Measure the frozen Atlas SQL and Pearson workflows through a real API process.

The supplied backup is only copied and hashed. All requests use a disposable
copy with an explicit SQLite URL. Cold startup and human waiting are excluded.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import cast

import httpx
from verify_atlas_disposable_startup import await_ready, launch, sha256, stop


def upload(client: httpx.Client, name: str, contents: bytes) -> dict[str, object]:
    response = client.post("/api/v1/overview/datasets", files={"file": (name, contents, "text/csv")})
    response.raise_for_status()
    return cast(dict[str, object], response.json())


def duration(events: list[dict[str, object]], first: str, last: str, step: str | None = None) -> float | None:
    selected = [event for event in events if step is None or event.get("step_id") == step]
    start = next((event for event in selected if event["type"] == first), None)
    end = next((event for event in selected if event["type"] == last), None)
    if start is None or end is None:
        return None
    a = datetime.fromisoformat(str(start["occurred_at"]).replace("Z", "+00:00"))
    b = datetime.fromisoformat(str(end["occurred_at"]).replace("Z", "+00:00"))
    return round((b - a).total_seconds() * 1_000, 2)


def run_one(client: httpx.Client, dataset_id: str, kind: str, index: int) -> dict[str, object]:
    request: dict[str, object] = {"dataset_id": dataset_id, "idempotency_key": f"warm-atlas-{kind}-{index:04d}"}
    if kind == "sql":
        request.update({"objective": "Sum revenue by region using SQL", "sql_analysis": {
            "aggregate": "sum", "measure": "revenue", "group_by": "region",
        }})
    else:
        request.update({"objective": "Test correlation significance", "stat_analysis": {
            "test": "pearson", "col_a": "exposure", "col_b": "outcome", "design": "linear_association",
        }})
    started = time.perf_counter()
    response = client.post("/api/v1/atlas/runs", json=request)
    response.raise_for_status()
    run_id = response.json()["run_id"]
    for _ in range(400):
        response = client.get(f"/api/v1/atlas/runs/{run_id}")
        response.raise_for_status()
        run = response.json()
        if run["plan"]["state"] in {"completed", "failed", "cancelled", "waiting"}:
            break
        time.sleep(0.05)
    else:
        raise TimeoutError(f"Atlas run {run_id} did not finish within the polling bound")
    total_ms = round((time.perf_counter() - started) * 1_000, 2)
    if run["plan"]["state"] != "completed":
        raise AssertionError(f"Atlas run {run_id} ended {run['plan']['state']}")
    output = next((event["payload"]["output"] for event in run["events"]
                   if isinstance(event.get("payload"), dict) and "output" in event["payload"]
                   and event["payload"]["output"].get("execution_state") == "succeeded"), None)
    if output is None:
        raise AssertionError(f"No successful recorded computation in {run_id}")
    if kind == "sql":
        if output["rows"] != [{"group_value": "east", "result_value": 7.0},
                              {"group_value": "west", "result_value": 15.0}]:
            raise AssertionError(f"Incorrect SQL rows in {run_id}: {output['rows']}")
    elif output["result"]["statistic"] != 1.0 or output["analyzed_rows"] != 5 or output["excluded_rows"] != 0:
        raise AssertionError(f"Incorrect Pearson result in {run_id}")
    events = run["events"]
    return {
        "kind": kind, "run_id": run_id, "dataset_id": dataset_id, "state": run["plan"]["state"],
        "total_ms": total_ms,
        "planning_ms": duration(events, "run_created", "plan_created"),
        "queue_ms": duration(events, "plan_created", "step_started"),
        "tool_ms": duration(events, "step_started", "step_completed", "sql_question" if kind == "sql" else "statistical_analysis"),
        "review_ms": duration(events, "step_started", "step_completed", "audit"),
        "tool_reported_ms": output.get("duration_ms"),
        "execution_ref": output.get("sql_run_id") or output.get("execution_ref"),
    }


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--port", type=int, default=8771)
    args = parser.parse_args()
    backup = args.backup.resolve(strict=True)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    original_hash = sha256(backup)
    with tempfile.TemporaryDirectory(prefix="prism-atlas-benchmark-") as directory:
        temp = Path(directory)
        database = temp / "history.sqlite"
        shutil.copy2(backup, database)
        environment_file = temp / "api.env"
        environment_file.write_text(
            f"PRISM_ANALYTICAL_HISTORY_DATABASE_URL=sqlite:///{database.as_posix()}\n"
            f"PRISM_SQL_METADATA_PATH={str(temp / 'sql-lab.sqlite')}\n"
            "PRISM_REQUIRE_DURABLE_HISTORY=true\nPRISM_AI_PROVIDER=deterministic\n",
            encoding="utf-8",
        )
        process, log = launch(root, environment_file, output_dir / "warm-api.log", args.port)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=15) as client:
                await_ready(client, process)
                pointer_before = client.get("/api/v1/atlas/promotion/current").json()
                sql_dataset = upload(client, "warm-sql.csv", b"region,revenue\nwest,10\neast,7\nwest,5\n")
                stat_dataset = upload(client, "warm-stat.csv", b"exposure,outcome\n1,2\n2,4\n3,6\n4,8\n5,10\n")
                # Warm application imports, connections and the statistical worker.
                run_one(client, str(sql_dataset["dataset_id"]), "sql", 0)
                run_one(client, str(stat_dataset["dataset_id"]), "stat", 0)
                samples = [run_one(client, str(sql_dataset["dataset_id"] if kind == "sql" else stat_dataset["dataset_id"]), kind, i)
                           for i in range(1, 11) for kind in ("sql", "stat")]
                pointer_after = client.get("/api/v1/atlas/promotion/current").json()
        finally:
            stop(process, log)
        if pointer_before != pointer_after or sha256(backup) != original_hash:
            raise AssertionError("Production backup or copied promotion pointer changed")
        values = [cast(float, item["total_ms"]) for item in samples]
        result = {
            "sample_count": len(samples), "fixture": "10 SQL aggregation + 10 declared Pearson, sequential",
            "provider": "deterministic", "warmup_runs_excluded": 2, "human_wait_ms": 0,
            "cold_start_excluded": True, "p95_method": "nearest rank", "target_ms": 60_000,
            "total_p50_ms": percentile(values, 0.5), "total_p95_ms": percentile(values, 0.95),
            "total_max_ms": max(values), "passed_target": percentile(values, 0.95) <= 60_000,
            "backup_sha256_unchanged": original_hash,
            "promotion_pointer_unchanged": True, "samples": samples,
        }
        path = output_dir / "warm-workflow-result.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({key: result[key] for key in ("sample_count", "total_p50_ms", "total_p95_ms", "total_max_ms", "passed_target")}, sort_keys=True))


if __name__ == "__main__":
    main()
