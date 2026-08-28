"""
Run All Detectors — a single agentic entry point that auto-fires every
detector capable of running with zero additional user input, then leaves
the results in the exact shape `insight_orchestrator.orchestrate_insights()`
and the Overview/Stats Lab panels already expect.

Why this exists: `auto_insights` and `confounder_detection.auto_scan_for_
confounding` already run automatically on upload (see `app.py`'s
`set_active_dataset()`), but `hypothesis_sweep.sweep_hypotheses()` and
`anomaly.find_anomalies()` — both pure, deterministic, dataset-wide checks
that need no column/target selection — only ever run when the user
manually opens Stats Lab or the Overview "Anomaly Detection" expander and
clicks their own button. `insight_orchestrator` stays silent
(`MIN_DETECTORS_FOR_OUTPUT = 2`) until enough of those manual visits have
happened, even though nothing about either check actually requires a
human in the loop to decide what to run. This module closes that gap with
one explicit action: it does not introduce new detection logic, it only
fires the two already-shipped, already-tested detector functions and
returns their raw results so the caller (`app.py`) can drop them straight
into the same `st.session_state` slots the manual buttons already
populate — a "Run All Detectors" click is indistinguishable, downstream,
from a user having visited both tabs themselves.

Deliberately excluded: the Causal Effect Estimator (ATT/CATE) and Drift.
Both require the user to choose a treatment/outcome column (causal) or a
second dataset (drift) — there is no defensible automatic default, and
auto-firing a causal estimate against an arbitrarily-picked column pair
would manufacture a claim nobody asked for. Silence is the safer failure
mode there, same convention as every other detector in this codebase.

No Gemini calls happen here or as a side effect of calling
`run_all_detectors()` — narration (the "Generate Executive Summary"
button) stays a separate, explicit, user-triggered action exactly as it
already is today. This keeps the feature free to use repeatedly within
Gemini's free-tier RPM/RPD limits regardless of how many times a user
re-runs detection.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from modules import anomaly, hypothesis_sweep

# Guard thresholds for the *auto-run* path only. A very large dataset can
# make a full pairwise sweep or an IsolationForest fit slow enough that a
# single click would hang the UI with no way to cancel — past this cap,
# `run_all_detectors()` runs nothing and reports why, and the user can
# still run either detector individually from its own tab (which has no
# such cap; a deliberate, informed single-detector run is a different
# risk/benefit trade than an automatic one-click sweep of everything).
MAX_AUTORUN_ROWS = 250_000
MAX_AUTORUN_COLUMNS = 150


def autorun_eligible(df: Optional[pd.DataFrame], column_types: Optional[dict]) -> tuple[bool, Optional[str]]:
    """Whether `run_all_detectors()` should attempt anything at all for
    this dataset. Returns (eligible, reason) — reason is None when
    eligible, a short user-facing explanation otherwise."""
    if df is None or df.empty:
        return False, "No data loaded yet."
    if len(df) > MAX_AUTORUN_ROWS:
        return False, (
            f"This dataset has {len(df):,} rows, over the {MAX_AUTORUN_ROWS:,}-row auto-run "
            "cap. Run Hypothesis Sweep (Stats Lab) and Anomaly Detection (Overview) "
            "individually instead — each can still handle a dataset this size on its own."
        )
    n_cols = len(column_types or {})
    if n_cols > MAX_AUTORUN_COLUMNS:
        return False, (
            f"This dataset has {n_cols:,} columns, over the {MAX_AUTORUN_COLUMNS}-column "
            "auto-run cap. Run each detector individually from its own tab instead."
        )
    return True, None


def run_all_detectors(
    df: Optional[pd.DataFrame],
    column_types: Optional[dict],
    already_have_sweep: bool = False,
    already_have_anomaly: bool = False,
) -> dict:
    """Fire hypothesis_sweep and anomaly detection (whichever hasn't
    already run this session) in one call.

    Returns {
      "eligible": bool,          # False if autorun_eligible() blocked the whole call
      "block_reason": Optional[str],
      "ran": [str, ...],         # detector names actually executed this call
      "skipped": [{"detector": str, "reason": str}, ...],
      "sweep_result": Optional[dict],       # hypothesis_sweep.sweep_hypotheses() + annotate_power(), or None
      "confounder_check": list,             # hypothesis_sweep.cross_check_confounders() for the sweep above, [] if sweep didn't run
      "interaction_check": list,            # hypothesis_sweep.cross_check_interactions() for the sweep above, [] if sweep didn't run
      "categorical_interaction_check": list,  # hypothesis_sweep.cross_check_categorical_interactions() for the sweep above, [] if sweep didn't run
      "anomaly_result_df": Optional[pd.DataFrame],
      "anomaly_error": Optional[str],
    }

    Never raises: a detector that can't run on this data (no numeric
    columns, too few rows, missing scikit-learn) reports its own error /
    empty result exactly as its manual tab button already does, rather
    than aborting the whole call.
    """
    result: dict = {
        "eligible": True,
        "block_reason": None,
        "ran": [],
        "skipped": [],
        "sweep_result": None,
        "confounder_check": [],
        "interaction_check": [],
        "categorical_interaction_check": [],
        "anomaly_result_df": None,
        "anomaly_error": None,
    }

    eligible, reason = autorun_eligible(df, column_types)
    if not eligible:
        result["eligible"] = False
        result["block_reason"] = reason
        return result

    # Defensive: only pass through column_types entries that actually
    # exist in df. Neither hypothesis_sweep nor anomaly validate this
    # themselves (they trust column_types was derived from df, which is
    # true for every existing caller) — this call site is the one place
    # a caller could plausibly hand in a stale dict, so guard here rather
    # than assume.
    safe_column_types = {c: t for c, t in (column_types or {}).items() if c in df.columns}

    if already_have_sweep:
        result["skipped"].append({"detector": "hypothesis_sweep", "reason": "already run this session"})
    else:
        try:
            sweep_result = hypothesis_sweep.sweep_hypotheses(df, safe_column_types)
            sweep_result = hypothesis_sweep.annotate_power(sweep_result)
        except Exception as exc:  # pragma: no cover - defensive, no known trigger
            sweep_result = {
                "tested": [], "n_pairs_available": 0, "n_pairs_skipped": 0,
                "n_tests_run": 0, "n_significant": 0, "alpha": hypothesis_sweep.DEFAULT_ALPHA,
                "error": str(exc),
            }
        result["sweep_result"] = sweep_result
        result["ran"].append("hypothesis_sweep")
        try:
            result["confounder_check"] = hypothesis_sweep.cross_check_confounders(df, safe_column_types, sweep_result)
        except Exception:  # pragma: no cover - defensive, no known trigger
            result["confounder_check"] = []
        try:
            result["interaction_check"] = hypothesis_sweep.cross_check_interactions(df, safe_column_types, sweep_result)
        except Exception:  # pragma: no cover - defensive, no known trigger
            result["interaction_check"] = []
        try:
            result["categorical_interaction_check"] = hypothesis_sweep.cross_check_categorical_interactions(
                df, safe_column_types, sweep_result
            )
        except Exception:  # pragma: no cover - defensive, no known trigger
            result["categorical_interaction_check"] = []

    if already_have_anomaly:
        result["skipped"].append({"detector": "anomaly", "reason": "already run this session"})
    elif not anomaly.is_available():
        result["skipped"].append({"detector": "anomaly", "reason": "scikit-learn isn't installed"})
    else:
        flagged, anomaly_err = anomaly.find_anomalies(df, safe_column_types)
        result["anomaly_result_df"] = flagged
        result["anomaly_error"] = anomaly_err
        result["ran"].append("anomaly")

    return result
