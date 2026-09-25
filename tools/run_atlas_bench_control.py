"""Run one digest-bound AtlasBench control and persist its item telemetry."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps" / "api" / "src"), *[str(path) for path in (ROOT / "packages").glob("*/python")]]

from prism_api.atlas_bench_corpus import CORPUS_VERSION, all_tasks, corpus_hash  # noqa: E402
from prism_api.atlas_bench_live import AtlasProviderBenchSubject  # noqa: E402
from prism_api.atlas_bench_runner import run_suite  # noqa: E402
from prism_api.atlas_bench_store import DurableAtlasBenchStore  # noqa: E402
from prism_api_contracts import AtlasModelProviderName  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    parser.add_argument("--prompt-envelope", choices=["nested_json", "prose"], default="nested_json")
    args = parser.parse_args()
    os.environ["PRISM_AI_PROVIDER"] = "ollama"
    os.environ["PRISM_ATLAS_BENCH_OLLAMA_CONTEXT_TOKENS"] = "4096"
    os.environ["PRISM_ATLAS_BENCH_OLLAMA_TIMEOUT_SECONDS"] = "60"

    subject = AtlasProviderBenchSubject(
        AtlasModelProviderName.OLLAMA, model_override=args.model, prompt_envelope=args.prompt_envelope
    )
    suite, results = run_suite(subject, all_tasks(), corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    policy_id = subject.evaluation_policy_id(corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    suite = suite.model_copy(update={
        "runtime_model": subject.model,
        "runtime_model_digest": subject.model_digest,
        "provider": "ollama",
        "evaluation_policy_id": policy_id,
    })
    DurableAtlasBenchStore().save(suite, results)

    categories: dict[str, Counter[str]] = defaultdict(Counter)
    for result in results:
        categories[result.category.value][result.outcome] += 1
    print(json.dumps({
        "run_id": suite.run_id,
        "model": subject.model,
        "digest": subject.model_digest,
        "prompt_envelope": args.prompt_envelope,
        "evaluation_policy_id": policy_id,
        "total": suite.total_tasks,
        "correct": suite.total_passed,
        "incorrect_parsed": suite.incorrect_parsed,
        "unparseable_or_invalid": suite.unparseable_or_invalid,
        "done_reason": dict(Counter(result.done_reason or "missing" for result in results)),
        "categories": {name: dict(counts) for name, counts in sorted(categories.items())},
    }, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
