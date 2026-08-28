"""Tests for Story Mode's and Demo Mode's fact-check-badge integration (Run 16).

`modules.story_mode` narrates `ai_analyst.generate_key_insights()` output two
ways — Story Mode's voice-narrated slide deck and Demo Mode's scripted
walkthrough — making it the fourth and fifth call sites for that function,
alongside Auto Analyst's "Run Full Analysis" (verified since Run 10), the AI
Analyst tab's "Generate Key Insights" (verified since Run 14), and Report
Writer's HTML/PDF export (verified since Run 15). Until this run neither
Story Mode nor Demo Mode ran `insight_verifier` at all, so a plausible-but-
wrong number Gemini invents would be narrated and displayed with no
fact-check of its own — the same coverage gap those three runs closed
elsewhere. `_generate_and_verify_insights()` is the shared, side-effect-free
helper both paths now call, kept free of any `st` call so it's unit-testable
without a running Streamlit session.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from modules import story_mode


class _FakeGenerateContentModel:
    """Matches the fake used across the rest of this test suite
    (see tests/test_gemini_client.py, tests/test_report_writer.py).
    """

    def __init__(self, text):
        self._text = text

    def generate_content(self, contents):
        return _FakeResponse(self._text)


class _FakeResponse:
    def __init__(self, text):
        self.text = text


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "amount": [10, 20, 30, 40, 50] * 6,
            "segment": (["A", "B"] * 15),
        }
    )


def setup_function(_fn):
    # story_mode reads/writes several module-global st.session_state keys —
    # reset them before every test so cases can't leak into each other
    # (same pattern tests/test_atlas.py uses for the same reason).
    st.session_state.key_insights = []
    st.session_state.key_insights_error = None
    st.session_state.key_insights_verification = []


# ─────────────────────────────────────────────────────────────────────────
# _generate_and_verify_insights — the shared helper behind both call sites
# ─────────────────────────────────────────────────────────────────────────


def test_generate_and_verify_insights_flags_a_wrong_number():
    df = _sample_df()
    true_mean = df["amount"].mean()  # 30.0 — a real, checkable number
    text = f"1. Average amount is {true_mean:.1f}.\n2. Average amount is definitely 999999."
    model = _FakeGenerateContentModel(text)
    column_types = {"amount": "numeric", "segment": "categorical"}

    insights, verification, err = story_mode._generate_and_verify_insights(model, df, column_types)

    assert err is None
    assert len(insights) == 2
    assert len(verification) == 2
    statuses = {v["status"] for v in verification}
    assert "confirmed" in statuses
    assert "flagged" in statuses


def test_generate_and_verify_insights_empty_findings_returns_empty_verification():
    df = _sample_df()
    model = _FakeGenerateContentModel("")
    column_types = {"amount": "numeric", "segment": "categorical"}

    insights, verification, err = story_mode._generate_and_verify_insights(model, df, column_types)

    assert insights == []
    assert verification == []


# ─────────────────────────────────────────────────────────────────────────
# _ensure_insights — Story Mode's entry point
# ─────────────────────────────────────────────────────────────────────────


def test_ensure_insights_populates_verification_alongside_insights(monkeypatch):
    df = _sample_df()
    true_mean = df["amount"].mean()
    text = f"1. Average amount is {true_mean:.1f}."
    monkeypatch.setattr(story_mode.ai_analyst, "get_model", lambda: _FakeGenerateContentModel(text))
    st.session_state.working_df = df
    st.session_state.column_types = {"amount": "numeric", "segment": "categorical"}

    story_mode._ensure_insights()

    assert st.session_state.key_insights == [f"Average amount is {true_mean:.1f}."]
    assert len(st.session_state.key_insights_verification) == 1
    assert st.session_state.key_insights_verification[0]["status"] == "confirmed"


def test_ensure_insights_no_model_leaves_verification_empty(monkeypatch):
    monkeypatch.setattr(story_mode.ai_analyst, "get_model", lambda: None)
    st.session_state.working_df = _sample_df()
    st.session_state.column_types = {"amount": "numeric", "segment": "categorical"}

    story_mode._ensure_insights()

    assert st.session_state.key_insights_error
    assert st.session_state.key_insights_verification == []


def test_ensure_insights_skips_regeneration_when_insights_already_present(monkeypatch):
    calls = []
    monkeypatch.setattr(
        story_mode.ai_analyst,
        "get_model",
        lambda: calls.append("called") or _FakeGenerateContentModel("1. Anything."),
    )
    st.session_state.key_insights = ["Already have this one."]
    st.session_state.working_df = _sample_df()
    st.session_state.column_types = {"amount": "numeric", "segment": "categorical"}

    story_mode._ensure_insights()

    assert calls == []  # get_model() never called — no regeneration, no wasted Gemini call
    assert st.session_state.key_insights == ["Already have this one."]
