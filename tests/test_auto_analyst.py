"""Tests for modules.auto_analyst's pure-logic paths (plan fallback, result
summarization) — the parts that don't require a live Gemini model.
"""
from __future__ import annotations

import pandas as pd

from modules.auto_analyst import _default_plan, _summarize_result, synthesize_findings


def test_default_plan_always_includes_quality_check_and_conclusions():
    plan = _default_plan({"a": "numeric"})
    titles = [step["title"] for step in plan]
    assert titles[0] == "Data quality check"
    assert titles[-1] == "Conclusions"


def test_default_plan_adds_distributions_and_correlations_for_numeric():
    plan = _default_plan({"a": "numeric", "b": "numeric"})
    titles = [step["title"] for step in plan]
    assert "Distributions" in titles
    assert "Correlations" in titles


def test_default_plan_adds_time_trends_only_with_datetime():
    without_dt = _default_plan({"a": "numeric"})
    with_dt = _default_plan({"a": "numeric", "d": "datetime"})
    assert "Time trends" not in [s["title"] for s in without_dt]
    assert "Time trends" in [s["title"] for s in with_dt]


def test_default_plan_skips_segments_without_categorical():
    plan = _default_plan({"a": "numeric"})
    assert "Segments" not in [s["title"] for s in plan]


def test_summarize_result_handles_none_and_dataframe():
    assert _summarize_result(None) == "(no result)"
    df = pd.DataFrame({"a": range(20)})
    summary = _summarize_result(df)
    assert isinstance(summary, str)
    assert "a" in summary


def test_synthesize_findings_without_model_returns_error():
    bullets, error = synthesize_findings(None, [{"title": "x", "result": "y"}])
    assert bullets == []
    assert error is not None


def test_synthesize_findings_skips_errored_steps():
    # every step errored -> nothing left to summarize, so it should short-circuit
    # with a clear error rather than calling Gemini with an empty prompt.
    outcomes = [{"title": "Data quality check", "error": "boom", "result": None}]
    bullets, error = synthesize_findings(None, outcomes)
    assert bullets == []
    assert error is not None
