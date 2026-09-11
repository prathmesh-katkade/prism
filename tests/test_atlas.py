"""Tests for modules.atlas's proactive alert HUD state — the JARVIS-copilot
incremental slice: the orb should light up unprompted when there's a
high-severity Auto-Insight finding, and clear once the user has seen it.

Streamlit's bare-mode `st.session_state` behaves like a real dict outside a
browser session (see modules/ai_analyst.py's rate-limit comment for the same
observation), which is what makes these testable without a live app.
"""
from __future__ import annotations

import streamlit as st

from modules.atlas import classify_intent_fast, clear_alert, raise_alert, set_state


def setup_function(_fn):
    # atlas's session_state keys are module-global singletons across the
    # whole pytest process — reset the ones this test file touches before
    # every test so cases can't leak into each other.
    st.session_state.atlas_orb_state = "idle"
    st.session_state.atlas_alert_count = 0
    st.session_state.atlas_alert_fresh = False


def test_raise_alert_sets_alert_state_and_count():
    raise_alert(3)
    assert st.session_state.atlas_orb_state == "alert"
    assert st.session_state.atlas_alert_count == 3


def test_raise_alert_with_zero_is_a_noop():
    raise_alert(0)
    assert st.session_state.atlas_orb_state == "idle"
    assert st.session_state.atlas_alert_count == 0


def test_raise_alert_with_negative_is_a_noop():
    raise_alert(-1)
    assert st.session_state.atlas_orb_state == "idle"


def test_clear_alert_on_the_same_run_as_raise_alert_is_a_noop():
    # Overview is the default active tab, so its Auto-Insights panel (which
    # calls clear_alert()) can render in the very same script pass as the
    # upload that called raise_alert() — clearing here must not erase an
    # alert the browser hasn't painted yet.
    raise_alert(3)
    clear_alert()
    assert st.session_state.atlas_alert_count == 3
    assert st.session_state.atlas_orb_state == "alert"


def test_clear_alert_actually_clears_on_a_later_run():
    raise_alert(3)
    clear_alert()  # same-run grace period, consumed
    clear_alert()  # a later rerun's Overview render — now it actually clears
    assert st.session_state.atlas_alert_count == 0
    assert st.session_state.atlas_orb_state == "idle"


def test_clear_alert_does_not_clobber_a_non_alert_state():
    raise_alert(2)
    clear_alert()  # consume the same-run grace period
    set_state("speaking")  # something else happened after the alert was raised
    clear_alert()
    # the count still resets (it's been "seen"/superseded), but clear_alert
    # shouldn't stomp on whatever more-recent state the orb is actually in
    assert st.session_state.atlas_alert_count == 0
    assert st.session_state.atlas_orb_state == "speaking"


def test_clear_alert_when_never_raised_is_safe():
    clear_alert()
    assert st.session_state.atlas_alert_count == 0
    assert st.session_state.atlas_orb_state == "idle"


# ═══════════════════════════════════════════════════════════════════════
# classify_intent_fast — zero-Gemini keyword fast path (Run 17)
# ═══════════════════════════════════════════════════════════════════════
def test_fast_path_navigate_matches_exact_tab_name():
    intent = classify_intent_fast("go to Stats Lab")
    assert intent is not None
    assert intent["type"] == "APP_COMMAND"
    assert intent["action"] == "navigate"
    assert intent["target"] == "Stats Lab"


def test_fast_path_navigate_is_case_insensitive_and_trims_punctuation():
    intent = classify_intent_fast("  Open the ML LAB tab.  ")
    assert intent is not None
    assert intent["action"] == "navigate"
    assert intent["target"] == "ML Lab"


def test_fast_path_navigate_show_me_phrasing():
    intent = classify_intent_fast("show me clustering")
    assert intent is not None
    assert intent["action"] == "navigate"
    assert intent["target"] == "Clustering"


def test_fast_path_demo_mode():
    intent = classify_intent_fast("start demo mode")
    assert intent == {
        "type": "APP_COMMAND", "action": "demo_mode", "target": None,
        "question": None, "spoken_reply": intent["spoken_reply"],
    }
    assert intent["spoken_reply"]


def test_fast_path_story_mode():
    intent = classify_intent_fast("start story mode")
    assert intent is not None
    assert intent["action"] == "start_story_mode"


def test_fast_path_next_and_previous():
    assert classify_intent_fast("next")["action"] == "next"
    assert classify_intent_fast("next slide")["action"] == "next"
    assert classify_intent_fast("previous")["action"] == "previous"
    assert classify_intent_fast("go back")["action"] == "previous"


def test_fast_path_cancel_is_always_matched_regardless_of_context():
    # Cancel is safe to fast-path unconditionally: it only ever clears
    # pending state, never executes a destructive action.
    for phrase in ("cancel", "stop", "never mind"):
        intent = classify_intent_fast(phrase)
        assert intent is not None
        assert intent["action"] == "cancel"


def test_fast_path_does_not_match_ambiguous_confirm_words():
    # "yes" / "do it" / "go ahead" / "start" overlap between "confirm" and
    # "execute_plan" per the router's own system prompt (context-dependent
    # on whether Atlas is mid-confirmation or mid-plan-proposal) — must NOT
    # be guessed by the keyword fast path, only classify_intent()'s Gemini
    # call (which sees conversation context) may resolve them.
    for phrase in ("yes", "do it", "go ahead", "confirm", "start", "go"):
        assert classify_intent_fast(phrase) is None


def test_fast_path_returns_none_for_data_questions():
    assert classify_intent_fast("what's the average revenue by region") is None


def test_fast_path_returns_none_for_chitchat():
    assert classify_intent_fast("hello there, how are you") is None


def test_fast_path_returns_none_for_empty_or_whitespace():
    assert classify_intent_fast("") is None
    assert classify_intent_fast("   ") is None
    assert classify_intent_fast(None) is None


def test_fast_path_navigate_unknown_tab_falls_through():
    # "go to" a phrase that isn't one of Prism's real tab names must not
    # be force-matched to the nearest tab — better to let Gemini handle it.
    assert classify_intent_fast("go to the moon") is None
