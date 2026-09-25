"""Read persisted AtlasBench outcomes without rerunning the model."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps" / "api" / "src"), *[str(path) for path in (ROOT / "packages").glob("*/python")]]

from prism_api.atlas_bench_store import DurableAtlasBenchStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_ids", nargs="+")
    args = parser.parse_args()
    store = DurableAtlasBenchStore()
    for run_id in args.run_ids:
        run = store.get_run(run_id)
        if run is None:
            raise SystemExit(f"Missing durable run: {run_id}")
        results = store.task_results(run_id)
        if len(results) != run.total_tasks:
            raise SystemExit(f"Incomplete durable run: {run_id}")
        categories: dict[str, Counter[str]] = defaultdict(Counter)
        for result in results:
            categories[result.category.value][result.outcome] += 1
        print(json.dumps({
            "run_id": run.run_id,
            "model": run.runtime_model,
            "digest": run.runtime_model_digest,
            "policy": run.evaluation_policy_id,
            "correct": run.total_passed,
            "incorrect_parsed": run.incorrect_parsed,
            "unparseable_or_invalid": run.unparseable_or_invalid,
            "categories": {name: dict(counts) for name, counts in sorted(categories.items())},
        }, sort_keys=True))


if __name__ == "__main__":
    main()
