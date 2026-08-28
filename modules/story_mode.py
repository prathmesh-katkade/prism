"""
Story Mode & Demo Mode — Atlas narrating Prism's findings out loud.

Neither existed before Atlas — both are built fresh here rather than
"upgraded." Story Mode turns the AI Analyst's key insights into a
voice-narrated slide deck; Demo Mode is a scripted, hands-free walkthrough
of the whole pipeline (quality scan -> hell-mode cleaning -> auto-analysis
-> top findings) over a bundled synthetic dataset.

Auto-advance caveat (Story Mode): Streamlit has no built-in channel for a
browser-side "this audio finished playing" event to reach Python without a
full bidirectional custom component, which is out of scope here. The
auto-advance timer below is therefore a best-effort ESTIMATE from word
count, not a true audio-end signal — if it drifts, the Pause button and
manual/voice Next-Previous are the reliable path and always work.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import streamlit as st
import streamlit.components.v1 as components

from modules import ai_analyst, atlas, cleaning, data_engine, insight_verifier, ui, visualization

DEMO_DATASET_PATH = Path(__file__).resolve().parent.parent / "samples" / "indian_startup_funding_messy.csv"

_WORDS_PER_SECOND = 2.3  # rough natural speaking rate, used only to pace demo mode and estimate auto-advance


def _speech_seconds(text: str) -> float:
    words = max(1, len(text.split()))
    return max(1.4, words / _WORDS_PER_SECOND)


def _narrate_and_pace(text: str) -> None:
    """speak() + a real sleep roughly matching how long that took to say,
    so back-to-back narration lines in a scripted sequence (Demo Mode)
    don't overlap each other's audio.
    """
    atlas.set_state("speaking")
    atlas.speak(text)
    time.sleep(_speech_seconds(text))


def _generate_and_verify_insights(model, df, column_types):
    """generate_key_insights() + a modules.insight_verifier fact-check pass
    over the result — the same static, zero-extra-Gemini-call verification
    Run 10 wired into Auto Analyst's "Run Full Analysis" findings, extended
    since to the AI Analyst tab's own "Generate Key Insights" button (Run 14)
    and the Report Writer's HTML/PDF export (Run 15). Story Mode and Demo
    Mode share this one helper rather than each hand-rolling the same two
    calls, and it stays free of any `st.*` call so it's testable without a
    running Streamlit session. Returns (insights, verification, err).
    """
    quality = data_engine.get_data_quality_report(df, column_types)
    _, top_corr = visualization.plot_correlation_heatmap(df)
    insights, err = ai_analyst.generate_key_insights(model, df, quality, column_types, top_corr)
    verification = insight_verifier.verify_findings(df, column_types, insights) if insights else []
    return insights, verification, err


# ═══════════════════════════════════════════════════════════════════════
# STORY MODE — voice-narrated slide deck over the AI Analyst's key insights
# ═══════════════════════════════════════════════════════════════════════
def _ensure_insights() -> None:
    if st.session_state.key_insights:
        return
    model = ai_analyst.get_model()
    if model is None:
        st.session_state.key_insights_error = (
            "I need a Gemini API key configured first — see the AI Analyst tab for setup steps."
        )
        return
    df, column_types = st.session_state.working_df, st.session_state.column_types
    insights, verification, err = _generate_and_verify_insights(model, df, column_types)
    st.session_state.key_insights = insights
    st.session_state.key_insights_error = err
    st.session_state.key_insights_verification = verification


def advance_slide(delta: int) -> None:
    total = len(st.session_state.key_insights)
    if total == 0:
        return
    st.session_state.story_slide_index = max(0, min(total - 1, st.session_state.story_slide_index + delta))


def exit_story_mode() -> None:
    st.session_state.story_mode_active = False


def render_story_mode() -> None:
    st.subheader("Story Mode")
    _ensure_insights()

    if st.session_state.key_insights_error:
        st.error(st.session_state.key_insights_error)
        if st.button("Exit Story Mode"):
            exit_story_mode()
            st.rerun()
        return

    insights = st.session_state.key_insights
    if not insights:
        st.info("No findings to narrate yet.")
        if st.button("Exit Story Mode"):
            exit_story_mode()
            st.rerun()
        return

    idx = st.session_state.story_slide_index
    idx = max(0, min(len(insights) - 1, idx))
    st.session_state.story_slide_index = idx
    current = insights[idx]
    verification = st.session_state.key_insights_verification
    status = verification[idx]["status"] if idx < len(verification) else None
    badge = ui.INSIGHT_VERIFICATION_BADGES.get(status, "") if status else ""

    with st.container(key="atlas_story_slide"):
        label = f"Finding {idx + 1} of {len(insights)}"
        st.markdown(
            f'<div class="insight-number">{label.upper()}{f" {badge}" if badge else ""}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(f"### {current}")

    atlas.set_state("speaking")
    atlas.speak(current)

    nav1, nav2, nav3, nav4 = st.columns(4)
    with nav1:
        if st.button("Previous", disabled=idx == 0, use_container_width=True):
            advance_slide(-1)
            st.rerun()
    with nav2:
        paused = st.session_state.get("story_paused", False)
        if st.button("Resume" if paused else "Pause", use_container_width=True):
            st.session_state.story_paused = not paused
            st.rerun()
    with nav3:
        if st.button("Next", disabled=idx == len(insights) - 1, use_container_width=True):
            advance_slide(1)
            st.rerun()
    with nav4:
        if st.button("Exit Story Mode", use_container_width=True):
            exit_story_mode()
            st.rerun()

    if not st.session_state.get("story_paused", False) and idx < len(insights) - 1:
        # Best-effort auto-advance — see module docstring caveat.
        components.html(
            f"""<script>
            setTimeout(function() {{
                try {{
                    const url = new URL(window.parent.location.href);
                    url.searchParams.set('story_tick', String(Date.now()));
                    window.parent.location.search = url.search;
                }} catch (e) {{}}
            }}, {int(_speech_seconds(current) * 1000) + 900});
            </script>""",
            height=0,
        )
        if st.query_params.get("story_tick"):
            del st.query_params["story_tick"]
            advance_slide(1)
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════
# DEMO MODE — scripted, hands-free walkthrough over a bundled messy dataset
# ═══════════════════════════════════════════════════════════════════════
def render_demo_mode(set_active_dataset: Callable) -> None:
    st.subheader("Demo Mode")
    st.caption("Hands-free — Atlas is driving. Sit back.")

    if not st.session_state.get("demo_done", False):
        if not DEMO_DATASET_PATH.exists():
            st.error(f"Demo dataset not found at {DEMO_DATASET_PATH}.")
            if st.button("Exit Demo"):
                st.session_state.demo_mode_running = False
                st.rerun()
            return

        log = st.empty()
        lines: list[str] = []

        def step(text: str) -> None:
            lines.append(text)
            log.markdown("\n\n".join(f"> {ln}" for ln in lines))
            _narrate_and_pace(text)

        import pandas as pd

        step('Demo mode engaged. Loading the Indian startup funding dataset now.')
        demo_df = pd.read_csv(DEMO_DATASET_PATH)
        set_active_dataset(demo_df, demo_df.copy(), "demo:indian_startup_funding_messy.csv")
        column_types = st.session_state.column_types

        quality = data_engine.get_data_quality_report(demo_df, column_types)
        step(
            f"Quality scan complete. {quality['n_rows']:,} rows, {quality['n_cols']} columns, "
            f"{quality['total_missing_pct']}% missing, {quality['duplicate_rows']} duplicate rows."
        )

        step("Running hell mode cleaning — filling nulls, dropping duplicates, dropping empty columns.")
        working = demo_df
        null_cols = [c for c in working.columns if working[c].isna().sum() > 0]
        for col in null_cols:
            strategy = "fill_median" if column_types.get(col) == "numeric" else "fill_mode"
            working = cleaning.handle_nulls(working, col, strategy)
        working, removed = cleaning.remove_duplicates(working)
        all_null_cols = [c for c, t in data_engine.detect_column_types(working).items() if t == "all_null"]
        if all_null_cols:
            working = cleaning.drop_columns(working, all_null_cols)
        st.session_state.working_df = working
        st.session_state.column_types = data_engine.detect_column_types(working)
        step(f"Cleaning done — {len(null_cols)} column(s) fixed, {removed} duplicate row(s) removed.")

        model = ai_analyst.get_model()
        if model is None:
            step("I'd run auto-analysis here, but no Gemini API key is configured — skipping ahead.")
            insights: list[str] = []
        else:
            step("Running auto-analysis.")
            insights, verification, err = _generate_and_verify_insights(model, working, st.session_state.column_types)
            st.session_state.key_insights = insights
            st.session_state.key_insights_verification = verification
            if err:
                step(f"Analysis hit a snag: {err}")
                insights = []

        for i, finding in enumerate(insights[:3], 1):
            step(f"Finding {i}: {finding}")

        step("That's what I can do.")
        st.session_state.demo_done = True
        st.rerun()

    st.success("Demo complete.")
    if st.session_state.key_insights:
        # Same insight-card + fact-check-badge markup every other
        # generate_key_insights() call site uses (modules.ui, shared since
        # Run 14) — Demo Mode used to hand-roll its own unverified copy.
        caption = ui.build_verification_caption(st.session_state.key_insights_verification)
        if caption:
            st.caption(caption)
        st.markdown(
            ui.build_insight_cards_html(st.session_state.key_insights, st.session_state.key_insights_verification),
            unsafe_allow_html=True,
        )
    if st.button("Exit Demo"):
        st.session_state.demo_mode_running = False
        st.session_state.demo_done = False
        st.rerun()
