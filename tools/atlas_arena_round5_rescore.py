"""Read-only re-adjudication of immutable Round 5 AtlasBench runs."""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps" / "api" / "src"), *[str(path) for path in (ROOT / "packages").glob("*/python")]]

from prism_api.atlas_bench_policy import (  # noqa: E402
    CRITICAL_REGRESSION_ALLOWANCE_ITEMS,
    EVALUATION_POLICY_VERSION,
    compute_evaluation_policy_id,
)
from prism_api.atlas_promotion import CRITICAL_CATEGORIES, decide_promotion  # noqa: E402
from prism_api_contracts import AtlasBenchSuiteRun  # noqa: E402

source = ROOT / "docs" / "atlas" / "arena" / "round-5.json"
report = json.loads(source.read_text(encoding="utf-8"))
database = Path(report["store_path"])
connection = sqlite3.connect("file:" + database.as_posix() + "?mode=ro", uri=True)
connection.row_factory = sqlite3.Row


def stored_run(model: dict[str, object]) -> AtlasBenchSuiteRun:
    bench = model["bench"]
    if not isinstance(bench, dict):
        raise ValueError("Round 5 model has no bench record")
    row = connection.execute("SELECT * FROM prism_atlas_bench_runs WHERE run_id=?", (bench["run_id"],)).fetchone()
    if row is None:
        raise ValueError(f"Missing durable run {bench['run_id']}")
    values = dict(row)
    values["category_scores"] = json.loads(values.pop("category_scores_payload"))
    run = AtlasBenchSuiteRun.model_validate(values)
    if (
        run.runtime_model != model["tag"]
        or run.runtime_model_digest != model["digest"]
        or run.total_passed != bench["correct"]
        or run.corpus_hash != report["corpus_hash"]
        or run.evaluation_policy_id != bench["evaluation_policy_id"]
    ):
        raise ValueError(f"Round 5 provenance mismatch for {model['tag']}")
    return run


models = report["models"]
production = stored_run(models[0])
policy = report["bench_policy"]
new_policy_id = compute_evaluation_policy_id(
    prompt_schema_version=policy["prompt_schema_version"],
    temperature=policy["temperature"],
    num_predict=policy["num_predict"],
    context_tokens=policy["num_ctx"],
    timeout_seconds=policy["timeout_seconds"],
    provider="ollama",
    corpus_version=report["corpus_version"],
    corpus_hash_value=report["corpus_hash"],
    shuffle_seed=policy["shuffle_seed"],
)
rescored = {
    "source_report": str(source),
    "source_corpus_hash": report["corpus_hash"],
    "stored_evaluation_policy_id": production.evaluation_policy_id,
    "future_evaluation_policy_id": new_policy_id,
    "evaluation_policy_version": EVALUATION_POLICY_VERSION,
    "critical_regression_allowance_items": CRITICAL_REGRESSION_ALLOWANCE_ITEMS,
    "overall_score_must_not_be_lower": True,
    "rescored_at": datetime.now(timezone.utc).isoformat(),
    "models": [],
}
for model in models:
    run = stored_run(model)
    if run.evaluation_policy_id != production.evaluation_policy_id:
        raise ValueError(f"Different stored evaluation policies for {model['tag']}")
    production_scores = {score.category: score for score in production.category_scores}
    item_losses = {
        score.category.value: production_scores[score.category].passed - score.passed
        for score in run.category_scores
        if score.category in CRITICAL_CATEGORIES and production_scores[score.category].passed > score.passed
    }
    verdict = "production_baseline" if model is models[0] else decide_promotion(str(model["tag"]), production, run).verdict.value
    row = {
        "tag": model["tag"],
        "run_id": run.run_id,
        "correct": run.total_passed,
        "production_correct": production.total_passed,
        "critical_item_losses": item_losses,
        "verdict": verdict,
    }
    rescored["models"].append(row)
    print(json.dumps(row, sort_keys=True), flush=True)

target = source.with_name("round-5-rescored.json")
target.write_text(json.dumps(rescored, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"Rescore written to {target}", flush=True)
