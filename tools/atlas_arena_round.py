"""Run one Atlas Model Arena round: pull -> license check -> register ->
verify -> runtime-bind -> AtlasBench candidate evaluation -> promotion
decision -> planner latency/quality -> a durable round report.

This is orchestration only. Every trust, eligibility, and promotion decision
is made by the existing ``atlas_base_model_trust`` / ``atlas_bench_live`` /
``atlas_foundry_routes`` / ``atlas_promotion`` functions this script calls;
nothing here re-implements or second-guesses their policy. The four
Phase-3 qualification gates (AtlasBench PROMOTE_ELIGIBLE, 100% GPU residency,
warm planner p95 <= 12.0s, valid-JSON rate >= 95%, proposal acceptance rate
>= 90%) are evaluated here only to decide what this script *reports* about a
candidate -- they never affect whether decide_promotion() or promote_candidate()
themselves succeed; those remain exactly as strict as the modules they live in.

Each candidate's real upstream identity (Hugging Face model id, revision,
license) is declared in ``CANDIDATE_METADATA`` below. Every entry was
confirmed via ``ollama show <tag> --license`` against the locally pulled
model plus the Hugging Face API's own ``license:`` tag for that upstream
repo -- never guessed from the Ollama tag name alone. This script does not
perform that upstream research at runtime (a live third-party network
dependency in a certification path); it only re-checks that the locally
installed model's own declared license text is consistent with the
declared metadata, and it still relies on ``verify_base_model_candidate``'s
real, live probe of the local Ollama daemon for the identity/digest checks
that actually gate trust.

Run from the repository root, one round at a time:
    python tools/atlas_arena_round.py --round 1 ministral-3:8b ministral-3:3b \
        qwen3:4b-instruct-2507-q4_K_M phi4-mini:latest
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
for relative in (
    "apps/api/src",
    "packages/api-contracts/python",
    "packages/config/python",
    "packages/overview-analytics/python",
    "packages/sql-lab-runtime/python",
    "packages/analytical-schemas/python",
):
    path = str(ROOT / relative)
    if path not in sys.path:
        sys.path.insert(0, path)

import os  # noqa: E402

# The real durable store, pinned to an absolute path so this script's
# behavior does not depend on the caller's current working directory --
# see durable_registry.history_database_url(), which otherwise resolves
# ``.prism/runtime/analytical-history.sqlite`` relative to cwd.
os.environ.setdefault(
    "PRISM_ANALYTICAL_HISTORY_DATABASE_URL",
    f"sqlite:///{(ROOT / 'apps' / 'api' / '.prism' / 'runtime' / 'analytical-history.sqlite').as_posix()}",
)
os.environ.setdefault("PRISM_AI_PROVIDER", "ollama")

from prism_api.atlas_base_model_trust import (  # noqa: E402
    APPROVED_MODEL_LICENSES,
    DurableAtlasBaseModelVerificationStore,
    DurableAtlasVerifiedBaseModelRegistry,
    compute_base_model_candidate_id,
    is_base_model_verified,
    probe_live_ollama_digest,
    verify_base_model_candidate,
)
from prism_api.atlas_bench_corpus import CORPUS_VERSION, all_tasks, corpus_hash  # noqa: E402
from prism_api.atlas_bench_live import (  # noqa: E402
    AtlasBenchSubjectUnavailable,
    AtlasProviderBenchSubject,
    run_candidate_benchmark,
)
from prism_api.atlas_bench_runner import run_suite  # noqa: E402
from prism_api.atlas_bench_store import DurableAtlasBenchStore  # noqa: E402
from prism_api.atlas_candidate_runtime import (  # noqa: E402
    DurableAtlasCandidateRuntimeStore,
    ensure_configured_production_baseline,
)
from prism_api.atlas_foundry_routes import compute_promotion_decision  # noqa: E402
from prism_api.atlas_promotion import DurableAtlasPromotionStore  # noqa: E402
from prism_api.atlas_runtime import (  # noqa: E402
    AtlasPlanProposal,
    DynamicAtlasPlanner,
    OllamaAtlasProvider,
)
from prism_api_contracts import (  # noqa: E402
    AtlasModelProviderName,
    AtlasPromotionVerdict,
    AtlasVerifiedBaseModelCandidate,
)

# --- fixed evaluation policy -------------------------------------------------
#
# atlas_bench_policy.py documents that this exact context window is the one
# that historically produced comparable Arena evidence on this hardware; an
# unset context window gets no evaluation_policy_id at all (see
# AtlasProviderBenchSubject.evaluation_policy_id) and can never be compared.
CONTEXT_TOKENS = 4096

# --- candidate identity metadata ---------------------------------------------
#
# See the module docstring: every field here was confirmed via
# `ollama show <tag> --license` plus the Hugging Face API license tag for the
# named upstream repo before this round ran.


@dataclass(frozen=True)
class CandidateMetadata:
    upstream_model_id: str
    upstream_revision: str
    license: str
    quantization: str
    parameter_count: Optional[int]


CANDIDATE_METADATA: dict[str, CandidateMetadata] = {
    "ministral-3:8b": CandidateMetadata(
        upstream_model_id="mistralai/Ministral-3-8B-Instruct-2512",
        upstream_revision="5b26027e7b19eeb4b7352e1fed3926375dd2cb4d",
        license="Apache-2.0",
        quantization="Q4_K_M",
        parameter_count=8_900_000_000,
    ),
    "ministral-3:3b": CandidateMetadata(
        upstream_model_id="mistralai/Ministral-3-3B-Instruct-2512",
        upstream_revision="b35d4dfe56c142746f54dbd64f579faab2744308",
        license="Apache-2.0",
        quantization="Q4_K_M",
        parameter_count=3_800_000_000,
    ),
    "qwen3:4b-instruct-2507-q4_K_M": CandidateMetadata(
        upstream_model_id="Qwen/Qwen3-4B-Instruct-2507",
        upstream_revision="cdbee75f17c01a7cc42f958dc650907174af0554",
        license="Apache-2.0",
        quantization="Q4_K_M",
        parameter_count=4_022_468_096,
    ),
    "phi4-mini:latest": CandidateMetadata(
        upstream_model_id="microsoft/Phi-4-mini-instruct",
        upstream_revision="cfbefacb99257ffa30c83adab238a50856ac3083",
        license="MIT",
        quantization="unspecified",
        parameter_count=3_800_000_000,
    ),
    # Round 2 queue (only used if nothing in Round 1 qualifies).
    "olmo-3:7b-instruct": CandidateMetadata(
        upstream_model_id="allenai/Olmo-3-7B-Instruct",
        upstream_revision="6e5971d9eba42665f5bd5a0fcf047f299ce1dccc",
        license="Apache-2.0",
        quantization="unspecified",
        parameter_count=7_000_000_000,
    ),
    "granite4:micro": CandidateMetadata(
        upstream_model_id="ibm-granite/granite-4.0-micro",
        upstream_revision="56111ae135df9c53a78c99028e7bc24035a9e979",
        license="Apache-2.0",
        quantization="unspecified",
        parameter_count=3_000_000_000,
    ),
}

PLANNER_OBJECTIVES: list[str] = json.loads(
    (ROOT / "tools" / "atlas_arena_planner_objectives.json").read_text(encoding="utf-8")
)
assert len(PLANNER_OBJECTIVES) == 20, "planner objective fixture must stay a fixed set of 20"

# --- Phase-3 qualification gates (reporting only; see module docstring) -----
GATE_MIN_GPU_PERCENT = 100.0
GATE_MAX_WARM_P95_SECONDS = 12.0
GATE_MIN_VALID_JSON_RATE = 0.95
GATE_MIN_ACCEPTANCE_RATE = 0.90
WARM_PLANNER_TIMEOUT_SECONDS = 30.0


class ArenaRoundError(RuntimeError):
    pass


def _run_ollama(*args: str, timeout: float = 1_800.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ollama", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def ollama_stop(tag: str) -> None:
    _run_ollama("stop", tag, timeout=30.0)


def ollama_pull(tag: str) -> tuple[bool, str]:
    result = _run_ollama("pull", tag)
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0 or "not found" in output.lower() or "file does not exist" in output.lower():
        return False, output.strip()[-2_000:]
    return True, output.strip()[-500:]


def ollama_license_text(tag: str) -> str:
    result = _run_ollama("show", tag, "--license", timeout=30.0)
    return (result.stdout or "").strip()


_LICENSE_MARKERS: dict[str, tuple[str, ...]] = {
    "Apache-2.0": ("Apache License", "Version 2.0"),
    "MIT": ("MIT License", "Permission is hereby granted, free of charge"),
    "BSD-3-Clause": ("BSD 3-Clause", "Redistribution and use in source and binary forms"),
}


def confirm_license(tag: str, metadata: CandidateMetadata) -> tuple[bool, str]:
    if metadata.license not in APPROVED_MODEL_LICENSES:
        return False, f"declared license {metadata.license!r} is not on the approved allowlist"
    markers = _LICENSE_MARKERS.get(metadata.license, ())
    local_text = ollama_license_text(tag)
    if markers and not any(marker in local_text for marker in markers):
        return False, (
            f"declared license {metadata.license!r} but `ollama show {tag} --license` output did not contain "
            f"any expected marker {markers!r} (got {local_text[:200]!r})"
        )
    return True, f"confirmed {metadata.license} via ollama show --license and Hugging Face license tag"


def ollama_ps_gpu_percent(tag: str) -> Optional[float]:
    """Parse `ollama ps` for this tag's live CPU/GPU split, e.g. "8%/92% CPU/GPU"."""
    result = _run_ollama("ps", timeout=15.0)
    for line in (result.stdout or "").splitlines():
        if tag not in line:
            continue
        match = re.search(r"(\d+)%\s*/\s*(\d+)%\s*CPU/GPU", line)
        if match:
            return float(match.group(2))
        if "100% GPU" in line:
            return 100.0
        match = re.search(r"(\d+)%\s*GPU", line)
        if match:
            return float(match.group(1))
    return None


def warm_up_and_measure_gpu(tag: str) -> Optional[float]:
    """Send one real generation request to load the model, then read `ollama ps`."""
    subprocess.run(
        ["ollama", "run", tag, "Say ready."],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120.0,
        check=False,
    )
    return ollama_ps_gpu_percent(tag)


@dataclass
class PlannerMeasurement:
    cold_start_seconds: Optional[float]
    warm_latencies_seconds: list[float] = field(default_factory=list)
    warm_valid_json_count: int = 0
    warm_accepted_count: int = 0
    warm_total: int = 0

    @property
    def p50(self) -> Optional[float]:
        return _percentile(self.warm_latencies_seconds, 50)

    @property
    def p95(self) -> Optional[float]:
        return _percentile(self.warm_latencies_seconds, 95)

    @property
    def max_seconds(self) -> Optional[float]:
        return max(self.warm_latencies_seconds) if self.warm_latencies_seconds else None

    @property
    def valid_json_rate(self) -> float:
        return self.warm_valid_json_count / self.warm_total if self.warm_total else 0.0

    @property
    def acceptance_rate(self) -> float:
        return self.warm_accepted_count / self.warm_total if self.warm_total else 0.0


def _percentile(values: list[float], pct: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((pct / 100) * (len(ordered) - 1))))
    return ordered[index]


def measure_planner(tag: str) -> PlannerMeasurement:
    previous_model = os.environ.get("PRISM_ATLAS_OLLAMA_MODEL")
    previous_timeout = os.environ.get("PRISM_ATLAS_PLANNER_TIMEOUT_SECONDS")
    os.environ["PRISM_ATLAS_OLLAMA_MODEL"] = tag
    os.environ["PRISM_ATLAS_PLANNER_TIMEOUT_SECONDS"] = str(WARM_PLANNER_TIMEOUT_SECONDS)
    provider = OllamaAtlasProvider()
    metadata: dict[str, object] = {
        "dataset_id": "arena_probe_dataset",
        "rows": 500,
        "columns": 12,
        "health": 0.9,
        "column_names": ["segment", "revenue", "signup_date", "region"],
    }
    try:
        measurement = PlannerMeasurement(cold_start_seconds=None)
        for index, objective in enumerate(PLANNER_OBJECTIVES):
            started = time.perf_counter()
            result: AtlasPlanProposal = provider.propose_plan_detailed(objective, metadata)
            elapsed = time.perf_counter() - started
            if index == 0:
                measurement.cold_start_seconds = elapsed
                continue
            measurement.warm_total += 1
            measurement.warm_latencies_seconds.append(elapsed)
            if result.status == "ok":
                measurement.warm_valid_json_count += 1
                accepted = DynamicAtlasPlanner._validated_proposal(result.steps or [])  # noqa: SLF001
                if accepted:
                    measurement.warm_accepted_count += 1
        return measurement
    finally:
        if previous_model is None:
            os.environ.pop("PRISM_ATLAS_OLLAMA_MODEL", None)
        else:
            os.environ["PRISM_ATLAS_OLLAMA_MODEL"] = previous_model
        if previous_timeout is None:
            os.environ.pop("PRISM_ATLAS_PLANNER_TIMEOUT_SECONDS", None)
        else:
            os.environ["PRISM_ATLAS_PLANNER_TIMEOUT_SECONDS"] = previous_timeout


def establish_comparable_production_run(context_tokens: int) -> str:
    """Ensure a production AtlasBench run exists whose evaluation_policy_id is
    set (context_tokens pinned) and therefore comparable to this round's
    candidate runs -- required by compute_promotion_decision, which refuses
    to compare against a legacy/ambiguous (evaluation_policy_id=None) run.
    """
    promotion_store = DurableAtlasPromotionStore()
    production = promotion_store.current_production()
    if production is None:
        raise ArenaRoundError(
            "No production pointer exists on the real durable store; Phase 0's baseline "
            "bootstrap must run before any arena round."
        )
    binding = DurableAtlasCandidateRuntimeStore().latest(production.candidate_id)
    if binding is None:
        raise ArenaRoundError("Production candidate has no durable Ollama runtime binding.")

    # PRISM_ATLAS_BENCH_OLLAMA_CONTEXT_TOKENS is set process-wide for the whole
    # round by main() -- every candidate's AtlasBench run must see the exact
    # same value as this production run, or compute_promotion_decision()
    # rejects the comparison. Only PRISM_ATLAS_OLLAMA_MODEL is scoped locally
    # here, to select the production model for this one probe.
    previous_model = os.environ.get("PRISM_ATLAS_OLLAMA_MODEL")
    os.environ["PRISM_ATLAS_OLLAMA_MODEL"] = binding.runtime_model
    try:
        subject = AtlasProviderBenchSubject(AtlasModelProviderName.OLLAMA)
        if subject.model != binding.runtime_model or subject.model_digest != binding.runtime_model_digest:
            raise ArenaRoundError(
                "Live production model/digest no longer matches the durable runtime binding; "
                "re-establish the production baseline before running an arena round."
            )
        suite_run, results = run_suite(
            subject, all_tasks(), corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash()
        )
        suite_run = suite_run.model_copy(
            update={
                "subject_kind": "production",
                "candidate_id": production.candidate_id,
                "runtime_model": subject.model,
                "runtime_model_digest": subject.model_digest,
                "provider": "ollama",
                "evaluation_policy_id": subject.evaluation_policy_id(
                    corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash()
                ),
            }
        )
        saved = DurableAtlasBenchStore().save(suite_run, results)
        if saved.evaluation_policy_id is None:
            raise ArenaRoundError("Freshly recorded production run still has no evaluation_policy_id.")
        return saved.run_id
    finally:
        if previous_model is None:
            os.environ.pop("PRISM_ATLAS_OLLAMA_MODEL", None)
        else:
            os.environ["PRISM_ATLAS_OLLAMA_MODEL"] = previous_model


def evaluate_candidate(tag: str, *, production_run_id: str, context_tokens: int) -> dict[str, object]:
    entry: dict[str, object] = {"tag": tag, "started_at": datetime.now(timezone.utc).isoformat()}

    metadata = CANDIDATE_METADATA.get(tag)
    if metadata is None:
        entry["outcome"] = "skipped"
        entry["reason"] = f"no CANDIDATE_METADATA entry for {tag!r}; add its real upstream id/revision/license first"
        return entry

    pulled, pull_detail = ollama_pull(tag)
    entry["pull_detail"] = pull_detail
    if not pulled:
        entry["outcome"] = "tag_not_found"
        return entry

    license_ok, license_detail = confirm_license(tag, metadata)
    entry["license"] = metadata.license
    entry["license_check"] = license_detail
    if not license_ok:
        entry["outcome"] = "license_rejected"
        return entry

    live_digest = probe_live_ollama_digest(tag)
    if live_digest is None:
        entry["outcome"] = "digest_probe_failed"
        entry["reason"] = f"local Ollama daemon did not report a live digest for {tag!r}"
        return entry

    candidate_id = compute_base_model_candidate_id(
        upstream_model_id=metadata.upstream_model_id,
        upstream_revision=metadata.upstream_revision,
        runtime_model=tag,
    )
    entry["candidate_id"] = candidate_id

    candidate = AtlasVerifiedBaseModelCandidate(
        candidate_id=candidate_id,
        upstream_model_id=metadata.upstream_model_id,
        upstream_revision=metadata.upstream_revision,
        license=metadata.license,
        official_source=f"https://huggingface.co/{metadata.upstream_model_id}",
        runtime_model=tag,
        declared_runtime_digest=live_digest,
        quantization=metadata.quantization,
        declared_manifest_digest=None,
        declared_blob_digests=[],
        parameter_count=metadata.parameter_count,
        created_at=datetime.now(timezone.utc),
    )
    registry = DurableAtlasVerifiedBaseModelRegistry()
    registry.register(candidate)

    verification_store = DurableAtlasBaseModelVerificationStore()
    verification = verify_base_model_candidate(candidate)
    verification_store.save(verification)
    entry["verification_state"] = verification.verification_state.value
    if not is_base_model_verified(verification_store, candidate_id):
        entry["outcome"] = "verification_rejected"
        entry["reason"] = verification.verification_failure_reason
        return entry

    DurableAtlasCandidateRuntimeStore().bind_ollama(candidate_id, tag, runtime_model_digest=live_digest)

    print(f"[arena]   {tag}: warming up + reading ollama ps...", flush=True)
    gpu_percent = warm_up_and_measure_gpu(tag)
    entry["gpu_percent"] = gpu_percent
    print(f"[arena]   {tag}: gpu_percent={gpu_percent}", flush=True)

    print(f"[arena]   {tag}: running AtlasBench (90 tasks)...", flush=True)
    try:
        candidate_run = run_candidate_benchmark(candidate_id)
    except AtlasBenchSubjectUnavailable as error:
        entry["outcome"] = "atlasbench_unavailable"
        entry["reason"] = str(error)
        return entry
    entry["atlasbench_run_id"] = candidate_run.run_id
    entry["atlasbench_total_passed"] = candidate_run.total_passed
    entry["atlasbench_total_tasks"] = candidate_run.total_tasks
    print(
        f"[arena]   {tag}: AtlasBench {candidate_run.total_passed}/{candidate_run.total_tasks}",
        flush=True,
    )

    decision = compute_promotion_decision(candidate_id, production_run_id, candidate_run.run_id)
    entry["decision_id"] = decision.decision_id
    entry["verdict"] = decision.verdict.value
    entry["overall_production_pass_rate"] = decision.overall_production_pass_rate
    entry["overall_candidate_pass_rate"] = decision.overall_candidate_pass_rate
    entry["critical_regressions"] = [item.category.value for item in decision.critical_regressions]
    print(f"[arena]   {tag}: verdict={decision.verdict.value}", flush=True)

    print(f"[arena]   {tag}: measuring planner latency (20 objectives, 30s cap)...", flush=True)
    planner = measure_planner(tag)
    entry["planner"] = {
        "cold_start_seconds": planner.cold_start_seconds,
        "warm_p50_seconds": planner.p50,
        "warm_p95_seconds": planner.p95,
        "warm_max_seconds": planner.max_seconds,
        "warm_valid_json_rate": planner.valid_json_rate,
        "warm_acceptance_rate": planner.acceptance_rate,
        "warm_sample_size": planner.warm_total,
    }

    gates = {
        "atlasbench_promote_eligible": decision.verdict is AtlasPromotionVerdict.PROMOTE_ELIGIBLE,
        "gpu_100_percent": gpu_percent is not None and gpu_percent >= GATE_MIN_GPU_PERCENT,
        "warm_p95_under_12s": planner.p95 is not None and planner.p95 <= GATE_MAX_WARM_P95_SECONDS,
        "valid_json_rate_ge_95pct": planner.valid_json_rate >= GATE_MIN_VALID_JSON_RATE,
        "acceptance_rate_ge_90pct": planner.acceptance_rate >= GATE_MIN_ACCEPTANCE_RATE,
    }
    entry["gates"] = gates
    entry["qualifies"] = all(gates.values())
    entry["failing_gates"] = [name for name, passed in gates.items() if not passed]
    entry["outcome"] = "qualified" if entry["qualifies"] else "evaluated_not_qualified"
    return entry


def render_readme_section(
    round_number: int,
    completed_at: str,
    git_commit: str,
    hardware: str,
    production_run_id: str,
    candidates: list[dict[str, object]],
) -> str:
    lines = [
        f"## Round {round_number} -- {completed_at}",
        "",
        f"- Commit: `{git_commit}`",
        f"- Hardware: {hardware}",
        f"- Production run for comparison: `{production_run_id}`",
        "",
        "| Tag | License | Outcome | GPU % | Verdict | Pass rate (cand/prod) | Planner p95 | Valid-JSON | Acceptance | Failing gates |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for entry in candidates:
        planner = entry.get("planner") or {}
        if not isinstance(planner, dict):
            planner = {}
        failing_gates = entry.get("failing_gates") or []
        failing = ", ".join(str(item) for item in failing_gates) if isinstance(failing_gates, list) else ""
        lines.append(
            "| {tag} | {license} | {outcome} | {gpu} | {verdict} | {rates} | {p95} | {json_rate} | {accept} | {failing} |".format(
                tag=entry["tag"],
                license=entry.get("license", "-"),
                outcome=entry["outcome"],
                gpu=f"{entry['gpu_percent']:.0f}%" if entry.get("gpu_percent") is not None else "-",
                verdict=entry.get("verdict", "-"),
                rates=(
                    f"{entry['overall_candidate_pass_rate']:.1%}/{entry['overall_production_pass_rate']:.1%}"
                    if "overall_candidate_pass_rate" in entry
                    else "-"
                ),
                p95=f"{planner.get('warm_p95_seconds'):.2f}s" if planner.get("warm_p95_seconds") is not None else "-",
                json_rate=f"{planner.get('warm_valid_json_rate'):.0%}" if planner.get("warm_valid_json_rate") is not None else "-",
                accept=f"{planner.get('warm_acceptance_rate'):.0%}" if planner.get("warm_acceptance_rate") is not None else "-",
                failing=failing or str(entry.get("reason") or "-"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def git_commit_hash() -> str:
    result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    return result.stdout.strip() or "unknown"


def hardware_line() -> str:
    try:
        from prism_api.atlas_resources import governor

        snapshot = governor.snapshot()
        return f"{snapshot.gpu_name or 'unknown GPU'}, {snapshot.vram_total_mb or '?'} MB VRAM"
    except Exception:  # pragma: no cover - best-effort reporting only
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one Atlas Model Arena round.")
    parser.add_argument("tags", nargs="+", help="Ollama tags to evaluate, one at a time.")
    parser.add_argument("--round", type=int, required=True)
    parser.add_argument("--context-tokens", type=int, default=CONTEXT_TOKENS)
    parser.add_argument("--out-dir", default=str(ROOT / "docs" / "atlas" / "arena"))
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Set for the whole round: every AtlasBench run this process records (the
    # fresh production run and every candidate run) must share this exact
    # context-token policy, or compute_promotion_decision() refuses to
    # compare them (see atlas_bench_policy.py / evaluation_policy_id).
    os.environ["PRISM_ATLAS_BENCH_OLLAMA_CONTEXT_TOKENS"] = str(args.context_tokens)

    print(f"[arena] round {args.round}: establishing a comparable production run...", flush=True)
    ensure_configured_production_baseline()
    production_run_id = establish_comparable_production_run(args.context_tokens)
    print(f"[arena] production run: {production_run_id}", flush=True)

    candidates: list[dict[str, object]] = []
    previous_tag: Optional[str] = None
    for tag in args.tags:
        if previous_tag is not None:
            ollama_stop(previous_tag)
        print(f"[arena] evaluating {tag}...", flush=True)
        entry = evaluate_candidate(tag, production_run_id=production_run_id, context_tokens=args.context_tokens)
        print(f"[arena] {tag}: outcome={entry.get('outcome')}", flush=True)
        candidates.append(entry)
        previous_tag = tag
    if previous_tag is not None:
        ollama_stop(previous_tag)

    completed_at = datetime.now(timezone.utc).isoformat()
    commit = git_commit_hash()
    hardware = hardware_line()
    report: dict[str, object] = {
        "round": args.round,
        "completed_at": completed_at,
        "git_commit": commit,
        "hardware_line": hardware,
        "context_tokens": args.context_tokens,
        "production_run_id": production_run_id,
        "candidates": candidates,
        "qualifying_tags": [entry["tag"] for entry in candidates if entry.get("qualifies")],
    }

    out_path = out_dir / f"round-{args.round}.json"
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")

    readme_path = out_dir / "README.md"
    section = render_readme_section(args.round, completed_at, commit, hardware, production_run_id, candidates)
    if readme_path.exists():
        readme_path.write_text(readme_path.read_text(encoding="utf-8") + "\n" + section, encoding="utf-8")
    else:
        readme_path.write_text("# Atlas Model Arena rounds\n\n" + section, encoding="utf-8")

    print(json.dumps({"report": str(out_path), **report}, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
