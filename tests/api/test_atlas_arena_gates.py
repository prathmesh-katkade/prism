from __future__ import annotations

import json

from prism_api.atlas_arena_gates import arena_gate_failure


def _evidence(tmp_path, *, p95: float = 13.0):  # type: ignore[no-untyped-def]
    (tmp_path / "round-test.json").write_text(json.dumps({"models": [{
        "tag": "candidate-model", "digest": "verified-digest",
        "bench": {"run_id": "bench-run"},
        "gpu_percent_min_observed": 92,
        "planner": {"p95_seconds": p95, "valid_json_rate": 0.99, "acceptance_rate": 0.95},
    }]}), encoding="utf-8")


def test_deep_latency_budget_is_15_seconds_and_other_gates_stay_fixed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _evidence(tmp_path)
    kwargs = {"runtime_model": "candidate-model", "runtime_digest": "verified-digest", "bench_run_id": "bench-run", "report_dir": tmp_path}
    assert arena_gate_failure(**kwargs, tier="fast") == "Warm planner p95 exceeds the fast tier budget."
    assert arena_gate_failure(**kwargs, tier="deep") is None
    assert arena_gate_failure(**{**kwargs, "runtime_digest": "wrong"}, tier="deep") is not None
    assert arena_gate_failure(**{**kwargs, "bench_run_id": "missing"}, tier="deep") is not None


def test_missing_arena_evidence_fails_closed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    assert arena_gate_failure(runtime_model="candidate-model", runtime_digest="verified-digest", bench_run_id="bench-run", tier="deep", report_dir=tmp_path) is not None
