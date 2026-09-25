"""Measure installed Round 5 models without registering or promoting candidates."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps" / "api" / "src"), *[str(path) for path in (ROOT / "packages").glob("*/python")]]

# This is the existing production store used by the preceding physical arena
# rounds. A new, empty database in this worktree would invent a pointer.
STORE_PATH = ROOT.parent / "prism" / "apps" / "api" / ".prism" / "runtime" / "analytical-history.sqlite"
if not STORE_PATH.is_file():
    raise SystemExit(f"Production history store is absent: {STORE_PATH}")
os.environ["PRISM_ANALYTICAL_HISTORY_DATABASE_URL"] = f"sqlite:///{STORE_PATH.as_posix()}"
os.environ["PRISM_AI_PROVIDER"] = "ollama"
os.environ["PRISM_ATLAS_BENCH_OLLAMA_CONTEXT_TOKENS"] = "4096"
os.environ["PRISM_ATLAS_BENCH_OLLAMA_TIMEOUT_SECONDS"] = "60"

from prism_api.atlas_bench_corpus import CORPUS_VERSION, all_tasks, corpus_hash  # noqa: E402
from prism_api.atlas_bench_live import AtlasProviderBenchSubject  # noqa: E402
from prism_api.atlas_bench_runner import run_suite  # noqa: E402
from prism_api.atlas_bench_shuffle import DEFAULT_SHUFFLE_SEED  # noqa: E402
from prism_api.atlas_bench_store import DurableAtlasBenchStore  # noqa: E402
from prism_api.atlas_candidate_runtime import DurableAtlasCandidateRuntimeStore  # noqa: E402
from prism_api.atlas_promotion import DurableAtlasPromotionStore, decide_promotion  # noqa: E402
from prism_api_contracts import AtlasModelProviderName, AtlasPromotionVerdict  # noqa: E402

from tools.atlas_arena_round import measure_planner, ollama_stop  # noqa: E402

TAGS = [
    "qwen3:4b-instruct-2507-q4_K_M",
    "qwen2.5:3b",
    "ministral-3:8b",
    "ministral-3:3b",
    "granite4:micro",
    "granite4:tiny-h",
    "qwen3:8b",
    "qwen2.5:7b-instruct",
    "phi4-mini:latest",
    "olmo-3:7b-instruct",
]
REPORT_PATH = ROOT / "docs" / "atlas" / "arena" / "round-5.json"


def write_report(report: dict[str, Any]) -> None:
    staged = REPORT_PATH.with_suffix(".json.tmp")
    staged.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(staged, REPORT_PATH)


def capture_gpu(tag: str) -> dict[str, Any]:
    process = subprocess.run(["ollama", "ps"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, check=False)
    lines = [line for line in process.stdout.splitlines() if tag in line]
    line = lines[0] if len(lines) == 1 else None
    percent = None
    if process.returncode == 0 and line:
        split = re.search(r"(\d+)%\s*/\s*(\d+)%\s*CPU/GPU", line)
        whole = re.search(r"(\d+)%\s*GPU", line)
        if split:
            percent = float(split.group(2))
        elif whole:
            percent = float(whole.group(1))
    return {"exit_code": process.returncode, "line": line, "gpu_percent": percent, "stdout": process.stdout}


def bench_summary(suite: Any, results: list[Any]) -> dict[str, Any]:
    categories: dict[str, Counter[str]] = defaultdict(Counter)
    for result in results:
        categories[result.category.value][result.outcome] += 1
    counts = [result.eval_count for result in results if result.eval_count is not None]
    return {
        "run_id": suite.run_id,
        "correct": suite.total_passed,
        "incorrect_parsed": suite.incorrect_parsed,
        "unparseable_or_invalid": suite.unparseable_or_invalid,
        "total": suite.total_tasks,
        "categories": {name: dict(values) for name, values in sorted(categories.items())},
        "done_reason_distribution": dict(Counter(result.done_reason or "missing" for result in results)),
        "eval_count_distribution": dict(sorted(Counter(str(value) for value in counts).items(), key=lambda pair: int(pair[0]))),
        "eval_count_missing": len(results) - len(counts),
        "shuffle_seed": suite.shuffle_seed,
        "evaluation_policy_id": suite.evaluation_policy_id,
    }


def main() -> int:
    production = DurableAtlasPromotionStore().current_production()
    if production is None:
        raise SystemExit("No durable production pointer")
    binding = DurableAtlasCandidateRuntimeStore().latest(production.candidate_id)
    if binding is None or binding.runtime_model != TAGS[0] or not binding.runtime_model_digest:
        raise SystemExit(f"Production binding does not name expected first model: {binding}")
    store = DurableAtlasBenchStore()
    corpus_id = corpus_hash()
    if REPORT_PATH.exists():
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        if report.get("corpus_hash") != corpus_id or report.get("tags") != TAGS or report.get("production_event_id") != production.event_id:
            raise SystemExit("Existing Round 5 report has incompatible provenance")
    else:
        report = {
            "round": 5,
            "status": "in_progress",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "corpus_version": CORPUS_VERSION,
            "corpus_hash": corpus_id,
            "tags": TAGS,
            "production_event_id": production.event_id,
            "production_candidate_id": production.candidate_id,
            "production_pointer_changed": False,
            "store_path": str(STORE_PATH),
            "bench_policy": {
                "prompt_envelope": "nested_json",
                "prompt_schema_version": AtlasProviderBenchSubject.PROMPT_SCHEMA_VERSION,
                "answer_field": "choice",
                "answer_type": "per_item_exact_string_enum",
                "shuffle_seed": DEFAULT_SHUFFLE_SEED,
                "temperature": AtlasProviderBenchSubject.TEMPERATURE,
                "num_predict": AtlasProviderBenchSubject.NUM_PREDICT,
                "num_ctx": 4096,
                "timeout_seconds": 60,
                "think": False,
            },
            "planner_policy": {
                "objectives": 40,
                "warm_samples": 39,
                "temperature": 0,
                "num_predict": 1800,
                "num_ctx": 4096,
                "timeout_seconds": 30,
                "think": False,
            },
            "models": [],
            "gates": {"gpu_min_percent": 85, "warm_p95_max_seconds": 12, "valid_json_min_rate": 0.95, "acceptance_min_rate": 0.90},
        }
        write_report(report)

    prior_tag = None
    for index, tag in enumerate(TAGS):
        existing = next((entry for entry in report["models"] if entry["tag"] == tag), None)
        if existing and existing.get("status") == "complete":
            prior_tag = tag
            print(f"[round5] {tag}: already complete", flush=True)
            continue
        if prior_tag:
            ollama_stop(prior_tag)
        print(f"[round5] {index + 1}/10 {tag}: bench", flush=True)
        subject = AtlasProviderBenchSubject(AtlasModelProviderName.OLLAMA, model_override=tag)
        if subject.model_digest == "digest-unavailable":
            raise SystemExit(f"No verified Ollama digest for {tag}")
        if index == 0 and subject.model_digest != binding.runtime_model_digest:
            raise SystemExit(f"Production model digest drift: {subject.model_digest} != {binding.runtime_model_digest}")
        if existing:
            entry = existing
            suite = store.get_run(entry["bench"]["run_id"])
            if suite is None:
                raise SystemExit(f"Missing persisted suite for {tag}")
        else:
            suite, results = run_suite(subject, all_tasks(), corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_id)
            policy_id = subject.evaluation_policy_id(corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_id, shuffle_seed=suite.shuffle_seed)
            suite = suite.model_copy(update={
                "subject_kind": "production" if index == 0 else "arena",
                "candidate_id": production.candidate_id if index == 0 else None,
                "runtime_model": tag,
                "runtime_model_digest": subject.model_digest,
                "provider": "ollama",
                "evaluation_policy_id": policy_id,
            })
            store.save(suite, results)
            entry = {
                "tag": tag,
                "digest": subject.model_digest,
                "status": "bench_complete",
                "bench": bench_summary(suite, results),
                "gpu_after_bench": capture_gpu(tag),
            }
            report["models"].append(entry)
            write_report(report)
            print(f"[round5] {tag}: {suite.total_passed}/{suite.total_tasks}; GPU {entry['gpu_after_bench']['gpu_percent']}", flush=True)

        if suite.runtime_model_digest != subject.model_digest or suite.corpus_hash != corpus_id:
            raise SystemExit(f"Persisted bench provenance mismatch for {tag}")
        baseline = store.get_run(report["models"][0]["bench"]["run_id"])
        if (
            baseline is None
            or suite.evaluation_policy_id != baseline.evaluation_policy_id
            or suite.shuffle_seed != baseline.shuffle_seed
            or suite.shuffle_seed != DEFAULT_SHUFFLE_SEED
        ):
            raise SystemExit(f"Non-comparable evaluation policy for {tag}")

        print(f"[round5] {tag}: planner 40 objectives", flush=True)
        planner = measure_planner(tag)
        entry["planner"] = {
            "cold_start_seconds": planner.cold_start_seconds,
            "warm_count": planner.sample_size(),
            "p50_seconds": planner.p50(),
            "p95_seconds": planner.p95(),
            "valid_json_rate": planner.valid_json_rate(),
            "acceptance_rate": planner.acceptance_rate(),
            "rejection_cause_counts": planner.rejection_cause_counts(),
            "samples": [
                {"group": sample.group, "status": sample.status, "seconds": sample.elapsed_seconds, "accepted": sample.accepted}
                for sample in planner.samples
            ],
        }
        entry["gpu_after_planner"] = capture_gpu(tag)
        percentages = [entry["gpu_after_bench"]["gpu_percent"], entry["gpu_after_planner"]["gpu_percent"]]
        gpu = min(percentages) if all(value is not None for value in percentages) else None
        entry["gpu_percent_min_observed"] = gpu
        if index == 0:
            entry["atlasbench_verdict"] = "production_baseline"
            entry["critical_regressions"] = []
        else:
            decision = decide_promotion(tag, baseline, suite)
            entry["atlasbench_verdict"] = decision.verdict.value
            entry["critical_regressions"] = [item.category.value for item in decision.critical_regressions]
        entry["gate_results"] = {
            "atlasbench_promote_eligible": None if index == 0 else entry["atlasbench_verdict"] == AtlasPromotionVerdict.PROMOTE_ELIGIBLE.value,
            "gpu_ge_85_percent": None if gpu is None else gpu >= 85,
            "warm_p95_le_12_seconds": None if planner.p95() is None else planner.p95() <= 12,
            "valid_json_ge_95_percent": planner.valid_json_rate() >= 0.95,
            "acceptance_ge_90_percent": planner.acceptance_rate() >= 0.90,
            "operational_certification": None,
        }
        entry["status"] = "complete"
        write_report(report)
        print(f"[round5] {tag}: planner p50={planner.p50()} p95={planner.p95()} valid={planner.valid_json_rate()} accepted={planner.acceptance_rate()} gates={entry['gate_results']}", flush=True)
        prior_tag = tag

    latest = DurableAtlasPromotionStore().current_production()
    if latest is None or latest.event_id != production.event_id:
        raise SystemExit("Production pointer changed during Round 5")
    report["status"] = "complete"
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    report["production_pointer_changed"] = False
    write_report(report)
    print(f"[round5] complete: {REPORT_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
