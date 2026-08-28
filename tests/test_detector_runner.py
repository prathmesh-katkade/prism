"""Tests for modules.detector_runner — the "Run All Detectors" agentic
entry point that auto-fires the deterministic, zero-extra-input detectors
(hypothesis_sweep, anomaly) so insight_orchestrator has enough to
synthesize without the user visiting two separate tabs first.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.detector_runner import (
    MAX_AUTORUN_COLUMNS,
    MAX_AUTORUN_ROWS,
    autorun_eligible,
    run_all_detectors,
)


def _viable_df(n: int = 200, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=n)
    y = 3 * x + rng.normal(scale=0.1, size=n)  # strong planted correlation
    group = rng.choice(["a", "b", "c"], size=n)
    offset = pd.Series(group).map({"a": 0, "b": 5, "c": 10}).to_numpy()
    z = offset + rng.normal(scale=0.5, size=n)
    return pd.DataFrame({"x": x, "y": y, "z": z, "group": group})


def _column_types(df: pd.DataFrame) -> dict[str, str]:
    return {c: ("numeric" if pd.api.types.is_numeric_dtype(df[c]) else "categorical") for c in df.columns}


# ─────────────────────────────────────────────────────────────────────────
# autorun_eligible
# ─────────────────────────────────────────────────────────────────────────


def test_autorun_eligible_true_for_normal_dataset():
    df = _viable_df()
    eligible, reason = autorun_eligible(df, _column_types(df))
    assert eligible is True
    assert reason is None


def test_autorun_eligible_false_for_none_df():
    eligible, reason = autorun_eligible(None, {})
    assert eligible is False
    assert reason


def test_autorun_eligible_false_for_empty_df():
    eligible, reason = autorun_eligible(pd.DataFrame(), {})
    assert eligible is False
    assert reason


def test_autorun_eligible_false_over_row_cap():
    df = pd.DataFrame({"x": np.arange(MAX_AUTORUN_ROWS + 1)})
    eligible, reason = autorun_eligible(df, _column_types(df))
    assert eligible is False
    assert "rows" in reason


def test_autorun_eligible_false_over_column_cap():
    df = pd.DataFrame({f"c{i}": np.arange(5) for i in range(MAX_AUTORUN_COLUMNS + 1)})
    eligible, reason = autorun_eligible(df, _column_types(df))
    assert eligible is False
    assert "column" in reason.lower()


def test_autorun_eligible_true_at_exactly_the_row_cap():
    df = pd.DataFrame({"x": np.arange(MAX_AUTORUN_ROWS), "y": np.arange(MAX_AUTORUN_ROWS)})
    eligible, _ = autorun_eligible(df, _column_types(df))
    assert eligible is True


# ─────────────────────────────────────────────────────────────────────────
# run_all_detectors
# ─────────────────────────────────────────────────────────────────────────


def test_run_all_detectors_runs_both_on_a_fresh_dataset():
    df = _viable_df()
    result = run_all_detectors(df, _column_types(df))
    assert result["eligible"] is True
    assert result["block_reason"] is None
    assert "hypothesis_sweep" in result["ran"]
    assert "anomaly" in result["ran"]
    assert result["skipped"] == []
    assert result["sweep_result"] is not None
    assert result["sweep_result"]["tested"]  # viable pairs exist in this synthetic df
    # power annotation ran (t-test/ANOVA rows get power fields when applicable)
    assert result["anomaly_result_df"] is not None
    assert result["anomaly_error"] is None
    # confounder cross-check wired the same as the manual "Run Hypothesis
    # Sweep" button (see cross_check_confounders() call in app.py)
    assert isinstance(result["confounder_check"], list)
    # Both interaction checks (ANOVA + chi-square) wired the same way — a
    # standing gap this run closed: "Run All Detectors" used to skip both,
    # leaving the panels stuck on a stale/empty result from before the
    # dataset that got auto-run.
    assert isinstance(result["interaction_check"], list)
    assert isinstance(result["categorical_interaction_check"], list)


def test_run_all_detectors_skips_sweep_already_computed_this_session():
    df = _viable_df()
    result = run_all_detectors(df, _column_types(df), already_have_sweep=True)
    assert "hypothesis_sweep" not in result["ran"]
    assert result["sweep_result"] is None
    assert any(s["detector"] == "hypothesis_sweep" for s in result["skipped"])
    assert "anomaly" in result["ran"]  # the other detector still runs


def test_run_all_detectors_skips_anomaly_already_computed_this_session():
    df = _viable_df()
    result = run_all_detectors(df, _column_types(df), already_have_anomaly=True)
    assert "anomaly" not in result["ran"]
    assert result["anomaly_result_df"] is None
    assert any(s["detector"] == "anomaly" for s in result["skipped"])
    assert "hypothesis_sweep" in result["ran"]


def test_run_all_detectors_skips_both_when_both_already_computed():
    df = _viable_df()
    result = run_all_detectors(df, _column_types(df), already_have_sweep=True, already_have_anomaly=True)
    assert result["ran"] == []
    assert len(result["skipped"]) == 2


def test_run_all_detectors_blocked_over_row_cap_runs_nothing():
    df = pd.DataFrame({"x": np.arange(MAX_AUTORUN_ROWS + 1), "y": np.arange(MAX_AUTORUN_ROWS + 1)})
    result = run_all_detectors(df, _column_types(df))
    assert result["eligible"] is False
    assert result["block_reason"]
    assert result["ran"] == []
    assert result["sweep_result"] is None
    assert result["anomaly_result_df"] is None


def test_run_all_detectors_no_viable_columns_does_not_crash():
    # A single numeric column: no pairs for the sweep, but still enough
    # rows/columns for anomaly detection to run.
    df = pd.DataFrame({"x": np.arange(50, dtype=float)})
    result = run_all_detectors(df, _column_types(df))
    assert result["eligible"] is True
    assert result["sweep_result"]["tested"] == []
    assert result["anomaly_result_df"] is not None  # ran fine on the lone numeric column


def test_run_all_detectors_too_few_rows_for_anomaly_reports_error_not_crash():
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [4.0, 5.0, 6.0]})
    result = run_all_detectors(df, _column_types(df))
    assert result["eligible"] is True
    assert "anomaly" in result["ran"]
    assert result["anomaly_result_df"] is None
    assert result["anomaly_error"] is not None


def test_run_all_detectors_returns_none_df_gracefully():
    result = run_all_detectors(None, {})
    assert result["eligible"] is False
    assert result["ran"] == []


def test_run_all_detectors_never_raises_on_malformed_column_types():
    # Defensive: column_types referencing a column not in df shouldn't crash.
    df = _viable_df()
    bad_types = _column_types(df)
    bad_types["ghost_column"] = "numeric"
    result = run_all_detectors(df, bad_types)
    assert result["eligible"] is True  # should not raise


# ─────────────────────────────────────────────────────────────────────────
# Integration: run_all_detectors() -> insight_orchestrator.orchestrate_insights()
#
# This is the actual point of the feature — a single "Run All Detectors"
# click should give the orchestrator enough to stop being silent, without
# the user ever visiting Stats Lab or the Anomaly Detection expander. Uses
# the same {"count", "total_rows", "reasons"} anomaly-summary shape
# app.py's own _anomaly_orchestrator_summary() builds from a flagged
# DataFrame (see app.py), since insight_orchestrator never touches pandas
# directly.
# ─────────────────────────────────────────────────────────────────────────


def _anomaly_summary_from_df(flagged, total_rows):
    if flagged is None or flagged.empty:
        return None
    reasons = flagged["anomaly_reason"].tolist() if "anomaly_reason" in flagged.columns else []
    return {"count": int(len(flagged)), "total_rows": int(total_rows), "reasons": reasons}


def test_run_all_detectors_feeds_orchestrator_to_non_silent_result():
    from modules.insight_orchestrator import orchestrate_insights

    df = _viable_df(n=300, seed=1)
    column_types = _column_types(df)
    result = run_all_detectors(df, column_types)
    assert "hypothesis_sweep" in result["ran"]
    assert "anomaly" in result["ran"]

    orchestration = orchestrate_insights(
        {
            "hypothesis_sweep": result["sweep_result"],
            "anomaly": _anomaly_summary_from_df(result["anomaly_result_df"], len(df)),
        }
    )
    # Two detectors fired with real findings on this planted-signal dataset
    # (x/y are near-deterministically correlated, z genuinely differs by
    # group) — the orchestrator should have enough to synthesize rather
    # than stay silent, exactly the gap this feature closes.
    assert orchestration.silent is False
    assert orchestration.n_detectors_fired >= 2
    assert orchestration.top
