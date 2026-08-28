"""Tests for modules.ui's insight-card + fact-check-badge rendering helpers.

build_insight_cards_html() and build_verification_caption() are pure string-
building functions factored out of app.py so the same "FINDING NN [badge]"
card markup used by Auto Analyst's "Run Full Analysis" panel (verified since
Run 10) can be reused, unchanged, by the AI Analyst tab's standalone
"Generate Key Insights" button — the second Gemini call site that quotes
numbers straight from the data but, until this run, had no fact-check badge
of its own. Kept side-effect free (no st.markdown call inside) specifically
so this logic is unit-testable without a running Streamlit session.
"""
from __future__ import annotations

from modules.ui import build_insight_cards_html, build_verification_caption

# ─────────────────────────────────────────────────────────────────────────
# build_insight_cards_html — no verification (backward-compatible path)
# ─────────────────────────────────────────────────────────────────────────


def test_no_verification_renders_plain_cards():
    html = build_insight_cards_html(["Revenue is up 12%.", "Churn fell."])
    assert 'FINDING 01' in html
    assert 'FINDING 02' in html
    assert "Revenue is up 12%." in html
    assert "Churn fell." in html
    assert "prism-badge" not in html


def test_empty_findings_returns_empty_string():
    assert build_insight_cards_html([]) == ""


def test_finding_count_matches_card_count():
    findings = [f"Finding number {i}" for i in range(5)]
    html = build_insight_cards_html(findings)
    assert html.count('class="insight-card"') == 5


# ─────────────────────────────────────────────────────────────────────────
# build_insight_cards_html — with verification badges
# ─────────────────────────────────────────────────────────────────────────


def test_confirmed_finding_gets_verified_badge():
    html = build_insight_cards_html(
        ["There are 100 rows."], verification=[{"status": "confirmed", "checked": 1, "matched": 1}]
    )
    assert "verified" in html
    assert "b-pass" in html


def test_flagged_finding_gets_unconfirmed_badge():
    html = build_insight_cards_html(
        ["There are 9999 rows."], verification=[{"status": "flagged", "checked": 1, "matched": 0}]
    )
    assert "unconfirmed" in html
    assert "b-fail" in html


def test_unverifiable_finding_gets_no_badge():
    html = build_insight_cards_html(
        ["Segment A dominates."], verification=[{"status": "unverifiable", "checked": 0, "matched": 0}]
    )
    assert "b-pass" not in html
    assert "b-fail" not in html


def test_verification_shorter_than_findings_does_not_crash():
    # e.g. verification failed for some findings but not others — every
    # finding must still render a card, just without a badge past the end.
    html = build_insight_cards_html(["First.", "Second.", "Third."], verification=[{"status": "confirmed"}])
    assert html.count('class="insight-card"') == 3
    assert "verified" in html


def test_verification_none_is_same_as_omitted():
    with_none = build_insight_cards_html(["A finding."], verification=None)
    without = build_insight_cards_html(["A finding."])
    assert with_none == without


# ─────────────────────────────────────────────────────────────────────────
# build_verification_caption
# ─────────────────────────────────────────────────────────────────────────


def test_caption_none_when_nothing_checked():
    assert build_verification_caption([]) is None
    assert build_verification_caption([{"status": "unverifiable"}]) is None


def test_caption_reports_confirmed_and_flagged_counts():
    verification = [
        {"status": "confirmed"}, {"status": "confirmed"}, {"status": "flagged"}, {"status": "unverifiable"},
    ]
    caption = build_verification_caption(verification)
    assert caption is not None
    assert "2 finding(s)" in caption
    assert "1 with an unconfirmed number" in caption


def test_caption_all_confirmed_has_no_flagged_language():
    caption = build_verification_caption([{"status": "confirmed"}, {"status": "confirmed"}])
    assert caption is not None
    assert "unconfirmed" not in caption
