"""Fail-closed check of versioned arena measurements before model promotion."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Literal, cast


def arena_gate_failure(
    *, runtime_model: str, runtime_digest: str, bench_run_id: str, tier: Literal["fast", "deep"],
    report_dir: Path | None = None,
) -> str | None:
    root = report_dir or Path(__file__).resolve().parents[3] / "docs" / "atlas" / "arena"
    found = False
    for path in sorted(root.glob("round-*.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(report, dict) or not isinstance(report.get("models"), list):
            continue
        for model in report["models"]:
            if not isinstance(model, dict):
                continue
            bench = model.get("bench")
            if not isinstance(bench, dict) or bench.get("run_id") != bench_run_id:
                continue
            found = True
            if model.get("tag") != runtime_model or model.get("digest") != runtime_digest:
                return "Arena evidence runtime model or digest does not match the verified binding."
            planner = model.get("planner")
            if not isinstance(planner, dict):
                return "Arena evidence has no planner measurements."
            gpu = model.get("gpu_percent_min_observed")
            p95 = planner.get("p95_seconds")
            valid_json = planner.get("valid_json_rate")
            acceptance = planner.get("acceptance_rate")
            measurements = (gpu, p95, valid_json, acceptance)
            if any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in measurements):
                return "Arena evidence is missing a numeric gate measurement."
            gpu_value, p95_value, json_value, acceptance_value = (float(cast(float, value)) for value in measurements)
            if not all(math.isfinite(value) for value in (gpu_value, p95_value, json_value, acceptance_value)):
                return "Arena evidence contains a non-finite gate measurement."
            if gpu_value < 0 or p95_value < 0 or not 0 <= json_value <= 1 or not 0 <= acceptance_value <= 1:
                return "Arena evidence contains an out-of-range gate measurement."
            if gpu_value < 85:
                return "GPU residency is below 85%."
            if p95_value > (15 if tier == "deep" else 12):
                return f"Warm planner p95 exceeds the {tier} tier budget."
            if json_value < 0.95:
                return "Valid-JSON rate is below 95%."
            if acceptance_value < 0.90:
                return "Planner acceptance is below 90%."
            return None
    return "No matching arena evidence for the candidate AtlasBench run." if not found else None
