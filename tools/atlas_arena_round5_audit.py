"""Read back every Round 5 task result from the durable production store."""

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
report = json.loads((ROOT / "docs/atlas/arena/round-5.json").read_text(encoding="utf-8"))
database = Path(report["store_path"])
connection = sqlite3.connect("file:" + database.as_posix() + "?mode=ro", uri=True)

for model in report["models"]:
    run_id = model["bench"]["run_id"]
    rows = connection.execute(
        "SELECT task_id, outcome, presentation_permutation_payload, raw_response, done_reason, eval_count "
        "FROM prism_atlas_bench_task_results WHERE run_id=?",
        (run_id,),
    ).fetchall()
    counts = {name: sum(row[1] == name for row in rows) for name in ("correct", "incorrect_parsed", "unparseable_or_invalid")}
    checks = {
        "rows": len(rows) == 90,
        "unique_tasks": len({row[0] for row in rows}) == 90,
        "permutations": all(sorted(json.loads(row[2])) == [0, 1, 2, 3] for row in rows),
        "failure_raw_responses": all(bool(row[3]) for row in rows if row[1] != "correct"),
        "done_reasons": all(row[4] == "stop" for row in rows),
        "eval_counts": all(row[5] is not None for row in rows),
        "outcomes": (
            counts["correct"], counts["incorrect_parsed"], counts["unparseable_or_invalid"]
        ) == (
            model["bench"]["correct"], model["bench"]["incorrect_parsed"], model["bench"]["unparseable_or_invalid"]
        ),
    }
    print(model["tag"], run_id, counts, checks, flush=True)
    if not all(checks.values()):
        raise SystemExit("Round 5 durable audit failed")

print("AUDIT PASS: 10 runs and 900 durable task results", flush=True)
