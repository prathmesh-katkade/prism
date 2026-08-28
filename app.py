"""
Prism — an Auto-EDA tool with an AI analyst layer.

Entry point: a landing screen (hero, feature cards, sample datasets, session
restore) that collapses into the sidebar (upload + cleaning controls) and six
main tabs (Overview / Clean / Combine / Visualize / SQL Lab / AI Analyst)
once a dataset is active. All the actual logic lives in modules/ — this file
is mostly Streamlit plumbing and state management.

Run with:  streamlit run app.py

Developed by Prathmesh Katkade.
"""

import html
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st

from modules import (
    ai_analyst,
    anomaly,
    atlas,
    auto_analyst,
    autocleaner,
    cleaning,
    clustering,
    dashboard_builder,
    data_dictionary,
    data_engine,
    dataset_knowledge,
    datetime_intel,
    domains,
    drift,
    enrichment,
    forecasting,
    geo,
    hellmode,
    india,
    join_engine,
    mllab,
    pii_detector,
    profiling,
    recipes,
    report,
    report_writer,
    session_io,
    sql_lab,
    stats_lab,
    story_mode,
    theme,
    type_coercion,
    ui,
    visualization,
    voice_input,
)

# --------------------------------------------------------------------------
# Page setup
# --------------------------------------------------------------------------
st.set_page_config(page_title="Prism | Auto-EDA & AI Analyst", page_icon="P", layout="wide")

# --------------------------------------------------------------------------
# Session state — this is Prism's "memory" between reruns. Streamlit reruns
# the whole script on every interaction, so anything that must survive a
# rerun (the loaded data, cleaning history, chat log) lives here.
# --------------------------------------------------------------------------
_DEFAULTS = {
    "raw_df": None,  # the dataset exactly as first loaded (for before/after + reset)
    "working_df": None,  # the dataset after any cleaning steps applied so far
    "column_types": {},  # column -> 'numeric' | 'categorical' | 'datetime' | 'text' | 'all_null'
    "dataset_fingerprint": None,  # {"name", "tips", "match_score"} if the active dataset matches a known-dataset signature
    "cleaning_log": [],  # list of {"description": str, "code": str} — one per applied step
    "chat_history": [],  # AI Analyst chat transcript
    "key_insights": [],  # last "Generate Key Insights" output — list of up to 5 bullet strings
    "key_insights_error": None,  # error from the last "Generate Key Insights" attempt, if any
    "manual_chart_fig": None,  # last chart built via the Visualize tab's manual mode
    "manual_chart_error": None,  # error message from the last manual-chart build attempt, if any
    "last_file_name": None,  # detects a new upload vs. a plain rerun; also used in exports
    "sql_editor": "",  # SQL Lab's query text (bound to the text_area's key)
    "sql_result_df": None,  # last successful query result
    "sql_error": None,  # last query's error message, if any
    "sql_exec_time": None,  # last query's execution time in seconds
    "sql_explanation": "",  # last "Explain this query" output
    "sql_explanation_error": None,  # error from the last "Explain this query" attempt, if any
    "sql_source": "Local dataset",  # SQL Lab source selector — "Local dataset" or "MySQL database"
    "mysql_engine": None,  # live SQLAlchemy Engine for the connected MySQL database, if any
    "mysql_connection_label": None,  # "user@host:port/database" shown once connected — never includes the password
    "mysql_connect_error": None,  # error from the last connection attempt, if any
    "mysql_tables": [],  # table names visible to the connected MySQL user
    "mysql_sql_editor": "",  # MySQL SQL Lab's query text (bound to its text_area's key)
    "mysql_allow_writes": False,  # opt-in checkbox — when False, non-SELECT statements are refused client-side
    "mysql_result_df": None,  # last successful MySQL query result
    "mysql_query_error": None,  # last MySQL query's error message, if any
    "mysql_exec_time": None,  # last MySQL query's execution time in seconds
    "mysql_truncated": False,  # True if the last result was cut off at sql_lab.MYSQL_MAX_ROWS
    "second_df": None,  # second file uploaded in the Combine tab (raw, uncleaned)
    "second_file_name": None,  # detects a new second-file upload vs. a plain rerun
    "combine_preview_df": None,  # last previewed join result
    "combine_stats": None,  # stats dict for the last previewed join
    "last_voice_text": None,  # dedupes repeated speech_to_text() return values across reruns
    "pending_voice_question": None,  # a transcribed question waiting to be fed into the chat pipeline
    "theme_mode": theme.DEFAULT_THEME,  # one of theme.THEMES — sidebar selector
    "onboarding_dismissed": False,  # first-visit step-by-step intro, dismissible once per session
    "undo_stack": [],  # snapshots of {working_df, column_types, cleaning_log} before each mutation, capped at 10
    "anomaly_result_df": None,  # last "Find Anomalies" result
    "anomaly_error": None,  # error from the last anomaly-detection attempt, if any
    "auto_analyst_plan": None,  # last "Run Full Analysis" plan — list of {"title", "question"}
    "auto_analyst_step_outcomes": [],  # per-step results from the last Auto Analyst run
    "auto_analyst_findings": [],  # last Auto Analyst "top 5 findings" synthesis
    "auto_analyst_findings_error": None,  # error from the last findings synthesis, if any
    "stats_lab_result": None,  # last "Run Test" result dict from Stats Lab
    "forecast_result": None,  # last "Generate Forecast" result dict from Forecasting
    "forecast_error": None,  # error from the last forecast attempt, if any
    "cluster_result": None,  # last "Run Clustering" result dict
    "cluster_segment_names": [],  # last "Name Segments with AI" descriptions
    "cluster_segment_error": None,  # error from the last segment-naming attempt, if any
    "drift_result": None,  # last "Run Drift Comparison" report from the Combine tab's Compare mode
    "dashboard_spec": None,  # last "Build My Dashboard" spec (kpis + charts), editable via Remove/Swap
    "auto_report_content": None,  # last "Generate Report" content dict (for PDF/HTML export)
    "recipe_apply_log": [],  # last "Apply Recipe" per-step applied/skipped log
    "pii_findings": {},  # PII Detector's scan of the active dataset — {"email"/"phone"/"name": [...]}
    "jump_to_tab": None,  # tab label to auto-select via JS once, right after tabs render
    "hellmode_date_result": None,  # last "Standardize Dates" preview {"column","parsed","failed","day_first"}
    "hellmode_impute_recs": {},  # last "AI Recommend" imputation strategy suggestions
    "hellmode_impute_recs_error": None,  # error from the last AI-recommend-imputation attempt, if any
    "mllab_result": None,  # last "Run Baseline Models" result dict
    "mllab_error": None,  # error from the last baseline model run, if any
    "mllab_shap_values": None,  # last "Generate SHAP Explanations" result (shap.Explanation), if any
    "mllab_shap_error": None,  # error from the last SHAP attempt, if any
    "enrichment_report": None,  # last "Titan Enrichment" run's {"locations_enriched", ...} report
    "chaos_result": None,  # last "Run Chaos Test" preview: {"chaotic_df", "report", "before_health", "after_health"}
    "data_dictionary_rows": None,  # last-generated Data Dictionary rows (list[dict]), editable via st.data_editor
    "pending_large_upload": None,  # {"df", "filename"} awaiting a Smart Sampling choice before it becomes active
    "sample_info": None,  # persistent banner text when the active dataset is a Smart Sampling sample, else None
    "autocleaner_report": None,  # {"narration", "before_score", "safe_applied", "safe_log"} from the last Auto Clean run
    "autocleaner_review_queue": [],  # pending REVIEW-tier actions awaiting approve/reject
    "autocleaner_snapshot": None,  # {working_df, column_types, cleaning_log} captured right before Auto Clean ran —
                                    # lets "Undo All Auto Clean Changes" restore in one click regardless of how many
                                    # REVIEW actions were approved afterward, independent of the regular undo_stack
    "active_section": "Overview",  # which nav pill is selected — replaces st.tabs() so
                                    # Atlas's "navigate" voice command can actually switch it
    "pending_active_section": None,  # Atlas commands write here, not directly to
                                      # active_section — Streamlit forbids setting a
                                      # widget's key after that widget has already
                                      # rendered this run; applied before segmented_control
                                      # renders on the NEXT run instead. See its
                                      # apply-and-clear site just above segmented_control.
    "atlas_voice_enabled": True,  # sidebar toggle — global mute for all TTS
    "pii_strict_mode": False,  # Indian PII Vault: withhold flagged columns' sample values from every LLM call
    "india_mode": True,  # sidebar toggle — FY labels, Indian number formatting, day-first dates, festival markers
    "atlas_orb_state": "idle",  # "idle" | "listening" | "processing" | "speaking"
    "atlas_pending_confirmation": None,  # {action, target, message, approved} — see atlas.guarded()
    "atlas_greeted": False,  # plays the on-load greeting exactly once per session
    "story_mode_active": False,  # True while the Story Mode overlay is showing (Atlas-narrated)
    "story_slide_index": 0,
    "story_paused": False,
    "demo_mode_running": False,  # True while hands-free Demo Mode is executing
    "demo_done": False,  # True once the scripted Demo Mode walkthrough has finished narrating
}
for key, default_value in _DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default_value

theme.apply_custom_theme(st.session_state.theme_mode)
theme.apply_plotly_theme(st.session_state.theme_mode)

UNDO_STACK_CAP = 10


def push_undo_snapshot() -> None:
    """Capture the current working_df/column_types/cleaning_log so a later
    mutation can be undone. Call this BEFORE applying any cleaning action.
    """
    st.session_state.undo_stack.append(
        {
            "working_df": st.session_state.working_df.copy(),
            "column_types": dict(st.session_state.column_types),
            "cleaning_log": list(st.session_state.cleaning_log),
        }
    )
    if len(st.session_state.undo_stack) > UNDO_STACK_CAP:
        st.session_state.undo_stack.pop(0)


def log_step(description: str, code: str) -> None:
    """Append one entry to the cleaning history (used for display and for
    the "Export as Python Script" button).
    """
    st.session_state.cleaning_log.append({"description": description, "code": code})


def resolve_sheet_choice(uploaded_file, key_prefix: str):
    """For a multi-sheet Excel upload, render a picker and only report "ready"
    once the user confirms a sheet. CSVs and single-sheet workbooks are
    always immediately ready, so the common case has zero extra clicks.

    Returns (sheet_name_or_0, ready).
    """
    sheet_names = data_engine.get_excel_sheet_names(uploaded_file)
    if not sheet_names or len(sheet_names) <= 1:
        return 0, True
    st.info(f"This Excel file has {len(sheet_names)} sheets — pick one to load.")
    chosen = st.selectbox("Sheet", sheet_names, key=f"{key_prefix}_sheet_picker")
    confirmed = st.button("Load Selected Sheet", key=f"{key_prefix}_sheet_confirm", use_container_width=True)
    return chosen, confirmed


def set_active_dataset(raw_df, working_df, source_name, cleaning_log=None, chat_history=None) -> None:
    """Replace the entire active dataset and reset every piece of state tied
    to the previous one. Used by: a fresh sidebar upload, a sample dataset,
    a restored session, and the Combine tab's "Use as Active Dataset".
    """
    st.session_state.raw_df = raw_df
    st.session_state.working_df = working_df
    st.session_state.column_types = data_engine.detect_column_types(working_df)
    st.session_state.pii_findings = pii_detector.scan_dataframe(working_df, st.session_state.column_types)
    st.session_state.dataset_fingerprint = dataset_knowledge.identify_dataset(list(working_df.columns))
    st.session_state.cleaning_log = cleaning_log if cleaning_log is not None else []
    st.session_state.chat_history = chat_history if chat_history is not None else []
    st.session_state.key_insights = []
    st.session_state.key_insights_error = None
    st.session_state.sql_result_df = None
    st.session_state.sql_error = None
    st.session_state.sql_explanation = ""
    st.session_state.sql_explanation_error = None
    st.session_state.second_df = None
    st.session_state.second_file_name = None
    st.session_state.combine_preview_df = None
    st.session_state.combine_stats = None
    st.session_state.manual_chart_fig = None
    st.session_state.manual_chart_error = None
    st.session_state.undo_stack = []
    st.session_state.anomaly_result_df = None
    st.session_state.anomaly_error = None
    st.session_state.auto_analyst_plan = None
    st.session_state.auto_analyst_step_outcomes = []
    st.session_state.auto_analyst_findings = []
    st.session_state.auto_analyst_findings_error = None
    st.session_state.stats_lab_result = None
    st.session_state.forecast_result = None
    st.session_state.forecast_error = None
    st.session_state.cluster_result = None
    st.session_state.cluster_segment_names = []
    st.session_state.cluster_segment_error = None
    st.session_state.drift_result = None
    st.session_state.dashboard_spec = None
    st.session_state.auto_report_content = None
    st.session_state.recipe_apply_log = []
    st.session_state.story_mode_active = False
    st.session_state.story_steps = []
    st.session_state.story_step_index = 0
    st.session_state.hellmode_date_result = None
    st.session_state.hellmode_impute_recs = {}
    st.session_state.hellmode_impute_recs_error = None
    st.session_state.mllab_result = None
    st.session_state.mllab_error = None
    st.session_state.mllab_shap_values = None
    st.session_state.mllab_shap_error = None
    st.session_state.enrichment_report = None
    st.session_state.chaos_result = None
    st.session_state.data_dictionary_rows = None
    st.session_state.sample_info = None
    st.session_state.autocleaner_report = None
    st.session_state.autocleaner_review_queue = []
    st.session_state.autocleaner_snapshot = None
    st.session_state.last_file_name = source_name


# --------------------------------------------------------------------------
# Atlas command registry — the concrete Prism actions the intent router can
# execute. Registered once (idempotently, on every rerun) so atlas.dispatch()
# can look them up by action name after classify_intent() routes an
# utterance here. Every function takes a single `target` argument (may be
# None) and returns nothing — side effects land in st.session_state, same
# as every other mutation in this file.
# --------------------------------------------------------------------------
_NAV_ALIASES = {t.lower(): t for t in atlas.TAB_NAMES}
_SAMPLE_ALIASES = {name.lower(): name for name in ui.SAMPLE_DATASETS}


def _cmd_load_sample(target) -> None:
    if st.session_state.working_df is not None:
        atlas.say_only("You've already got a dataset loaded — say \"reset\" in the sidebar first if you want to swap it.")
        return
    label = _SAMPLE_ALIASES.get(str(target).strip().lower()) if target else None
    label = label or "Sales"
    sample_df = ui.load_sample_dataframe(label)
    set_active_dataset(sample_df, sample_df.copy(), f"sample:{label.lower()}.csv")
    announce_ambient_insights(
        sample_df, data_engine.get_data_quality_report(sample_df, st.session_state.column_types)
    )


def _cmd_navigate(target) -> None:
    if st.session_state.working_df is None:
        atlas.say_only("Upload data first and I'll get to work.")
        return
    if not target:
        atlas.say_only("Which section — Overview, Clean, Combine, Visualize, SQL Lab, or AI Analyst?")
        return
    section = _NAV_ALIASES.get(str(target).strip().lower())
    if not section:
        atlas.say_only(f"I don't have a '{target}' section.")
        return
    st.session_state.pending_active_section = section
    st.session_state.story_mode_active = False


def _cmd_clean_nulls(target) -> None:
    if st.session_state.working_df is None:
        atlas.say_only("Upload data first and I'll get to work.")
        return
    if not atlas.guarded("clean_nulls", target, "This fills or drops missing values across the whole dataset."):
        return
    working = st.session_state.working_df
    null_cols = [c for c in working.columns if working[c].isna().sum() > 0]
    if not null_cols:
        atlas.say_only("No missing values to clean — the dataset's already complete.")
        return
    push_undo_snapshot()
    new_df = working
    for col in null_cols:
        strategy = "fill_median" if st.session_state.column_types.get(col) == "numeric" else "fill_mode"
        new_df = cleaning.handle_nulls(new_df, col, strategy)
        log_step(f"Atlas: applied '{strategy}' to column '{col}'", cleaning.nulls_code(col, strategy))
    st.session_state.working_df = new_df
    st.session_state.column_types = data_engine.detect_column_types(new_df)
    atlas.say_only(f"Done — cleaned {len(null_cols)} column(s) with missing values.")


def _render_result_safely(result) -> None:
    """st.write(result) on a dict/other-container result can crash outright
    — e.g. pandas' internal DataFrame() conversion raises TypeError trying
    to sort a dict's keys when they're a mix of types (a NaN float key
    alongside string category names, which happens for real with something
    as ordinary as a Gemini-generated .value_counts()-style dict on a
    column that has missing values). Sandboxed code producing a result
    shape Streamlit can't render cleanly is exactly the kind of thing this
    boundary needs to survive rather than crash the whole app on.
    """
    try:
        st.write(result)
    except Exception:
        st.code(repr(result))


def _run_full_auto_analysis(model, df_, column_types_, plan: list[dict]) -> tuple[list[dict], list[str], Optional[str]]:
    """Shared step-runner for both the Auto Analyst tab's "Run Full
    Analysis" button and Atlas's "execute_plan" command: run every step in
    `plan` through the safe-execution sandbox (same one AI Analyst chat
    uses), narrating progress via st.status() as it goes, then synthesize
    the results into headline findings.
    """
    step_outcomes: list[dict] = []
    step_history: list[dict] = []

    with st.status(f"Running {len(plan)}-step analysis...", expanded=True) as run_status:
        for i, step in enumerate(plan, 1):
            run_status.write(f"**Step {i}/{len(plan)} — {step['title']}**: running...")
            outcome = auto_analyst.run_plan_step(model, df_, column_types_, step, step_history)
            step_outcomes.append(outcome)
            step_history.append({"role": "user", "content": step["question"]})
            step_history.append(
                {"role": "assistant", "code": outcome.get("code"), "ask_error": outcome.get("ask_error")}
            )
            if outcome.get("ask_error") or outcome.get("error"):
                run_status.write(
                    f"Step {i}/{len(plan)} — {step['title']}: failed "
                    f"({outcome.get('ask_error') or outcome.get('error')})"
                )
            else:
                run_status.write(f"Step {i}/{len(plan)} — {step['title']}: done")
        run_status.update(label="Analysis complete", state="complete", expanded=False)

    with st.spinner(ui.get_loading_message()):
        findings, findings_error = auto_analyst.synthesize_findings(model, step_outcomes)

    return step_outcomes, findings, findings_error


def _cmd_propose_plan(target) -> None:
    """Atlas drafts a multi-step exploration plan for the loaded dataset
    and shows it in the chat panel, then waits for the user to say "go"
    (routed to _cmd_execute_plan) — Gemini calls and sandboxed code
    execution only happen once the plan has actually been approved.
    """
    if st.session_state.working_df is None:
        atlas.say_only("Upload data first and I'll get to work.")
        return
    model = ai_analyst.get_model()
    if model is None:
        atlas.say_only("I need a Gemini API key configured first — see the AI Analyst tab for setup steps.")
        return

    df_, column_types_ = st.session_state.working_df, st.session_state.column_types
    with st.spinner(ui.get_loading_message()):
        plan = auto_analyst.generate_analysis_plan(model, df_, column_types_)
    st.session_state.auto_analyst_plan = plan

    steps_html = "<br>".join(
        f"{i}. <b>{html.escape(step['title'])}</b> &mdash; {html.escape(step['question'])}"
        for i, step in enumerate(plan, 1)
    )
    atlas.say(
        f"Here's my {len(plan)}-step plan for this dataset — say go and I'll run it.",
        chat_html=(
            f"Here's my plan:<br>{steps_html}<br><br>"
            "Say <b>go</b> and I'll run all of it, or tell me what to change first."
        ),
    )


def _cmd_execute_plan(target) -> None:
    """Runs the plan Atlas just proposed — or, if none is queued yet,
    plans and runs in one go — and reports synthesized findings back in
    the chat panel. Shares _run_full_auto_analysis() with the Auto Analyst
    tab's button so voice/typed and click-driven runs behave identically.
    """
    if st.session_state.working_df is None:
        atlas.say_only("Upload data first and I'll get to work.")
        return
    model = ai_analyst.get_model()
    if model is None:
        atlas.say_only("I need a Gemini API key configured first — see the AI Analyst tab for setup steps.")
        return

    df_, column_types_ = st.session_state.working_df, st.session_state.column_types
    plan = st.session_state.get("auto_analyst_plan")
    if not plan:
        with st.spinner(ui.get_loading_message()):
            plan = auto_analyst.generate_analysis_plan(model, df_, column_types_)
        st.session_state.auto_analyst_plan = plan

    step_outcomes, findings, findings_error = _run_full_auto_analysis(model, df_, column_types_, plan)
    st.session_state.auto_analyst_step_outcomes = step_outcomes
    st.session_state.auto_analyst_findings = findings
    st.session_state.auto_analyst_findings_error = findings_error
    st.session_state.pending_active_section = "Auto Analyst"

    if not findings:
        atlas.say_only(
            f"Ran the analysis but couldn't pull out clean findings: {findings_error or 'no findings returned'}."
        )
        return

    findings_html = "<br>".join(f"{i}. {html.escape(f)}" for i, f in enumerate(findings, 1))
    atlas.say(
        f"Done — found {len(findings)} key thing(s) worth knowing.",
        chat_html=f"Done — here's what I found:<br>{findings_html}<br><br>Full detail is in the Auto Analyst tab.",
    )


def _cmd_generate_report(target) -> None:
    if st.session_state.working_df is None:
        atlas.say_only("Upload data first and I'll get to work.")
        return
    st.session_state.pending_active_section = "Visualize"
    atlas.say_only("Your report's ready to download from the Visualize tab's Export Report section.")


def _cmd_build_dashboard(target) -> None:
    _cmd_navigate("Visualize")
    if st.session_state.working_df is not None:
        atlas.say_only("Here's your auto-generated dashboard.")


def _cmd_run_recipe(target) -> None:
    if st.session_state.working_df is None:
        atlas.say_only("Upload data first and I'll get to work.")
        return
    recipe = (target or "standard cleanup").strip().lower()
    if recipe not in ("standard cleanup", "standard", "cleanup", "hell mode", "hell mode cleaning"):
        atlas.say_only("I only know the 'standard cleanup' recipe so far.")
        return
    if not atlas.guarded(
        "run_recipe", target,
        "This runs the standard cleanup recipe: fill missing values, drop duplicate rows, and drop empty columns.",
    ):
        return
    push_undo_snapshot()
    df_ = st.session_state.working_df
    null_cols = [c for c in df_.columns if df_[c].isna().sum() > 0]
    for col in null_cols:
        strategy = "fill_median" if st.session_state.column_types.get(col) == "numeric" else "fill_mode"
        df_ = cleaning.handle_nulls(df_, col, strategy)
    df_, removed = cleaning.remove_duplicates(df_)
    all_null_cols = [c for c, t in data_engine.detect_column_types(df_).items() if t == "all_null"]
    if all_null_cols:
        df_ = cleaning.drop_columns(df_, all_null_cols)
    st.session_state.working_df = df_
    st.session_state.column_types = data_engine.detect_column_types(df_)
    log_step("Atlas: ran the 'standard cleanup' recipe", "# standard cleanup recipe")
    atlas.say_only(f"Recipe complete — {len(null_cols)} column(s) cleaned, {removed} duplicate row(s) removed.")


def _cmd_start_story_mode(target) -> None:
    if st.session_state.working_df is None:
        atlas.say_only("Upload data first and I'll get to work.")
        return
    st.session_state.story_mode_active = True
    st.session_state.story_slide_index = 0


def _cmd_demo_mode(target) -> None:
    st.session_state.demo_mode_running = True
    st.session_state.demo_done = False
    st.session_state.story_mode_active = False


def _cmd_next(target) -> None:
    if st.session_state.story_mode_active:
        story_mode.advance_slide(1)
    else:
        atlas.say_only("There's no story in progress.")


def _cmd_previous(target) -> None:
    if st.session_state.story_mode_active:
        story_mode.advance_slide(-1)
    else:
        atlas.say_only("There's no story in progress.")


def announce_ambient_insights(df, quality: dict) -> None:
    """Item 5 (ambient insights) — after ANY fresh dataset load, Atlas
    proactively summarizes row/column count, the two most important quality
    findings, and one suggested next action, ending with a question. A
    "yes"/"do it" reply then routes through the normal intent router as a
    'confirm' for whichever guarded command that question implies.
    """
    findings = []
    if quality["total_missing_pct"] > 0:
        findings.append(f"{quality['total_missing_pct']}% of cells missing")
    if quality["duplicate_rows"] > 0:
        findings.append(f"{quality['duplicate_rows']} duplicate row(s)")
    if quality["all_null_columns"]:
        findings.append(f"{len(quality['all_null_columns'])} fully empty column(s)")

    if findings:
        summary = (
            f"Loaded {quality['n_rows']:,} rows across {quality['n_cols']} columns. "
            f"I'm seeing {' and '.join(findings[:2])}. Shall I clean these — or say "
            '"plan this" and I\'ll figure out the right steps first.'
        )
    else:
        summary = (
            f"Loaded {quality['n_rows']:,} rows across {quality['n_cols']} columns — "
            'looking clean already. Say "plan this" and I\'ll work out an analysis plan, '
            "or just tell me what you want to know."
        )
    atlas.say_only(summary)


def _run_auto_clean(target=None) -> None:
    """Shared entry point for the Overview tab's "Auto Clean" button and
    Atlas's "auto clean" voice command: scan every Hell Mode detector,
    build a deterministic SAFE/REVIEW plan, auto-apply every SAFE action,
    and stage REVIEW actions for approve/reject cards.

    One snapshot is captured before anything runs (separate from the
    regular undo_stack) so "Undo All Auto Clean Changes" can restore the
    pre-run state in one click regardless of how many REVIEW actions get
    approved afterward across later reruns.
    """
    if st.session_state.working_df is None:
        atlas.say_only("Upload data first and I'll get to work.")
        return

    df_ = st.session_state.working_df
    column_types_ = st.session_state.column_types
    quality_ = data_engine.get_data_quality_report(df_, column_types_)
    before_score = data_engine.get_health_score(quality_, column_types_, st.session_state.pii_findings)

    scan_results = autocleaner.scan(df_, column_types_, quality_)
    plan = autocleaner.build_plan(df_, column_types_, scan_results)
    narration = autocleaner.narrate_plan(ai_analyst.get_model(), plan, before_score)

    st.session_state.autocleaner_snapshot = {
        "working_df": df_.copy(), "column_types": dict(column_types_),
        "cleaning_log": list(st.session_state.cleaning_log),
    }
    push_undo_snapshot()

    new_df, new_types, log_entries, applied = autocleaner.execute_safe_actions(df_, column_types_, plan)
    st.session_state.working_df = new_df
    st.session_state.column_types = new_types
    st.session_state.cleaning_log.extend(log_entries)
    st.session_state.autocleaner_review_queue = [a for a in plan if a["risk"] == "REVIEW"]
    st.session_state.autocleaner_report = {
        "narration": narration, "before_score": before_score,
        "safe_applied": applied, "safe_log": [e["description"] for e in log_entries],
    }
    atlas.say_only(narration)


def _cmd_generate_dictionary(target) -> None:
    if st.session_state.working_df is None:
        atlas.say_only("Upload data first and I'll get to work.")
        return
    df_ = st.session_state.working_df
    column_types_ = st.session_state.column_types
    quality_ = data_engine.get_data_quality_report(df_, column_types_)
    descriptions, _ = data_dictionary.generate_descriptions(ai_analyst.get_model(), df_, column_types_)
    st.session_state.data_dictionary_rows = data_dictionary.build_dictionary(df_, column_types_, quality_, descriptions)
    st.session_state.pending_active_section = "Overview"
    atlas.say_only(f"Documented all {df_.shape[1]} columns — see the Data Dictionary on the Overview tab.")


def _cmd_auto_clean(target) -> None:
    """Atlas voice/typed entry point — guarded, unlike the Overview tab's
    button (a direct click is already an unambiguous action; a spoken
    command gets the same two-phase confirmation as Atlas's other
    data-mutating commands before _run_auto_clean() actually runs).
    """
    if st.session_state.working_df is None:
        atlas.say_only("Upload data first and I'll get to work.")
        return
    if not atlas.guarded(
        "auto_clean", target,
        "This scans your dataset and applies every safe fix automatically — judgment calls will be shown to you for approval.",
    ):
        return
    _run_auto_clean(target)


for _action, _fn in {
    "navigate": _cmd_navigate,
    "load_sample": _cmd_load_sample,
    "clean_nulls": _cmd_clean_nulls,
    "propose_plan": _cmd_propose_plan,
    "execute_plan": _cmd_execute_plan,
    "generate_report": _cmd_generate_report,
    "build_dashboard": _cmd_build_dashboard,
    "run_recipe": _cmd_run_recipe,
    "start_story_mode": _cmd_start_story_mode,
    "demo_mode": _cmd_demo_mode,
    "auto_clean": _cmd_auto_clean,
    "generate_dictionary": _cmd_generate_dictionary,
    "next": _cmd_next,
    "previous": _cmd_previous,
}.items():
    atlas.register_command(_action, _fn)


# --------------------------------------------------------------------------
# Sidebar — grouped into "⚙️ App Preferences" (theme, Atlas voice, India
# Mode, Strict mode) and "📁 Data Sources" (file upload) expanders, then
# "🧹 Data Processing" (cleaning tools) + history below once a dataset is
# active. Sample datasets and session restore stay on the landing screen,
# not in the sidebar — they're the primary first-run call to action before
# any data is loaded, and burying them in a collapsed sidebar expander
# would be a step backward for onboarding, not a cleanup. Rendered on
# every page, including the landing screen.
# --------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<span class="hero-title-animated" style="font-size:1.8rem;">PRISM</span>', unsafe_allow_html=True)
    st.caption("Auto-EDA · AI Analyst")

    with st.expander("⚙️ App Preferences", expanded=False):
        theme_keys = list(theme.THEMES.keys())
        st.selectbox(
            "Theme",
            theme_keys,
            key="theme_mode",
            format_func=lambda k: theme.THEMES[k]["label"],
        )
        st.toggle("Atlas voice", key="atlas_voice_enabled", help="Mute/unmute all spoken replies.")
        st.toggle(
            "🇮🇳 India Mode", key="india_mode",
            help="Fiscal-year (Apr–Mar) labels, Indian number grouping (1,20,000 / ₹1.2L), "
                 "day-first date parsing, and festival markers on time-series charts.",
        )
        st.toggle(
            "🔒 Strict mode", key="pii_strict_mode",
            help="When on, columns flagged by the Indian PII Vault (Aadhaar, PAN, GSTIN, IFSC, "
                 "mobile numbers, emails, names) never have their actual values sent to Gemini — "
                 "the AI Analyst still sees the column exists (schema only), never a real value "
                 "from it. Off by default so the AI Analyst can reason over real examples; turn "
                 "this on for datasets you can't risk sending PII samples for, even briefly.",
        )

    with st.expander("📁 Data Sources", expanded=st.session_state.working_df is None):
        st.caption("Sample datasets and restoring a saved session are on the landing page — shown "
                    "before any dataset is active, so they stay the first thing a new user sees "
                    "rather than a collapsed sidebar item.")
        uploaded_file = st.file_uploader("Upload CSV or Excel", type=["csv", "xlsx", "xls"])

        if (
            uploaded_file is not None
            and uploaded_file.name != st.session_state.last_file_name
            and st.session_state.pending_large_upload is None
        ):
            sheet_choice, sheet_ready = resolve_sheet_choice(uploaded_file, "primary")
            if sheet_ready:
                with st.spinner("Reading and analyzing your data..."):
                    # max_rows=None: read (near-)the full file rather than the usual
                    # first-MAX_ROWS truncation, so a large file can go through the
                    # Smart Sampling picker below instead of always losing "the tail".
                    new_df, load_error, load_warnings = data_engine.load_data(
                        uploaded_file, sheet_name=sheet_choice, max_rows=None
                    )

                if load_error:
                    st.error(load_error)
                elif new_df.shape[0] > data_engine.MAX_ROWS:
                    st.session_state.pending_large_upload = {
                        "df": new_df, "filename": uploaded_file.name, "warnings": load_warnings,
                    }
                else:
                    set_active_dataset(new_df, new_df.copy(), uploaded_file.name)
                    for w in load_warnings:
                        st.warning(w)
                    st.success(f"Loaded {new_df.shape[0]:,} rows x {new_df.shape[1]} columns")
                    announce_ambient_insights(
                        new_df, data_engine.get_data_quality_report(new_df, st.session_state.column_types)
                    )

        # --- Smart Sampling — shown once a large file has been read, until the
        # user picks a sampling method. Kept out of the block above so opening
        # this picker doesn't re-read the (possibly large) file on every rerun.
        if st.session_state.pending_large_upload is not None:
            pending = st.session_state.pending_large_upload
            pending_df = pending["df"]
            st.info(
                f"This file has {pending_df.shape[0]:,} rows — pick how Prism should sample it "
                f"down to {data_engine.MAX_ROWS:,} to stay responsive."
            )
            sample_method = st.radio(
                "Sampling method", ["Random", "Stratified"], key="smart_sample_method", horizontal=True
            )
            strat_col = None
            if sample_method == "Stratified":
                cat_cols = [c for c in pending_df.columns if pending_df[c].nunique() <= 50]
                if cat_cols:
                    strat_col = st.selectbox(
                        "Preserve proportions by", cat_cols, key="smart_sample_strat_col",
                        help="Each category in this column keeps the same share of rows as in the full file.",
                    )
                else:
                    st.caption("No column with 50 or fewer distinct values found — using random sampling instead.")
                    sample_method = "Random"
            if st.button("Use this sample", key="smart_sample_confirm", use_container_width=True):
                sampled_df, explanation = data_engine.sample_dataframe(
                    pending_df, sample_method.lower(), data_engine.MAX_ROWS, strat_col
                )
                set_active_dataset(sampled_df, sampled_df.copy(), pending["filename"])
                for w in pending["warnings"]:
                    st.warning(w)
                st.session_state.sample_info = explanation
                st.session_state.pending_large_upload = None
                st.toast("Sample ready.")
                announce_ambient_insights(
                    sampled_df, data_engine.get_data_quality_report(sampled_df, st.session_state.column_types)
                )
                st.rerun()

    working_df = st.session_state.working_df

    if working_df is not None:
        st.divider()
        st.markdown("### 🧹 Data Processing")
        st.caption("Smart Type Coercion and Datetime Features live below, alongside the rest of the cleaning tools.")

        # --- Missing values -------------------------------------------------
        with st.expander("Handle Missing Values", expanded=False):
            null_cols = [c for c in working_df.columns if working_df[c].isna().sum() > 0]
            if null_cols:
                with st.form("null_form"):
                    selected_cols = st.multiselect("Columns", null_cols, default=null_cols)
                    strategy_label = st.selectbox(
                        "Strategy",
                        ["Drop rows", "Fill with mean", "Fill with median", "Fill with mode", "Fill with custom value"],
                    )
                    custom_value = None
                    if strategy_label == "Fill with custom value":
                        custom_value = st.text_input("Custom value")
                    null_submitted = st.form_submit_button("Apply")

                if null_submitted:
                    strategy_map = {
                        "Drop rows": "drop_rows",
                        "Fill with mean": "fill_mean",
                        "Fill with median": "fill_median",
                        "Fill with mode": "fill_mode",
                        "Fill with custom value": "fill_custom",
                    }
                    strategy = strategy_map[strategy_label]
                    push_undo_snapshot()
                    new_df = working_df
                    apply_errors = []
                    for col in selected_cols:
                        try:
                            new_df = cleaning.handle_nulls(new_df, col, strategy, custom_value)
                            log_step(
                                f"Applied '{strategy_label}' to column '{col}'",
                                cleaning.nulls_code(col, strategy, custom_value),
                            )
                        except Exception as e:
                            apply_errors.append(str(e))
                    st.session_state.working_df = new_df
                    st.session_state.column_types = data_engine.detect_column_types(new_df)
                    for e in apply_errors:
                        st.error(e)
                    if not apply_errors:
                        st.toast("Missing-value strategy applied. 🧼")
            else:
                st.info("No missing values detected.")

        # --- Duplicates & columns --------------------------------------------
        with st.expander("Duplicates & Columns", expanded=False):
            n_dupes = int(working_df.duplicated().sum())
            st.write(f"Duplicate rows: **{n_dupes}**")
            if st.button("Remove Duplicate Rows", disabled=n_dupes == 0, use_container_width=True):
                push_undo_snapshot()
                new_df, removed = cleaning.remove_duplicates(working_df)
                st.session_state.working_df = new_df
                log_step(f"Removed {removed} duplicate row(s)", cleaning.duplicates_code())
                st.toast(f"Removed {removed} duplicate row(s). 🗑️")

            all_null_cols = [c for c, t in st.session_state.column_types.items() if t == "all_null"]
            drop_choices = st.multiselect("Drop columns", working_df.columns.tolist(), default=all_null_cols)
            if st.button("Drop Selected Columns", disabled=not drop_choices, use_container_width=True):
                push_undo_snapshot()
                new_df = cleaning.drop_columns(working_df, drop_choices)
                st.session_state.working_df = new_df
                st.session_state.column_types = data_engine.detect_column_types(new_df)
                log_step(f"Dropped column(s): {', '.join(drop_choices)}", cleaning.drop_columns_code(drop_choices))
                st.toast("Column(s) dropped. 🗑️")

        # --- Dtype fixes -------------------------------------------------------
        with st.expander("Fix Column Types", expanded=False):
            with st.form("dtype_form"):
                dtype_col = st.selectbox("Column", working_df.columns.tolist())
                target_type = st.selectbox("Convert to", ["numeric", "datetime", "text", "category"])
                dtype_submitted = st.form_submit_button("Convert")

            if dtype_submitted:
                new_df, dtype_error = cleaning.convert_dtype(working_df, dtype_col, target_type)
                if dtype_error:
                    st.error(dtype_error)
                else:
                    push_undo_snapshot()
                    st.session_state.working_df = new_df
                    st.session_state.column_types = data_engine.detect_column_types(new_df)
                    log_step(f"Converted '{dtype_col}' to {target_type}", cleaning.dtype_code(dtype_col, target_type))
                    st.toast(f"Converted '{dtype_col}' to {target_type}. 🔄")

        # --- Datetime feature extraction + gap detection -----------------------
        datetime_cols = [c for c, t in st.session_state.column_types.items() if t == "datetime"]
        if datetime_cols:
            with st.expander("Datetime Features", expanded=False):
                dt_col = st.selectbox("Column", datetime_cols, key="dt_feature_col")
                if st.button("Extract Year / Month / Day / Weekday / Quarter", use_container_width=True):
                    push_undo_snapshot()
                    new_df, added_cols = datetime_intel.extract_datetime_features(working_df, dt_col)
                    st.session_state.working_df = new_df
                    st.session_state.column_types = data_engine.detect_column_types(new_df)
                    log_step(
                        f"Extracted datetime features from '{dt_col}'", cleaning.datetime_features_code(dt_col)
                    )
                    st.toast(f"Added {len(added_cols)} new column(s) from '{dt_col}'. ➕")

                if st.session_state.india_mode:
                    if st.button(
                        "Add Fiscal Year / Quarter (Apr–Mar)", use_container_width=True,
                        help='Adds "<column>_fiscal_year" (e.g. "FY2025-26") and "<column>_fiscal_quarter" columns.',
                    ):
                        push_undo_snapshot()
                        new_df = india.add_fiscal_columns(working_df, dt_col)
                        st.session_state.working_df = new_df
                        st.session_state.column_types = data_engine.detect_column_types(new_df)
                        log_step(f"Added fiscal year/quarter from '{dt_col}'", india.fiscal_columns_code(dt_col))
                        st.toast(f"Added fiscal year/quarter columns from '{dt_col}'. 🇮🇳")

                gaps = datetime_intel.detect_gaps(working_df, dt_col)
                if gaps:
                    st.markdown("**Detected gaps** (assuming daily frequency)")
                    for gap in gaps[:5]:
                        st.caption(f"{gap['days_missing']} days missing between {gap['start']} and {gap['end']}")
                    if len(gaps) > 5:
                        st.caption(f"...and {len(gaps) - 5} more gap(s).")
                else:
                    st.caption("No gaps detected.")

        # --- Smart type coercion ------------------------------------------------
        coercion_candidates = type_coercion.detect_numeric_candidates(working_df, st.session_state.column_types)
        if coercion_candidates:
            with st.expander("Smart Type Coercion", expanded=False):
                for cand in coercion_candidates:
                    st.markdown(f"**{cand['column']}** — {cand['match_pct']}% look numeric")
                    _, preview_series = type_coercion.convert_column(working_df, cand["column"])
                    st.caption(f"Before: {', '.join(cand['sample_before'])}")
                    st.caption(f"After:  {', '.join(str(round(v, 2)) for v in preview_series.head(5))}")
                    if st.button(
                        f"Convert '{cand['column']}' to numeric",
                        key=f"coerce_{cand['column']}",
                        use_container_width=True,
                    ):
                        push_undo_snapshot()
                        converted_df, _ = type_coercion.convert_column(working_df, cand["column"])
                        st.session_state.working_df = converted_df
                        st.session_state.column_types = data_engine.detect_column_types(converted_df)
                        log_step(
                            f"Converted '{cand['column']}' from formatted text to numeric",
                            cleaning.type_coercion_code(cand["column"]),
                        )
                        st.toast(f"Converted '{cand['column']}' to numeric. 🔢")

        if st.button("Reset to Original Data", use_container_width=True):
            push_undo_snapshot()
            st.session_state.working_df = st.session_state.raw_df.copy()
            st.session_state.column_types = data_engine.detect_column_types(st.session_state.raw_df)
            st.toast("Reset to original uploaded data. ⏮️")

        # --- Cleaning history, undo, export --------------------------------------
        st.divider()
        st.markdown("### 📜 Cleaning History")
        if st.session_state.cleaning_log:
            for i, step in enumerate(st.session_state.cleaning_log, 1):
                st.caption(f"{i}. {step['description']}")
        else:
            st.caption("No cleaning steps yet.")

        hc1, hc2 = st.columns(2)
        with hc1:
            if st.button("Undo", disabled=not st.session_state.undo_stack, use_container_width=True):
                snapshot = st.session_state.undo_stack.pop()
                st.session_state.working_df = snapshot["working_df"]
                st.session_state.column_types = snapshot["column_types"]
                st.session_state.cleaning_log = snapshot["cleaning_log"]
                st.toast("Reverted the last step. ↩️")
        with hc2:
            script_text = cleaning.export_script(st.session_state.cleaning_log, st.session_state.last_file_name)
            st.download_button(
                "Export .py",
                data=script_text.encode("utf-8"),
                file_name="prism_cleaning_script.py",
                mime="text/x-python",
                use_container_width=True,
                disabled=not st.session_state.cleaning_log,
            )

        # --- Cleaning recipes: save the history above as a named, reusable JSON
        # recipe, or apply a previously saved one to this dataset. ------------------
        st.divider()
        with st.expander("🧪 Cleaning Recipes", expanded=False):
            recipe_name_input = st.text_input("Recipe name", value="my_cleaning_recipe", key="recipe_name_input")
            recipe_json_text = recipes.save_recipe(recipe_name_input, st.session_state.cleaning_log)
            st.download_button(
                "Save Recipe",
                data=recipe_json_text.encode("utf-8"),
                file_name=f"{recipe_name_input or 'prism_recipe'}.json",
                mime="application/json",
                use_container_width=True,
                disabled=not st.session_state.cleaning_log,
            )

            recipe_file = st.file_uploader("Apply a recipe to this dataset", type=["json"], key="recipe_uploader")
            if recipe_file is not None:
                loaded_recipe, recipe_load_error = recipes.load_recipe(recipe_file.getvalue())
                if recipe_load_error:
                    st.error(recipe_load_error)
                elif st.button("Apply Recipe", use_container_width=True, key="apply_recipe_btn"):
                    push_undo_snapshot()
                    recipe_result_df, recipe_step_log = recipes.apply_recipe(working_df, loaded_recipe)
                    st.session_state.working_df = recipe_result_df
                    st.session_state.column_types = data_engine.detect_column_types(recipe_result_df)
                    st.session_state.recipe_apply_log = recipe_step_log
                    log_step(
                        f"Applied recipe '{loaded_recipe.get('name', 'unnamed')}'",
                        f"# Applied recipe: {loaded_recipe.get('name', 'unnamed')}",
                    )
                    st.toast(f"Applied recipe '{loaded_recipe.get('name', 'unnamed')}'. 🧪")

            if st.session_state.recipe_apply_log:
                st.markdown("**Recipe apply log**")
                for log_entry in st.session_state.recipe_apply_log:
                    status_label = "Applied" if log_entry["status"] == "applied" else "Skipped"
                    st.caption(f"**{status_label}** — {log_entry['description']}: {log_entry['detail']}")

        # --- Session save ---------------------------------------------------------
        st.divider()
        st.markdown("### 💾 Session")
        session_json = session_io.save_session(
            st.session_state.raw_df, st.session_state.working_df,
            st.session_state.cleaning_log, st.session_state.chat_history,
        )
        st.download_button(
            "Save Session",
            data=session_json.encode("utf-8"),
            file_name="prism_session.json",
            mime="application/json",
            use_container_width=True,
        )

        st.divider()
        st.markdown("### 🤖 AI Analyst")
        if ai_analyst.get_api_key():
            st.caption(f"Gemini ({ai_analyst.MODEL_NAME}) — API key detected.")
        else:
            st.caption("No GEMINI_API_KEY found. See the AI Analyst tab for setup steps.")


# --------------------------------------------------------------------------
# Atlas — persistent voice/typed command bar + orb, present on every screen
# (landing included, so "load sample data" works before any dataset exists).
# Every utterance (voice or typed) goes through the same
# atlas.handle_utterance() -> classify_intent() router; APP_COMMAND and
# CHITCHAT are fully handled inside atlas.py via the command registry above,
# DATA_QUESTION is handed back here so it can run through the existing,
# already-tested ai_analyst.ask_and_execute() pipeline — the same one typed
# questions used before Atlas existed, now shared by both input paths so
# follow-ups ("now by month") work identically regardless of how the
# previous turn arrived.
#
# Processing is deliberately NOT done here, immediately after capture — see
# _process_atlas_utterance() below and its two call sites. Streamlit drops a
# keyed widget's persisted session_state value if that widget isn't
# instantiated during a script run; calling st.rerun() here, before
# st.segmented_control("Navigate", ..., key="active_section") ever runs on
# the tabbed page, would skip that widget for this pass and silently reset
# the active section back to "Overview" on the next one. Confirmed by
# isolated repro before landing on this structure — not a hypothetical.
# --------------------------------------------------------------------------
atlas.render_pending_confirmation_ui()
# The floating orb is a standalone indicator for contexts with no Atlas
# side panel: the landing page (no dataset yet), and Story/Demo Mode
# (which take over the full screen and skip the side panel — see its own
# skip condition below). Once a real dataset is active outside those
# modes, the side panel renders its own small orb in its header — showing
# both was a real bug: the floating orb sat on top of the side panel,
# overlapping the "Ask by voice" button and the chat input. Mirrors the
# side panel's own condition exactly, inverted.
if st.session_state.working_df is None or st.session_state.demo_mode_running or st.session_state.story_mode_active:
    atlas.render_orb()

if not st.session_state.atlas_greeted and st.session_state.working_df is None:
    st.session_state.atlas_greeted = True
    atlas.say_only('Systems online. Upload a dataset or say "load sample data" to begin.')

_atlas_utterance = None
with st.container(key="atlas_command_bar"):
    mic_col, hint_col = st.columns([1, 4])
    with mic_col:
        if voice_input.is_available():
            voice_text = voice_input.record_question(key="atlas_global_mic")
            if voice_text and voice_text != st.session_state.last_voice_text:
                st.session_state.last_voice_text = voice_text
                atlas.set_state("listening")
                _atlas_utterance = voice_text
        else:
            st.caption("Voice input unavailable — mic permission denied or package missing. Type a command below.")
    with hint_col:
        if st.session_state.get("atlas_last_heard"):
            st.caption(f'Atlas heard: "{st.session_state.atlas_last_heard}"')

typed_command = st.chat_input('Ask Atlas anything, or type a command — e.g. "clean the nulls"')
if typed_command:
    _atlas_utterance = typed_command


def _process_atlas_utterance(utterance: Optional[str]) -> None:
    """Route `utterance` through the intent router and always end in
    st.rerun(). Call this only from a point where every keyed widget for
    this page has already been instantiated this run — see the module-level
    comment above for why.
    """
    if not utterance:
        return
    st.session_state.atlas_last_heard = utterance
    intent = atlas.handle_utterance(utterance)

    if intent["type"] == "DATA_QUESTION":
        if st.session_state.working_df is None:
            atlas.say_only("Upload data first and I'll get to work.")
        else:
            data_model = ai_analyst.get_model()
            if data_model is None:
                atlas.say_only("I need a Gemini API key configured first — see the AI Analyst tab for setup steps.")
            else:
                question = intent.get("question") or utterance
                with st.spinner("Thinking..."):
                    outcome = ai_analyst.ask_and_execute(
                        data_model, st.session_state.working_df, st.session_state.column_types,
                        question, st.session_state.chat_history[:-1],
                        st.session_state.pii_findings, st.session_state.pii_strict_mode,
                        st.session_state.dataset_fingerprint,
                    )
                chart_fig = None
                if not outcome["ask_error"] and not outcome["error"] and ai_analyst.question_implies_chart(question):
                    chart_fig = ai_analyst.build_chart_from_result(outcome["result"], question)
                st.session_state.chat_history.append(
                    {
                        "role": "assistant", "question": question, "code": outcome["code"],
                        "result": outcome["result"], "error": outcome["error"], "ask_error": outcome["ask_error"],
                        "retried": outcome.get("retried", False), "original_error": outcome.get("original_error"),
                        "chart_fig": chart_fig,
                    }
                )
                atlas.set_state("speaking")
                if outcome.get("ask_error") or outcome.get("error"):
                    atlas.speak(outcome.get("ask_error") or outcome.get("error"))
                else:
                    atlas.speak("Here's what I found — check the AI Analyst tab.")
        st.session_state.pending_active_section = "AI Analyst"
    st.rerun()


# --------------------------------------------------------------------------
# Main area
# --------------------------------------------------------------------------
# Deliberately no plain st.title("Prism") here — confirmed via screenshot
# that it was pure redundant chrome: the sidebar already carries a
# persistent "PRISM" brand mark on every screen, the landing page's own
# hero (below) has a much better-designed title, and the tabbed app's
# sticky header (dataset name/health) is what's actually useful once a
# dataset is active. A plain, unstyled duplicate of the brand name at the
# very top of every single page added visual noise without adding
# information.

if st.session_state.working_df is None:
    # ---------------------------------------------------------------------
    # Landing screen — shown before any dataset is active.
    # ---------------------------------------------------------------------
    ui.render_hero()
    ui.render_workflow_strip()
    ui.render_feature_cards()
    st.divider()

    _, palette_matched_tab = ui.render_command_palette()

    st.divider()
    chosen_sample = ui.render_sample_buttons()
    if chosen_sample:
        sample_df = ui.load_sample_dataframe(chosen_sample)
        set_active_dataset(sample_df, sample_df.copy(), f"sample:{chosen_sample.lower()}.csv")
        if palette_matched_tab:
            st.session_state.jump_to_tab = palette_matched_tab
        st.toast(f"Loaded the {chosen_sample} sample dataset. 🎉")
        announce_ambient_insights(
            sample_df, data_engine.get_data_quality_report(sample_df, st.session_state.column_types)
        )
        st.rerun()

    st.divider()
    session_file = ui.render_load_session_widget()
    if session_file is not None:
        bundle, session_load_error = session_io.load_session(session_file.getvalue())
        if session_load_error:
            st.error(session_load_error)
        else:
            set_active_dataset(
                bundle["raw_df"], bundle["working_df"], "restored_session.csv",
                cleaning_log=bundle["cleaning_log"], chat_history=bundle["chat_history"],
            )
            st.toast("Session restored. 📂")
            st.rerun()

    ui.render_footer()
    # Safe to process here: the landing page has no keyed nav widget for an
    # early st.rerun() to skip (see the long comment above the Atlas command
    # bar). Once a dataset loads, this branch is never reached again.
    _process_atlas_utterance(_atlas_utterance)
    st.stop()

# ---------------------------------------------------------------------------
# Tabbed app — reached once a dataset is active.
# ---------------------------------------------------------------------------
ui.render_onboarding()

df = st.session_state.working_df
column_types = st.session_state.column_types

_TAB_ICONS = {
    "Overview": "📊", "Clean": "🧹", "Hell Mode": "🔥", "Combine": "🔗", "Visualize": "📈", "SQL Lab": "🗄️",
    "AI Analyst": "💬", "Auto Analyst": "🤖", "Stats Lab": "🧪", "Forecasting": "🔮", "Clustering": "🧩",
    "Domain Lens": "🔬", "Geo Lens": "🗺️", "ML Lab": "🧬",
}

has_datetime_col = "datetime" in column_types.values()

_nav_options = [
    "Overview", "Clean", "Hell Mode", "Combine", "Visualize", "SQL Lab", "AI Analyst", "Auto Analyst", "Stats Lab",
]
if has_datetime_col:
    _nav_options.append("Forecasting")
_nav_options.append("Clustering")
_nav_options.append("Domain Lens")
_nav_options.append("Geo Lens")
_nav_options.append("ML Lab")

if st.session_state.active_section not in _nav_options:
    st.session_state.active_section = "Overview"

if st.session_state.jump_to_tab:
    if st.session_state.jump_to_tab in _nav_options:
        st.session_state.active_section = st.session_state.jump_to_tab
        st.session_state.pop("nav_primary_pills", None)  # force the pills to re-derive from `default` below
    st.session_state.jump_to_tab = None

if st.session_state.pending_active_section:
    if st.session_state.pending_active_section in _nav_options:
        st.session_state.active_section = st.session_state.pending_active_section
        st.session_state.pop("nav_primary_pills", None)
    st.session_state.pending_active_section = None

quality_for_header = data_engine.get_data_quality_report(df, column_types)
ui.render_sticky_header(
    st.session_state.last_file_name or "Untitled dataset",
    quality_for_header["n_rows"],
    quality_for_header["n_cols"],
    data_engine.get_health_score(quality_for_header, column_types, st.session_state.pii_findings),
    quality_for_header.get("memory_usage", ""),
)

if st.session_state.sample_info:
    st.caption(f"🔬 {st.session_state.sample_info}")

if st.session_state.dataset_fingerprint:
    _fp = st.session_state.dataset_fingerprint
    with st.expander(f"🔎 This looks like **{_fp['name']}** — known quirks worth knowing", expanded=False):
        for _tip in _fp["tips"]:
            st.markdown(f"- {_tip}")
        st.caption("Ask Atlas about these too — it already knows.")

if st.session_state.demo_mode_running:
    story_mode.render_demo_mode(set_active_dataset)
elif st.session_state.story_mode_active:
    story_mode.render_story_mode()
else:
    # A controllable nav — not st.tabs(), which has no API to switch the
    # active tab from Python. Driven by st.session_state.active_section so
    # Atlas's "navigate" command (_cmd_navigate, above) can actually change
    # it: set st.session_state.active_section then st.rerun(), and this
    # widget picks the new value up on the next render. Using elif below
    # (instead of tabs' render-everything-then-hide-with-CSS model) also
    # means only the active section's code runs each rerun, not all
    # thirteen-plus. Also replaces the old ui.render_tab_jump_script() JS
    # hack — this widget is a real Python-side control, so "jump to this
    # tab" is just an assignment to st.session_state.active_section, above.
    #
    # Progressive disclosure: with 13-14 destinations, a single segmented_
    # control wraps into a dense multi-row block on first paint — every
    # destination competing for attention regardless of how often it's
    # actually used. Split into a primary set (the four things almost every
    # session touches) plus an "Advanced Tools" popover for the rest, which
    # stay one click away rather than gone — Atlas voice navigation and
    # jump_to_tab reach every tab in _nav_options either way, only the
    # *default visible* set is curated.
    _PRIMARY_NAV = ["Overview", "Clean", "Visualize", "AI Analyst"]
    _ADVANCED_NAV = [t for t in _nav_options if t not in _PRIMARY_NAV]

    nav_col, more_col = st.columns([5, 1.4])
    with nav_col:
        primary_pick = st.segmented_control(
            "Navigate", _PRIMARY_NAV,
            default=st.session_state.active_section if st.session_state.active_section in _PRIMARY_NAV else None,
            key="nav_primary_pills",
            format_func=lambda name: f"{_TAB_ICONS.get(name, '')} {name}".strip(),
        )
    with more_col:
        advanced_active = st.session_state.active_section in _ADVANCED_NAV
        with st.popover(
            f"{'▸ ' if advanced_active else ''}⋯ Advanced Tools{' — ' + st.session_state.active_section if advanced_active else ''}",
            use_container_width=True,
        ):
            st.caption("Combine, SQL Lab, and the analysis labs — one click away, not gone.")
            for _tab in _ADVANCED_NAV:
                if st.button(
                    f"{_TAB_ICONS.get(_tab, '')}  {_tab}", key=f"nav_adv_{_tab}", use_container_width=True,
                    type="primary" if _tab == st.session_state.active_section else "secondary",
                ):
                    st.session_state.active_section = _tab
                    st.session_state.pop("nav_primary_pills", None)
                    st.rerun()

    if primary_pick is not None and primary_pick != st.session_state.active_section:
        st.session_state.active_section = primary_pick
        st.rerun()

# --------------------------------------------------------------------------
# Atlas side panel — a persistent, always-visible copilot column (Sprint 2
# of the HUD redesign) fixed to the right edge via CSS on the container's
# .st-key-atlas_side_panel class (modules/theme.py) — same technique
# atlas.py already uses for its confirm box, so no custom component is
# needed for a "real" side-by-side column. Skipped during Story/Demo Mode,
# which already take over the full screen. Rendered here (after
# segmented_control, before _process_atlas_utterance below) so any new
# utterance this panel captures is still safe to act on this run — see the
# long ordering comment above the original command bar.
# --------------------------------------------------------------------------
if not st.session_state.demo_mode_running and not st.session_state.story_mode_active:
    with st.container(key="atlas_side_panel"):
        st.markdown(
            f'<div class="atlas-panel-hd">'
            f'<div class="atlas-orb-sm atlas-orb {st.session_state.get("atlas_orb_state", "idle")}"></div>'
            f'<div><div class="t hud">Atlas</div>'
            f'<div class="s mono">ONLINE &middot; {atlas.MODEL_NAME}</div></div></div>',
            unsafe_allow_html=True,
        )
        for msg in st.session_state.chat_history[-10:]:
            if msg["role"] == "user":
                st.markdown(
                    f'<div class="atlas-msg u"><div class="who">You</div>{msg.get("content", "")}</div>',
                    unsafe_allow_html=True,
                )
            else:
                if msg.get("atlas_note"):
                    text = msg["atlas_note"]
                elif msg.get("ask_error") or msg.get("error"):
                    text = msg.get("ask_error") or msg.get("error")
                else:
                    text = f'Answered &mdash; see {msg.get("question", "the result")} in AI Analyst.'
                st.markdown(f'<div class="atlas-msg a"><div class="who">Atlas</div>{text}</div>', unsafe_allow_html=True)
        if not st.session_state.chat_history:
            st.caption("Ask a question or try a quick action below.")

        if st.session_state.auto_analyst_plan and not st.session_state.auto_analyst_step_outcomes:
            if st.button("▶ Run this plan", key="atlas_run_plan_btn", type="primary", use_container_width=True):
                st.session_state.chat_history.append({"role": "user", "content": "Run this plan"})
                _cmd_execute_plan(None)
                st.rerun()

        chip_row = st.columns(2)
        chip_labels = ["Plan this dataset", "Summarize dataset", "Find anomalies", "Suggest cleaning", "Explain this chart"]
        for i, label in enumerate(chip_labels):
            if chip_row[i % 2].button(label, key=f"atlas_chip_{i}", use_container_width=True):
                _atlas_utterance = label

        if voice_input.is_available():
            voice_text = voice_input.record_question(key="atlas_panel_mic")
            if voice_text and voice_text != st.session_state.last_voice_text:
                st.session_state.last_voice_text = voice_text
                atlas.set_state("listening")
                _atlas_utterance = voice_text
        else:
            st.caption("Voice unavailable — type below instead.")

        with st.form(key="atlas_panel_form", clear_on_submit=True, border=False):
            panel_text = st.text_input(
                "Message Atlas", placeholder="Ask Atlas about your data…", label_visibility="collapsed",
                key="atlas_panel_text",
            )
            sent = st.form_submit_button("Send", use_container_width=True)
        if sent and panel_text:
            _atlas_utterance = panel_text

    st.markdown(
        '<style>.block-container{padding-right:352px !important;}</style>', unsafe_allow_html=True
    )

# Every keyed widget for whichever branch above just ran (segmented_control,
# the Atlas side panel, or Story/Demo Mode's own internal buttons) has now
# been instantiated this pass, so it's finally safe to let an utterance's
# handling call st.rerun().
_process_atlas_utterance(_atlas_utterance)

# --------------------------------------------------------------------------
# Overview tab — data quality report, column health, drill-down, anomalies
# --------------------------------------------------------------------------
if st.session_state.demo_mode_running or st.session_state.story_mode_active:
    pass
elif st.session_state.active_section == "Overview":
    ui.render_help_expander(
        "A full data-quality audit: missing values, outliers, column types, and summary "
        "stats — plus per-column health, a drill-down, and anomaly detection below."
    )

    quality = data_engine.get_data_quality_report(df, column_types)
    health_breakdown = data_engine.get_health_breakdown(quality, column_types, st.session_state.pii_findings)
    health_score = health_breakdown["total"]
    total_outliers = sum(v["count"] for v in quality["outliers"].values()) if quality["outliers"] else 0

    m0, m1, m2, m3, m4 = st.columns(5)
    with m0:
        ui.render_health_ring(health_score)
    m1.metric("Rows", f"{quality['n_rows']:,}")
    m2.metric("Missing", f"{quality['total_missing_pct']}%")
    m3.metric("Duplicates", quality["duplicate_rows"])
    m4.metric("Outliers", f"{total_outliers:,}")

    with st.expander("How is this score calculated?", expanded=False):
        for component, weight in data_engine.HEALTH_COMPONENT_WEIGHTS.items():
            st.caption(f"**{component.replace('_', ' ').title()}** — {health_breakdown[component]} / {weight}")
        st.progress(health_score / 100, text=f"Total: {health_score} / 100")

    # ------------------------------------------------------------------
    # Auto Cleaner — v5's flagship: scan -> plan -> auto-apply SAFE fixes
    # -> approve/reject REVIEW cards -> a before/after report. See
    # modules/autocleaner.py for the scan/plan/execute pipeline and
    # _run_auto_clean() above for how this wires into undo + Atlas voice.
    # ------------------------------------------------------------------
    if st.button("🧹 Auto Clean", type="primary", use_container_width=True, help="Scan and fix in one click"):
        with st.spinner("Atlas is scanning your dataset…"):
            _run_auto_clean()
        st.rerun()

    if st.session_state.autocleaner_report:
        report = st.session_state.autocleaner_report
        current_quality = data_engine.get_data_quality_report(st.session_state.working_df, st.session_state.column_types)
        current_score = data_engine.get_health_score(
            current_quality, st.session_state.column_types, st.session_state.pii_findings
        )
        with st.container(border=True):
            st.info(report["narration"])
            st.caption(autocleaner.health_delta_line(report["before_score"], current_score))
            if report["safe_log"]:
                with st.expander(f"{report['safe_applied']} safe fix(es) applied", expanded=False):
                    for line in report["safe_log"]:
                        st.caption(f"✓ {line}")

            queue = st.session_state.autocleaner_review_queue
            if queue:
                st.markdown(f"**{len(queue)} action(s) need your judgment**")
                if st.button("Approve all", key="autoclean_approve_all"):
                    push_undo_snapshot()
                    work_df, work_types = st.session_state.working_df, st.session_state.column_types
                    for review_action in list(queue):
                        work_df, work_types, description, code = autocleaner.apply_action(
                            work_df, work_types, review_action
                        )
                        log_step(description, code)
                    st.session_state.working_df = work_df
                    st.session_state.column_types = work_types
                    st.session_state.autocleaner_review_queue = []
                    st.toast("Approved every pending action.")
                    st.rerun()

                for i, review_action in enumerate(queue):
                    with st.container(border=True):
                        rc1, rc2 = st.columns([4, 1])
                        rc1.markdown(
                            f"**{autocleaner.ACTION_LABELS.get(review_action['action'], review_action['action'])}** "
                            f"— `{review_action['column']}`"
                        )
                        rc1.caption(f"{review_action['detail']} · {review_action['reason']}")
                        approve_col, reject_col = rc2.columns(2)
                        if approve_col.button("✓", key=f"autoclean_approve_{i}", help="Approve", use_container_width=True):
                            push_undo_snapshot()
                            new_df, new_types, description, code = autocleaner.apply_action(
                                st.session_state.working_df, st.session_state.column_types, review_action
                            )
                            st.session_state.working_df = new_df
                            st.session_state.column_types = new_types
                            log_step(description, code)
                            st.session_state.autocleaner_review_queue = [
                                a for a in st.session_state.autocleaner_review_queue if a is not review_action
                            ]
                            st.toast("Applied.")
                            st.rerun()
                        if reject_col.button("✗", key=f"autoclean_reject_{i}", help="Reject", use_container_width=True):
                            st.session_state.autocleaner_review_queue = [
                                a for a in st.session_state.autocleaner_review_queue if a is not review_action
                            ]
                            st.rerun()
            elif report["safe_applied"] or report.get("safe_log"):
                st.success("All caught up — nothing left to review.")

            if st.session_state.autocleaner_snapshot is not None:
                if st.button("Undo All Auto Clean Changes", key="autoclean_undo_all"):
                    snap = st.session_state.autocleaner_snapshot
                    st.session_state.working_df = snap["working_df"]
                    st.session_state.column_types = snap["column_types"]
                    st.session_state.cleaning_log = snap["cleaning_log"]
                    st.session_state.autocleaner_report = None
                    st.session_state.autocleaner_review_queue = []
                    st.session_state.autocleaner_snapshot = None
                    st.toast("Reverted every Auto Clean change.")
                    st.rerun()

    if quality["all_null_columns"]:
        st.warning(
            f"Fully empty columns detected: {', '.join(quality['all_null_columns'])}. "
            "Consider dropping them in the sidebar's Data Processing panel."
        )

    if pii_detector.has_findings(st.session_state.pii_findings):
        st.error(f"**Privacy notice:** {pii_detector.describe_findings(st.session_state.pii_findings)}")
        with st.expander("Indian PII Vault — details & masking", expanded=False):
            for pii_type, label in pii_detector.PII_TYPE_LABELS.items():
                entries = st.session_state.pii_findings.get(pii_type, [])
                if not entries:
                    continue
                st.markdown(f"**{label}**")
                for entry in entries:
                    pii_col = entry["column"]
                    pcol1, pcol2, pcol3 = st.columns([2, 2, 1])
                    pcol1.write(f"`{pii_col}`")
                    pcol2.caption(f"{entry['match_pct']}% match — e.g. {entry['sample']}")
                    with pcol3:
                        if st.button("Mask", key=f"mask_{pii_type}_{pii_col}", use_container_width=True):
                            push_undo_snapshot()
                            masked_df = pii_detector.mask_column(df, pii_col, pii_type)
                            st.session_state.working_df = masked_df
                            log_step(
                                f"Masked {label.lower()} in '{pii_col}'",
                                f"# Masked {pii_type} values in '{pii_col}' for privacy.",
                            )
                            st.session_state.pii_findings = pii_detector.scan_dataframe(
                                masked_df, st.session_state.column_types
                            )
                            st.toast(f"Masked '{pii_col}'. 🔒")
                            st.rerun()

    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("**Missing Values by Column**")
        missing_df = pd.DataFrame(
            {"Column": quality["missing_by_column"].keys(), "Missing %": quality["missing_by_column"].values()}
        ).sort_values("Missing %", ascending=False)
        st.dataframe(missing_df, use_container_width=True, hide_index=True)

    with col_right:
        st.markdown("**Outliers (IQR method)**")
        if quality["outliers"]:
            outlier_df = pd.DataFrame(
                [{"Column": c, "Outliers": v["count"], "Outlier %": v["pct"]} for c, v in quality["outliers"].items()]
            ).sort_values("Outliers", ascending=False)
            st.dataframe(outlier_df, use_container_width=True, hide_index=True)
        else:
            st.info("No numeric columns to check for outliers.")

    ui.render_section_label("Column Profiler")
    ui.render_column_profiler_grid(df, column_types, quality, st.session_state.india_mode)

    ui.render_section_label("Data Dictionary")
    if st.button("📖 Generate Data Dictionary", key="gen_data_dict"):
        with st.spinner("Documenting every column…"):
            descriptions, dict_error = data_dictionary.generate_descriptions(ai_analyst.get_model(), df, column_types)
            st.session_state.data_dictionary_rows = data_dictionary.build_dictionary(
                df, column_types, quality, descriptions
            )
        if dict_error:
            st.warning(f"Gemini description generation hit a snag ({dict_error}) — used templated descriptions instead.")

    if st.session_state.data_dictionary_rows:
        edited_rows = st.data_editor(
            pd.DataFrame(st.session_state.data_dictionary_rows), use_container_width=True, hide_index=True,
            key="data_dictionary_editor", disabled=["Column", "Type", "Example Values", "Missing %", "Notes"],
        )
        st.session_state.data_dictionary_rows = edited_rows.to_dict("records")
        dict_name = st.session_state.last_file_name or "dataset"
        ddl_col, ddx_col = st.columns(2)
        with ddl_col:
            st.download_button(
                "Download as Markdown",
                data=data_dictionary.to_markdown(st.session_state.data_dictionary_rows, dict_name).encode("utf-8"),
                file_name="data_dictionary.md", mime="text/markdown", use_container_width=True,
            )
        with ddx_col:
            st.download_button(
                "Download as Excel",
                data=data_dictionary.to_xlsx_bytes(st.session_state.data_dictionary_rows, dict_name),
                file_name="data_dictionary.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    st.markdown("**Summary Statistics**")
    st.dataframe(visualization.style_describe_table(visualization.get_overview_stats(df)), use_container_width=True)

    st.markdown("**Data Preview**")
    st.dataframe(df.head(20), use_container_width=True)

    st.divider()
    with st.expander("Column Health", expanded=False):
        profiles = profiling.profile_all_columns(df, column_types, quality)
        health_df = pd.DataFrame(
            [
                {
                    "Column": p["column"],
                    "Type": p["type"],
                    "Health": p["health"].upper(),
                    "Notes": "; ".join(p["issues"] + p["warnings"]) or "—",
                }
                for p in profiles
            ]
        )
        st.dataframe(health_df, use_container_width=True, hide_index=True)

    with st.expander("Column Drill-Down", expanded=False):
        drill_col = st.selectbox("Choose a column", df.columns.tolist(), key="drilldown_col")
        prof = profiling.profile_column(df, drill_col, column_types, quality)

        st.markdown(f"**Health: {prof['health'].upper()}**")
        for msg in prof["issues"]:
            st.error(msg)
        for msg in prof["warnings"]:
            st.warning(msg)

        dd1, dd2 = st.columns(2)
        with dd1:
            st.metric("Missing %", f"{prof['missing_pct']}%")
            if prof["skew_label"]:
                st.write(f"**Skewness:** {prof['skew_label']}")
            if prof["kurt_label"]:
                st.write(f"**Kurtosis:** {prof['kurt_label']}")
        with dd2:
            st.write("**Top 10 values**")
            st.dataframe(df[drill_col].value_counts().head(10).rename("count"), use_container_width=True)

        drill_type = column_types.get(drill_col)
        if drill_type == "numeric":
            hist, box = visualization.plot_numeric(df, drill_col)
            st.plotly_chart(hist, use_container_width=True)
            st.plotly_chart(box, use_container_width=True)
        elif drill_type == "categorical":
            cat_fig = visualization.plot_categorical(df, drill_col)
            if cat_fig is not None:
                st.plotly_chart(cat_fig, use_container_width=True)
        else:
            st.info("No dedicated chart for this column type — see the Top 10 values above.")

        st.write("**Descriptive stats**")
        st.dataframe(df[[drill_col]].describe(include="all").transpose(), use_container_width=True)

    with st.expander("Anomaly Detection", expanded=False):
        if not anomaly.is_available():
            st.warning("scikit-learn isn't installed. Run `pip install -r requirements.txt` and restart the app.")
        else:
            if st.button("Find Anomalies", key="find_anomalies_btn"):
                with st.spinner(ui.get_loading_message()):
                    flagged, anomaly_err = anomaly.find_anomalies(df, column_types)
                st.session_state.anomaly_result_df = flagged
                st.session_state.anomaly_error = anomaly_err

            if st.session_state.anomaly_error:
                st.error(st.session_state.anomaly_error)
            elif st.session_state.anomaly_result_df is not None:
                flagged = st.session_state.anomaly_result_df
                if flagged.empty:
                    st.info("No anomalies detected.")
                else:
                    st.write(f"**{len(flagged)} anomalous row(s) flagged:**")
                    st.dataframe(flagged, use_container_width=True)
                    if st.button("Exclude flagged rows from active dataset", key="exclude_anomalies_btn"):
                        push_undo_snapshot()
                        new_df = df.drop(index=flagged.index)
                        st.session_state.working_df = new_df
                        st.session_state.column_types = data_engine.detect_column_types(new_df)
                        log_step(
                            f"Excluded {len(flagged)} anomalous row(s) (IsolationForest)",
                            cleaning.anomaly_exclude_code(len(flagged)),
                        )
                        st.session_state.anomaly_result_df = None
                        st.toast(f"Excluded {len(flagged)} anomalous row(s). 🚨")
                        st.rerun()

# --------------------------------------------------------------------------
# Clean tab — before/after comparison + cleaned dataset download
# (the actual cleaning controls live in the sidebar, per the spec's layout)
# --------------------------------------------------------------------------
elif st.session_state.active_section == "Clean":
    ui.render_help_expander(
        "Review exactly what changed since upload. Cleaning actions themselves live in the "
        "sidebar's Data Processing panel."
    )

    st.subheader("Before vs After")
    diff = cleaning.compare_before_after(st.session_state.raw_df, df)

    d1, d2, d3 = st.columns(3)
    d1.metric("Rows", diff["rows_after"], delta=diff["rows_after"] - diff["rows_before"])
    d2.metric("Columns", diff["cols_after"], delta=diff["cols_after"] - diff["cols_before"])
    d3.metric("Missing Cells", diff["nulls_after"], delta=diff["nulls_after"] - diff["nulls_before"])

    if diff["dtype_changes"]:
        st.markdown("**Dtype changes**")
        for col, (old, new) in diff["dtype_changes"].items():
            st.write(f"- `{col}`: {old} → {new}")

    st.divider()
    st.subheader("Cleaning Log")
    if st.session_state.cleaning_log:
        for step in st.session_state.cleaning_log:
            st.write(f"- {step['description']}")
    else:
        ui.render_empty_state(
            "🧹", "No cleaning steps yet",
            "Use the sidebar's Data Processing panel to get started.",
        )

    st.divider()
    st.subheader("Original vs Cleaned Preview")
    prev_left, prev_right = st.columns(2)
    with prev_left:
        st.caption("Original")
        st.dataframe(st.session_state.raw_df.head(10), use_container_width=True)
    with prev_right:
        st.caption("Cleaned")
        st.dataframe(df.head(10), use_container_width=True)

    st.divider()
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button(
            "Download Cleaned Dataset (CSV)",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="prism_cleaned_data.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with dl2:
        raw_quality = data_engine.get_data_quality_report(st.session_state.raw_df, column_types)
        health_before_cert = data_engine.get_health_score(raw_quality, column_types)
        health_after_cert = data_engine.get_health_score(quality_for_header, column_types, st.session_state.pii_findings)
        st.download_button(
            "Download Cleaning Certificate (PDF)",
            data=report_writer.generate_cleaning_certificate(
                st.session_state.last_file_name or "dataset", df.shape[0], df.shape[1],
                health_before_cert, health_after_cert, st.session_state.cleaning_log,
            ),
            file_name="prism_cleaning_certificate.pdf",
            mime="application/pdf",
            use_container_width=True,
            help="An audit-trail PDF: dataset name, date, health score before/after, and every cleaning action taken.",
        )

# --------------------------------------------------------------------------
# Hell Mode tab — a deeper cleaning engine for real-world-messy data: null
# synonyms, Indian-formatted numbers, mixed date formats, fuzzy category
# cleanup, mixed measurement units, and richer imputation strategies.
# --------------------------------------------------------------------------
elif st.session_state.active_section == "Hell Mode":
    ui.render_help_expander(
        "A deeper cleaning engine for real-world-messy data: disguised nulls, Indian-formatted "
        "numbers (₹/lakh/crore), mixed date formats, fuzzy-duplicate categories, mixed units, and "
        "richer imputation (KNN, group-wise, AI-recommended)."
    )

    st.subheader("Hell Mode")

    # --- 1. Null synonym detection -----------------------------------------
    st.markdown("#### Null Synonym Detection")
    st.caption(
        "Scans text columns for disguised nulls (\"NA\", \"-\", \"Nil\", ...) that pandas "
        "doesn't recognize as missing by default."
    )

    with st.expander("Synonym list (editable)", expanded=False):
        synonyms_text = st.text_area(
            "One synonym per line", value="\n".join(hellmode.DEFAULT_NULL_SYNONYMS),
            key="null_synonyms_text", height=150,
        )
    active_synonyms = [line.strip() for line in synonyms_text.splitlines() if line.strip()]

    disguised_findings = hellmode.scan_disguised_nulls(df, column_types, active_synonyms)
    if not disguised_findings:
        ui.render_empty_state(
            "🕵️", "No disguised nulls found", "Every text/categorical column looks clean against the current synonym list."
        )
    else:
        for line in hellmode.describe_disguised_nulls(disguised_findings):
            st.warning(line)
        if st.button("Convert all to proper NaN", key="convert_disguised_nulls_btn", use_container_width=True):
            push_undo_snapshot()
            new_df = hellmode.convert_disguised_nulls(df, list(disguised_findings.keys()), active_synonyms)
            st.session_state.working_df = new_df
            st.session_state.column_types = data_engine.detect_column_types(new_df)
            log_step(
                f"Converted disguised nulls to NaN in: {', '.join(disguised_findings.keys())}",
                hellmode.disguised_nulls_code(list(disguised_findings.keys()), active_synonyms),
            )
            st.toast("Disguised nulls converted. 🕵️")
            st.rerun()

    # --- 2. Indian number parser --------------------------------------------
    st.divider()
    st.markdown("#### Indian Number Parser")
    st.caption("Detects ₹/Rs./lakh/crore-formatted numbers and converts them to absolute numeric values.")

    indian_candidates = hellmode.detect_indian_number_candidates(df, column_types)
    if not indian_candidates:
        ui.render_empty_state(
            "🇮🇳", "No Indian-formatted numbers detected", "No text column looked like ₹/Rs./lakh/crore-style numbers."
        )
    else:
        for cand in indian_candidates:
            st.markdown(f"**{cand['column']}** — {cand['match_pct']}% look numeric")
            st.dataframe(
                pd.DataFrame({"Before": cand["sample_before"], "After": cand["sample_after"]}),
                use_container_width=True, hide_index=True,
            )
            add_suffix = st.checkbox(
                f"Rename to '{cand['column']}_inr' after conversion", value=True, key=f"indian_suffix_{cand['column']}"
            )
            if st.button(f"Convert '{cand['column']}'", key=f"indian_convert_{cand['column']}", use_container_width=True):
                push_undo_snapshot()
                new_df, new_col = hellmode.convert_indian_column(df, cand["column"], add_unit_suffix=add_suffix)
                st.session_state.working_df = new_df
                st.session_state.column_types = data_engine.detect_column_types(new_df)
                rename_note = f" (renamed to '{new_col}')" if new_col != cand["column"] else ""
                log_step(
                    f"Converted '{cand['column']}' from Indian-formatted text to numeric{rename_note}",
                    hellmode.indian_number_code(cand["column"], new_col),
                )
                st.toast(f"Converted '{cand['column']}' to numeric. 🇮🇳")
                st.rerun()

    # --- 3. Mixed date format resolver ---------------------------------------
    st.divider()
    st.markdown("#### Mixed Date Format Resolver")
    st.caption("Standardizes a column with multiple date formats into one datetime dtype.")

    date_candidate_cols = [c for c, t in column_types.items() if t in ("text", "categorical", "datetime")]
    if not date_candidate_cols:
        ui.render_empty_state("📅", "No candidate columns", "No text or datetime-like columns to resolve.")
    else:
        date_col = st.selectbox("Column", date_candidate_cols, key="date_resolver_col")

        format_tally = hellmode.detect_date_formats(df[date_col])
        if format_tally:
            st.caption("Formats found: " + ", ".join(f"{k} ({v})" for k, v in format_tally.items()))

        ambiguous_dates = hellmode.find_ambiguous_dates(df[date_col])
        if ambiguous_dates:
            st.warning(f"{len(ambiguous_dates)} distinct ambiguous date value(s) found (day-first vs month-first).")
            st.dataframe(pd.DataFrame(ambiguous_dates), use_container_width=True, hide_index=True)

        day_first_choice = st.radio(
            "For ambiguous dates, treat the column as:",
            ["Day-first (Indian/EU default)", "Month-first (US)"],
            key="date_resolver_dayfirst",
        )
        day_first = day_first_choice == "Day-first (Indian/EU default)"

        if st.button("Standardize Dates", key="resolve_dates_btn", use_container_width=True):
            parsed, failed = hellmode.resolve_dates(df[date_col], day_first=day_first)
            st.session_state.hellmode_date_result = {
                "column": date_col, "parsed": parsed, "failed": failed, "day_first": day_first,
            }

        date_result = st.session_state.hellmode_date_result
        if date_result is not None and date_result["column"] == date_col:
            st.caption(f"{date_result['parsed'].notna().sum()} of {len(date_result['parsed'])} values parsed successfully.")
            if date_result["failed"]:
                st.error(f"{len(date_result['failed'])} distinct value(s) failed to parse: {', '.join(date_result['failed'][:10])}")
            if st.button("Apply Standardized Dates", key="apply_dates_btn", type="primary", use_container_width=True):
                push_undo_snapshot()
                new_df = df.copy()
                new_df[date_col] = date_result["parsed"]
                st.session_state.working_df = new_df
                st.session_state.column_types = data_engine.detect_column_types(new_df)
                log_step(
                    f"Standardized mixed date formats in '{date_col}' "
                    f"({'day-first' if date_result['day_first'] else 'month-first'})",
                    hellmode.date_resolver_code(date_col, date_result["day_first"]),
                )
                st.session_state.hellmode_date_result = None
                st.toast(f"Standardized dates in '{date_col}'. 📅")
                st.rerun()

    # --- 4. Fuzzy category cleanup --------------------------------------------
    st.divider()
    st.markdown("#### Fuzzy Category Cleanup")
    st.caption("Clusters similar category values (case variants, trailing spaces, misspellings) using rapidfuzz.")

    categorical_cols = [c for c, t in column_types.items() if t == "categorical"]
    if not categorical_cols:
        ui.render_empty_state("🧵", "No categorical columns", "Fuzzy cleanup needs at least one categorical column.")
    else:
        fuzzy_col = st.selectbox("Column", categorical_cols, key="fuzzy_col")
        fuzzy_threshold = st.slider("Similarity threshold", min_value=50, max_value=100, value=85, key="fuzzy_threshold")
        fuzzy_groups = hellmode.suggest_fuzzy_groups(df[fuzzy_col], threshold=fuzzy_threshold)

        if not fuzzy_groups:
            st.info(f"No similar-value groups found in '{fuzzy_col}' at this threshold.")
        else:
            selected_fuzzy_groups = []
            for group_idx, group in enumerate(fuzzy_groups):
                with st.expander(
                    f"{group['canonical']} — {len(group['members'])} variants, {group['total_count']} rows",
                    expanded=False,
                ):
                    canonical_choice = st.selectbox(
                        "Canonical name", [m["value"] for m in group["members"]],
                        index=0, key=f"fuzzy_canonical_{group_idx}",
                    )
                    for member in group["members"]:
                        st.caption(f"- {member['value']!r}: {member['count']} row(s)")
                    merge_this_group = st.checkbox("Merge this group", value=True, key=f"fuzzy_merge_{group_idx}")
                    if merge_this_group:
                        selected_fuzzy_groups.append((group, canonical_choice))

            if st.button(
                "Apply Selected Merges", key="apply_fuzzy_btn", type="primary",
                use_container_width=True, disabled=not selected_fuzzy_groups,
            ):
                push_undo_snapshot()
                merge_map = {
                    member["value"]: canonical_choice
                    for group, canonical_choice in selected_fuzzy_groups
                    for member in group["members"]
                    if member["value"] != canonical_choice
                }
                new_df = hellmode.apply_fuzzy_merge(df, fuzzy_col, merge_map)
                st.session_state.working_df = new_df
                log_step(
                    f"Merged {len(selected_fuzzy_groups)} fuzzy-duplicate group(s) in '{fuzzy_col}'",
                    hellmode.fuzzy_merge_code(fuzzy_col, merge_map),
                )
                st.toast(f"Merged fuzzy duplicates in '{fuzzy_col}'. 🧵")
                st.rerun()

    # --- 5. Unit chaos detector ------------------------------------------------
    st.divider()
    st.markdown("#### Unit Chaos Detector")
    st.caption("Scans for mixed measurement units within one column (e.g. km/m/miles) and normalizes to one unit.")

    unit_findings = hellmode.detect_mixed_units(df, column_types)
    if not unit_findings:
        ui.render_empty_state(
            "📏", "No mixed units detected", "No column showed more than one recognized unit (distance, weight)."
        )
    else:
        for finding in unit_findings:
            units_summary = ", ".join(f"{u} ({n})" for u, n in finding["units_found"].items())
            st.markdown(f"**{finding['column']}** ({finding['family']}) — units found: {units_summary}")

            unit_options = list(hellmode.UNIT_FAMILIES[finding["family"]]["to_base"].keys())
            base_unit = hellmode.UNIT_FAMILIES[finding["family"]]["base_unit"]
            target_unit = st.selectbox(
                "Normalize to", unit_options, index=unit_options.index(base_unit), key=f"unit_target_{finding['column']}"
            )
            if st.button(f"Normalize '{finding['column']}'", key=f"unit_normalize_{finding['column']}", use_container_width=True):
                push_undo_snapshot()
                converted, description = hellmode.normalize_units(df[finding["column"]], finding["family"], target_unit)
                new_df = df.copy()
                new_df[finding["column"]] = converted
                st.session_state.working_df = new_df
                st.session_state.column_types = data_engine.detect_column_types(new_df)
                log_step(
                    f"{finding['column']}: {description}",
                    hellmode.unit_normalize_code(finding["column"], finding["family"], target_unit),
                )
                st.toast(f"Normalized units in '{finding['column']}'. 📏")
                st.rerun()

    # --- 6. Imputation intelligence ---------------------------------------------
    st.divider()
    st.markdown("#### Imputation Intelligence")
    st.caption(
        "Beyond mean/median/mode: forward/back fill, KNN imputation, group-wise fill by another "
        "column, and an AI-recommended strategy per column."
    )

    missing_value_cols = [c for c in df.columns if df[c].isna().sum() > 0]
    if not missing_value_cols:
        ui.render_empty_state("🧩", "No missing values", "Nothing to impute — this dataset has no missing values.")
    else:
        if st.button("AI Recommend", key="ai_recommend_impute_btn", use_container_width=True):
            impute_model = ai_analyst.get_model()
            with st.spinner(ui.get_loading_message()):
                impute_recs, impute_recs_error = hellmode.ai_recommend_imputation(
                    impute_model, df, column_types, data_engine.get_data_quality_report(df, column_types)
                )
            st.session_state.hellmode_impute_recs = impute_recs
            st.session_state.hellmode_impute_recs_error = impute_recs_error

        if st.session_state.hellmode_impute_recs_error:
            st.warning(st.session_state.hellmode_impute_recs_error)
        elif st.session_state.hellmode_impute_recs:
            st.markdown("**AI-recommended strategies** (review before applying)")
            for rec_col, rec in st.session_state.hellmode_impute_recs.items():
                strategy_label = hellmode.IMPUTATION_STRATEGY_LABELS.get(rec["strategy"], rec["strategy"])
                st.info(f"**{rec_col}** → {strategy_label} — {rec['reason']}")

        impute_col = st.selectbox("Column", missing_value_cols, key="impute_col")
        impute_strategy_label = st.selectbox(
            "Strategy", list(hellmode.IMPUTATION_STRATEGY_LABELS.values()), key="impute_strategy_label"
        )
        impute_strategy = {v: k for k, v in hellmode.IMPUTATION_STRATEGY_LABELS.items()}[impute_strategy_label]

        impute_group_col = None
        impute_custom_value = None
        if impute_strategy == "groupwise":
            impute_group_col = st.selectbox(
                "Group by column", [c for c in df.columns if c != impute_col], key="impute_group_col"
            )
        elif impute_strategy == "constant":
            impute_custom_value = st.text_input("Constant value", key="impute_custom_value")

        if st.button("Apply Imputation", key="apply_impute_btn", type="primary", use_container_width=True):
            imputed_df, impute_error = hellmode.impute_column(
                df, impute_col, impute_strategy, group_col=impute_group_col, custom_value=impute_custom_value
            )
            if impute_error:
                st.error(impute_error)
            else:
                push_undo_snapshot()
                st.session_state.working_df = imputed_df
                st.session_state.column_types = data_engine.detect_column_types(imputed_df)
                log_step(
                    f"Imputed '{impute_col}' via {hellmode.IMPUTATION_STRATEGY_LABELS.get(impute_strategy, impute_strategy)}",
                    hellmode.impute_code(impute_col, impute_strategy, group_col=impute_group_col, custom_value=impute_custom_value),
                )
                st.toast(f"Imputed '{impute_col}'. 🧩")
                st.rerun()

    # --- 8. Chaos Intensity — data resilience stress-tester -----------------
    st.divider()
    st.markdown("#### 🌪️ Chaos Intensity — Data Resilience Stress-Test")
    st.caption(
        "Deliberately degrades a **preview copy** of this dataset — numeric distribution drift, "
        "null injection, and casing corruption — scaled by the slider below, so you can see how "
        "badly a real degradation event would hurt your Data Health Score before it happens for "
        "real. Nothing changes until you choose to keep the result."
    )
    chaos_intensity = st.slider("Chaos Intensity", 0, 100, 30, key="chaos_intensity_pct", format="%d%%")
    if st.button("🌪️ Run Chaos Test", key="chaos_run_btn", use_container_width=True):
        before_quality = data_engine.get_data_quality_report(df, column_types)
        before_health = data_engine.get_health_score(before_quality, column_types)
        chaotic_df, chaos_report = hellmode.inject_chaos(df, column_types, chaos_intensity)
        chaotic_types = data_engine.detect_column_types(chaotic_df)
        after_quality = data_engine.get_data_quality_report(chaotic_df, chaotic_types)
        after_health = data_engine.get_health_score(after_quality, chaotic_types)
        st.session_state.chaos_result = {
            "chaotic_df": chaotic_df, "report": chaos_report,
            "before_health": before_health, "after_health": after_health, "intensity": chaos_intensity,
        }

    if st.session_state.chaos_result:
        cr = st.session_state.chaos_result
        hres1, hres2 = st.columns(2)
        hres1.metric("Health Score — Before", cr["before_health"])
        hres2.metric("Health Score — After", cr["after_health"], delta=cr["after_health"] - cr["before_health"])
        st.caption(
            f"Distribution drift: {', '.join(cr['report']['drifted_columns']) or 'none this run'} · "
            f"Nulls injected: {cr['report']['null_cells_injected']:,} cell(s) · "
            f"Casing corrupted: {', '.join(cr['report']['casing_corrupted_columns']) or 'none'}"
        )
        if st.button("Apply this chaos test to the active dataset", key="chaos_apply_btn", use_container_width=True):
            push_undo_snapshot()
            st.session_state.working_df = cr["chaotic_df"]
            st.session_state.column_types = data_engine.detect_column_types(cr["chaotic_df"])
            log_step(
                f"Chaos Intensity stress-test applied at {cr['intensity']}% "
                f"(Health Score {cr['before_health']} → {cr['after_health']})",
                "# Chaos Intensity draws from a random generator — not reproducible as a static pandas script.",
            )
            st.toast("Chaos applied — data degraded as previewed. 🌪️")
            st.session_state.chaos_result = None
            st.rerun()

# --------------------------------------------------------------------------
# Combine tab — join a second uploaded file onto the active dataset. Setting
# the result as active rewires every other tab (Clean, Visualize, SQL Lab,
# AI Analyst) to operate on the joined data, since they all just read
# st.session_state.working_df.
# --------------------------------------------------------------------------
elif st.session_state.active_section == "Combine":
    ui.render_help_expander(
        "Upload a second file and join it onto your active dataset by a detected or "
        "manually chosen key."
    )

    st.subheader("Combine with Another File")
    combine_mode = st.radio(
        "Mode", ["Join datasets", "Compare for drift"], key="combine_mode", horizontal=True,
    )
    st.caption(
        "Upload a second dataset to join it onto your active data, or compare it against your "
        "active data for dataset drift (e.g. this month vs last month)."
    )

    second_file = st.file_uploader(
        "Upload second CSV or Excel", type=["csv", "xlsx", "xls"], key="second_file_uploader"
    )

    if second_file is not None and second_file.name != st.session_state.second_file_name:
        second_sheet_choice, second_sheet_ready = resolve_sheet_choice(second_file, "second")
        if second_sheet_ready:
            with st.spinner("Reading second file..."):
                new_second_df, second_error, second_warnings = data_engine.load_data(
                    second_file, sheet_name=second_sheet_choice
                )
            if second_error:
                st.error(second_error)
            else:
                st.session_state.second_df = new_second_df
                st.session_state.second_file_name = second_file.name
                st.session_state.combine_preview_df = None
                st.session_state.combine_stats = None
                st.session_state.drift_result = None
                for w in second_warnings:
                    st.warning(w)
                st.success(f"Loaded second file: {new_second_df.shape[0]:,} rows x {new_second_df.shape[1]} columns")

    if st.session_state.second_df is None:
        ui.render_empty_state(
            "🔗", "Nothing to combine yet",
            "Upload a second CSV or Excel file above to join it onto your active dataset, or compare "
            "the two for drift.",
        )
    else:
        second_df = st.session_state.second_df

        prev_left, prev_right = st.columns(2)
        with prev_left:
            st.caption(f"Active dataset — {df.shape[0]:,} rows × {df.shape[1]} columns")
            st.dataframe(df.head(5), use_container_width=True)
        with prev_right:
            st.caption(f"{st.session_state.second_file_name} — {second_df.shape[0]:,} rows × {second_df.shape[1]} columns")
            st.dataframe(second_df.head(5), use_container_width=True)

        if combine_mode == "Join datasets":
            candidates = join_engine.detect_candidate_join_keys(df, second_df)
            if candidates:
                st.markdown("**Candidate Join Keys** (matching column names, ranked by value overlap)")
                candidates_df = pd.DataFrame(candidates).rename(
                    columns={
                        "column": "Column",
                        "overlap_pct": "Overlap %",
                        "left_unique": "Unique (active)",
                        "right_unique": "Unique (second)",
                    }
                )
                st.dataframe(candidates_df, use_container_width=True, hide_index=True)
                default_left_key = default_right_key = candidates[0]["column"]
            else:
                st.warning(
                    "No columns with matching names were found between the two files. "
                    "Pick a join key manually below."
                )
                default_left_key, default_right_key = df.columns[0], second_df.columns[0]

            jc1, jc2, jc3 = st.columns(3)
            with jc1:
                left_key = st.selectbox(
                    "Active dataset key", df.columns.tolist(),
                    index=df.columns.get_loc(default_left_key) if default_left_key in df.columns else 0,
                )
            with jc2:
                right_key = st.selectbox(
                    "Second file key", second_df.columns.tolist(),
                    index=second_df.columns.get_loc(default_right_key) if default_right_key in second_df.columns else 0,
                )
            with jc3:
                join_type = st.selectbox("Join type", ["inner", "left", "right", "outer"])
            st.caption(join_engine.JOIN_TYPE_DESCRIPTIONS[join_type])

            if st.button("Preview Join", use_container_width=True):
                try:
                    joined_df, join_stats = join_engine.join_dataframes(df, second_df, left_key, right_key, join_type)
                    st.session_state.combine_preview_df = joined_df
                    st.session_state.combine_stats = join_stats
                except Exception as e:
                    st.session_state.combine_preview_df = None
                    st.session_state.combine_stats = None
                    st.error(f"Join failed: {e}")

            if st.session_state.combine_preview_df is not None:
                stats = st.session_state.combine_stats
                s1, s2, s3, s4 = st.columns(4)
                s1.metric("Rows Before", f"{stats['rows_before']:,}")
                s2.metric("Rows After", f"{stats['rows_after']:,}", delta=stats["rows_after"] - stats["rows_before"])
                s3.metric("Columns Gained", stats["columns_gained"])
                s4.metric("Key Match Rate", f"{stats['match_pct']}%")

                st.markdown("**Joined Preview**")
                st.dataframe(st.session_state.combine_preview_df.head(20), use_container_width=True)

                if st.button("Use as Active Dataset", type="primary", use_container_width=True):
                    new_active_df = st.session_state.combine_preview_df
                    join_description = (
                        f"Combined with '{st.session_state.second_file_name}' via a {join_type} join on "
                        f"'{left_key}' = '{right_key}'"
                    )
                    set_active_dataset(
                        new_active_df.copy(),
                        new_active_df.copy(),
                        f"combined:{st.session_state.second_file_name}",
                        cleaning_log=[
                            {
                                "description": join_description,
                                "code": cleaning.join_code(
                                    st.session_state.second_file_name, left_key, right_key, join_type
                                ),
                            }
                        ],
                    )
                    st.toast("Joined dataset is now active — every tab will use it. 🔗")
                    st.rerun()

        else:
            st.caption(
                f"Comparing active dataset ({df.shape[0]:,} rows) as the baseline against "
                f"'{st.session_state.second_file_name}' ({second_df.shape[0]:,} rows) as the comparison."
            )

            if st.button("Run Drift Comparison", type="primary", use_container_width=True):
                st.session_state.drift_result = drift.compare_datasets(df, second_df, column_types)

            drift_result = st.session_state.drift_result
            if drift_result is not None:
                st.metric("Overall Drift Score", f"{drift_result['overall_drift_score']}/100")

                if drift_result["columns_only_in_a"]:
                    st.warning(f"Columns only in the active dataset: {', '.join(drift_result['columns_only_in_a'])}")
                if drift_result["columns_only_in_b"]:
                    st.warning(
                        f"Columns only in '{st.session_state.second_file_name}': "
                        f"{', '.join(drift_result['columns_only_in_b'])}"
                    )

                if not drift_result["column_reports"]:
                    st.info("No shared numeric or categorical columns to compare.")
                else:
                    st.markdown("**What changed the most**")
                    summary_df = pd.DataFrame(
                        [
                            {
                                "Column": r["column"],
                                "Type": r["type"],
                                "Drift Score": r["drift_score"],
                                "Summary": drift.describe_drift(r),
                            }
                            for r in drift_result["column_reports"]
                        ]
                    )
                    st.dataframe(summary_df, use_container_width=True, hide_index=True)

                    st.markdown("**Column-by-column detail**")
                    for r in drift_result["column_reports"]:
                        with st.expander(f"{r['column']} — drift score {r['drift_score']}", expanded=False):
                            st.plotly_chart(
                                drift.build_overlap_chart(r), use_container_width=True, key=f"drift_chart_{r['column']}"
                            )
                            if r["type"] == "categorical":
                                if r["new_categories"]:
                                    st.write(f"**New categories in B:** {', '.join(map(str, r['new_categories']))}")
                                if r["missing_categories"]:
                                    st.write(
                                        f"**Missing categories in B:** {', '.join(map(str, r['missing_categories']))}"
                                    )

# --------------------------------------------------------------------------
# Visualize tab — smart auto-charts, correlation heatmap, HTML export
# --------------------------------------------------------------------------
elif st.session_state.active_section == "Visualize":
    ui.render_help_expander(
        "Auto-picked charts per column type, a correlation heatmap, and a manual chart "
        "builder for full control."
    )

    st.subheader("Auto-Generated Charts")

    id_like_cols = profiling.get_id_like_columns(df)
    chart_column_types = {c: t for c, t in column_types.items() if c not in id_like_cols}
    if id_like_cols:
        st.caption(f"Excluded probable ID column(s) from auto-charts: {', '.join(id_like_cols)}")

    with st.spinner(ui.get_loading_message()):
        charts, top_corr = visualization.auto_generate_charts(df, chart_column_types)

    if st.session_state.india_mode:
        # Auto-generated trend charts are titled "{num_col} over {dt_col}" —
        # see modules/visualization.py:auto_generate_charts. Add subtle
        # festival markers to those specifically, not every chart.
        for dt_col in (c for c, t in column_types.items() if t == "datetime"):
            for title, fig in charts.items():
                if title.endswith(f" over {dt_col}"):
                    dt_series = pd.to_datetime(df[dt_col], errors="coerce").dropna()
                    if not dt_series.empty:
                        india.add_festival_markers(fig, dt_series.min(), dt_series.max())

    if top_corr:
        st.markdown("**Top Correlations**")
        for c1, c2, val in top_corr:
            st.info(f"**{c1}** ↔ **{c2}** — {visualization.describe_correlation(val)}")

    if not charts:
        ui.render_empty_state(
            "📈", "Not enough variety to chart yet", "Try cleaning up a few more columns, or build one manually below."
        )
    else:
        chart_items = list(charts.items())
        for i in range(0, len(chart_items), 2):
            cols = st.columns(2)
            for offset, col in enumerate(cols):
                idx = i + offset
                if idx < len(chart_items):
                    title, fig = chart_items[idx]
                    with col:
                        st.plotly_chart(fig, use_container_width=True, key=f"auto_chart_{idx}_{title}")

    st.divider()
    st.subheader("Manual Chart Builder")
    st.caption("Auto mode above not showing what you need? Pick the axes and chart type yourself.")

    mc1, mc2, mc3 = st.columns(3)
    with mc1:
        manual_x = st.selectbox("X-axis", df.columns.tolist(), key="manual_x")
    with mc2:
        manual_chart_type = st.selectbox("Chart type", visualization.MANUAL_CHART_TYPES, key="manual_chart_type")
    with mc3:
        y_required = manual_chart_type in visualization.MANUAL_CHART_TYPES_REQUIRING_Y
        y_options = ["(none)"] + [c for c in df.columns if c != manual_x]
        y_label = st.selectbox(f"Y-axis{'' if y_required else ' (optional)'}", y_options, key="manual_y")
        manual_y = None if y_label == "(none)" else y_label

    if st.button("Build Chart", use_container_width=True):
        try:
            st.session_state.manual_chart_fig = visualization.build_manual_chart(
                df, manual_chart_type, manual_x, manual_y
            )
            st.session_state.manual_chart_error = None
        except Exception as e:
            st.session_state.manual_chart_fig = None
            st.session_state.manual_chart_error = str(e)

    if st.session_state.manual_chart_error:
        st.error(st.session_state.manual_chart_error)
    elif st.session_state.manual_chart_fig is not None:
        st.plotly_chart(st.session_state.manual_chart_fig, use_container_width=True)

    st.divider()
    st.subheader("Auto-Dashboard")
    st.caption("One click: Gemini designs a set of KPI cards and 4-6 charts for this dataset.")

    if st.button("Build My Dashboard", use_container_width=True):
        dashboard_model = ai_analyst.get_model()
        with st.spinner(ui.get_loading_message()):
            st.session_state.dashboard_spec = dashboard_builder.generate_dashboard_spec(
                dashboard_model, df, column_types
            )

    dashboard_spec = st.session_state.dashboard_spec
    if dashboard_spec is None:
        ui.render_empty_state(
            "📊", "No dashboard yet",
            'Click "Build My Dashboard" above and Gemini will design KPI cards and charts for this data.',
        )
    else:
        if dashboard_spec["kpis"]:
            kpi_cols = st.columns(len(dashboard_spec["kpis"]))
            for kpi_col, kpi in zip(kpi_cols, dashboard_spec["kpis"]):
                kpi_value = dashboard_builder.compute_kpi(df, kpi)
                display_value = f"{kpi_value:,.2f}" if isinstance(kpi_value, float) else kpi_value
                kpi_col.metric(kpi.get("label", kpi["column"]), display_value if display_value is not None else "—")

        if not dashboard_spec["charts"]:
            st.info("No charts could be built for this dataset.")
        else:
            chart_entries = list(enumerate(dashboard_spec["charts"]))
            for row_start in range(0, len(chart_entries), 2):
                row_entries = chart_entries[row_start : row_start + 2]
                row_cols = st.columns(len(row_entries))
                for row_col, (chart_idx, chart_spec) in zip(row_cols, row_entries):
                    with row_col:
                        dash_fig = dashboard_builder.build_dashboard_chart(df, chart_spec)
                        if dash_fig is None:
                            st.warning(f"Couldn't build a chart for '{chart_spec.get('x')}'.")
                        else:
                            st.plotly_chart(dash_fig, use_container_width=True, key=f"dash_chart_{chart_idx}")
                            if chart_spec.get("reason"):
                                st.caption(chart_spec["reason"])

                        remove_col, swap_col = st.columns(2)
                        with remove_col:
                            if st.button("Remove", key=f"dash_remove_{chart_idx}", use_container_width=True):
                                dashboard_spec["charts"].pop(chart_idx)
                                st.session_state.dashboard_spec = dashboard_spec
                                st.rerun()
                        with swap_col:
                            if st.button("Swap", key=f"dash_swap_{chart_idx}", use_container_width=True):
                                dashboard_spec["charts"][chart_idx] = dashboard_builder.swap_chart_type(chart_spec)
                                st.session_state.dashboard_spec = dashboard_spec
                                st.rerun()

    st.divider()
    st.subheader("Export Report")
    st.caption("Generates a standalone HTML file with the data quality summary, all charts, and key stats.")

    quality_for_export = data_engine.get_data_quality_report(df, column_types)
    stats_df = visualization.get_overview_stats(df)
    html_report = report.generate_html_report(
        df, quality_for_export, stats_df, charts, [step["description"] for step in st.session_state.cleaning_log]
    )
    st.download_button(
        "Download Full HTML Report",
        data=html_report.encode("utf-8"),
        file_name="prism_eda_report.html",
        mime="text/html",
        use_container_width=True,
    )

    st.divider()
    st.subheader("Auto-Report Writer")
    st.caption(
        "One click: an executive-style write-up — summary, data quality, key findings with "
        "embedded charts, and recommendations — exportable as PDF or HTML."
    )

    if st.button("Generate Report", use_container_width=True):
        report_model = ai_analyst.get_model()
        with st.spinner(ui.get_loading_message()):
            st.session_state.auto_report_content = report_writer.build_report_content(
                report_model, df, quality_for_export, column_types, charts, top_corr
            )

    report_content = st.session_state.auto_report_content
    if report_content is None:
        ui.render_empty_state(
            "📝", "No report yet", 'Click "Generate Report" above for an executive-style write-up with embedded charts.'
        )
    else:
        st.markdown(f"**Executive Summary**  \n{report_content['executive_summary']}")
        if report_content["findings_error"]:
            st.warning(report_content["findings_error"])

        report_pdf_bytes = report_writer.generate_pdf_report(report_content, st.session_state.last_file_name or "dataset")
        report_html_text = report_writer.generate_html_report(report_content, st.session_state.last_file_name or "dataset")

        rc1, rc2 = st.columns(2)
        with rc1:
            st.download_button(
                "Download Report (PDF)",
                data=report_pdf_bytes,
                file_name="prism_analysis_report.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        with rc2:
            st.download_button(
                "Download Report (HTML)",
                data=report_html_text.encode("utf-8"),
                file_name="prism_analysis_report.html",
                mime="text/html",
                use_container_width=True,
            )

# --------------------------------------------------------------------------
# SQL Lab tab — run raw SQL against the active dataset via DuckDB (registered
# as table "data"), with clickable example queries and an optional
# AI-generated plain-English explanation of whatever query is in the editor.
# --------------------------------------------------------------------------
elif st.session_state.active_section == "SQL Lab":
    ui.render_help_expander(
        "Run raw SQL against your active dataset via DuckDB, or connect to a live MySQL "
        "database and query it directly."
    )

    st.subheader("SQL Lab")

    st.session_state.sql_source = st.radio(
        "Source", ["Local dataset", "MySQL database"],
        index=["Local dataset", "MySQL database"].index(st.session_state.sql_source),
        horizontal=True, label_visibility="collapsed",
    )

    # ----------------------------------------------------------------
    # Local dataset — unchanged DuckDB-backed SQL Lab
    # ----------------------------------------------------------------
    if st.session_state.sql_source == "Local dataset":
        if sql_lab.duckdb is None:
            st.warning("The `duckdb` package isn't installed. Run `pip install -r requirements.txt` and restart the app.")
        else:
            st.caption('Your active dataset is registered as a table named `data`. Any DuckDB SQL works.')

            examples = sql_lab.build_example_queries(df, column_types)
            st.markdown("**Example Queries**")
            example_cols = st.columns(len(examples))
            for ex_col, (label, example_sql) in zip(example_cols, examples.items()):
                with ex_col:
                    if st.button(label, key=f"sql_example_{label}", use_container_width=True):
                        st.session_state.sql_editor = example_sql

            st.text_area(
                "SQL query", key="sql_editor", height=140,
                placeholder="SELECT * FROM data LIMIT 10;",
            )

            run_col, explain_col = st.columns(2)
            with run_col:
                run_clicked = st.button("Run Query", type="primary", use_container_width=True)
            with explain_col:
                explain_clicked = st.button("Explain This Query", use_container_width=True)

            if run_clicked:
                query_text = st.session_state.sql_editor.strip()
                if not query_text:
                    st.warning("Write a query first — the editor is empty.")
                else:
                    sql_result, sql_error, sql_elapsed = sql_lab.run_query(df, query_text)
                    st.session_state.sql_result_df = sql_result
                    st.session_state.sql_error = sql_error
                    st.session_state.sql_exec_time = sql_elapsed

            if st.session_state.sql_error:
                st.error(st.session_state.sql_error)
            elif st.session_state.sql_result_df is not None:
                st.caption(
                    f"{len(st.session_state.sql_result_df):,} rows · "
                    f"{st.session_state.sql_exec_time * 1000:.1f} ms"
                )
                st.dataframe(st.session_state.sql_result_df, use_container_width=True)
            else:
                ui.render_empty_state(
                    "🗄️", "No query run yet", "Try an example query above, or write your own and click \"Run Query\"."
                )

            if explain_clicked:
                query_text = st.session_state.sql_editor.strip()
                if not query_text:
                    st.warning("Write a query first — the editor is empty.")
                else:
                    sql_gemini_model = ai_analyst.get_model()
                    if sql_gemini_model is None:
                        st.warning(ai_analyst.GEMINI_SETUP_HELP)
                    else:
                        with st.spinner(ui.get_loading_message()):
                            explanation, explain_error = ai_analyst.explain_sql(sql_gemini_model, query_text)
                        st.session_state.sql_explanation = explanation
                        st.session_state.sql_explanation_error = explain_error

            if st.session_state.sql_explanation_error:
                st.error(st.session_state.sql_explanation_error)
            elif st.session_state.sql_explanation:
                st.info(st.session_state.sql_explanation)

    # ----------------------------------------------------------------
    # MySQL database — live connection, opt-in, read-only by default.
    # Credentials are entered fresh each session and live only in
    # st.session_state (server-side memory) for as long as this browser
    # session is open; they're never written to disk, committed, or
    # included in "Save session" exports. See modules/sql_lab.py.
    # ----------------------------------------------------------------
    else:
        if not sql_lab.mysql_available():
            st.warning(
                "MySQL support needs the `sqlalchemy`, `pymysql`, and `cryptography` packages — "
                "run `pip install -r requirements.txt` and restart the app."
            )
        elif st.session_state.mysql_engine is None:
            st.caption(
                "Connect to a MySQL database for this session only. For safety, connect with a "
                "**read-only** MySQL user scoped to just the schema you need, rather than `root` — "
                "SQL Lab also blocks write queries by default regardless of the account's privileges."
            )
            with st.form("mysql_connect_form"):
                c1, c2 = st.columns([3, 1])
                host = c1.text_input("Host", placeholder="127.0.0.1")
                port = c2.number_input("Port", min_value=1, max_value=65535, value=sql_lab.MYSQL_DEFAULT_PORT)
                database = st.text_input("Database", placeholder="my_database")
                c3, c4 = st.columns(2)
                user = c3.text_input("Username", placeholder="root")
                password = c4.text_input("Password", type="password")
                connect_clicked = st.form_submit_button("Connect", type="primary", use_container_width=True)

            if connect_clicked:
                info = sql_lab.MySQLConnectionInfo(
                    host=host, port=int(port), database=database, user=user, password=password
                )
                with st.spinner("Connecting..."):
                    engine, connect_error = sql_lab.build_mysql_engine(info)
                if connect_error:
                    st.session_state.mysql_connect_error = connect_error
                else:
                    st.session_state.mysql_engine = engine
                    st.session_state.mysql_connect_error = None
                    st.session_state.mysql_connection_label = f"{user}@{host}:{int(port)}/{database}"
                    tables, tables_error = sql_lab.list_mysql_tables(engine)
                    st.session_state.mysql_tables = tables
                    if tables_error:
                        st.session_state.mysql_connect_error = tables_error
                    st.rerun()

            if st.session_state.mysql_connect_error:
                st.error(st.session_state.mysql_connect_error)

            if host == "127.0.0.1" or host == "localhost":
                st.info(
                    "Host is `127.0.0.1`/`localhost` — that only resolves if this Prism instance "
                    "itself is running on the same machine as MySQL. A Prism instance deployed on "
                    "Render (or anywhere else remote) can't reach a database on your own computer "
                    "at that address unless it's exposed via a tunnel or public endpoint."
                )
        else:
            st.success(f"Connected — `{st.session_state.mysql_connection_label}`")
            disc_col, _ = st.columns([1, 3])
            if disc_col.button("Disconnect", use_container_width=True):
                sql_lab.close_mysql_engine(st.session_state.mysql_engine)
                st.session_state.mysql_engine = None
                st.session_state.mysql_connection_label = None
                st.session_state.mysql_tables = []
                st.session_state.mysql_result_df = None
                st.session_state.mysql_query_error = None
                st.rerun()

            if st.session_state.mysql_tables:
                with st.expander(f"Tables ({len(st.session_state.mysql_tables)})"):
                    for table_name in st.session_state.mysql_tables:
                        if st.button(table_name, key=f"mysql_table_{table_name}", use_container_width=True):
                            st.session_state.mysql_sql_editor = f"SELECT *\nFROM `{table_name}`\nLIMIT 10;"

            st.text_area(
                "SQL query", key="mysql_sql_editor", height=140,
                placeholder="SELECT * FROM my_table LIMIT 10;",
            )

            st.session_state.mysql_allow_writes = st.checkbox(
                "Allow write queries (INSERT/UPDATE/DELETE/...)", value=st.session_state.mysql_allow_writes,
                help="Off by default. SQL Lab refuses anything that isn't a plain read unless this is checked.",
            )

            if st.button("Run Query", type="primary", use_container_width=True, key="mysql_run_query"):
                query_text = st.session_state.mysql_sql_editor.strip()
                if not query_text:
                    st.warning("Write a query first — the editor is empty.")
                else:
                    result_df, query_error, elapsed, truncated = sql_lab.run_mysql_query(
                        st.session_state.mysql_engine, query_text,
                        allow_writes=st.session_state.mysql_allow_writes,
                    )
                    st.session_state.mysql_result_df = result_df
                    st.session_state.mysql_query_error = query_error
                    st.session_state.mysql_exec_time = elapsed
                    st.session_state.mysql_truncated = truncated

            if st.session_state.mysql_query_error:
                st.error(st.session_state.mysql_query_error)
            elif st.session_state.mysql_result_df is not None:
                st.caption(
                    f"{len(st.session_state.mysql_result_df):,} rows · "
                    f"{st.session_state.mysql_exec_time * 1000:.1f} ms"
                )
                if st.session_state.mysql_truncated:
                    st.warning(f"Result truncated at {sql_lab.MYSQL_MAX_ROWS:,} rows.")
                st.dataframe(st.session_state.mysql_result_df, use_container_width=True)
            else:
                ui.render_empty_state(
                    "🗄️", "No query run yet",
                    "Pick a table above, or write your own query and click \"Run Query\"."
                )

# --------------------------------------------------------------------------
# AI Analyst tab — key insights + natural-language chat over the dataframe
# Backed by Google Gemini (see ai_analyst.MODEL_NAME). Key comes from a .env file
# (GEMINI_API_KEY) via python-dotenv — see README for setup.
# --------------------------------------------------------------------------
elif st.session_state.active_section == "AI Analyst":
    ui.render_help_expander(
        "Ask questions about your data in plain English — by typing or by voice — and get "
        "pandas-powered answers."
    )

    st.subheader("AI Analyst")

    gemini_model = ai_analyst.get_model()

    if gemini_model is None:
        st.warning(ai_analyst.GEMINI_SETUP_HELP)
    else:
        if st.button("Generate Key Insights"):
            skeleton = st.empty()
            with skeleton.container():
                # Shaped like the insight-card list about to replace it — a
                # skeleton previews what's coming, not just "something is
                # happening" (st.spinner's only real job).
                for _ in range(5):
                    ui.render_shimmer(height=52)
            quality_for_ai = data_engine.get_data_quality_report(df, column_types)
            _, top_corr_for_ai = visualization.plot_correlation_heatmap(df)
            insights, insight_error = ai_analyst.generate_key_insights(
                gemini_model, df, quality_for_ai, column_types, top_corr_for_ai
            )
            skeleton.empty()
            st.session_state.key_insights = insights
            st.session_state.key_insights_error = insight_error

        if st.session_state.key_insights_error:
            st.error(st.session_state.key_insights_error)
        elif st.session_state.key_insights:
            cards_html = "".join(
                f'<div class="insight-card"><div class="insight-number">FINDING {i + 1:02d}</div>'
                f'<div class="insight-text">{finding}</div></div>'
                for i, finding in enumerate(st.session_state.key_insights)
            )
            st.markdown(cards_html, unsafe_allow_html=True)

        st.divider()
        st.markdown("**Ask a question about your data**")
        st.caption(
            "Ask Atlas anything from the command bar at the top — by voice or by typing — and it "
            "lands here. Every question sends Gemini a compact metadata summary (dtypes, missing "
            "counts, numeric min/mean/max, categorical unique counts) plus a 3-row sample — never "
            "the full dataset."
        )

        if not st.session_state.chat_history:
            ui.render_empty_state(
                "💬", "No questions asked yet",
                'Ask Atlas from the command bar at the top — by voice or by typing — to start chatting with your data.',
            )

        for msg_idx, msg in enumerate(st.session_state.chat_history):
            if msg["role"] == "user":
                with st.chat_message("user"):
                    st.write(msg.get("content", ""))
            else:
                with st.chat_message("assistant"):
                    if msg.get("atlas_note"):
                        st.write(msg["atlas_note"])
                        continue

                    if msg.get("ask_error"):
                        st.error(msg["ask_error"])
                        continue

                    if msg.get("retried"):
                        st.caption(
                            f"First attempt failed ({msg.get('original_error')}) — "
                            "Gemini corrected it automatically."
                        )

                    if msg.get("code"):
                        with st.expander("View generated code"):
                            st.code(msg["code"], language="python")

                    if msg.get("error"):
                        st.error(msg["error"])
                        continue

                    result = msg.get("result")
                    if isinstance(result, (pd.DataFrame,)):
                        st.dataframe(result, use_container_width=True)
                    elif isinstance(result, pd.Series):
                        st.dataframe(result.to_frame(name="value"), use_container_width=True)
                    elif isinstance(result, (bool, np.bool_)):
                        st.write(result)
                    elif isinstance(result, (int, float, np.integer, np.floating)):
                        value = round(float(result), 4) if isinstance(result, (float, np.floating)) else result
                        st.metric(label=msg.get("question", "Result"), value=value)
                    elif result is not None:
                        _render_result_safely(result)

                    if msg.get("chart_fig") is not None:
                        st.plotly_chart(msg["chart_fig"], use_container_width=True, key=f"chat_chart_{msg_idx}")

# --------------------------------------------------------------------------
# Auto Analyst tab — agentic "Run Full Analysis": Gemini drafts an ordered
# plan, each step runs through the same safe-execution sandbox as the AI
# Analyst chat, then Gemini synthesizes the results into 5 headline findings.
# --------------------------------------------------------------------------
elif st.session_state.active_section == "Auto Analyst":
    ui.render_help_expander(
        "One click: Gemini plans an exploratory analysis (quality check, distributions, "
        "segments, correlations, time trends if applicable, conclusions), runs each step "
        "through the safe-execution sandbox, and summarizes the top findings."
    )

    st.subheader("Auto Analyst")

    auto_model = ai_analyst.get_model()

    if auto_model is None:
        st.warning(ai_analyst.GEMINI_SETUP_HELP)
    else:
        if st.button("Run Full Analysis", type="primary", use_container_width=True):
            plan = auto_analyst.generate_analysis_plan(auto_model, df, column_types)
            step_outcomes, findings, findings_error = _run_full_auto_analysis(auto_model, df, column_types, plan)

            st.session_state.auto_analyst_plan = plan
            st.session_state.auto_analyst_step_outcomes = step_outcomes
            st.session_state.auto_analyst_findings = findings
            st.session_state.auto_analyst_findings_error = findings_error
            st.balloons()

        if not st.session_state.auto_analyst_step_outcomes:
            ui.render_empty_state(
                "🤖", "No analysis yet",
                'Click "Run Full Analysis" above and Gemini will plan and run a full exploratory pass.',
            )
        else:
            st.divider()
            st.markdown("### Analysis Complete")

            if st.session_state.auto_analyst_findings_error:
                st.error(st.session_state.auto_analyst_findings_error)
            elif st.session_state.auto_analyst_findings:
                cards_html = "".join(
                    f'<div class="insight-card"><div class="insight-number">FINDING {i + 1:02d}</div>'
                    f'<div class="insight-text">{finding}</div></div>'
                    for i, finding in enumerate(st.session_state.auto_analyst_findings)
                )
                st.markdown(cards_html, unsafe_allow_html=True)

                if st.button("🎬 Story Mode", type="primary", use_container_width=True, key="enter_story_mode"):
                    # Story Mode (modules/story_mode.py) narrates
                    # st.session_state.key_insights — hand it this run's Auto
                    # Analyst findings so Atlas narrates what was just found here.
                    st.session_state.key_insights = st.session_state.auto_analyst_findings
                    st.session_state.key_insights_error = None
                    st.session_state.story_slide_index = 0
                    st.session_state.story_mode_active = True
                    st.rerun()

            st.divider()
            st.markdown("**Step-by-step results**")
            for i, outcome in enumerate(st.session_state.auto_analyst_step_outcomes, 1):
                with st.expander(f"Step {i}: {outcome['title']}", expanded=False):
                    st.caption(outcome["question"])

                    if outcome.get("ask_error"):
                        st.error(outcome["ask_error"])
                        continue

                    if outcome.get("retried"):
                        st.caption(
                            f"First attempt failed ({outcome.get('original_error')}) — "
                            "Gemini corrected it automatically."
                        )

                    if outcome.get("code"):
                        st.code(outcome["code"], language="python")

                    if outcome.get("error"):
                        st.error(outcome["error"])
                        continue

                    result = outcome.get("result")
                    if isinstance(result, pd.DataFrame):
                        st.dataframe(result, use_container_width=True)
                    elif isinstance(result, pd.Series):
                        st.dataframe(result.to_frame(name="value"), use_container_width=True)
                    elif result is not None:
                        _render_result_safely(result)

# --------------------------------------------------------------------------
# Stats Lab tab — guided statistical testing. Pick two columns, get a
# suggested test (t-test / ANOVA / chi-square / Pearson correlation) with a
# one-line reason, run it via scipy.stats, and see a plain-English verdict
# plus normality/assumption-check warnings.
# --------------------------------------------------------------------------
elif st.session_state.active_section == "Stats Lab":
    ui.render_help_expander(
        "Pick two columns and Stats Lab suggests the right statistical test, runs it via "
        "scipy.stats, and explains the result in plain English — with assumption-check warnings."
    )

    st.subheader("Stats Lab")

    testable_cols = [c for c, t in column_types.items() if t in ("numeric", "categorical")]
    if len(testable_cols) < 2:
        ui.render_empty_state(
            "🧪", "Not enough columns to test",
            "Stats Lab needs at least 2 numeric or categorical columns to suggest a test.",
        )
    else:
        sc1, sc2 = st.columns(2)
        with sc1:
            stats_col_a = st.selectbox("Column A", testable_cols, key="stats_col_a")
        with sc2:
            remaining_cols = [c for c in testable_cols if c != stats_col_a]
            stats_col_b = st.selectbox("Column B", remaining_cols, key="stats_col_b")

        suggestion = stats_lab.suggest_test(df, column_types, stats_col_a, stats_col_b)

        if suggestion.get("error"):
            st.warning(suggestion["error"])
        else:
            st.info(
                f"**Suggested test: {stats_lab.TEST_LABELS[suggestion['test']]}** — {suggestion['reason']}"
            )

            if st.button("Run Test", type="primary", use_container_width=True):
                st.session_state.stats_lab_result = stats_lab.run_test(df, suggestion)

            result = st.session_state.stats_lab_result
            if result is None:
                ui.render_empty_state("🧪", "No test run yet", 'Click "Run Test" above to see the verdict.')
            else:
                if result.get("error"):
                    st.error(result["error"])
                else:
                    st.markdown(f"**{stats_lab.interpret_result(result)}**")

                    rc1, rc2, rc3 = st.columns(3)
                    rc1.metric("Test statistic", f"{result['statistic']:.4f}")
                    rc2.metric("p-value", f"{result['p_value']:.4g}")
                    rc3.metric(result["effect_size_name"], f"{result['effect_size']:.4f}")

                    if "contingency_table" in result:
                        st.markdown("**Contingency table**")
                        st.dataframe(result["contingency_table"], use_container_width=True)

                    if "means" in result:
                        st.markdown("**Group means**")
                        means_df = pd.DataFrame(
                            {
                                "Group": list(result["means"].keys()),
                                "Mean": list(result["means"].values()),
                                "n": [result["groups"][g] for g in result["means"]],
                            }
                        )
                        st.dataframe(means_df, use_container_width=True, hide_index=True)

                    for warning_msg in stats_lab.normality_warnings(result):
                        st.warning(warning_msg)

# --------------------------------------------------------------------------
# Forecasting tab — only rendered when the dataset has a datetime column.
# Pick a datetime + numeric column, get a statsmodels forecast (Exponential
# Smoothing, falling back to SARIMAX) with a confidence band, a horizon
# slider, a downloadable CSV, and a plain-English reliability caveat.
# --------------------------------------------------------------------------
elif st.session_state.active_section == "Forecasting":
    ui.render_help_expander(
        "Pick a datetime + numeric column to project a forecast with a confidence band, "
        "using statsmodels (Exponential Smoothing, falling back to SARIMAX)."
    )

    st.subheader("Forecasting")

    numeric_cols_for_forecast = [c for c, t in column_types.items() if t == "numeric"]
    if not numeric_cols_for_forecast:
        ui.render_empty_state(
            "🔮", "No numeric column to forecast",
            "Forecasting needs at least one numeric column to project into the future.",
        )
    else:
        datetime_cols_for_forecast = [c for c, t in column_types.items() if t == "datetime"]

        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            forecast_dt_col = st.selectbox("Datetime column", datetime_cols_for_forecast, key="forecast_dt_col")
        with fc2:
            forecast_num_col = st.selectbox("Numeric column", numeric_cols_for_forecast, key="forecast_num_col")
        with fc3:
            forecast_horizon = st.slider("Horizon (periods)", min_value=7, max_value=90, value=30, key="forecast_horizon")

        if st.button("Generate Forecast", type="primary", use_container_width=True):
            series, freq, prep_error = forecasting.prepare_series(df, forecast_dt_col, forecast_num_col)
            if prep_error:
                st.session_state.forecast_result = None
                st.session_state.forecast_error = prep_error
            else:
                with st.spinner(ui.get_loading_message()):
                    forecast_outcome = forecasting.run_forecast(series, forecast_horizon, freq)
                if forecast_outcome.get("error"):
                    st.session_state.forecast_result = None
                    st.session_state.forecast_error = forecast_outcome["error"]
                else:
                    st.session_state.forecast_result = forecast_outcome
                    st.session_state.forecast_error = None

        if st.session_state.forecast_error:
            st.error(st.session_state.forecast_error)
        elif st.session_state.forecast_result is None:
            ui.render_empty_state(
                "🔮", "No forecast yet", 'Pick your columns and horizon, then click "Generate Forecast".'
            )
        else:
            forecast_outcome = st.session_state.forecast_result
            if forecast_outcome.get("warning"):
                st.caption(forecast_outcome["warning"])
            st.caption(f"Model used: {forecast_outcome['model_used']}")

            forecast_fig = forecasting.build_forecast_chart(
                forecast_outcome["history"], forecast_outcome["forecast"], f"{forecast_num_col} forecast"
            )
            st.plotly_chart(forecast_fig, use_container_width=True)

            st.info(
                forecasting.forecast_caveat(
                    len(forecast_outcome["history"]), len(forecast_outcome["forecast"]), forecast_outcome["model_used"]
                )
            )

            st.download_button(
                "Download Forecast CSV",
                data=forecast_outcome["forecast"].reset_index().to_csv(index=False).encode("utf-8"),
                file_name="prism_forecast.csv",
                mime="text/csv",
                use_container_width=True,
            )

# --------------------------------------------------------------------------
# Clustering tab — KMeans on standardized numeric columns with an
# elbow-method K suggestion, a 2D PCA scatter colored by cluster, and an
# optional Gemini pass to name/describe each segment in one line.
# --------------------------------------------------------------------------
elif st.session_state.active_section == "Clustering":
    ui.render_help_expander(
        "Pick numeric columns to segment your data with KMeans — an elbow-method suggestion "
        "picks K for you, and a 2D PCA scatter shows the resulting clusters."
    )

    st.subheader("Clustering & Segmentation")

    if len(df) < clustering.MIN_ROWS_FOR_CLUSTERING:
        st.warning(
            f"This dataset has only {len(df)} rows — clustering results below "
            f"{clustering.MIN_ROWS_FOR_CLUSTERING} rows can be unstable. Proceed with caution."
        )

    numeric_cols_for_cluster = [c for c, t in column_types.items() if t == "numeric"]
    if len(numeric_cols_for_cluster) < 2:
        ui.render_empty_state(
            "🧩", "Not enough numeric columns", "Clustering needs at least 2 numeric columns to segment your data."
        )
    else:
        selected_cluster_cols = st.multiselect(
            "Numeric columns to cluster on",
            numeric_cols_for_cluster,
            default=numeric_cols_for_cluster[: min(5, len(numeric_cols_for_cluster))],
            key="cluster_cols",
        )

        if len(selected_cluster_cols) < 2:
            st.info("Pick at least 2 numeric columns.")
        else:
            clean_row_count = df[selected_cluster_cols].dropna().shape[0]
            if clean_row_count < 4:
                st.error(
                    f"Only {clean_row_count} complete rows across the selected columns — "
                    "need at least 4 to cluster."
                )
            else:
                suggested_k, inertias = clustering.suggest_k(df, selected_cluster_cols)
                max_k = max(2, min(clustering.MAX_K, clean_row_count - 1))

                if inertias:
                    with st.expander("Elbow method chart", expanded=False):
                        st.plotly_chart(clustering.build_elbow_chart(inertias), use_container_width=True)

                k_choice = st.slider(
                    "Number of clusters (K)", min_value=2, max_value=max_k,
                    value=min(suggested_k, max_k), key="cluster_k",
                )
                st.caption(f"Elbow-method suggestion: K={min(suggested_k, max_k)}")

                if st.button("Run Clustering", type="primary", use_container_width=True):
                    st.session_state.cluster_result = clustering.run_clustering(df, selected_cluster_cols, k_choice)
                    st.session_state.cluster_segment_names = []
                    st.session_state.cluster_segment_error = None

                cluster_result = st.session_state.cluster_result
                if cluster_result is None:
                    ui.render_empty_state(
                        "🧩", "No clusters yet", 'Click "Run Clustering" above to segment this data.'
                    )
                else:
                    if cluster_result.get("error"):
                        st.error(cluster_result["error"])
                    else:
                        st.plotly_chart(
                            clustering.build_scatter(
                                cluster_result["scatter_df"], cluster_result["pca_explained_variance"]
                            ),
                            use_container_width=True,
                        )

                        st.markdown("**Cluster stats** (mean of each column, per cluster)")
                        st.dataframe(cluster_result["cluster_stats"], use_container_width=True)

                        if st.button("Name Segments with AI", key="name_segments_btn"):
                            cluster_model = ai_analyst.get_model()
                            if cluster_model is None:
                                st.warning(ai_analyst.GEMINI_SETUP_HELP)
                            else:
                                with st.spinner(ui.get_loading_message()):
                                    names, name_error = clustering.name_segments(
                                        cluster_model, cluster_result["cluster_stats"]
                                    )
                                st.session_state.cluster_segment_names = names
                                st.session_state.cluster_segment_error = name_error

                        if st.session_state.cluster_segment_error:
                            st.error(st.session_state.cluster_segment_error)
                        elif st.session_state.cluster_segment_names:
                            for segment_desc in st.session_state.cluster_segment_names:
                                st.info(segment_desc)

# --------------------------------------------------------------------------
# Domain Lens tab — map your columns to a domain's expected roles and get
# ready-made analytics: Product (retention, DAU/MAU, funnels, churn) or
# Banking (RFM, anomalies, NPA, credit utilization).
# --------------------------------------------------------------------------
elif st.session_state.active_section == "Domain Lens":
    ui.render_help_expander(
        "Map your columns to a domain's expected roles and get ready-made analytics: Product "
        "(retention, DAU/MAU, funnels, churn) or Banking (RFM, anomalies, NPA, credit utilization)."
    )

    st.subheader("Domain Lens")
    domain_mode = st.radio("Mode", ["Product Analytics", "Banking Analytics"], key="domain_mode", horizontal=True)

    all_domain_cols = df.columns.tolist()
    optional_col_choices = ["(none)"] + all_domain_cols

    if domain_mode == "Product Analytics":
        st.markdown("#### Column Mapper")
        pc1, pc2, pc3, pc4 = st.columns(4)
        with pc1:
            product_user_col = st.selectbox("User ID", all_domain_cols, key="product_user_col")
        with pc2:
            product_event_choice = st.selectbox("Event/Order column (optional)", optional_col_choices, key="product_event_col")
            product_event_col = None if product_event_choice == "(none)" else product_event_choice
        with pc3:
            product_timestamp_col = st.selectbox("Timestamp", all_domain_cols, key="product_timestamp_col")
        with pc4:
            product_revenue_choice = st.selectbox("Revenue (optional)", optional_col_choices, key="product_revenue_col")

        st.divider()
        st.markdown("#### Retention Cohorts")
        st.caption(domains.PRODUCT_METRIC_EXPLANATIONS["retention"])
        try:
            retention_df = domains.compute_retention_cohorts(df, product_user_col, product_timestamp_col)
            if retention_df.empty:
                st.info("Not enough date range in this column pair to build cohorts.")
            else:
                st.plotly_chart(domains.build_cohort_heatmap(retention_df), use_container_width=True)
        except Exception as e:
            st.error(f"Couldn't compute retention cohorts: {e}")

        st.divider()
        st.markdown("#### DAU / MAU & Stickiness")
        st.caption(domains.PRODUCT_METRIC_EXPLANATIONS["dau_mau"])
        try:
            dau_mau_df = domains.compute_dau_mau(df, product_user_col, product_timestamp_col)
            dm1, dm2 = st.columns(2)
            with dm1:
                st.plotly_chart(domains.build_dau_mau_chart(dau_mau_df), use_container_width=True)
            with dm2:
                st.plotly_chart(domains.build_stickiness_chart(dau_mau_df), use_container_width=True)
            st.metric("Average Stickiness", f"{dau_mau_df['stickiness'].mean() * 100:.1f}%")
        except Exception as e:
            st.error(f"Couldn't compute DAU/MAU: {e}")

        st.divider()
        st.markdown("#### Funnel Analysis")
        st.caption(domains.PRODUCT_METRIC_EXPLANATIONS["funnel"])
        if not product_event_col:
            ui.render_empty_state("🪜", "No event column mapped", "Map an Event/Order column above to build a funnel.")
        else:
            funnel_event_values = df[product_event_col].dropna().unique().tolist()
            funnel_stages = st.multiselect("Ordered stages (2-5)", funnel_event_values, key="funnel_stages")
            if len(funnel_stages) < 2:
                st.info("Pick at least 2 ordered stages (up to 5).")
            elif len(funnel_stages) > 5:
                st.warning("Pick at most 5 stages.")
            else:
                funnel_result = domains.compute_funnel(df, product_user_col, product_event_col, funnel_stages)
                st.plotly_chart(domains.build_funnel_chart(funnel_result, funnel_stages), use_container_width=True)
                st.dataframe(
                    pd.DataFrame(
                        {
                            "Stage": funnel_stages,
                            "Users": [funnel_result["stage_counts"][s] for s in funnel_stages],
                            "Conversion % (of first stage)": [funnel_result["conversion_pct"][s] for s in funnel_stages],
                            "Drop-off % (vs. previous)": [funnel_result["dropoff_pct"].get(s) for s in funnel_stages],
                        }
                    ),
                    use_container_width=True, hide_index=True,
                )

        st.divider()
        st.markdown("#### Churn Flag")
        st.caption(domains.PRODUCT_METRIC_EXPLANATIONS["churn"])
        churn_inactive_days = st.slider("Inactive for at least (days)", min_value=7, max_value=180, value=30, key="churn_inactive_days")
        try:
            churn_df = domains.flag_churn(df, product_user_col, product_timestamp_col, churn_inactive_days)
            cm1, cm2 = st.columns(2)
            cm1.metric("Churned Users", int(churn_df["churned"].sum()))
            cm2.metric("Churn Rate", f"{100 * churn_df['churned'].mean():.1f}%" if len(churn_df) else "—")
            st.dataframe(churn_df.sort_values("days_inactive", ascending=False), use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Couldn't compute churn: {e}")

    else:
        st.markdown("#### Column Mapper")
        bc1, bc2, bc3 = st.columns(3)
        with bc1:
            bank_customer_col = st.selectbox("Customer/Account ID", all_domain_cols, key="bank_customer_col")
        with bc2:
            bank_amount_col = st.selectbox("Transaction Amount", all_domain_cols, key="bank_amount_col")
        with bc3:
            bank_date_col = st.selectbox("Transaction Date", all_domain_cols, key="bank_date_col")

        bc4, bc5, bc6 = st.columns(3)
        with bc4:
            bank_loan_amount_choice = st.selectbox("Loan Amount (optional)", optional_col_choices, key="bank_loan_amount_col")
            bank_loan_amount_col = None if bank_loan_amount_choice == "(none)" else bank_loan_amount_choice
        with bc5:
            bank_overdue_choice = st.selectbox("Days Overdue (optional)", optional_col_choices, key="bank_overdue_col")
            bank_overdue_col = None if bank_overdue_choice == "(none)" else bank_overdue_choice
        with bc6:
            bank_limit_choice = st.selectbox("Credit Limit (optional)", optional_col_choices, key="bank_limit_col")
            bank_limit_col = None if bank_limit_choice == "(none)" else bank_limit_choice

        bank_balance_choice = st.selectbox(
            "Balance (optional, for credit utilization)", optional_col_choices, key="bank_balance_col"
        )
        bank_balance_col = None if bank_balance_choice == "(none)" else bank_balance_choice

        st.divider()
        st.markdown("#### RFM Segmentation")
        st.caption(domains.BANKING_METRIC_EXPLANATIONS["rfm"])
        try:
            rfm_df = domains.compute_rfm(df, bank_customer_col, bank_date_col, bank_amount_col)
            if rfm_df.empty:
                st.info("Not enough data to compute RFM segments.")
            else:
                st.plotly_chart(domains.build_rfm_segment_chart(rfm_df), use_container_width=True)
                st.dataframe(rfm_df, use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Couldn't compute RFM: {e}")

        st.divider()
        st.markdown("#### Transaction Anomalies")
        st.caption(domains.BANKING_METRIC_EXPLANATIONS["anomalies"])
        try:
            anomalies_df = domains.detect_transaction_anomalies(df, bank_customer_col, bank_amount_col, bank_date_col)
            if anomalies_df.empty:
                st.info("No anomalies flagged.")
            else:
                st.warning(f"{len(anomalies_df)} anomaly flag(s) found.")
                st.dataframe(anomalies_df, use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Couldn't detect anomalies: {e}")

        if bank_loan_amount_col and bank_overdue_col:
            st.divider()
            st.markdown("#### NPA / Overdue Analysis")
            st.caption(domains.BANKING_METRIC_EXPLANATIONS["npa"])
            try:
                npa_result = domains.compute_npa_ratio(df, bank_loan_amount_col, bank_overdue_col)
                n1, n2, n3 = st.columns(3)
                n1.metric("NPA Ratio", f"{npa_result['npa_ratio_pct']}%")
                n2.metric("NPA Loans", npa_result["npa_count"])
                n3.metric("Total Loans", npa_result["total_count"])
                bucket_counts = domains.compute_overdue_buckets(df, bank_overdue_col)
                st.plotly_chart(domains.build_overdue_bucket_chart(bucket_counts), use_container_width=True)
            except Exception as e:
                st.error(f"Couldn't compute NPA analysis: {e}")

        if bank_limit_col and bank_balance_col:
            st.divider()
            st.markdown("#### Credit Utilization")
            st.caption(domains.BANKING_METRIC_EXPLANATIONS["credit_utilization"])
            try:
                utilization = domains.compute_credit_utilization(df, bank_limit_col, bank_balance_col)
                if utilization.empty:
                    st.info("Not enough data to compute credit utilization.")
                else:
                    u1, u2 = st.columns(2)
                    u1.metric("Average Utilization", f"{utilization.mean():.1f}%")
                    u2.metric("Customers Over 30%", f"{100 * (utilization > 30).mean():.1f}%")
                    st.plotly_chart(domains.build_credit_utilization_chart(utilization), use_container_width=True)
            except Exception as e:
                st.error(f"Couldn't compute credit utilization: {e}")

# --------------------------------------------------------------------------
# Geo Lens tab (v5) — India choropleth. Detects a state/UT column by
# fuzzy-matching against modules.india's canonical list, lets the user pick
# a metric + aggregation, and renders a choropleth (data/india_states.geojson)
# plus a top-5/bottom-5 bar chart. See modules/geo.py for the matching and
# chart-building logic.
# --------------------------------------------------------------------------
elif st.session_state.active_section == "Geo Lens":
    ui.render_help_expander(
        "Pick a state/UT column and a metric — Geo Lens fuzzy-matches state names against "
        "the 28 states + 8 union territories and renders a choropleth of India."
    )
    st.subheader("Geo Lens")

    if not geo.is_geojson_available():
        ui.render_empty_state(
            "🗺️", "Map data unavailable", "data/india_states.geojson is missing — Geo Lens is skipped until it's restored."
        )
    else:
        state_candidates = geo.detect_state_columns(df, column_types)
        if not state_candidates:
            ui.render_empty_state(
                "🗺️", "No state/UT column detected",
                "None of this dataset's columns look like Indian state or union territory names.",
            )
        else:
            numeric_cols = [c for c, t in column_types.items() if t == "numeric"]
            if not numeric_cols:
                ui.render_empty_state(
                    "🗺️", "No numeric column to map", "Geo Lens needs at least one numeric column to aggregate by state."
                )
            else:
                gc1, gc2, gc3 = st.columns(3)
                with gc1:
                    state_col = st.selectbox(
                        "State / UT column", [c["column"] for c in state_candidates], key="geo_state_col",
                        format_func=lambda c: f"{c} ({next(sc['match_pct'] for sc in state_candidates if sc['column'] == c)}% matched)",
                    )
                with gc2:
                    metric_col = st.selectbox("Metric column", numeric_cols, key="geo_metric_col")
                with gc3:
                    agg = st.selectbox("Aggregation", ["sum", "mean", "count", "median"], key="geo_agg")

                fig, unmatched, state_totals = geo.build_choropleth(df, state_col, metric_col, agg)
                if fig is None:
                    st.error("Could not build the choropleth — the map data may be missing.")
                else:
                    map_col, bar_col = st.columns([3, 2])
                    with map_col:
                        st.plotly_chart(fig, use_container_width=True)
                    with bar_col:
                        bt_fig = geo.top_bottom_chart(state_totals, metric_col)
                        if bt_fig is not None:
                            st.plotly_chart(bt_fig, use_container_width=True)

                    if unmatched:
                        with st.expander(f"{len(unmatched)} unmatched value(s) — excluded from the map", expanded=False):
                            for value in unmatched:
                                st.caption(f"'{value}' — no confident match against a state/UT name")

    st.divider()
    st.markdown("#### ✨ Titan Enrichment")
    st.caption(
        "Merges free public weather data onto rows with a location + date, so a question like "
        "\"did rain affect sales that week\" is answerable without hunting down weather data yourself. "
        "Uses Open-Meteo — no API key, nothing sent to a third party beyond the location name and date range."
    )
    enrichment_candidates = enrichment.detect_enrichment_columns(df, column_types)
    if not enrichment_candidates:
        st.caption("No location + date column pair detected — nothing to enrich.")
    else:
        ec1, ec2 = st.columns(2)
        with ec1:
            enrich_location_col = st.selectbox(
                "Location column", [c["location_column"] for c in enrichment_candidates], key="enrich_location_col",
            )
        with ec2:
            matching_date_cols = [c["date_column"] for c in enrichment_candidates if c["location_column"] == enrich_location_col]
            enrich_date_col = st.selectbox("Date column", matching_date_cols, key="enrich_date_col")

        pii_flagged = pii_detector.flagged_columns(st.session_state.get("pii_findings") or {})
        blocked_cols = [c for c in (enrich_location_col, enrich_date_col) if c in pii_flagged]
        if st.session_state.pii_strict_mode and blocked_cols:
            st.warning(
                f"Strict mode is on and {', '.join(blocked_cols)} is flagged by the Indian PII Vault — "
                f"Titan Enrichment is blocked for this column, the same protection the AI Analyst gets. "
                f"Turn off Strict mode to proceed if you're confident this column is safe to send to Open-Meteo."
            )
        elif st.button("✨ Run Titan Enrichment", key="enrich_run_btn", use_container_width=True):
            with st.spinner(ui.get_loading_message()):
                enriched_df, enrich_report = enrichment.enrich_with_weather(df, enrich_location_col, enrich_date_col)
                st.session_state.working_df = enriched_df
                st.session_state.column_types = data_engine.detect_column_types(enriched_df)
                st.session_state.enrichment_report = enrich_report
                if enrich_report["locations_enriched"]:
                    log_step(
                        f"Titan Enrichment: merged weather for {len(enrich_report['locations_enriched'])} "
                        f"location(s) via '{enrich_location_col}' + '{enrich_date_col}'",
                        f"# Titan Enrichment ran interactively — geocoding + Open-Meteo weather lookup,\n"
                        f"# not reproducible as a static pandas script.",
                    )
                    st.toast(f"Enriched {enrich_report['rows_matched']} row(s) with weather data. ✨")
                st.rerun()

        if st.session_state.enrichment_report:
            rep = st.session_state.enrichment_report
            if rep["locations_enriched"]:
                st.success(
                    f"Weather merged for {len(rep['locations_enriched'])} location(s) — "
                    f"{rep['rows_matched']} row(s) matched. New columns: temp_max_c, temp_min_c, precipitation_mm."
                )
            if rep["locations_failed"]:
                st.caption(f"Couldn't resolve: {', '.join(rep['locations_failed'])}")
            if rep["locations_skipped_for_cap"]:
                st.caption(
                    f"{len(rep['locations_skipped_for_cap'])} additional distinct location(s) skipped — capped at "
                    f"{enrichment.MAX_DISTINCT_LOCATIONS} per run to stay quick and considerate of a free public API."
                )

# --------------------------------------------------------------------------
# ML Lab tab — the data-science bridge: a feature engineering assistant,
# a baseline model runner (Logistic/Linear Regression vs. Random Forest),
# and a class-imbalance detector with optional SMOTE. Baseline exploration
# only — never a deployed model.
# --------------------------------------------------------------------------
elif st.session_state.active_section == "ML Lab":
    ui.render_help_expander(
        "Pick a target column for feature-engineering suggestions, then run baseline "
        "Logistic/Linear Regression vs. Random Forest models — exploration only, not a deployed model."
    )

    st.subheader("ML Lab")
    st.info("**Baseline exploration only — not a deployed model.**")

    if len(df) < 100:
        st.warning(f"This dataset has only {len(df)} rows — baseline models may be unstable with so little data.")

    mllab_target_col = st.selectbox("Target column", df.columns.tolist(), key="mllab_target_col")

    if df[mllab_target_col].nunique() < 2:
        st.error(f"'{mllab_target_col}' has only 1 distinct value — pick a different target to train a model.")
    else:
        mllab_task_type = mllab.detect_task_type(df[mllab_target_col])
        st.caption(f"Detected task type: **{mllab_task_type.capitalize()}**")

        st.divider()
        st.markdown("#### Feature Engineering Assistant")
        feature_suggestions = mllab.suggest_features(df, column_types, mllab_target_col)
        if not feature_suggestions:
            ui.render_empty_state(
                "🛠️", "No suggestions", "No feature engineering suggestions for this target/column combination."
            )
        else:
            for suggestion_idx, suggestion in enumerate(feature_suggestions):
                cols_label = suggestion.get("column") or " & ".join(suggestion.get("columns", []))
                fcol1, fcol2 = st.columns([4, 1])
                with fcol1:
                    st.write(f"**{suggestion['type'].replace('_', ' ').title()}** — {cols_label}")
                    st.caption(suggestion["reason"])
                with fcol2:
                    if st.button("Apply", key=f"apply_feature_{suggestion_idx}", use_container_width=True):
                        push_undo_snapshot()
                        new_df, description, code = mllab.apply_suggestion(df, suggestion)
                        st.session_state.working_df = new_df
                        st.session_state.column_types = data_engine.detect_column_types(new_df)
                        log_step(description, code)
                        st.toast(f"{description}. 🛠️")
                        st.rerun()

        st.divider()
        st.markdown("#### Baseline Model Runner")

        mllab_feature_choices = [c for c in df.columns if c != mllab_target_col]
        mllab_selected_features = st.multiselect(
            "Feature columns", mllab_feature_choices,
            default=mllab_feature_choices[: min(8, len(mllab_feature_choices))], key="mllab_feature_cols",
        )

        mllab_use_smote = False
        if mllab_task_type == "classification":
            imbalance_info = mllab.check_class_imbalance(df[mllab_target_col])
            st.plotly_chart(mllab.build_class_distribution_chart(imbalance_info), use_container_width=True)
            if imbalance_info["is_imbalanced"]:
                st.warning(mllab.imbalance_explanation(imbalance_info))
                mllab_use_smote = st.checkbox("Apply SMOTE resampling to the training set", key="mllab_use_smote")
                st.caption(mllab.SMOTE_TEST_SET_NOTE)

        if not mllab_selected_features:
            st.info("Pick at least one feature column.")
        elif st.button("Run Baseline Models", type="primary", use_container_width=True):
            skeleton = st.empty()
            with skeleton.container():
                # Shaped like the two metric columns + charts about to
                # replace it, not just a generic spinner.
                shim1, shim2 = st.columns(2)
                with shim1:
                    ui.render_shimmer(height=80)
                with shim2:
                    ui.render_shimmer(height=80)
                ui.render_shimmer(height=220)
            st.session_state.mllab_shap_values = None  # a new model run invalidates any prior SHAP explanation
            st.session_state.mllab_shap_error = None
            try:
                st.session_state.mllab_result = mllab.run_baseline_models(
                    df, mllab_selected_features, mllab_target_col, mllab_task_type, use_smote=mllab_use_smote
                )
                st.session_state.mllab_error = None
            except Exception as e:
                st.session_state.mllab_result = None
                st.session_state.mllab_error = str(e)
            skeleton.empty()

        if st.session_state.mllab_error:
            st.error(st.session_state.mllab_error)
        elif st.session_state.mllab_result is None:
            ui.render_empty_state("🧬", "No model run yet", 'Pick feature columns and click "Run Baseline Models".')
        else:
            baseline_result = st.session_state.mllab_result
            st.caption(
                f"Trained on {baseline_result['n_train']} rows, tested on {baseline_result['n_test']} rows (80/20 split)."
            )

            if baseline_result["smote_before_after"]:
                sba = baseline_result["smote_before_after"]
                if "error" in sba:
                    st.warning(f"SMOTE couldn't be applied: {sba['error']}")
                else:
                    st.caption(f"SMOTE: training set went from {sba['before']} to {sba['after']}.")

            metric_cols = st.columns(2)
            for metric_col, (model_name, metrics) in zip(metric_cols, baseline_result["results"].items()):
                with metric_col:
                    st.markdown(f"**{model_name}**")
                    for metric_name, value in metrics.items():
                        st.metric(metric_name.upper(), value)

            st.success(mllab.build_verdict(baseline_result))

            if baseline_result["confusion_matrix"] is not None:
                st.plotly_chart(
                    mllab.build_confusion_matrix_chart(baseline_result["confusion_matrix"], baseline_result["confusion_labels"]),
                    use_container_width=True,
                )
            if baseline_result["feature_importances"] is not None:
                st.plotly_chart(
                    mllab.build_feature_importance_chart(baseline_result["feature_importances"]), use_container_width=True
                )

            st.divider()
            st.markdown("#### Explainability (SHAP)")
            st.caption(
                "Visual, per-feature explanation of the Random Forest model above — which features "
                "drive its predictions overall, and how each one pushed a single prediction up or down."
            )
            if st.button("Generate SHAP Explanations", key="mllab_shap_btn", use_container_width=True):
                with st.spinner(ui.get_loading_message()):
                    try:
                        st.session_state.mllab_shap_values = mllab.explain_with_shap(
                            baseline_result["fitted_rf_model"],
                            baseline_result["X_train_transformed"],
                            baseline_result["X_test_transformed"],
                            baseline_result["feature_names"],
                        )
                        st.session_state.mllab_shap_error = None
                    except Exception as e:
                        st.session_state.mllab_shap_values = None
                        st.session_state.mllab_shap_error = (
                            f"SHAP couldn't explain this Random Forest model: {e}"
                        )

            if st.session_state.mllab_shap_error:
                st.warning(st.session_state.mllab_shap_error)
            elif st.session_state.mllab_shap_values is not None:
                import matplotlib.pyplot as plt
                import shap

                display_values = mllab.shap_for_display(st.session_state.mllab_shap_values)

                st.markdown(f"**Summary Plot** — top {mllab.SHAP_MAX_DISPLAY} features, overall impact and direction")
                fig_summary = plt.figure()
                shap.summary_plot(display_values, max_display=mllab.SHAP_MAX_DISPLAY, show=False)
                st.pyplot(fig_summary, use_container_width=True)
                plt.close(fig_summary)

                st.markdown("**Waterfall Plot** — how each feature pushed the first test row's prediction")
                fig_waterfall = plt.figure()
                shap.plots.waterfall(display_values[0], max_display=mllab.SHAP_MAX_DISPLAY, show=False)
                st.pyplot(fig_waterfall, use_container_width=True)
                plt.close(fig_waterfall)

ui.render_footer()
