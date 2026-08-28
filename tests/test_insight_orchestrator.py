"""Tests for modules.insight_orchestrator — the cross-detector synthesis
layer that de-duplicates overlapping claims from Prism's independent
detector modules, flags agreement/contradiction, and severity-ranks the
result into a "what matters most" list. Pure synthesis over already-
computed detector output — no detection logic is re-run here.
"""
from __future__ import annotations

from modules.insight_orchestrator import (
    MIN_DETECTORS_FOR_OUTPUT,
    Claim,
    fingerprint_result,
    format_top_text,
    group_claims,
    narrate_orchestration,
    normalize_findings,
    orchestrate_insights,
    orchestration_reference_numbers,
    proactive_alert_text,
    proactive_alert_text_tier2,
    severity_icon,
    verify_narration,
)

# ─────────────────────────────────────────────────────────────────────────
# Fixtures — synthetic raw detector outputs
# ─────────────────────────────────────────────────────────────────────────


def _auto_insights_raw():
    return [
        {
            "category": "correlation",
            "severity": "high",
            "column": "spend ↔ revenue",
            "metric": "r=0.91",
            "message": "'spend' and 'revenue' are strongly correlated (r=0.910).",
        },
        {
            "category": "missing_data",
            "severity": "medium",
            "column": "region",
            "metric": "15.0% missing",
            "message": "'region' has 15.0% missing values.",
        },
        {
            "category": "duplicates",
            "severity": "low",
            "column": "(all columns)",
            "metric": "3 duplicates",
            "message": "Found 3 exact duplicate rows.",
        },
    ]


def _confounder_raw_agreeing_with_causal():
    """A confounder finding on the same (spend, revenue) pair the fixture
    causal ATT result below also targets, whose flagged confounder
    ('channel') is NOT among the causal estimate's covariates — the
    textbook contradiction case."""
    return [
        {
            "x": "spend",
            "y": "revenue",
            "overall_r": 0.91,
            "findings": [
                {
                    "confounder": "channel",
                    "type": "categorical",
                    "overall_r": 0.91,
                    "adjusted_r": -0.1,
                    "verdict": "paradox",
                    "detail": [{"group": "online", "r": -0.2, "n": 20}],
                }
            ],
        }
    ]


def _causal_att_raw_missing_channel_covariate():
    return {
        "ok": True,
        "att": 12.3,
        "ci_low": 4.0,
        "ci_high": 20.0,
        "n_treated": 30,
        "n_control": 30,
        "n_matched": 28,
        "match_rate": 0.93,
        "treatment_col": "spend",
        "treated_value": "high",
        "control_value": "low",
        "outcome_col": "revenue",
        "covariates": ["tenure"],  # deliberately excludes 'channel'
        "balance_before": [],
        "balance_after": [],
        "warnings": [],
    }


def _causal_att_raw_adjusting_for_confounder():
    return {
        "ok": True,
        "att": 12.3,
        "ci_low": 4.0,
        "ci_high": 20.0,
        "n_treated": 30,
        "n_control": 30,
        "n_matched": 28,
        "match_rate": 0.93,
        "treatment_col": "spend",
        "treated_value": "high",
        "control_value": "low",
        "outcome_col": "revenue",
        "covariates": ["tenure", "channel"],  # includes the flagged confounder
        "balance_before": [],
        "balance_after": [],
        "warnings": [],
    }


def _causal_cate_raw_sign_reversal():
    return {
        "ok": True,
        "pooled": {"treatment_col": "spend", "outcome_col": "revenue", "att": 8.0, "ci_low": 2.0, "ci_high": 14.0},
        "subgroup_col": "region",
        "subgroups": [],
        "sign_reversal": True,
        "heterogeneity_detected": True,
        "warnings": [],
    }


def _anomaly_raw():
    return {
        "count": 12,
        "total_rows": 100,
        "reasons": [
            "spend is 4.2x above the column median.",
            "spend is 3.9x above the column median.",
            "tenure is 2.1x below the column median.",
        ],
    }


def _drift_raw():
    return {
        "column_reports": [
            {"column": "revenue", "type": "numeric", "drift_score": 82.0},
            {"column": "notes", "type": "categorical", "drift_score": 10.0},
        ],
    }


def _verifier_raw():
    return {
        "findings": [
            "Revenue is strongly correlated with spend at 0.91.",
            "Average tenure is 14.2 months across all customers.",
        ],
        "verification": [
            {"status": "flagged", "checked": 1, "matched": 0},
            {"status": "confirmed", "checked": 1, "matched": 1},
        ],
        "columns": ["revenue", "spend", "tenure"],
    }


def _auto_insights_raw_medium_only():
    """Same shape as _auto_insights_raw() but with no "high" severity entry
    — used by the tier-2 proactive alert tests so a lone confounder paradox
    is unambiguously the top-ranked claim rather than tying with auto_
    insights' own high-severity correlation finding."""
    return [
        {
            "category": "missing_data",
            "severity": "medium",
            "column": "region",
            "metric": "15.0% missing",
            "message": "'region' has 15.0% missing values.",
        },
    ]


def _confounder_raw_lone_high_paradox():
    """A confounder paradox on a pair no other baseline detector's output
    touches — confounder_detection runs silently on every upload (like
    auto_insights) but, unlike auto_insights, has no proactive alert of its
    own. This is the fixture the tier-2 alert tests exist to cover."""
    return [
        {
            "x": "tenure",
            "y": "plan_tier",
            "overall_r": 0.4,
            "findings": [
                {
                    "confounder": "region",
                    "type": "categorical",
                    "overall_r": 0.4,
                    "adjusted_r": -0.05,
                    "verdict": "paradox",
                    "detail": [],
                }
            ],
        }
    ]


def _hypothesis_sweep_raw():
    return {
        "tested": [
            {
                "col_a": "revenue", "col_b": "spend", "test": "pearson",
                "test_label": "Pearson correlation", "statistic": 0.91, "p_value": 0.0001,
                "p_adj": 0.0004, "significant": True, "effect_size": 0.91,
                "effect_size_name": "Pearson r", "effect_size_label": "large", "n": 200,
            },
            {
                "col_a": "region", "col_b": "channel", "test": "chi2",
                "test_label": "Chi-square", "statistic": 4.1, "p_value": 0.04,
                "p_adj": 0.09, "significant": False, "effect_size": 0.12,
                "effect_size_name": "Cramer's V", "effect_size_label": "small", "n": 200,
            },
            {
                "col_a": "tenure", "col_b": "plan_tier", "test": "anova",
                "test_label": "One-way ANOVA", "statistic": 6.2, "p_value": 0.002,
                "p_adj": 0.006, "significant": True, "effect_size": 0.04,
                "effect_size_name": "eta-squared", "effect_size_label": "small", "n": 200,
            },
        ],
        "n_pairs_available": 3, "n_pairs_skipped": 0, "n_tests_run": 3,
        "n_significant": 2, "alpha": 0.05,
    }


# ─────────────────────────────────────────────────────────────────────────
# Normalization
# ─────────────────────────────────────────────────────────────────────────


def test_normalize_auto_insights_splits_pair_subjects():
    claims = normalize_findings({"auto_insights": _auto_insights_raw()})
    corr_claim = next(c for c in claims if c.kind == "auto_insights:correlation")
    assert corr_claim.subjects == frozenset({"spend", "revenue"})
    dup_claim = next(c for c in claims if c.kind == "auto_insights:duplicates")
    assert dup_claim.subjects == frozenset()  # "(all columns)" -> dataset-wide


def test_normalize_confounder_paradox_is_high_severity():
    claims = normalize_findings({"confounder": _confounder_raw_agreeing_with_causal()})
    assert len(claims) == 1
    assert claims[0].severity == "high"
    assert claims[0].subjects == frozenset({"spend", "revenue"})
    assert claims[0].meta["confounder"] == "channel"


def test_normalize_causal_att_significant_when_ci_excludes_zero():
    claims = normalize_findings({"causal_att": _causal_att_raw_missing_channel_covariate()})
    assert claims[0].severity == "high"


def test_normalize_causal_att_low_severity_when_ci_crosses_zero():
    raw = _causal_att_raw_missing_channel_covariate()
    raw["ci_low"], raw["ci_high"] = -2.0, 20.0
    claims = normalize_findings({"causal_att": raw})
    assert claims[0].severity == "low"


def test_normalize_causal_att_not_ok_produces_no_claims():
    claims = normalize_findings({"causal_att": {"ok": False, "error": "not enough data"}})
    assert claims == []


def test_normalize_causal_cate_sign_reversal_is_high_severity():
    claims = normalize_findings({"causal_cate": _causal_cate_raw_sign_reversal()})
    assert len(claims) == 1
    assert claims[0].severity == "high"
    assert claims[0].subjects == frozenset({"spend", "revenue"})


def test_normalize_causal_cate_no_heterogeneity_produces_no_claims():
    raw = _causal_cate_raw_sign_reversal()
    raw["sign_reversal"] = False
    raw["heterogeneity_detected"] = False
    assert normalize_findings({"causal_cate": raw}) == []


def test_normalize_anomaly_extracts_top_column_and_scales_severity():
    claims = normalize_findings({"anomaly": _anomaly_raw()})
    assert len(claims) == 1
    assert claims[0].subjects == frozenset({"spend"})  # most common column in reasons
    assert claims[0].severity == "high"  # 12% >= 10%


def test_normalize_anomaly_with_no_extractable_column_is_dataset_wide():
    claims = normalize_findings(
        {"anomaly": {"count": 2, "total_rows": 100, "reasons": ["Unusual combination of values across numeric columns."]}}
    )
    assert claims[0].subjects == frozenset()


def test_normalize_anomaly_empty_count_produces_no_claims():
    assert normalize_findings({"anomaly": {"count": 0, "total_rows": 100, "reasons": []}}) == []


def test_normalize_drift_filters_below_threshold():
    claims = normalize_findings({"drift": _drift_raw()})
    assert len(claims) == 1
    assert claims[0].subjects == frozenset({"revenue"})
    assert claims[0].severity == "high"  # 82 >= 75


def test_normalize_verifier_only_surfaces_flagged_findings():
    # confirmed findings are already badged in the Auto Analyst tab — only
    # a flagged (unmatched-number) finding is worth cross-checking here.
    claims = normalize_findings({"verifier": _verifier_raw()})
    assert len(claims) == 1
    assert claims[0].detector == "verifier"
    assert "0.91" in claims[0].message or "correlated" in claims[0].message


def test_normalize_verifier_extracts_subjects_from_finding_text():
    claims = normalize_findings({"verifier": _verifier_raw()})
    assert claims[0].subjects == frozenset({"revenue", "spend"})


def test_normalize_verifier_no_flagged_findings_produces_no_claims():
    raw = _verifier_raw()
    raw["verification"] = [{"status": "confirmed", "checked": 1, "matched": 1}] * 2
    assert normalize_findings({"verifier": raw}) == []


def test_normalize_verifier_empty_findings_is_safe():
    assert normalize_findings({"verifier": {"findings": [], "verification": [], "columns": []}}) == []
    assert normalize_findings({"verifier": None}) == []


def test_normalize_hypothesis_sweep_only_surfaces_fdr_significant_pairs():
    # Only pairs that survived Benjamini-Hochberg correction are reportable
    # on their own — a pre-correction p<0.05 out of a batch sweep is not.
    claims = normalize_findings({"hypothesis_sweep": _hypothesis_sweep_raw()})
    assert len(claims) == 2
    assert all(c.detector == "hypothesis_sweep" for c in claims)
    kinds = {frozenset(c.subjects) for c in claims}
    assert frozenset({"revenue", "spend"}) in kinds
    assert frozenset({"tenure", "plan_tier"}) in kinds
    assert frozenset({"region", "channel"}) not in kinds  # not significant post-FDR


def test_normalize_hypothesis_sweep_severity_follows_effect_size_label():
    claims = normalize_findings({"hypothesis_sweep": _hypothesis_sweep_raw()})
    large = next(c for c in claims if c.subjects == frozenset({"revenue", "spend"}))
    small = next(c for c in claims if c.subjects == frozenset({"tenure", "plan_tier"}))
    assert large.severity == "high"
    assert small.severity == "low"


def test_normalize_hypothesis_sweep_empty_and_none_are_safe():
    assert normalize_findings({"hypothesis_sweep": {"tested": []}}) == []
    assert normalize_findings({"hypothesis_sweep": None}) == []


def test_hypothesis_sweep_claim_agrees_with_auto_insights_on_shared_subject():
    # The sweep independently re-derives the same revenue/spend relationship
    # Auto-Insights already flagged via a completely different code path
    # (a formal FDR-corrected hypothesis test vs. a raw correlation scan) —
    # that agreement is exactly the cross-detector signal this orchestrator
    # exists to surface.
    result = orchestrate_insights(
        {"auto_insights": _auto_insights_raw(), "hypothesis_sweep": _hypothesis_sweep_raw()}
    )
    assert result.silent is False
    matching = [g for g in result.groups if g.subjects == frozenset({"revenue", "spend"})]
    assert matching, [g.subjects for g in result.groups]
    assert {c.detector for c in matching[0].claims} >= {"auto_insights", "hypothesis_sweep"}
    assert matching[0].agreement is True


def test_normalize_unknown_detector_key_is_ignored():
    claims = normalize_findings({"some_future_detector": [{"whatever": True}]})
    assert claims == []


def test_normalize_malformed_detector_output_does_not_raise():
    # auto_insights adapter expects dicts with a "message" key — garbage in
    # one detector must not break normalization of the others.
    claims = normalize_findings({"auto_insights": ["not a dict"], "drift": _drift_raw()})
    assert any(c.detector == "drift" for c in claims)


def test_normalize_none_and_missing_values_are_safe():
    assert normalize_findings({"auto_insights": None, "confounder": None}) == []
    assert normalize_findings({}) == []
    assert normalize_findings(None) == []


# ─────────────────────────────────────────────────────────────────────────
# Grouping / de-duplication
# ─────────────────────────────────────────────────────────────────────────


def test_group_claims_merges_same_subject_pair_across_detectors():
    claims = normalize_findings(
        {
            "auto_insights": _auto_insights_raw(),
            "confounder": _confounder_raw_agreeing_with_causal(),
        }
    )
    groups = group_claims(claims)
    spend_revenue_groups = [g for g in groups if g.subjects == frozenset({"spend", "revenue"})]
    assert len(spend_revenue_groups) == 1
    group = spend_revenue_groups[0]
    assert set(group.detectors) == {"auto_insights", "confounder"}
    assert group.agreement is True


def test_group_claims_keeps_dataset_wide_findings_separate():
    claims = [
        Claim(detector="auto_insights", subjects=frozenset(), severity="low", kind="a", message="finding A"),
        Claim(detector="drift", subjects=frozenset(), severity="low", kind="b", message="finding B"),
    ]
    groups = group_claims(claims)
    # two dataset-wide claims from different detectors must NOT be merged
    # into one topic just because both have empty subjects
    assert len(groups) == 2


def test_dedupe_exact_collapses_identical_repeated_claim():
    # normalize_findings() itself does not dedupe (that's orchestrate_insights'
    # job) — accidental duplication upstream (e.g. a detector re-run) must
    # still collapse to one claim once orchestrated.
    raw = _auto_insights_raw()
    result = orchestrate_insights({"auto_insights": raw + raw, "drift": _drift_raw()})
    corr_claims = [c for c in result.groups if c.subjects == frozenset({"spend", "revenue"})][0].claims
    assert len(corr_claims) == 1


# ─────────────────────────────────────────────────────────────────────────
# Agreement / contradiction
# ─────────────────────────────────────────────────────────────────────────


def test_agreement_across_three_detectors_on_same_pair():
    result = orchestrate_insights(
        {
            "auto_insights": _auto_insights_raw(),
            "confounder": _confounder_raw_agreeing_with_causal(),
            "causal_att": _causal_att_raw_adjusting_for_confounder(),
        }
    )
    group = next(g for g in result.groups if g.subjects == frozenset({"spend", "revenue"}))
    assert group.agreement is True
    assert set(group.detectors) == {"auto_insights", "confounder", "causal_att"}
    # covariates include the confounder -> no contradiction here
    assert group.contradiction is None


def test_contradiction_flagged_when_causal_estimate_ignores_flagged_confounder():
    result = orchestrate_insights(
        {
            "confounder": _confounder_raw_agreeing_with_causal(),
            "causal_att": _causal_att_raw_missing_channel_covariate(),
        }
    )
    assert len(result.contradictions) == 1
    contradiction_group = result.contradictions[0]
    assert "channel" in contradiction_group.contradiction
    assert "Check this" in contradiction_group.contradiction
    assert contradiction_group.headline == contradiction_group.contradiction


def test_no_contradiction_when_causal_estimate_adjusts_for_confounder():
    result = orchestrate_insights(
        {
            "confounder": _confounder_raw_agreeing_with_causal(),
            "causal_att": _causal_att_raw_adjusting_for_confounder(),
        }
    )
    assert result.contradictions == []


def test_contradiction_is_a_flag_not_a_hard_error_still_produces_output():
    # A contradiction must never look like a crash/error path — the group
    # still carries its normal claims and a valid severity.
    result = orchestrate_insights(
        {
            "confounder": _confounder_raw_agreeing_with_causal(),
            "causal_att": _causal_att_raw_missing_channel_covariate(),
        }
    )
    assert result.silent is False
    group = result.contradictions[0]
    assert group.severity in ("high", "medium", "low")
    assert len(group.claims) >= 2


# ─────────────────────────────────────────────────────────────────────────
# Severity ranking
# ─────────────────────────────────────────────────────────────────────────


def test_top_list_is_ranked_worst_first():
    result = orchestrate_insights(
        {
            "auto_insights": _auto_insights_raw(),  # includes a low-severity duplicates finding
            "drift": _drift_raw(),  # one high-severity drift finding
        }
    )
    assert result.silent is False
    scores = [g.score for g in result.top]
    assert scores == sorted(scores, reverse=True)


def test_contradiction_and_agreement_outrank_a_lone_high_severity_claim():
    result = orchestrate_insights(
        {
            "confounder": _confounder_raw_agreeing_with_causal(),
            "causal_att": _causal_att_raw_missing_channel_covariate(),
            "drift": _drift_raw(),  # a lone high-severity claim, no agreement/contradiction
        }
    )
    assert result.top[0].contradiction is not None


def test_top_list_capped_at_max_top():
    from modules.insight_orchestrator import MAX_TOP

    many_drift_reports = {
        "column_reports": [{"column": f"col_{i}", "type": "numeric", "drift_score": 90.0} for i in range(20)]
    }
    result = orchestrate_insights({"auto_insights": _auto_insights_raw(), "drift": many_drift_reports})
    assert len(result.top) == MAX_TOP
    assert len(result.groups) > MAX_TOP


def test_verifier_claim_agrees_with_auto_insights_on_shared_subject():
    # A flagged Auto Analyst finding about revenue/ad_spend, plus an
    # independent Auto-Insights claim about the same pair, should collapse
    # into one grouped topic — the whole point of routing verifier output
    # through the same subject-based grouping as every other detector.
    result = orchestrate_insights({"auto_insights": _auto_insights_raw(), "verifier": _verifier_raw()})
    assert result.silent is False
    matching = [g for g in result.groups if g.subjects == frozenset({"revenue", "spend"})]
    assert matching, [g.subjects for g in result.groups]
    assert {c.detector for c in matching[0].claims} >= {"auto_insights", "verifier"}


# ─────────────────────────────────────────────────────────────────────────
# Silent / empty-state path
# ─────────────────────────────────────────────────────────────────────────


def test_silent_when_zero_detectors_have_findings():
    result = orchestrate_insights({})
    assert result.silent is True
    assert result.top == []
    assert result.n_detectors_fired == 0


def test_silent_when_only_one_detector_has_findings():
    assert MIN_DETECTORS_FOR_OUTPUT == 2
    result = orchestrate_insights({"auto_insights": _auto_insights_raw()})
    assert result.silent is True
    assert result.top == []
    assert result.n_detectors_fired == 1
    assert result.n_total_claims == len(_auto_insights_raw())


def test_not_silent_once_a_second_detector_contributes():
    result = orchestrate_insights({"auto_insights": _auto_insights_raw(), "drift": _drift_raw()})
    assert result.silent is False
    assert result.n_detectors_fired == 2
    assert len(result.top) > 0


def test_silent_when_all_detectors_present_but_empty():
    result = orchestrate_insights({"auto_insights": [], "confounder": None, "causal_att": {"ok": False}})
    assert result.silent is True


# ─────────────────────────────────────────────────────────────────────────
# Narration — cache/fallback convention
# ─────────────────────────────────────────────────────────────────────────


def test_narrate_orchestration_no_model_returns_error():
    result = orchestrate_insights({"auto_insights": _auto_insights_raw(), "drift": _drift_raw()})
    text, error = narrate_orchestration(None, result)
    assert text == ""
    assert error


def test_narrate_orchestration_silent_result_skips_gemini():
    class _ShouldNotBeCalled:
        def generate_content(self, contents):
            raise AssertionError("Gemini should not be called for a silent orchestration result")

    result = orchestrate_insights({"auto_insights": _auto_insights_raw()})  # only 1 detector -> silent
    text, error = narrate_orchestration(_ShouldNotBeCalled(), result)
    assert error is None
    assert "not enough" in text.lower()


def test_narrate_orchestration_calls_gemini_with_ranked_findings():
    result = orchestrate_insights(
        {
            "confounder": _confounder_raw_agreeing_with_causal(),
            "causal_att": _causal_att_raw_missing_channel_covariate(),
        }
    )

    class _FakeResponse:
        text = "Your spend-revenue relationship looks strong, but double-check the channel confound before acting on it."

    class _FakeModel:
        def generate_content(self, contents):
            assert "check this" in contents.lower() or "channel" in contents.lower()
            return _FakeResponse()

    text, error = narrate_orchestration(_FakeModel(), result)
    assert error is None
    assert "channel" in text.lower()


def test_fingerprint_result_stable_for_same_top_list():
    result = orchestrate_insights({"auto_insights": _auto_insights_raw(), "drift": _drift_raw()})
    fp1 = fingerprint_result(result)
    fp2 = fingerprint_result(result)
    assert fp1 == fp2
    assert fp1 != "empty"


def test_fingerprint_result_empty_for_silent_result():
    result = orchestrate_insights({"auto_insights": _auto_insights_raw()})
    assert fingerprint_result(result) == "empty"


# ─────────────────────────────────────────────────────────────────────────
# Narration fact-check — orchestration_reference_numbers / verify_narration
# ─────────────────────────────────────────────────────────────────────────


def test_orchestration_reference_numbers_empty_for_silent_or_none():
    silent = orchestrate_insights({"auto_insights": _auto_insights_raw()})  # only 1 detector -> silent
    assert orchestration_reference_numbers(silent) == set()
    assert orchestration_reference_numbers(None) == set()


def test_orchestration_reference_numbers_pulls_from_top_headlines():
    from modules.insight_verifier import extract_numbers

    result = orchestrate_insights({"auto_insights": _auto_insights_raw(), "drift": _drift_raw()})
    numbers = orchestration_reference_numbers(result)
    for group in result.top:
        for n in extract_numbers(group.headline):
            assert n in numbers


def test_verify_narration_confirmed_when_a_headline_number_matches():
    result = orchestrate_insights({"auto_insights": _auto_insights_raw(), "drift": _drift_raw()})
    numbers = orchestration_reference_numbers(result)
    assert numbers, "fixture should produce at least one checkable number"
    n = next(iter(numbers))
    narration = f"One finding worth a look cites {n} — take a second pass."
    verification = verify_narration(narration, result)
    assert verification["status"] == "confirmed"


def test_verify_narration_flagged_when_fabricated():
    result = orchestrate_insights({"auto_insights": _auto_insights_raw(), "drift": _drift_raw()})
    narration = "A wild 8675309 appears in these results — extraordinary."
    verification = verify_narration(narration, result)
    assert verification["status"] == "flagged"


def test_verify_narration_unverifiable_when_no_numbers_in_text():
    result = orchestrate_insights({"auto_insights": _auto_insights_raw(), "drift": _drift_raw()})
    verification = verify_narration("Nothing quantitative to report here.", result)
    assert verification["status"] == "unverifiable"


def test_verify_narration_never_raises_on_malformed_result():
    verification = verify_narration("Some text with 42 in it.", "not a result")  # type: ignore[arg-type]
    assert verification["status"] in ("flagged", "unverifiable")
    assert fingerprint_result(None) == "empty"


def test_fingerprint_result_changes_when_top_list_changes():
    result_a = orchestrate_insights({"auto_insights": _auto_insights_raw(), "drift": _drift_raw()})
    result_b = orchestrate_insights(
        {
            "confounder": _confounder_raw_agreeing_with_causal(),
            "causal_att": _causal_att_raw_missing_channel_covariate(),
        }
    )
    assert fingerprint_result(result_a) != fingerprint_result(result_b)


# ─────────────────────────────────────────────────────────────────────────
# Proactive alert — the JARVIS-copilot "surfaces without being asked" slice.
# Atlas should only interrupt for the orchestrator's genuinely unique
# signal (cross-detector agreement or contradiction), never for a lone
# finding a single detector's own panel already shows, and never for the
# baseline two-detector result that fires automatically on every upload
# (auto_insights + confounder_scan) — that's already covered by the
# separate ambient-upload announcement.
# ─────────────────────────────────────────────────────────────────────────


def test_proactive_alert_none_for_none_result():
    assert proactive_alert_text(None, last_alerted_fingerprint=None) is None


def test_proactive_alert_none_when_silent():
    result = orchestrate_insights({})
    assert proactive_alert_text(result, last_alerted_fingerprint=None) is None


def test_proactive_alert_none_at_baseline_two_detectors():
    # auto_insights + drift both fire, same as the automatic upload-time
    # pair (auto_insights + confounder_scan) — not "new" news yet.
    result = orchestrate_insights({"auto_insights": _auto_insights_raw(), "drift": _drift_raw()})
    assert result.n_detectors_fired == 2
    assert proactive_alert_text(result, last_alerted_fingerprint=None) is None


def test_proactive_alert_none_for_lone_high_severity_with_no_agreement_or_contradiction():
    # A third detector fires, but its top finding is a lone claim no other
    # detector corroborates — that's exactly what the panel below already
    # shows, so nothing new to interrupt for.
    result = orchestrate_insights(
        {"auto_insights": _auto_insights_raw(), "drift": _drift_raw(), "anomaly": _anomaly_raw()}
    )
    assert result.n_detectors_fired == 3
    top = result.top[0]
    assert top.agreement is False and top.contradiction is None
    assert proactive_alert_text(result, last_alerted_fingerprint=None) is None


def test_proactive_alert_fires_on_agreement_after_a_third_detector():
    result = orchestrate_insights(
        {
            "auto_insights": _auto_insights_raw(),
            "confounder": _confounder_raw_agreeing_with_causal(),
            "causal_att": _causal_att_raw_adjusting_for_confounder(),
        }
    )
    assert result.n_detectors_fired == 3
    alert = proactive_alert_text(result, last_alerted_fingerprint=None)
    assert alert is not None
    assert "spend" in alert["text"] and "revenue" in alert["text"]
    assert alert["fingerprint"] == fingerprint_result(result)


def test_proactive_alert_fires_on_contradiction_after_a_third_detector():
    result = orchestrate_insights(
        {
            "confounder": _confounder_raw_agreeing_with_causal(),
            "causal_att": _causal_att_raw_missing_channel_covariate(),
            "drift": _drift_raw(),
        }
    )
    assert result.n_detectors_fired == 3
    assert result.top[0].contradiction is not None
    alert = proactive_alert_text(result, last_alerted_fingerprint=None)
    assert alert is not None
    assert "disagree" in alert["text"].lower() or "check" in alert["text"].lower()


def test_proactive_alert_does_not_refire_for_an_already_alerted_fingerprint():
    result = orchestrate_insights(
        {
            "auto_insights": _auto_insights_raw(),
            "confounder": _confounder_raw_agreeing_with_causal(),
            "causal_att": _causal_att_raw_adjusting_for_confounder(),
        }
    )
    fp = fingerprint_result(result)
    assert proactive_alert_text(result, last_alerted_fingerprint=fp) is None


def test_proactive_alert_fires_again_once_the_fingerprint_changes():
    result = orchestrate_insights(
        {
            "auto_insights": _auto_insights_raw(),
            "confounder": _confounder_raw_agreeing_with_causal(),
            "causal_att": _causal_att_raw_adjusting_for_confounder(),
        }
    )
    assert proactive_alert_text(result, last_alerted_fingerprint="some-stale-fingerprint") is not None


# ─────────────────────────────────────────────────────────────────────────
# Proactive alert, tier 2 — a lone high-severity claim from a detector that
# (unlike auto_insights) has no proactive announcement of its own. Today
# that's confounder_detection: it runs silently on every upload alongside
# auto_insights, but only auto_insights' high-severity count drives
# atlas.raise_alert(). A freshly detected Simpson's-paradox-style
# confounder is exactly the kind of finding worth interrupting for, even
# at the two-detector baseline (unlike tier 1, which needs a third
# detector to rule out re-announcing the baseline state).
# ─────────────────────────────────────────────────────────────────────────


def test_tier2_alert_none_for_none_result():
    assert proactive_alert_text_tier2(None, last_alerted_fingerprint=None) is None


def test_tier2_alert_none_when_silent():
    result = orchestrate_insights({})
    assert proactive_alert_text_tier2(result, last_alerted_fingerprint=None) is None


def test_tier2_alert_fires_at_baseline_for_lone_confounder_paradox():
    # Only 2 detectors (the automatic upload-time pair), no third detector
    # needed — unlike tier 1, since nothing else announces this finding.
    result = orchestrate_insights(
        {
            "auto_insights": _auto_insights_raw_medium_only(),
            "confounder": _confounder_raw_lone_high_paradox(),
        }
    )
    assert result.n_detectors_fired == 2
    top = result.top[0]
    assert top.severity == "high" and top.detectors == ["confounder"]
    alert = proactive_alert_text_tier2(result, last_alerted_fingerprint=None)
    assert alert is not None
    assert "tenure" in alert["text"] and "plan_tier" in alert["text"]
    assert alert["fingerprint"] == fingerprint_result(result)


def test_tier2_alert_none_for_lone_high_auto_insights_claim():
    # auto_insights already drives its own ambient alert on upload (see
    # atlas.raise_alert()) — a lone auto_insights claim must not double-speak.
    result = orchestrate_insights({"auto_insights": _auto_insights_raw(), "drift": _drift_raw()})
    top = result.top[0]
    assert top.severity == "high"
    assert proactive_alert_text_tier2(result, last_alerted_fingerprint=None) is None


def test_tier2_alert_none_when_tier1_would_fire_instead():
    # Agreement/contradiction cases are tier 1's job, not tier 2's.
    result = orchestrate_insights(
        {
            "auto_insights": _auto_insights_raw(),
            "confounder": _confounder_raw_agreeing_with_causal(),
            "causal_att": _causal_att_raw_adjusting_for_confounder(),
        }
    )
    assert result.top[0].agreement is True
    assert proactive_alert_text_tier2(result, last_alerted_fingerprint=None) is None


def test_tier2_alert_none_for_lone_medium_severity_confounder_claim():
    attenuated = _confounder_raw_lone_high_paradox()
    attenuated[0]["findings"][0]["verdict"] = "attenuated"
    result = orchestrate_insights({"auto_insights": _auto_insights_raw_medium_only(), "confounder": attenuated})
    assert result.top[0].severity == "medium"
    assert proactive_alert_text_tier2(result, last_alerted_fingerprint=None) is None


def test_tier2_alert_does_not_refire_for_an_already_alerted_fingerprint():
    result = orchestrate_insights(
        {
            "auto_insights": _auto_insights_raw_medium_only(),
            "confounder": _confounder_raw_lone_high_paradox(),
        }
    )
    fp = fingerprint_result(result)
    assert proactive_alert_text_tier2(result, last_alerted_fingerprint=fp) is None


# ─────────────────────────────────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────────────────────────────────


def test_format_top_text_tags_contradiction_and_agreement():
    result = orchestrate_insights(
        {
            "confounder": _confounder_raw_agreeing_with_causal(),
            "causal_att": _causal_att_raw_missing_channel_covariate(),
        }
    )
    text = format_top_text(result.top)
    assert "CHECK THIS" in text


def test_format_top_text_empty():
    assert "No cross-checked findings" in format_top_text([])


def test_severity_icon_covers_known_values():
    assert severity_icon("high") != severity_icon("low")
    assert severity_icon("unknown") == "⚪"
