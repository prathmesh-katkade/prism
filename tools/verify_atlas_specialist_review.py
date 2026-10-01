"""Real, isolated proof of bounded specialist review end to end.

Launches the actual API against a disposable copy of the preserved backup
with PRISM_AI_PROVIDER=ollama, runs one real SQL investigation and one real
statistical investigation through the genuine, live-verified production
model binding, then restarts the process and confirms every persisted
specialist message -- deterministic and model-origin alike -- survives
unchanged. Never writes to the supplied backup; the disposable copy is
deleted on exit.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx
from verify_atlas_disposable_startup import await_ready, launch, sha256, stop


def _run_investigation(client: httpx.Client, dataset_id: str, request: dict[str, object]) -> dict[str, object]:
    started = client.post("/api/v1/atlas/runs", json={"dataset_id": dataset_id, **request})
    started.raise_for_status()
    run_id = started.json()["run_id"]
    for _ in range(400):
        run = client.get(f"/api/v1/atlas/runs/{run_id}").json()
        if run["plan"]["state"] in {"completed", "failed", "cancelled", "waiting"}:
            break
        time.sleep(0.1)
    else:
        raise TimeoutError(f"Atlas run {run_id} did not finish within the polling bound")
    if run["plan"]["state"] != "completed":
        raise RuntimeError(f"Atlas run {run_id} ended {run['plan']['state']}")
    # plan.state flips to "completed" before the best-effort, non-blocking
    # Atlas synthesis review attempt runs (by design: the deterministic
    # answer must never wait on that optional model call). That attempt
    # always appends exactly one step_completed event with step_id
    # "synthesis" when it finishes, success or failure alike -- wait for
    # that specific, known terminal signal rather than guessing from
    # message-count stability, which can look falsely "settled" during a
    # multi-second real-model call that hasn't produced output yet.
    for _ in range(200):
        run = client.get(f"/api/v1/atlas/runs/{run_id}").json()
        if any(event["type"] == "step_completed" and event.get("step_id") == "synthesis" for event in run["events"]):
            break
        time.sleep(0.2)
    else:
        raise TimeoutError(f"Atlas run {run_id}'s synthesis review never reported a terminal status")
    return run


def _review_summary(run: dict[str, object]) -> dict[str, object]:
    messages = run["messages"]
    model_messages = [message for message in messages if message["origin"] == "model"]
    unavailable = [message for message in messages if message["kind"] == "review_unavailable"]
    review_events = [event["payload"]["specialist_review"] for event in run["events"]
                     if isinstance(event.get("payload"), dict) and isinstance(event["payload"].get("specialist_review"), dict)]
    return {
        "message_count": len(messages),
        "model_origin_messages": [
            {"specialist": message["specialist"], "kind": message["kind"],
             "model_binding": message["model_binding"], "input_refs": message["input_refs"]}
            for message in model_messages
        ],
        "review_unavailable_messages": [
            {"specialist": message["specialist"], "content": message["content"]} for message in unavailable
        ],
        "review_events": review_events,
        "answer": run["answer"],
        "uncertainty": run["uncertainty"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--port", type=int, default=8781)
    args = parser.parse_args()
    backup = args.backup.resolve(strict=True)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    original_hash = sha256(backup)
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory(prefix="prism-atlas-review-") as directory:
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
        result: dict[str, object] = {"backup_sha256_before": original_hash}
        process, log = launch(root, environment_file, output_dir / "review-api-1.log", args.port, provider="ollama")
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=30) as client:
                await_ready(client, process)
                pointer_before = client.get("/api/v1/atlas/promotion/current").json()
                sql_dataset = client.post("/api/v1/overview/datasets", files={
                    "file": ("review-sql.csv", b"region,revenue\nwest,10\neast,7\nwest,5\n", "text/csv")
                }).json()
                stat_dataset = client.post("/api/v1/overview/datasets", files={
                    "file": ("review-stat.csv", b"exposure,outcome\n1,2\n2,4\n3,6\n4,8\n5,10\n", "text/csv")
                }).json()
                sql_run = _run_investigation(client, sql_dataset["dataset_id"], {
                    "objective": "Sum revenue by region using SQL",
                    "sql_analysis": {"aggregate": "sum", "measure": "revenue", "group_by": "region"},
                })
                stat_run = _run_investigation(client, stat_dataset["dataset_id"], {
                    "objective": "Test correlation significance",
                    "stat_analysis": {"test": "pearson", "col_a": "exposure", "col_b": "outcome", "design": "linear_association"},
                })
                result["sql_run_id"] = sql_run["run_id"]
                result["stat_run_id"] = stat_run["run_id"]
                result["sql_review"] = _review_summary(sql_run)
                result["stat_review"] = _review_summary(stat_run)
        finally:
            stop(process, log)

        process, log = launch(root, environment_file, output_dir / "review-api-2.log", args.port, provider="ollama")
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=30) as client:
                await_ready(client, process)
                pointer_after = client.get("/api/v1/atlas/promotion/current").json()
                sql_after = client.get(f"/api/v1/atlas/runs/{result['sql_run_id']}").json()
                stat_after = client.get(f"/api/v1/atlas/runs/{result['stat_run_id']}").json()
                result["sql_review_after_restart"] = _review_summary(sql_after)
                result["stat_review_after_restart"] = _review_summary(stat_after)
        finally:
            stop(process, log)

        result["backup_sha256_after"] = sha256(backup)
        if result["backup_sha256_after"] != original_hash:
            raise AssertionError("Supplied backup changed")
        if pointer_before != pointer_after:
            raise AssertionError("Promotion pointer changed across restart")
        if result["sql_review"] != result["sql_review_after_restart"]:
            raise AssertionError("SQL run's specialist review messages changed across restart")
        if result["stat_review"] != result["stat_review_after_restart"]:
            raise AssertionError("Stat run's specialist review messages changed across restart")
        result["promotion_pointer_unchanged"] = True
        output = output_dir / "specialist-review-result.json"
        output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({
            "result_file": str(output),
            "sql_model_messages": len(result["sql_review"]["model_origin_messages"]),  # type: ignore[index]
            "stat_model_messages": len(result["stat_review"]["model_origin_messages"]),  # type: ignore[index]
            "backup_sha256_unchanged": True,
            "promotion_pointer_unchanged": True,
        }, sort_keys=True))


if __name__ == "__main__":
    main()
