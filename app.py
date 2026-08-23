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
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st

from modules import (
    ai_analyst,
    anomaly,
    app_db,
    atlas,
    auto_analyst,
    auto_insights,
    autocleaner,
    causal_inference,
    cleaning,
    clustering,
    confounder_detection,
    dashboard_builder,
    data_dictionary,
    data_engine,
    dataset_knowledge,
    datetime_intel,
    db_connect,
    detector_runner,
    domains,
    drift,
    enrichment,
    experiment_design,
    forecasting,
    geo,
    hellmode,
    hypothesis_sweep,
    india,
    insight_orchestrator,
    insight_verifier,
    join_engine,
    mllab,
    pii_detector,
    profiling,
    recipes,
    regression_diagnostics,
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

try:
    from streamlit_ace import st_ace
except ImportError:  # optional dependency — SQL Lab falls back to a plain st.text_area if it's missing
    st_ace = None

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
    "key_insights_verification": [],  # insight_verifier.verify_findings() result for key_insights, same order/length
    "auto_insights": None,  # list of auto-detected insight dicts (run on upload)
    "auto_insights_narration": None,  # Gemini-narrated executive summary of auto-insights
    "auto_insights_narration_verification": None,  # auto_insights.verify_narration() result for the narration above
    "confounder_scan": None,  # confounder_detection.auto_scan_for_confounding() result (run on upload)
    "confounder_narrations": {},  # (x, y, confounder) -> cached Gemini narration text, avoids re-spending a call per rerun
    "causal_result": None,  # last causal_inference.estimate_causal_effect() result dict (kept across reruns so the panel doesn't collapse)
    "causal_narration": None,  # cached Gemini narration of causal_result, avoids re-spending a call per rerun
    "cate_result": None,  # last causal_inference.estimate_cate_by_subgroup() result dict (kept across reruns so the panel doesn't collapse)
    "cate_narration": None,  # cached Gemini narration of cate_result, avoids re-spending a call per rerun
    "orchestration_narration": None,  # cached Gemini narration of the Agent Summary panel's ranked "what matters most" list
    "orchestration_narration_fingerprint": None,  # insight_orchestrator.fingerprint_result() covered by the narration above
    "orchestration_narration_verification": None,  # insight_orchestrator.verify_narration() result for the narration above
    "atlas_orchestration_alert_fingerprint": None,  # fingerprint of the last orchestration result Atlas proactively spoke up about (see _maybe_announce_orchestration())
    "atlas_orchestration_alert_tier2_fingerprint": None,  # separate fingerprint tracker for the tier-2 lone-confounder-paradox alert (see _maybe_announce_orchestration())
    "regression_diag_result": None,  # fit_ols() result dict for the Regression Diagnostics panel
    "regression_diag_error": None,  # error from the last diagnostics fit attempt, if any
    "manual_chart_fig": None,  # last chart built via the Visualize tab's manual mode
    "manual_chart_error": None,  # error message from the last manual-chart build attempt, if any
    "last_file_name": None,  # detects a new upload vs. a plain rerun; also used in exports
    "sql_lab_tabs": [{"id": "t1", "name": "Query 1", "sql": ""}],  # SQL Lab's open query tabs
    "sql_lab_active_tab_id": "t1",  # which sql_lab_tabs entry the editor is currently showing
    "sql_lab_tabs_rev": 0,  # bumped whenever a tab is added/closed, to force the tab-picker widget to remount
    "sql_lab_editor_rev": 0,  # bumped whenever SQL text is injected programmatically (example/NL2SQL/saved/
                              # history/fix-suggestion), to force the editor widget to remount with the new
                              # text — Streamlit forbids writing a widget's session_state key once that widget
                              # has rendered this run, so a fresh key is the reliable way to push in new content
                              # regardless of where the triggering button sits relative to the editor on the page
    "sql_lab_extra_tables": {},  # name -> DataFrame, tables registered in SQL Lab beyond "data"; session-only, never persisted
    "sql_result_df": None,  # last successful query result
    "sql_error": None,  # last query's error message, if any
    "sql_exec_time": None,  # last query's execution time in seconds
    "sql_lab_truncated": False,  # True if the last result was cut down to sql_lab.DEFAULT_ROW_CAP rows
    "sql_lab_row_count_full": 0,  # untruncated row count of the last result, for the truncation notice
    "sql_explanation": "",  # last "Explain this query" output
    "sql_explanation_error": None,  # error from the last "Explain this query" attempt, if any
    "sql_lab_fix_suggestion": "",  # last "Suggest a Fix" output
    "sql_lab_fix_error": None,  # error from the last "Suggest a Fix" attempt, if any
    "sql_lab_gen_sql_question": "",  # NL-to-SQL question box text
    "sql_lab_explain_plan": None,  # last "Analyze Performance" EXPLAIN ANALYZE output
    "sql_lab_explain_error": None,  # error from the last "Analyze Performance" attempt, if any
    "sql_lab_history": [],  # [{"sql","status","elapsed_seconds","rows","timestamp"}], newest first, capped at 50
    "sql_lab_saved_queries": [],  # [{"name","sql"}] loaded/saved this session via the Saved Queries expander
    "sql_lab_assertions": [],  # current editable Data Tests suite — list of assertion specs (see sql_lab.run_assertions)
    "sql_lab_assertion_results": [],  # last "Run Test Suite" pass/fail/error results
    "db_connection": None,  # {"engine_type","params","params_key","status","error"} or None if never connected —
                             # session-level, like sql_lab_tabs, NOT dataset-scoped like sql_lab_extra_tables, so it
                             # deliberately survives a set_active_dataset() swap; only "Disconnect" clears it
    "db_connection_tables": [],  # cached list of live table names (db_connect.get_live_table_names), refreshed on connect
    "db_connection_table_schemas": {},  # {table_name: "col (dtype), ..."} sampled once at connect — feeds Atlas's
                                         # generate_sql() prompt for live-only tables the local dataset knows nothing about
    "db_pending_confirm_sql": None,  # SQL staged by the manual-UI destructive-statement gate, awaiting confirm —
                                      # DOES reset on a dataset swap (stale staged SQL against a replaced context shouldn't fire)
    "visitor_id": None,  # anonymous per-browser identity for MySQL-backed persistence (saved
                          # queries/recipes/session snapshots) — resolved once per session by
                          # modules.app_db.get_visitor_id() from a long-lived cookie (or a fresh
                          # uuid4, written back via a components.html() cookie-setter); NOT
                          # re-read from st.context.cookies after that first resolution, since
                          # cookies are only snapshotted at WebSocket-connect time
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
    "anomaly_narration": None,  # Gemini-narrated explanation of the last flagged anomaly set
    "anomaly_narration_fingerprint": None,  # anomaly.fingerprint_flagged() of the set the narration above covers
    "anomaly_narration_verification": None,  # anomaly.verify_narration() result for the narration above
    "anomaly_methods_summary": None,  # per-method flagged counts from the last ensemble "Find Anomalies" run, if any
    "anomaly_driver_narration": None,  # Gemini-narrated explanation of the last anomaly-drivers result
    "anomaly_driver_narration_fingerprint": None,  # anomaly.fingerprint_drivers() of the drivers the narration above covers
    "anomaly_driver_narration_verification": None,  # anomaly.verify_narration() result for the narration above
    "auto_analyst_plan": None,  # last "Run Full Analysis" plan — list of {"title", "question"}
    "auto_analyst_step_outcomes": [],  # per-step results from the last Auto Analyst run
    "auto_analyst_findings": [],  # last Auto Analyst "top 5 findings" synthesis
    "auto_analyst_findings_error": None,  # error from the last findings synthesis, if any
    "auto_analyst_verification": [],  # per-finding fact-check results from modules.insight_verifier
    "stats_lab_result": None,  # last "Run Test" result dict from Stats Lab
    "hypothesis_sweep_result": None,  # last "Run Hypothesis Sweep" result dict from Stats Lab
    "hypothesis_sweep_narration": None,  # Gemini-narrated explanation of the last sweep's findings
    "hypothesis_sweep_narration_fingerprint": None,  # hypothesis_sweep.fingerprint_sweep() covered by the narration above
    "hypothesis_sweep_narration_verification": None,  # hypothesis_sweep.verify_narration() result for the narration above
    "hypothesis_sweep_confounder_check": None,  # hypothesis_sweep.cross_check_confounders() result for the last sweep
    "hypothesis_sweep_confounder_narrations": {},  # cache of confounder_detection.narrate_confounder_finding() results, keyed like confounder_narrations
    "hypothesis_sweep_interaction_check": None,  # hypothesis_sweep.cross_check_interactions() result for the last sweep
    "hypothesis_sweep_categorical_interaction_check": None,  # hypothesis_sweep.cross_check_categorical_interactions() result for the last sweep
    "detector_runner_last_ran": [],  # detector names fired by the last "Run All Detectors" click (modules/detector_runner.py), for a one-line confirmation caption
    "detector_runner_last_skipped": [],  # [{"detector","reason"}, ...] from that same click
    "mllab_feature_selection_result": None,  # last "Run Feature Selection" result dict from ML Lab
    "forecast_result": None,  # last "Generate Forecast" result dict from Forecasting
    "forecast_error": None,  # error from the last forecast attempt, if any
    "stl_decomp_result": None,  # forecasting.decompose_series() output for the STL Decomposition panel
    "stl_decomp_error": None,  # error from the last decomposition attempt, if any
    "changepoint_result": None,  # forecasting.detect_changepoints() output for the Structural Breaks panel
    "changepoint_error": None,  # error from the last changepoint-detection attempt, if any
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
    "atlas_orb_state": "idle",  # "idle" | "listening" | "processing" | "speaking" | "alert"
    "atlas_alert_count": 0,  # how many high-severity Auto-Insights triggered the current "alert" orb state
    "atlas_alert_fresh": False,  # one-run grace flag — see atlas.clear_alert()'s docstring
    "atlas_pending_confirmation": None,  # {action, target, message, approved} — see atlas.guarded()
    "atlas_greeted": False,  # plays the on-load greeting exactly once per session
    "_atlas_anomaly_mentioned_this_session": False,  # gates announce_ambient_insights' proactive
                                                       # anomaly mention to at most once per session
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
theme.sync_native_theme(st.session_state.theme_mode)

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
    st.session_state.key_insights_verification = []
    st.session_state.sql_result_df = None
    st.session_state.sql_error = None
    st.session_state.sql_explanation = ""
    st.session_state.sql_explanation_error = None
    st.session_state.sql_lab_truncated = False
    st.session_state.sql_lab_row_count_full = 0
    st.session_state.sql_lab_extra_tables = {}  # registered against the *previous* dataset — stale, drop them
    st.session_state.sql_lab_explain_plan = None
    st.session_state.sql_lab_explain_error = None
    st.session_state.sql_lab_fix_suggestion = ""
    st.session_state.sql_lab_fix_error = None
    st.session_state.db_pending_confirm_sql = None  # staged against the *previous* context — stale, drop it
    # NOTE: sql_lab_tabs/_history/_saved_queries/_assertions are deliberately
    # NOT reset here — authored query/test content, same as cleaning_log and
    # recipes surviving a dataset swap elsewhere in this function. db_connection/
    # db_connection_tables are ALSO deliberately not reset — a live DB connection
    # isn't dataset-scoped (see its _DEFAULTS comment); only "Disconnect" clears it.
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
    st.session_state.hypothesis_sweep_result = None
    st.session_state.hypothesis_sweep_narration = None
    st.session_state.hypothesis_sweep_narration_fingerprint = None
    st.session_state.hypothesis_sweep_narration_verification = None
    st.session_state.hypothesis_sweep_confounder_check = None
    st.session_state.hypothesis_sweep_confounder_narrations = {}
    st.session_state.hypothesis_sweep_interaction_check = None
    st.session_state.hypothesis_sweep_categorical_interaction_check = None
    st.session_state.detector_runner_last_ran = []
    st.session_state.detector_runner_last_skipped = []
    st.session_state.mllab_feature_selection_result = None
    st.session_state.forecast_result = None
    st.session_state.forecast_error = None
    st.session_state.stl_decomp_result = None
    st.session_state.stl_decomp_error = None
    st.session_state.changepoint_result = None
    st.session_state.changepoint_error = None
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
    st.session_state.regression_diag_result = None
    st.session_state.regression_diag_error = None
    st.session_state.enrichment_report = None
    st.session_state.chaos_result = None
    st.session_state.data_dictionary_rows = None
    st.session_state.auto_insights = auto_insights.generate_insights(working_df, st.session_state.column_types)
    st.session_state.auto_insights_narration = None
    st.session_state.auto_insights_narration_verification = None
    st.session_state.confounder_scan = confounder_detection.auto_scan_for_confounding(working_df, st.session_state.column_types)
    st.session_state.confounder_narrations = {}
    st.session_state.causal_result = None
    st.session_state.causal_narration = None
    st.session_state.cate_result = None
    st.session_state.cate_narration = None
    st.session_state.anomaly_result_df = None
    st.session_state.anomaly_error = None
    st.session_state.anomaly_narration = None
    st.session_state.anomaly_narration_fingerprint = None
    st.session_state.anomaly_narration_verification = None
    st.session_state.anomaly_methods_summary = None
    st.session_state.anomaly_driver_narration = None
    st.session_state.anomaly_driver_narration_fingerprint = None
    st.session_state.anomaly_driver_narration_verification = None
    st.session_state.orchestration_narration = None
    st.session_state.orchestration_narration_fingerprint = None
    st.session_state.orchestration_narration_verification = None
    st.session_state.sample_info = None
    st.session_state.autocleaner_report = None
    st.session_state.autocleaner_review_queue = []
    st.session_state.autocleaner_snapshot = None
    st.session_state.last_file_name = source_name


def sql_lab_active_tab() -> dict:
    """The sql_lab_tabs entry the editor is currently showing. Falls back to
    the first tab if sql_lab_active_tab_id ever points at a closed one."""
    for t in st.session_state.sql_lab_tabs:
        if t["id"] == st.session_state.sql_lab_active_tab_id:
            return t
    return st.session_state.sql_lab_tabs[0]


def sql_lab_all_tables() -> dict:
    """{"data": active dataframe} plus every table registered via SQL Lab's
    "Registered Tables" expander — the full table set any query/assertion/
    EXPLAIN call should run against."""
    tables = {"data": st.session_state.working_df}
    tables.update(st.session_state.sql_lab_extra_tables)
    return tables


def sql_lab_live_backend() -> Optional[str]:
    """None if no live connection, else the connected engine_type
    ("mysql"/"postgres"/"sqlite"/"sqlserver") — the single choke-point every
    SQL-executing call site checks to decide which executor to use."""
    conn = st.session_state.db_connection
    return conn["engine_type"] if conn else None


def sql_lab_attach_info() -> Optional[dict]:
    """None if no live DuckDB-attachable connection (no connection at all,
    or a SQL Server one — that engine has its own separate SQLAlchemy
    executor, db_connect.run_live_query_sqlserver), else
    {"attach_clause","attach_extension"} ready to spread into
    sql_lab.run_query_multi(..., attach_clause=..., attach_extension=...) /
    sql_lab.explain_query(..., attach_clause=..., attach_extension=...).
    Builds a fresh clause every call (cheap string formatting) rather than
    caching it — see modules/db_connect.py's docstring for why the actual
    query path never reuses the cached connection object either.
    """
    conn = st.session_state.db_connection
    if not conn or conn["engine_type"] not in db_connect.DUCKDB_ATTACH_ENGINES:
        return None
    return {
        "attach_clause": db_connect.build_attach_clause(conn["engine_type"], conn["params"], alias="live"),
        "attach_extension": db_connect.extension_for_engine(conn["engine_type"]),
    }


def sql_lab_run_query(sql: str, timeout_seconds=None, row_cap=None) -> dict:
    """Single choke-point for running a query in SQL Lab or from Atlas —
    picks the SQL Server executor or the local/DuckDB-attach executor based
    on the current connection, so every call site (manual Run Query, Atlas
    single/multi, the destructive-gate re-entry) shares one branch instead
    of repeating the if/else everywhere."""
    backend = sql_lab_live_backend()
    if backend == "sqlserver":
        engine = db_connect.get_sqlserver_engine(st.session_state.db_connection["params_key"])
        kwargs = {}
        if timeout_seconds is not None:
            kwargs["timeout_seconds"] = timeout_seconds
        if row_cap is not None:
            kwargs["row_cap"] = row_cap
        return db_connect.run_live_query_sqlserver(engine, sql, **kwargs)
    attach = sql_lab_attach_info() or {}
    kwargs = dict(attach)
    if timeout_seconds is not None:
        kwargs["timeout_seconds"] = timeout_seconds
    if row_cap is not None:
        kwargs["row_cap"] = row_cap
    return sql_lab.run_query_multi(sql_lab_all_tables(), sql, **kwargs)


def sql_lab_live_schema_note() -> str:
    """Short plain-text note describing the live-connected tables, meant to
    be appended to the natural-language question passed into
    ai_analyst.generate_sql()/generate_sql_plan(). Those functions only ever
    describe the local active dataset (`df_`/`column_types_`) — without this,
    Atlas has no idea `live.<table>` exists or what columns it has, and can
    only ever generate SQL against the locally uploaded data. Returns ""
    when there's no live connection (the common case), so call sites can
    unconditionally append it without an extra branch."""
    conn = st.session_state.db_connection
    schemas = st.session_state.db_connection_table_schemas
    if not conn or not schemas:
        return ""
    label = db_connect.ENGINE_LABELS.get(conn["engine_type"], conn["engine_type"])
    lines = [f'A live {label} connection is also attached as `live` — reference its tables as `"live"."<table>"`. Tables available:']
    for tname, cols in schemas.items():
        lines.append(f'- "{tname}": {cols}')
    return "\n".join(lines)


def _db_connection_expander_label() -> str:
    conn = st.session_state.db_connection
    if not conn:
        return "🔌 Database Connection"
    label = db_connect.ENGINE_LABELS.get(conn["engine_type"], conn["engine_type"])
    return f"🔌 Database Connection — Connected ({label})"


def _materialize_sqlite_upload(uploaded_file) -> str:
    """Writes an uploaded .sqlite/.db file to a stable temp path (same
    content -> same path, via a content hash) so DuckDB's sqlite ATTACH,
    which needs a real filesystem path rather than bytes, can read it.
    Re-uploads of the same bytes reuse the same file instead of piling up
    temp files across reruns."""
    import hashlib
    import tempfile
    from pathlib import Path

    content = uploaded_file.getvalue()
    digest = hashlib.sha256(content).hexdigest()[:16]
    path = Path(tempfile.gettempdir()) / f"prism_sqlite_{digest}.db"
    if not path.exists():
        path.write_bytes(content)
    return str(path)


ATLAS_SQL_TAB_ID = "atlas_sql"  # reserved tab id, never matches a user-created
                                 # tab's f"t{uuid.uuid4().hex[:8]}" pattern or "t1"


def _write_atlas_sql_tab(sql: str, name: str) -> None:
    """Create-or-update the reserved Atlas SQL tab and make it active. Not
    the SQL Lab branch's local _sql_lab_inject() closure — that one also
    calls st.rerun() itself, which would double-rerun here since this is
    called from _process_atlas_sql_question, itself called from
    _process_atlas_utterance which already reruns once at its own end.
    Falls through to re-creating the tab if the user had closed it via
    SQL Lab's "✕ Close" button — it's an ordinary sql_lab_tabs entry once
    created, closeable like any other.
    """
    existing = next((t for t in st.session_state.sql_lab_tabs if t["id"] == ATLAS_SQL_TAB_ID), None)
    if existing is None:
        st.session_state.sql_lab_tabs.append({"id": ATLAS_SQL_TAB_ID, "name": name, "sql": sql})
        st.session_state.sql_lab_tabs_rev += 1  # only on create — remounts the tab picker with the new option
    else:
        existing["sql"] = sql
        existing["name"] = name
    st.session_state.sql_lab_active_tab_id = ATLAS_SQL_TAB_ID
    st.session_state.sql_lab_editor_rev += 1  # always — forces the ace editor widget to remount with new text


def _post_sql_lab_result(run_result: dict) -> None:
    """Populate the exact session_state keys SQL Lab's own "Run Query"
    button sets, so jumping there shows the result table immediately
    instead of an empty "No query run yet" panel — used by every path
    that runs a query outside that button's own click handler (Atlas
    single/multi, the live destructive-gate re-entry)."""
    st.session_state.sql_result_df = run_result["result_df"]
    st.session_state.sql_error = run_result["error"]
    st.session_state.sql_exec_time = run_result["elapsed_seconds"]
    st.session_state.sql_lab_truncated = run_result["truncated"]
    st.session_state.sql_lab_row_count_full = run_result["row_count_full"]


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
        sample_df, data_engine.get_data_quality_report(sample_df, st.session_state.column_types),
        st.session_state.column_types,
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

    verification = insight_verifier.verify_findings(df_, column_types_, findings) if findings else []
    st.session_state.auto_analyst_verification = verification

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


def announce_ambient_insights(df, quality: dict, column_types: dict) -> None:
    """Item 5 (ambient insights) — after ANY fresh dataset load, Atlas
    proactively summarizes row/column count, the two most important quality
    findings, and one suggested next action, ending with a question. A
    "yes"/"do it" reply then routes through the normal intent router as a
    'confirm' for whichever guarded command that question implies.

    Also folds in a proactive anomaly mention (gated once per session AND
    severe-only — IsolationForest's default contamination=0.05 flags ~5% of
    rows on almost any dataset with numeric variance, so an unfiltered
    mention would fire on nearly every load, including clean data; only a
    row deviating heavily — >=3x its column's median — is worth a spoken
    interruption).
    """
    findings = []
    if quality["total_missing_pct"] > 0:
        findings.append(f"{quality['total_missing_pct']}% of cells missing")
    if quality["duplicate_rows"] > 0:
        findings.append(f"{quality['duplicate_rows']} duplicate row(s)")
    if quality["all_null_columns"]:
        findings.append(f"{len(quality['all_null_columns'])} fully empty column(s)")

    anomaly_note = None
    if (
        not st.session_state.get("_atlas_anomaly_mentioned_this_session")
        and anomaly.is_available()
        and len(df) >= anomaly.MIN_ROWS_REQUIRED
    ):
        flagged, _anomaly_error = anomaly.find_anomalies(df, column_types)
        if flagged is not None and not flagged.empty:
            ratios = [
                float(m.group(1)) for r in flagged["anomaly_reason"] if (m := re.search(r"(\d+\.\d+)x", r))
            ]
            if ratios and max(ratios) >= 3.0:
                anomaly_note = f"one row looks like a real outlier ({max(ratios):.1f}x its column's median)"
                st.session_state._atlas_anomaly_mentioned_this_session = True

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
    if anomaly_note:
        summary += f" Also, {anomaly_note} — worth a look."
    atlas.say_only(summary)

    # JARVIS-copilot proactive alert: light the orb up unprompted if the
    # Auto-Insight scan (already computed by set_active_dataset(), no extra
    # Gemini call here) found anything high-severity. Runs after say_only()
    # above so it's the state the orb actually renders in this rerun.
    n_high = sum(1 for ins in (st.session_state.auto_insights or []) if ins["severity"] == "high")
    atlas.raise_alert(n_high)


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


def _anomaly_orchestrator_summary() -> Optional[dict]:
    """Reduce the last "Find Anomalies" result (a DataFrame, possibly from
    either the single-method or ensemble detector) down to the small,
    pandas-free summary modules.insight_orchestrator's anomaly adapter
    expects — the orchestrator never touches a DataFrame directly."""
    flagged = st.session_state.anomaly_result_df
    if flagged is None or flagged.empty:
        return None
    working = st.session_state.working_df
    total_rows = len(working) if working is not None else len(flagged)
    reasons = flagged["anomaly_reason"].tolist() if "anomaly_reason" in flagged.columns else []
    return {"count": int(len(flagged)), "total_rows": int(total_rows), "reasons": reasons}


def _build_orchestration_input() -> dict:
    """Assemble the already-computed findings from every detector Overview
    surfaces into the dict shape modules.insight_orchestrator.orchestrate_
    insights() expects. Nothing here re-runs detection — auto_insights and
    confounder_scan are computed once on upload (set_active_dataset()); the
    causal/anomaly/drift/verifier entries are whatever the user has already
    triggered via their own panels this session (None/empty until then,
    which is fine — the orchestrator stays silent below the detector-count
    threshold). The verifier entry is Auto Analyst's own insight_verifier
    safety net (Auto Analyst tab) feeding into the same synthesis as the
    Overview-tab detectors, so a flagged (numeric-claim-didn't-match)
    finding surfaces here too instead of staying siloed on a different tab.
    The hypothesis_sweep entry is Stats Lab's automated, FDR-corrected
    pairwise test sweep (None/empty until the user has run one) — a formal
    hypothesis test independently re-deriving a relationship auto_insights
    only flagged via a raw correlation scan is exactly the kind of
    cross-detector agreement this orchestrator exists to surface."""
    return {
        "auto_insights": st.session_state.auto_insights,
        "confounder": st.session_state.confounder_scan,
        "causal_att": st.session_state.causal_result,
        "causal_cate": st.session_state.cate_result,
        "anomaly": _anomaly_orchestrator_summary(),
        "drift": st.session_state.drift_result,
        "hypothesis_sweep": st.session_state.hypothesis_sweep_result,
        "verifier": {
            "findings": st.session_state.auto_analyst_findings,
            "verification": st.session_state.auto_analyst_verification,
            "columns": list(st.session_state.column_types.keys()) if st.session_state.column_types else [],
        },
    }


def _maybe_announce_orchestration(orchestration) -> None:
    """JARVIS-copilot proactive slice: the moment the Agent Summary
    orchestration's #1 finding becomes a genuinely new cross-detector
    agreement or contradiction, Atlas says so unprompted — no need to open
    the Overview tab or click "Generate Executive Summary" first. Thin
    wiring only; the actual decision (what counts as "new", which findings
    are worth interrupting for) lives in
    insight_orchestrator.proactive_alert_text(), which is plain data logic
    and unit-tested on its own. Called every rerun once a dataset is
    active (see below), so it fires regardless of which tab is currently
    open — e.g. running the Causal Effect Estimator on its own tab can
    trigger this without ever visiting Overview.
    """
    alert = insight_orchestrator.proactive_alert_text(
        orchestration, st.session_state.atlas_orchestration_alert_fingerprint
    )
    if alert is not None:
        st.session_state.atlas_orchestration_alert_fingerprint = alert["fingerprint"]
        atlas.say_only(alert["text"])
        atlas.raise_alert(1)
        return

    # Tier 2: a lone high-severity confounder paradox — the one detector that
    # runs silently on every upload with no proactive alert of its own (see
    # insight_orchestrator.proactive_alert_text_tier2()'s docstring). Checked
    # only when tier 1 didn't already speak up this rerun, so Atlas never
    # says two things in the same pass.
    tier2_alert = insight_orchestrator.proactive_alert_text_tier2(
        orchestration, st.session_state.atlas_orchestration_alert_tier2_fingerprint
    )
    if tier2_alert is None:
        return
    st.session_state.atlas_orchestration_alert_tier2_fingerprint = tier2_alert["fingerprint"]
    atlas.say_only(tier2_alert["text"])
    atlas.raise_alert(1)


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


def _cmd_save_sql_query(target) -> None:
    """Voice/typed "save this as X" — saves the query currently in SQL
    Lab's active tab into sql_lab_saved_queries (the session-durable list
    backing the Saved Queries expander's "This session" buttons), NOT the
    download-button JSON path — a server-side handler can't trigger a
    browser file-save dialog without a click, so this is the only path
    that can make a voice save feel instant.
    """
    if st.session_state.working_df is None:
        atlas.say_only("Upload data first and I'll get to work.")
        return
    sql = sql_lab_active_tab()["sql"].strip()
    if not sql:
        atlas.say_only("There's nothing in the SQL editor yet to save.")
        return
    name = (target or "").strip() or f"Atlas query {len(st.session_state.sql_lab_saved_queries) + 1}"
    existing_names = {q["name"] for q in st.session_state.sql_lab_saved_queries}
    if name in existing_names:
        # the Saved Queries UI keys each button by name — an unguarded duplicate
        # would crash that expander with a duplicate-widget-key error
        name = f"{name} ({sum(1 for n in existing_names if n.startswith(name)) + 1})"
    st.session_state.sql_lab_saved_queries.append({"name": name, "sql": sql})
    atlas.say_only(f'Saved as "{name}" — find it under Saved Queries in SQL Lab.')


def _cmd_run_live_sql(target) -> None:
    """Re-entry point for atlas.guarded()'s confirm round-trip when the
    AI generated a statement that would modify the connected live database
    — `target` is the staged SQL text itself (guarded() carries arbitrary
    strings through its target param, not just dataset/column names).
    Mirrors _process_atlas_sql_question's single-query tail: run it, write
    the reserved Atlas tab, populate the SQL Lab result panel, speak.
    """
    sql = (target or "").strip()
    if not sql:
        atlas.say_only("Nothing to run.")
        return
    if not sql_lab_live_backend():
        # The connection could have been dropped between staging the
        # confirmation and the user saying "confirm" — don't silently run
        # a write against local data instead.
        atlas.say_only("The live database connection isn't active anymore — nothing was run.")
        return
    run_result = sql_lab_run_query(sql)
    _write_atlas_sql_tab(sql, "Atlas: live query")
    _post_sql_lab_result(run_result)
    st.session_state.pending_active_section = "SQL Lab"
    if run_result["error"]:
        atlas.say_only(f"That didn't run: {run_result['error']}")
        return
    atlas.say_only("Done — that change went through. Check SQL Lab for the result.")


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
    "save_sql_query": _cmd_save_sql_query,
    "run_live_sql": _cmd_run_live_sql,
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
                        new_df, data_engine.get_data_quality_report(new_df, st.session_state.column_types),
                        st.session_state.column_types,
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
                    sampled_df, data_engine.get_data_quality_report(sampled_df, st.session_state.column_types),
                    st.session_state.column_types,
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
            def _apply_recipe_and_log(loaded_recipe: dict) -> None:
                """Shared by the upload-a-file path and the account-saved-
                recipes list below — both must produce identical undo-stack
                and cleaning-history behavior."""
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

            recipe_name_input = st.text_input("Recipe name", value="my_cleaning_recipe", key="recipe_name_input")
            recipe_json_text = recipes.save_recipe(recipe_name_input, st.session_state.cleaning_log)
            dl_col, acct_col = st.columns(2)
            dl_col.download_button(
                "Save Recipe",
                data=recipe_json_text.encode("utf-8"),
                file_name=f"{recipe_name_input or 'prism_recipe'}.json",
                mime="application/json",
                use_container_width=True,
                disabled=not st.session_state.cleaning_log,
            )
            # ---- Persisted across sessions (MySQL-backed, optional) --------
            # Recipes have no "list of my saved recipes" concept without this
            # — normally it's generate-fresh-and-download only. Renders
            # nothing at all when MySQL isn't configured.
            if app_db.is_configured():
                if acct_col.button(
                    "☁️ Save to My Account", key="recipe_save_to_account",
                    use_container_width=True, disabled=not st.session_state.cleaning_log,
                ):
                    visitor_id = app_db.get_visitor_id()
                    acct_ok, acct_err = app_db.save_recipe_to_db(visitor_id, recipe_name_input, recipe_json_text)
                    if acct_ok:
                        st.toast("Saved to your account. ☁️")
                    else:
                        st.error(acct_err)

            recipe_file = st.file_uploader("Apply a recipe to this dataset", type=["json"], key="recipe_uploader")
            if recipe_file is not None:
                loaded_recipe, recipe_load_error = recipes.load_recipe(recipe_file.getvalue())
                if recipe_load_error:
                    st.error(recipe_load_error)
                elif st.button("Apply Recipe", use_container_width=True, key="apply_recipe_btn"):
                    _apply_recipe_and_log(loaded_recipe)

            if app_db.is_configured():
                visitor_id = app_db.get_visitor_id()
                account_recipes = app_db.list_recipes(visitor_id)
                if account_recipes:
                    st.markdown("**Your saved recipes**")
                    for r in account_recipes:
                        rcol, applycol, delcol = st.columns([4, 2, 1])
                        rcol.markdown(r["name"])
                        if applycol.button("Apply", key=f"recipe_db_apply_{r['id']}", use_container_width=True):
                            recipe_json, recipe_err = app_db.load_recipe_from_db(visitor_id, r["id"])
                            if recipe_err:
                                st.error(recipe_err)
                            else:
                                loaded_recipe, recipe_load_error = recipes.load_recipe(recipe_json)
                                if recipe_load_error:
                                    st.error(recipe_load_error)
                                else:
                                    _apply_recipe_and_log(loaded_recipe)
                        if delcol.button("🗑️", key=f"recipe_db_del_{r['id']}"):
                            app_db.delete_recipe(visitor_id, r["id"])
                            st.rerun()

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

        # ---- Persisted across sessions (MySQL-backed, optional) --------
        # Renders nothing at all when MySQL isn't configured.
        if app_db.is_configured():
            snapshot_name_input = st.text_input(
                "Name this snapshot", value=f"session_{datetime.now():%Y-%m-%d_%H%M}",
                key="session_snapshot_name_input", label_visibility="collapsed",
            )
            if st.button("☁️ Save to My Account", key="session_save_to_account", use_container_width=True):
                visitor_id = app_db.get_visitor_id()
                acct_ok, acct_err = app_db.save_session_snapshot(
                    visitor_id, snapshot_name_input, session_json, len(st.session_state.working_df),
                )
                if acct_ok:
                    st.toast("Saved to your account. ☁️")
                else:
                    st.error(acct_err)

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


def _process_atlas_sql_question(question: str, complexity: str) -> None:
    """SQL_QUESTION handler — mirrors the DATA_QUESTION branch's guard
    checks below but generates + runs SQL (via modules/sql_lab.py) and
    writes into the reserved Atlas SQL tab instead of routing to AI
    Analyst. Called from _process_atlas_utterance; does not call
    st.rerun() itself — the caller already does, once, at its own end.

    complexity="single": one generate_sql + run_query_multi call, then a
    one-sentence spoken answer.
    complexity="multi": mirrors auto_analyst's plan -> execute -> synthesize
    shape (generate_sql_plan -> loop of generate_sql+run_query_multi,
    never aborting on a step's failure -> synthesize_sql_findings), for
    open-ended/diagnostic asks that need several queries chained together.
    """
    if st.session_state.working_df is None:
        atlas.say_only("Upload data first and I'll get to work.")
        return
    sql_model = ai_analyst.get_sql_model()
    if sql_model is None:
        atlas.say_only("I need a Gemini API key configured first — see the AI Analyst tab for setup steps.")
        return

    df_, column_types_ = st.session_state.working_df, st.session_state.column_types
    # Appended to whatever question text reaches generate_sql()/generate_sql_plan() —
    # those only ever describe df_/column_types_ (the local active dataset), so without
    # this Atlas has no idea a live.<table> exists at all. "" when there's no live
    # connection, so this is safe to append unconditionally.
    live_note = sql_lab_live_schema_note()

    if complexity == "multi":
        with st.spinner(ui.get_loading_message()):
            plan = ai_analyst.generate_sql_plan(
                sql_model, df_, column_types_, f"{question}\n\n{live_note}" if live_note else question
            )
        live_backend = sql_lab_live_backend()
        step_outcomes: list[dict] = []
        last_ok_sql, last_ok_result = None, None
        for step in plan:
            step_question = f"{step['question']}\n\n{live_note}" if live_note else step["question"]
            sql, gen_error = ai_analyst.generate_sql(sql_model, df_, column_types_, step_question)
            if gen_error:
                step_outcomes.append({"title": step["title"], "sql": "", "result_df": None, "error": gen_error})
                continue
            if live_backend and db_connect.is_destructive_statement(sql):
                # Multi-step plans never auto-run a write against the live DB —
                # that would need a per-step confirmation round-trip this loop
                # can't pause for. Skip it; the user can run it manually from
                # SQL Lab, where the same gate applies with a Run Anyway button.
                step_outcomes.append({
                    "title": step["title"], "sql": sql, "result_df": None,
                    "error": "Skipped — this step would modify live data. Run it manually from SQL Lab to confirm.",
                })
                continue
            run_result = sql_lab_run_query(sql)
            step_outcomes.append({
                "title": step["title"], "sql": sql,
                "result_df": run_result["result_df"], "error": run_result["error"],
            })
            if not run_result["error"]:
                last_ok_sql, last_ok_result = sql, run_result
        with st.spinner(ui.get_loading_message()):
            narrative, synth_error = ai_analyst.synthesize_sql_findings(sql_model, step_outcomes)
        if last_ok_sql:
            _write_atlas_sql_tab(last_ok_sql, f"Atlas: {question[:40]}")
            _post_sql_lab_result(last_ok_result)
            st.session_state.pending_active_section = "SQL Lab"
        atlas.say_only(
            narrative or f"Ran a {len(plan)}-step check but couldn't pull a clean answer out: "
            f"{synth_error or 'every step failed'}."
        )
        return

    # complexity == "single"
    with st.spinner(ui.get_loading_message()):
        sql, gen_error = ai_analyst.generate_sql(
            sql_model, df_, column_types_, f"{question}\n\n{live_note}" if live_note else question
        )
    if gen_error:
        atlas.say_only(gen_error)
        return
    live_backend = sql_lab_live_backend()
    if live_backend and db_connect.is_destructive_statement(sql):
        live_label = db_connect.ENGINE_LABELS.get(live_backend, live_backend)
        if not atlas.guarded(
            "run_live_sql", sql,
            f"That query will modify your connected {live_label} database: {sql[:160]}",
        ):
            return
    run_result = sql_lab_run_query(sql)
    _write_atlas_sql_tab(sql, f"Atlas: {question[:40]}")
    _post_sql_lab_result(run_result)
    st.session_state.pending_active_section = "SQL Lab"
    if run_result["error"]:
        atlas.say_only(f"That query didn't run: {run_result['error']}")
        return
    with st.spinner(ui.get_loading_message()):
        answer, _summarize_error = ai_analyst.summarize_sql_result(sql_model, question, run_result["result_df"])
    atlas.say_only(answer or "Done — check SQL Lab for the result.")


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
    elif intent["type"] == "SQL_QUESTION":
        question = intent.get("question") or utterance
        _process_atlas_sql_question(question, intent.get("complexity") or "single")
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
            sample_df, data_engine.get_data_quality_report(sample_df, st.session_state.column_types),
            st.session_state.column_types,
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

    # ---- Restore from account (MySQL-backed, optional) ---------------------
    # Renders nothing at all when MySQL isn't configured.
    if app_db.is_configured():
        account_visitor_id = app_db.get_visitor_id()
        account_snapshots = app_db.list_session_snapshots(account_visitor_id)
        if account_snapshots:
            st.markdown("**Or restore from your account**")
            for snap in account_snapshots:
                scol, rcol = st.columns([4, 1])
                scol.markdown(f"{snap['name']} · {snap['row_count']:,} rows · {snap['created_at']:%Y-%m-%d %H:%M}")
                if rcol.button("Restore", key=f"session_db_restore_{snap['id']}", use_container_width=True):
                    snap_json, snap_err = app_db.load_session_snapshot(account_visitor_id, snap["id"])
                    if snap_err:
                        st.error(snap_err)
                    else:
                        snap_bundle, snap_load_error = session_io.load_session(snap_json.encode("utf-8"))
                        if snap_load_error:
                            st.error(snap_load_error)
                        else:
                            set_active_dataset(
                                snap_bundle["raw_df"], snap_bundle["working_df"], "restored_session.csv",
                                cleaning_log=snap_bundle["cleaning_log"], chat_history=snap_bundle["chat_history"],
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

# Agent Summary orchestration is computed here — every rerun, regardless of
# which tab is active — rather than inside the Overview tab block below, so
# _maybe_announce_orchestration() can proactively surface a new cross-
# detector finding even while the user is on a completely different tab
# (e.g. just ran the Causal Effect Estimator). Pure synthesis over
# already-computed detector output, no Gemini call, so recomputing it every
# pass is cheap. The Overview tab reuses this same value below instead of
# recomputing it a second time.
_orchestration = insight_orchestrator.orchestrate_insights(_build_orchestration_input())
_maybe_announce_orchestration(_orchestration)

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
    _PRIMARY_NAV = ["Overview", "Clean", "Visualize", "SQL Lab", "AI Analyst"]
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
            st.caption("Combine and the analysis labs — one click away, not gone.")
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
        atlas.inject_orb_css()
        st.markdown(
            f'<div class="atlas-panel-hd">'
            f'<div class="atlas-orb-sm atlas-orb {st.session_state.get("atlas_orb_state", "idle")}"></div>'
            f'<div><div class="t hud">Atlas</div>'
            f'<div class="s mono">ONLINE &middot; {atlas.MODEL_NAME}</div></div></div>',
            unsafe_allow_html=True,
        )
        atlas.render_neuron_bg()
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

    # Reserve room for the fixed-position Atlas side panel (328px wide, see
    # .st-key-atlas_side_panel in modules/theme.py) so main content doesn't
    # render underneath it. Scoped to the same >768px breakpoint the panel's
    # own CSS uses to switch from "fixed right rail" to "stacks below main
    # content" — this rule used to apply unconditionally (`!important`, no
    # media query), which meant on a ~390px phone viewport it reserved 352px
    # of a 390px-wide screen for a panel that, even after being fixed to
    # stack inline, was still being squeezed into the ~22px left over. Found
    # via layout inspection while re-verifying the mobile Atlas-panel fix
    # this run — the panel's own CSS was only half the bug.
    st.markdown(
        '<style>@media (min-width: 769px) { .block-container{padding-right:352px !important;} }</style>',
        unsafe_allow_html=True,
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
    # Auto-Insight Engine — proactive insights surfaced on upload
    # ------------------------------------------------------------------
    # The user has now actually seen the findings that may have triggered
    # Atlas's proactive alert HUD (announce_ambient_insights() -> raise_alert())
    # — clear it so the orb doesn't keep pulsing for something already read.
    atlas.clear_alert()

    # ------------------------------------------------------------------
    # Run All Detectors — modules/detector_runner.py. Auto-Insights and
    # Confounder Check already ran on upload; Hypothesis Sweep and Anomaly
    # Detection are equally automatic (no column/target picking needed)
    # but otherwise stay dormant until the user visits Stats Lab / the
    # Anomaly Detection expander below and clicks their own button — which
    # is also why Agent Summary right below this often has too few
    # detectors to say anything yet. One click here fires both, using the
    # exact same functions and session-state slots those manual buttons
    # do, so the panels below (and Agent Summary) light up immediately.
    # Hidden once both have already run this session — nothing left for
    # it to do automatically at that point.
    # ------------------------------------------------------------------
    _already_have_sweep = st.session_state.hypothesis_sweep_result is not None
    _already_have_anomaly = st.session_state.anomaly_result_df is not None
    if not (_already_have_sweep and _already_have_anomaly):
        _autorun_eligible, _autorun_block_reason = detector_runner.autorun_eligible(df, column_types)
        with st.container(border=True):
            st.markdown("#### ⚡ Run All Detectors")
            st.caption(
                "Hypothesis Sweep and Anomaly Detection are fully automatic — no columns to "
                "pick — but only run when you open their own tab. Fire both now in one click."
            )
            if not _autorun_eligible:
                st.info(_autorun_block_reason)
            elif st.button("⚡ Run All Detectors", key="run_all_detectors_btn", type="primary"):
                with st.spinner(ui.get_loading_message()):
                    _run_result = detector_runner.run_all_detectors(
                        df, column_types,
                        already_have_sweep=_already_have_sweep,
                        already_have_anomaly=_already_have_anomaly,
                    )
                if "hypothesis_sweep" in _run_result["ran"]:
                    st.session_state.hypothesis_sweep_result = _run_result["sweep_result"]
                    st.session_state.hypothesis_sweep_confounder_check = _run_result["confounder_check"]
                    st.session_state.hypothesis_sweep_interaction_check = _run_result["interaction_check"]
                    st.session_state.hypothesis_sweep_categorical_interaction_check = _run_result["categorical_interaction_check"]
                    st.session_state.hypothesis_sweep_narration = None
                    st.session_state.hypothesis_sweep_narration_fingerprint = None
                    st.session_state.hypothesis_sweep_narration_verification = None
                    st.session_state.hypothesis_sweep_confounder_narrations = {}
                if "anomaly" in _run_result["ran"]:
                    st.session_state.anomaly_result_df = _run_result["anomaly_result_df"]
                    st.session_state.anomaly_error = _run_result["anomaly_error"]
                    st.session_state.anomaly_methods_summary = None
                    st.session_state.anomaly_narration = None
                    st.session_state.anomaly_narration_fingerprint = None
                    st.session_state.anomaly_narration_verification = None
                    st.session_state.anomaly_driver_narration = None
                    st.session_state.anomaly_driver_narration_fingerprint = None
                    st.session_state.anomaly_driver_narration_verification = None
                st.session_state.detector_runner_last_ran = _run_result["ran"]
                st.session_state.detector_runner_last_skipped = _run_result["skipped"]
                st.rerun()  # see the Agent Summary same-pass-staleness note below

            if st.session_state.detector_runner_last_ran:
                st.caption(f"✅ Ran: {', '.join(st.session_state.detector_runner_last_ran)}. See the results below.")

    # ------------------------------------------------------------------
    # Agent Summary — the orchestration layer over every detector panel
    # below. Pure synthesis, no detection of its own: collects whatever
    # Auto-Insights, Confounder Check, the Causal Effect Estimator (ATT +
    # CATE), Anomaly Detection, and Drift have already computed this
    # session, de-duplicates overlapping claims about the same variable
    # pair, flags cross-detector agreement (higher confidence) and the
    # one specific "check this" contradiction pattern (a causal estimate
    # that didn't adjust for a confounder Confounder Check just flagged
    # on the same pair), and ranks the result into a top-N list. Stays
    # silent — same convention as every panel below it — until at least
    # two detectors have actually fired this session.
    # ------------------------------------------------------------------
    orchestration = _orchestration  # computed once per rerun above, regardless of active tab
    if not orchestration.silent:
        with st.container(border=True):
            n_contradictions = len(orchestration.contradictions)
            flag_note = f"  •  {n_contradictions} to double-check" if n_contradictions else ""
            st.markdown(
                f"#### 🧠 Agent Summary  •  what matters most across "
                f"{orchestration.n_detectors_fired} detectors{flag_note}"
            )
            st.caption(
                "Synthesized from every check that's run this session — the same findings shown "
                "in the panels below, cross-checked against each other and ranked."
            )
            fingerprint = insight_orchestrator.fingerprint_result(orchestration)
            if (
                st.session_state.orchestration_narration
                and st.session_state.orchestration_narration_fingerprint == fingerprint
            ):
                st.info(st.session_state.orchestration_narration)
                caption = ui.build_verification_caption(
                    [st.session_state.orchestration_narration_verification or {"status": "unverifiable"}]
                )
                if caption:
                    st.caption(caption)
            elif st.button(
                "✨ Generate Executive Summary", key="orchestration_narrate",
                help="Ask Gemini to synthesize the ranked list below into one paragraph",
            ):
                model = ai_analyst.get_model()
                with st.spinner("Gemini is synthesizing the top findings…"):
                    narration, narr_error = insight_orchestrator.narrate_orchestration(model, orchestration)
                if narr_error:
                    st.warning(narr_error)
                else:
                    st.session_state.orchestration_narration = narration
                    st.session_state.orchestration_narration_fingerprint = fingerprint
                    # Fact-check the narration against the ranked top-list's own
                    # numbers — same insight_verifier-backed safety net every
                    # other Gemini-written surface in the app already has.
                    st.session_state.orchestration_narration_verification = (
                        insight_orchestrator.verify_narration(narration, orchestration)
                    )
                    st.rerun()

            for group in orchestration.top:
                if group.contradiction:
                    badge = "🟠 Check this"
                elif group.agreement:
                    badge = f"✅ Confirmed by {len(group.detectors)} detectors"
                else:
                    badge = f"{insight_orchestrator.severity_icon(group.severity)} {group.severity.title()}"
                subj = ", ".join(sorted(group.subjects)) if group.subjects else "Dataset-wide"
                st.markdown(f"**{badge}** — *{subj}*  \n{group.headline}")

    if st.session_state.auto_insights:
        insights_list = st.session_state.auto_insights
        n_high = sum(1 for i in insights_list if i["severity"] == "high")
        n_med = sum(1 for i in insights_list if i["severity"] == "medium")
        n_low = sum(1 for i in insights_list if i["severity"] == "low")
        severity_summary = ", ".join(
            f"{c} {l}" for c, l in [(n_high, "critical"), (n_med, "notable"), (n_low, "minor")] if c
        )
        with st.container(border=True):
            st.markdown(f"#### 🔍 Auto-Insights  •  {len(insights_list)} finding{'s' if len(insights_list) != 1 else ''}  ({severity_summary})")
            if st.session_state.auto_insights_narration:
                st.info(st.session_state.auto_insights_narration)
                caption = ui.build_verification_caption(
                    [st.session_state.auto_insights_narration_verification or {"status": "unverifiable"}]
                )
                if caption:
                    st.caption(caption)
            elif st.button("✨ Generate Executive Summary", key="auto_insights_narrate", help="Ask Gemini to narrate these findings"):
                model = ai_analyst.get_model()
                with st.spinner("Gemini is summarizing the findings…"):
                    narration, narr_error = auto_insights.narrate_insights(model, insights_list)
                if narr_error:
                    st.warning(narr_error)
                else:
                    st.session_state.auto_insights_narration = narration
                    # Fact-check the narration against the source insights' own
                    # numbers — same insight_verifier-backed safety net every
                    # other Gemini-written surface in the app already has.
                    st.session_state.auto_insights_narration_verification = (
                        auto_insights.verify_narration(narration, insights_list)
                    )
                    st.rerun()
            for ins in insights_list:
                icon = auto_insights.severity_icon(ins["severity"])
                cat = auto_insights.category_label(ins["category"])
                st.markdown(f"{icon} **{cat}** — {ins['message']}")

    # ------------------------------------------------------------------
    # Confounder Check — the agentic follow-up to a strong correlation:
    # "...but does it hold up once you control for a third variable?" Runs
    # automatically alongside Auto-Insights (deterministic, no Gemini call
    # for detection itself — see modules/confounder_detection.py), only
    # renders when it actually found something worth a second look.
    # ------------------------------------------------------------------
    if st.session_state.confounder_scan:
        with st.container(border=True):
            n_pairs = len(st.session_state.confounder_scan)
            st.markdown(f"#### 🧭 Confounder Check  •  {n_pairs} correlation{'s' if n_pairs != 1 else ''} worth a second look")
            st.caption("A strong correlation can flip sign or vanish once you control for a third variable (Simpson's Paradox). These held up worse than they looked at first glance.")
            for scan in st.session_state.confounder_scan:
                x_col, y_col = scan["x"], scan["y"]
                for finding in scan["findings"]:
                    verdict = finding["verdict"]
                    badge = "🔴 Paradox" if verdict == "paradox" else "🟡 Confounded"
                    label = (
                        f"{badge} — **{x_col}** vs **{y_col}**, controlling for **{finding['confounder']}**"
                    )
                    with st.expander(label, expanded=False):
                        st.caption(
                            f"Pooled correlation: r = {finding['overall_r']:.2f}  •  "
                            f"Adjusted: r = {finding['adjusted_r']:.2f}"
                        )
                        if finding["type"] == "categorical":
                            group_df = pd.DataFrame(finding["detail"])[["group", "r", "n"]]
                            group_df.columns = [finding["confounder"], "r within group", "n"]
                            st.dataframe(group_df, use_container_width=True, hide_index=True)
                        else:
                            st.caption(f"n = {finding['detail']['n']}")
                        cache_key = (x_col, y_col, finding["confounder"])
                        cached = st.session_state.confounder_narrations.get(cache_key)
                        if cached:
                            st.info(cached)
                        elif st.button("✨ Explain this", key=f"confounder_narrate_{x_col}_{y_col}_{finding['confounder']}"):
                            model = ai_analyst.get_model()
                            with st.spinner("Gemini is interpreting this…"):
                                narration, narr_error = confounder_detection.narrate_confounder_finding(
                                    model, x_col, y_col, finding
                                )
                            if narr_error:
                                st.warning(narr_error)
                            else:
                                st.session_state.confounder_narrations[cache_key] = narration
                                st.rerun()

    # ------------------------------------------------------------------
    # Causal Effect Estimator — the next agentic step after Confounder
    # Check: that panel diagnoses "this correlation might be confounded";
    # this one treats it, via propensity score matching (see
    # modules/causal_inference.py). Only rendered when the dataset has at
    # least one binary column to treat as "treatment" and enough numeric
    # columns to serve as an outcome plus covariates — otherwise there's
    # nothing meaningful to offer, same "stay silent rather than force it"
    # convention as Confounder Check and Auto-Insights.
    # ------------------------------------------------------------------
    _causal_binary_cols = [
        c for c, t in st.session_state.column_types.items()
        if t in ("categorical", "text", "boolean") and c in working_df.columns and working_df[c].nunique(dropna=True) == 2
    ]
    _causal_numeric_cols = [c for c, t in st.session_state.column_types.items() if t == "numeric" and c in working_df.columns]
    if _causal_binary_cols and len(_causal_numeric_cols) >= 2:
        with st.container(border=True):
            st.markdown("#### 🔬 Causal Effect Estimator")
            st.caption(
                "A correlation says two things move together. This estimates what actually happens to the "
                "outcome *because of* the treatment — matching each treated row to its most similar untreated "
                "row (propensity score matching) before comparing outcomes, so the estimate isn't just picking "
                "up a confound."
            )
            c1, c2, c3 = st.columns(3)
            treatment_col = c1.selectbox("Treatment column", _causal_binary_cols, key="causal_treatment_col")
            treated_options = sorted(working_df[treatment_col].dropna().unique().tolist(), key=str)
            treated_value = c2.selectbox("Treated = ", treated_options, key="causal_treated_value")
            outcome_options = [c for c in _causal_numeric_cols if c != treatment_col]
            outcome_col = c3.selectbox("Outcome column", outcome_options, key="causal_outcome_col")
            default_covariates = [c for c in outcome_options if c != outcome_col]
            covariates = st.multiselect(
                "Adjust for (covariates)", default_covariates, default=default_covariates, key="causal_covariates"
            )

            if st.button("Estimate causal effect", key="causal_estimate_btn"):
                if not covariates:
                    st.session_state.causal_result = {"ok": False, "error": "Pick at least one covariate to adjust for."}
                else:
                    with st.spinner("Matching treated and control units…"):
                        st.session_state.causal_result = causal_inference.estimate_causal_effect(
                            working_df, treatment_col, treated_value, outcome_col, covariates=covariates
                        )
                st.session_state.causal_narration = None
                st.session_state.cate_result = None
                st.session_state.cate_narration = None
                # Agent Summary renders earlier in this same script pass (by
                # design — it's the top-line synthesis, above the detail
                # panels) so it would otherwise show the *pre-click* causal
                # state for this one rerun; force a fresh pass so it picks
                # up the result just computed above.
                st.rerun()

            result = st.session_state.causal_result
            if result is not None:
                if not result["ok"]:
                    st.warning(result["error"])
                else:
                    m1, m2 = st.columns(2)
                    m1.metric(
                        f"ATT on {result['outcome_col']}",
                        f"{result['att']:.3g}",
                        help="Average Treatment effect on the Treated — the mean outcome difference within matched pairs.",
                    )
                    m2.metric("Match rate", f"{result['match_rate']:.0%}")
                    st.caption(
                        f"95% CI: [{result['ci_low']:.3g}, {result['ci_high']:.3g}]  •  "
                        f"Matched pairs: {result['n_matched']} of {result['n_treated']} treated units"
                    )

                    for w in result["warnings"]:
                        st.warning(w)

                    balance_df = pd.DataFrame(
                        {
                            "covariate": [b["covariate"] for b in result["balance_before"]],
                            "SMD before matching": [b["smd"] for b in result["balance_before"]],
                            "SMD after matching": [b["smd"] for b in result["balance_after"]],
                        }
                    )
                    st.caption("Covariate balance — |SMD| under 0.1 is conventionally considered well-matched.")
                    st.dataframe(balance_df, use_container_width=True, hide_index=True)

                    if st.session_state.causal_narration:
                        st.info(st.session_state.causal_narration)
                    elif st.button("✨ Explain this", key="causal_narrate_btn"):
                        model = ai_analyst.get_model()
                        with st.spinner("Gemini is interpreting this…"):
                            narration, narr_error = causal_inference.narrate_causal_effect(model, result)
                        if narr_error:
                            st.warning(narr_error)
                        else:
                            st.session_state.causal_narration = narration
                            st.rerun()

                    # --------------------------------------------------
                    # CATE by subgroup — does this effect actually hold for
                    # everyone, or does a single pooled ATT hide a treatment
                    # that helps one segment and hurts another? Only offered
                    # once a pooled estimate exists, and only when there's a
                    # low-cardinality categorical column to slice by (2-10
                    # groups — below 2 there's nothing to compare, above 10
                    # per-group sample sizes get too thin to match on).
                    # --------------------------------------------------
                    _cate_subgroup_cols = [
                        c for c, t in st.session_state.column_types.items()
                        if t in ("categorical", "text", "boolean")
                        and c in working_df.columns
                        and c != treatment_col
                        and 2 <= working_df[c].nunique(dropna=True) <= 10
                    ]
                    if _cate_subgroup_cols:
                        st.divider()
                        st.markdown("**Does the effect vary by subgroup?**")
                        st.caption(
                            "A single pooled number can hide a treatment that helps one segment and hurts "
                            "another. Re-runs the same matching estimate within each level of the column "
                            "below and checks whether the effect actually holds everywhere."
                        )
                        sc1, sc2 = st.columns([2, 1])
                        subgroup_col = sc1.selectbox("Subgroup column", _cate_subgroup_cols, key="cate_subgroup_col")
                        if sc2.button("Check heterogeneity", key="cate_estimate_btn"):
                            with st.spinner("Re-matching within each subgroup…"):
                                st.session_state.cate_result = causal_inference.estimate_cate_by_subgroup(
                                    working_df, treatment_col, treated_value, outcome_col, subgroup_col,
                                    covariates=covariates,
                                )
                            st.session_state.cate_narration = None
                            st.rerun()  # see the Agent Summary same-pass-staleness note above

                        cate_result = st.session_state.cate_result
                        if cate_result is not None:
                            if not cate_result["ok"]:
                                st.warning(cate_result["error"])
                            else:
                                if cate_result["sign_reversal"]:
                                    st.error(
                                        "⚠️ Sign reversal detected — the treatment helps in some subgroups and "
                                        "hurts in others. A blanket rollout would be the wrong call here."
                                    )
                                elif cate_result["heterogeneity_detected"]:
                                    st.warning(
                                        "The effect size differs meaningfully by subgroup (non-overlapping "
                                        "confidence intervals) — consider a targeted rollout over a blanket one."
                                    )
                                else:
                                    st.success("The effect looks consistent across subgroups — no evidence it varies.")

                                cate_fig = visualization.plot_cate_by_subgroup(cate_result)
                                if cate_fig is not None:
                                    st.plotly_chart(cate_fig, use_container_width=True)

                                for w in cate_result["warnings"]:
                                    st.caption(f"⚠ {w}")

                                if st.session_state.cate_narration:
                                    st.info(st.session_state.cate_narration)
                                elif st.button("✨ Explain this", key="cate_narrate_btn"):
                                    model = ai_analyst.get_model()
                                    with st.spinner("Gemini is interpreting this…"):
                                        narration, narr_error = causal_inference.narrate_cate_heterogeneity(model, cate_result)
                                    if narr_error:
                                        st.warning(narr_error)
                                    else:
                                        st.session_state.cate_narration = narration
                                        st.rerun()

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
            ensemble_mode = st.checkbox(
                "Ensemble mode — cross-check with LOF + DBSCAN",
                key="anomaly_ensemble_mode",
                help=(
                    "Instead of trusting one model, run Isolation Forest (global isolation), "
                    "LOF (local density), and DBSCAN (density-based clustering) and show how much "
                    "they agree. Needs at least 2 numeric columns and 20 rows."
                ),
            )
            if st.button("Find Anomalies", key="find_anomalies_btn"):
                with st.spinner(ui.get_loading_message()):
                    if ensemble_mode:
                        flagged, methods_summary, anomaly_err = anomaly.find_anomalies_ensemble(df, column_types)
                        st.session_state.anomaly_methods_summary = methods_summary
                    else:
                        flagged, anomaly_err = anomaly.find_anomalies(df, column_types)
                        st.session_state.anomaly_methods_summary = None
                st.session_state.anomaly_result_df = flagged
                st.session_state.anomaly_error = anomaly_err
                st.session_state.anomaly_narration = None
                st.session_state.anomaly_narration_fingerprint = None
                st.session_state.anomaly_narration_verification = None
                st.session_state.anomaly_driver_narration = None
                st.session_state.anomaly_driver_narration_fingerprint = None
                st.session_state.anomaly_driver_narration_verification = None
                st.rerun()  # see the Agent Summary same-pass-staleness note above

            if st.session_state.anomaly_error:
                st.error(st.session_state.anomaly_error)
            elif st.session_state.anomaly_result_df is not None:
                flagged = st.session_state.anomaly_result_df
                methods_summary = st.session_state.get("anomaly_methods_summary")
                if flagged.empty:
                    st.info("No anomalies detected.")
                else:
                    st.write(f"**{len(flagged)} anomalous row(s) flagged:**")
                    if methods_summary:
                        summary_cols = st.columns(len(methods_summary))
                        for col, (method, stats) in zip(summary_cols, methods_summary.items()):
                            col.metric(method.replace("_", " ").title(), f"{stats['flagged_count']}", f"{stats['pct']}%")
                        full_agreement = int((flagged["consensus_count"] == len(anomaly.ENSEMBLE_METHODS)).sum())
                        st.caption(
                            f"🔗 {full_agreement} of {len(flagged)} row(s) flagged by **all 3 methods** — "
                            "the strongest-consensus anomalies. Table below is sorted by agreement."
                        )
                    st.dataframe(flagged, use_container_width=True)

                    # Anomaly Drivers — IsolationForest/ensemble say *which* rows are
                    # unusual; this answers *why*, by testing every other column for
                    # a real difference between flagged and normal rows (Welch's
                    # t-test / Cohen's d for numeric, chi-square / Cramer's V for
                    # categorical). Pure statistics, no Gemini call, so it's computed
                    # unconditionally rather than gated behind a button.
                    drivers = anomaly.find_anomaly_drivers(df, flagged, column_types)
                    with st.expander("🔬 What makes these rows anomalous?", expanded=bool(drivers)):
                        if not drivers:
                            st.caption(
                                "No single column significantly distinguishes the flagged rows from "
                                "the rest (p ≥ 0.05 on every column tested) — the anomalies aren't "
                                "explained by any one feature alone."
                            )
                        else:
                            driver_rows = []
                            for d in drivers:
                                if d["type"] == "numeric":
                                    detail = f"anomaly mean {d['anomaly_mean']:.3g} vs. normal {d['normal_mean']:.3g}"
                                else:
                                    detail = "differs by category"
                                driver_rows.append(
                                    {
                                        "Column": d["column"],
                                        "Effect size": f"{d['effect_size_name']} = {d['effect_size']:.2f} ({d['effect_size_label']})",
                                        "Detail": detail,
                                        "p-value": f"{d['p_value']:.4f}",
                                    }
                                )
                            st.dataframe(pd.DataFrame(driver_rows), use_container_width=True, hide_index=True)

                            driver_fp = anomaly.fingerprint_drivers(drivers)
                            if (
                                st.session_state.anomaly_driver_narration
                                and st.session_state.anomaly_driver_narration_fingerprint == driver_fp
                            ):
                                st.info(f"🤖 {st.session_state.anomaly_driver_narration}")
                                driver_caption = ui.build_verification_caption(
                                    [st.session_state.anomaly_driver_narration_verification or {"status": "unverifiable"}]
                                )
                                if driver_caption:
                                    st.caption(driver_caption)
                            elif st.button(
                                "✨ Explain these drivers with AI",
                                key="narrate_anomaly_drivers_btn",
                                help="Ask Gemini to explain what characterizes the anomalous rows",
                            ):
                                model = ai_analyst.get_model()
                                with st.spinner("Gemini is reviewing the drivers…"):
                                    driver_narration, driver_narr_error = anomaly.narrate_anomaly_drivers(
                                        model, drivers, len(flagged)
                                    )
                                if driver_narr_error:
                                    st.warning(driver_narr_error)
                                else:
                                    st.session_state.anomaly_driver_narration = driver_narration
                                    st.session_state.anomaly_driver_narration_fingerprint = driver_fp
                                    st.session_state.anomaly_driver_narration_verification = anomaly.verify_narration(
                                        driver_narration, anomaly.driver_reference_numbers(drivers)
                                    )
                                    st.rerun()

                    # AI narration — cached per fingerprint of this exact flagged
                    # set so re-viewing it (tab switch, etc.) doesn't re-spend a
                    # Gemini call; only a genuinely different detection result
                    # invalidates the cache.
                    current_fp = anomaly.fingerprint_flagged(flagged)
                    if (
                        st.session_state.anomaly_narration
                        and st.session_state.anomaly_narration_fingerprint == current_fp
                    ):
                        st.info(f"🤖 {st.session_state.anomaly_narration}")
                        caption = ui.build_verification_caption(
                            [st.session_state.anomaly_narration_verification or {"status": "unverifiable"}]
                        )
                        if caption:
                            st.caption(caption)
                    elif st.button(
                        "✨ Explain these anomalies with AI",
                        key="narrate_anomalies_btn",
                        help="Ask Gemini to explain the pattern and suggest a next action",
                    ):
                        model = ai_analyst.get_model()
                        with st.spinner("Gemini is reviewing the flagged rows…"):
                            if methods_summary:
                                narration, narr_error = anomaly.narrate_ensemble_disagreement(model, flagged, methods_summary)
                                ref_numbers = anomaly.ensemble_reference_numbers(flagged, methods_summary)
                            else:
                                narration, narr_error = anomaly.narrate_anomalies(model, flagged)
                                ref_numbers = anomaly.anomaly_reference_numbers(flagged)
                        if narr_error:
                            st.warning(narr_error)
                        else:
                            st.session_state.anomaly_narration = narration
                            st.session_state.anomaly_narration_fingerprint = current_fp
                            # Fact-check the narration against the flagged set's
                            # own numbers — same insight_verifier-backed safety
                            # net every other Gemini-written surface has.
                            st.session_state.anomaly_narration_verification = (
                                anomaly.verify_narration(narration, ref_numbers)
                            )
                            st.rerun()

                    if st.button("Exclude flagged rows from active dataset", key="exclude_anomalies_btn"):
                        push_undo_snapshot()
                        new_df = df.drop(index=flagged.index)
                        st.session_state.working_df = new_df
                        st.session_state.column_types = data_engine.detect_column_types(new_df)
                        log_step(
                            f"Excluded {len(flagged)} anomalous row(s) ({'ensemble' if methods_summary else 'IsolationForest'})",
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
    st.subheader("🧭 Explore Mode")
    st.caption(
        "Auto-ranked chart suggestions — correlation strength, group differences, time trends, "
        "and skew, computed deterministically (no Gemini call) so this works even offline."
    )
    explore_suggestions = visualization.suggest_encodings(df, chart_column_types)
    if not explore_suggestions:
        ui.render_empty_state(
            "🧭", "Nothing strongly signals yet", "Add more numeric or moderate-cardinality categorical columns to unlock suggestions."
        )
    else:
        explore_cols = st.columns(2)
        for idx, suggestion in enumerate(explore_suggestions):
            with explore_cols[idx % 2]:
                try:
                    fig = visualization.build_manual_chart(
                        df, suggestion["chart_type"], suggestion["col_x"], suggestion["col_y"],
                        color=suggestion["color"],
                    )
                    st.plotly_chart(fig, use_container_width=True, key=f"explore_chart_{idx}")
                    st.caption(f"💡 {suggestion['reason']} (score {suggestion['score']:.2f})")
                    # The click-through that makes Explore Mode actionable
                    # instead of just informational: preload the Manual Chart
                    # Builder's widgets with this suggestion's encoding and
                    # jump straight to a rendered chart there, no re-picking
                    # axes by hand. Writes into st.session_state BEFORE the
                    # Manual Chart Builder's own st.selectbox()es run later in
                    # this same script (see suggestion_to_builder_state's
                    # docstring) then st.rerun()s so those widgets pick up the
                    # new values on next render — the standard Streamlit
                    # "preload a keyed widget" pattern.
                    if st.button("📥 Load into Manual Builder", key=f"explore_load_{idx}", use_container_width=True):
                        for widget_key, value in visualization.suggestion_to_builder_state(suggestion).items():
                            st.session_state[widget_key] = value
                        st.session_state.manual_chart_fig = fig
                        st.session_state.manual_chart_error = None
                        st.toast(f"Loaded '{suggestion['reason']}' into Manual Builder below. 📥")
                        st.rerun()
                except Exception:
                    # A suggestion is a hint, not a guarantee — skip silently
                    # rather than breaking the whole Explore Mode panel over
                    # one edge-case column combination.
                    continue

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

    # Extra encoding channels — the grammar-of-graphics-style slice toward a
    # PyGWalker/Tableau feel: an optional Color split, a Facet (small-
    # multiples) split, a second Facet Row split (dual-axis small multiples —
    # a genuine row x column grid, added this run), and, for Bar charts, a
    # choice of aggregation function. Only shown when the picked chart type
    # actually supports them, so the row disappears/shrinks rather than
    # confusing the user with controls that would silently do nothing. Built
    # as a dynamic column list (not a fixed st.columns(2)/(3)/(4)) so a chart
    # type that supports Color + Facet but not Aggregation (everything except
    # Bar) doesn't leave a visibly empty column.
    supports_color = manual_chart_type in visualization.MANUAL_CHART_TYPES_SUPPORTING_COLOR
    supports_agg = manual_chart_type == "Bar"
    supports_facet = manual_chart_type in visualization.MANUAL_CHART_TYPES_SUPPORTING_FACET
    manual_color, manual_agg, manual_facet, manual_facet_row = None, "mean", None, None
    active_channels = [
        name
        for name, enabled in (
            ("color", supports_color), ("agg", supports_agg),
            ("facet", supports_facet), ("facet_row", supports_facet),
        )
        if enabled
    ]
    if active_channels:
        channel_cols = st.columns(len(active_channels))
        for channel, col in zip(active_channels, channel_cols):
            with col:
                if channel == "color":
                    color_options = ["(none)"] + [c for c in df.columns if c not in (manual_x, manual_y)]
                    color_label = st.selectbox("Color (optional)", color_options, key="manual_color")
                    manual_color = None if color_label == "(none)" else color_label
                elif channel == "agg":
                    agg_label = st.selectbox(
                        "Aggregation", list(visualization.MANUAL_CHART_AGG_FUNCS.keys()), key="manual_agg"
                    )
                    manual_agg = visualization.MANUAL_CHART_AGG_FUNCS[agg_label]
                elif channel == "facet":
                    facet_options = ["(none)"] + [c for c in df.columns if c not in (manual_x, manual_y, manual_color)]
                    facet_label = st.selectbox("Facet columns by (optional)", facet_options, key="manual_facet")
                    manual_facet = None if facet_label == "(none)" else facet_label
                elif channel == "facet_row":
                    facet_row_options = ["(none)"] + [
                        c for c in df.columns if c not in (manual_x, manual_y, manual_color, manual_facet)
                    ]
                    facet_row_label = st.selectbox("Facet rows by (optional)", facet_row_options, key="manual_facet_row")
                    manual_facet_row = None if facet_row_label == "(none)" else facet_row_label

    if st.button("Build Chart", use_container_width=True):
        try:
            st.session_state.manual_chart_fig = visualization.build_manual_chart(
                df, manual_chart_type, manual_x, manual_y, color=manual_color, agg=manual_agg,
                facet=manual_facet, facet_row=manual_facet_row,
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
# SQL Lab tab — a standalone DuckDB workbench: multi-table queries, a
# syntax-highlighted multi-tab editor, a saved/persistent Data Tests suite
# (assertions + linter + EXPLAIN performance analyzer), NL-to-SQL and
# AI-suggested fixes on error, and CSV/Parquet export with one-click
# hand-off into Visualize / AI Analyst. modules/sql_lab.py holds every pure
# function; this branch is Streamlit wiring only, same split as every tab.
# --------------------------------------------------------------------------
elif st.session_state.active_section == "SQL Lab":
    ui.render_help_expander(
        "A full DuckDB workbench: query your active dataset (registered as table `data`) plus any extra "
        "tables you register, save queries and test suites, and check results with data-quality "
        "assertions — all local, no server required."
    )

    st.subheader("SQL Lab")

    if sql_lab.duckdb is None:
        st.warning("The `duckdb` package isn't installed. Run `pip install -r requirements.txt` and restart the app.")
    else:
        with st.container(key="sql_lab_console"):
            tables = sql_lab_all_tables()

            # ---- Database Connection ---------------------------------------
            with st.expander(_db_connection_expander_label(), expanded=False):
                live_conn = st.session_state.db_connection
                engine_labels = ["MySQL", "PostgreSQL", "SQLite", "SQL Server"]
                engine_by_label = {"MySQL": "mysql", "PostgreSQL": "postgres", "SQLite": "sqlite", "SQL Server": "sqlserver"}
                engine_choice = st.selectbox("Engine", engine_labels, key="db_conn_engine")
                engine_type = engine_by_label[engine_choice]

                if engine_type == "sqlserver":
                    st.caption(
                        "⚠️ Needs Microsoft's ODBC Driver for SQL Server — pre-installed on Streamlit Community "
                        "Cloud, NOT present on this app's current Render deploy (would need a Docker-based "
                        "deploy to add it). Works locally if the driver is installed on your machine."
                    )

                conn_params: dict = {}
                if engine_type == "sqlite":
                    st.caption("SQLite is a local file, not a network service — upload the .db file to query it.")
                    sqlite_file = st.file_uploader(
                        "Upload a .sqlite/.db file", type=["sqlite", "db", "sqlite3"], key="db_conn_sqlite_file",
                    )
                    if sqlite_file is not None:
                        conn_params["path"] = _materialize_sqlite_upload(sqlite_file)
                else:
                    pcol1, pcol2 = st.columns(2)
                    conn_params["host"] = pcol1.text_input("Host", key="db_conn_host")
                    conn_params["port"] = pcol2.number_input(
                        "Port", key="db_conn_port", value=db_connect.ENGINE_DEFAULT_PORTS[engine_type], step=1,
                    )
                    conn_params["user"] = st.text_input("Username", key="db_conn_user")
                    conn_params["password"] = st.text_input("Password", type="password", key="db_conn_password")
                    conn_params["database"] = st.text_input("Database name", key="db_conn_database")

                test_col, connect_col, disconnect_col = st.columns(3)
                sqlite_missing = engine_type == "sqlite" and not conn_params.get("path")

                if test_col.button("Test Connection", use_container_width=True, key="db_conn_test_btn"):
                    if sqlite_missing:
                        st.warning("Upload a .sqlite/.db file first.")
                    else:
                        with st.spinner("Testing connection..."):
                            test_ok, test_err = db_connect.test_connection(engine_type, conn_params)
                        if test_ok:
                            st.success("Connection OK ✓")
                        else:
                            st.error(test_err)

                if connect_col.button("Connect", type="primary", use_container_width=True, key="db_conn_connect_btn"):
                    if sqlite_missing:
                        st.warning("Upload a .sqlite/.db file first.")
                    else:
                        with st.spinner("Connecting..."):
                            connect_ok, connect_err = db_connect.test_connection(engine_type, conn_params)
                        if not connect_ok:
                            st.error(connect_err)
                        else:
                            params_key = db_connect.build_connection_params_key(engine_type, conn_params)
                            try:
                                if engine_type == "sqlserver":
                                    conn_obj = db_connect.get_sqlserver_engine(params_key)
                                else:
                                    conn_obj = db_connect.get_duckdb_attach_connection(engine_type, params_key)
                                table_names = db_connect.get_live_table_names(engine_type, conn_obj)
                            except Exception as e:
                                st.error(f"Connected, but couldn't list tables: {e}")
                                table_names = []
                            # Cache a small column-schema sample per table now, once,
                            # instead of re-sampling on every Atlas SQL question — this
                            # is what lets generate_sql() describe live-only tables
                            # (ones the local active dataset knows nothing about).
                            table_schemas: dict[str, str] = {}
                            for _tname in table_names[:8]:  # cap — a live DB could have hundreds
                                _sample_df, _sample_err = db_connect.get_live_table_sample(
                                    engine_type, conn_obj, _tname, n=5
                                )
                                if _sample_df is not None:
                                    table_schemas[_tname] = ", ".join(
                                        f"{c} ({_sample_df[c].dtype})" for c in _sample_df.columns
                                    )
                            st.session_state.db_connection = {
                                "engine_type": engine_type, "params": conn_params, "params_key": params_key,
                                "status": "connected", "error": None,
                            }
                            st.session_state.db_connection_tables = table_names
                            st.session_state.db_connection_table_schemas = table_schemas
                            st.toast(f"Connected to {engine_choice} — {len(table_names)} table(s) visible. 🔌")
                            st.rerun()

                if live_conn and disconnect_col.button("Disconnect", use_container_width=True, key="db_conn_disconnect_btn"):
                    db_connect.disconnect(live_conn["engine_type"])
                    st.session_state.db_connection = None
                    st.session_state.db_connection_tables = []
                    st.session_state.db_connection_table_schemas = {}
                    st.toast("Disconnected.")
                    st.rerun()

                if live_conn:
                    live_label = db_connect.ENGINE_LABELS.get(live_conn["engine_type"], live_conn["engine_type"])
                    st.caption(f"🟢 Connected · {live_label} · {len(st.session_state.db_connection_tables)} table(s) visible")
                    if st.session_state.db_connection_tables:
                        st.caption(", ".join(f"`{t}`" for t in st.session_state.db_connection_tables[:20]))

            # ---- Registered Tables ---------------------------------------
            with st.expander(f"Registered Tables ({len(tables)})", expanded=False):
                st.caption(f'`data` — active dataset · {len(df):,} rows × {df.shape[1]} columns')
                for tname, tdf in list(st.session_state.sql_lab_extra_tables.items()):
                    rm_col, info_col = st.columns([1, 8])
                    if rm_col.button("✕", key=f"sql_table_rm_{tname}", help=f"Remove {tname}"):
                        del st.session_state.sql_lab_extra_tables[tname]
                        st.rerun()
                    info_col.caption(f'`{tname}` — {len(tdf):,} rows × {tdf.shape[1]} columns')

                if st.session_state.db_connection and st.session_state.db_connection_tables:
                    live_label = db_connect.ENGINE_LABELS.get(
                        st.session_state.db_connection["engine_type"], st.session_state.db_connection["engine_type"]
                    )
                    for tname in st.session_state.db_connection_tables:
                        st.caption(f'`live.{tname}` — live {live_label} table (via the Database Connection above)')

                st.markdown("**Register another table**")
                extra_file = st.file_uploader(
                    "Upload a CSV/Excel file to query alongside `data` (this session only)",
                    type=["csv", "xlsx", "xls"], key="sql_lab_extra_uploader",
                )
                if extra_file is not None:
                    default_name = re.sub(r"\W+", "_", extra_file.name.rsplit(".", 1)[0]).strip("_").lower() or "table2"
                    new_table_name = st.text_input("Table name", value=default_name, key="sql_lab_extra_name")
                    if st.button("Register Table", key="sql_lab_register_btn"):
                        extra_df, load_error, _warnings = data_engine.load_data(extra_file)
                        if load_error:
                            st.error(load_error)
                        elif new_table_name == "data" or new_table_name in st.session_state.sql_lab_extra_tables:
                            st.error(f'"{new_table_name}" is already in use — pick a different table name.')
                        else:
                            st.session_state.sql_lab_extra_tables[new_table_name] = extra_df
                            st.toast(f'Registered "{new_table_name}" — {len(extra_df):,} rows. 🗄️')
                            st.rerun()

            # ---- Query tabs strip -----------------------------------------
            # A selectbox, not st.tabs() — same reason the app's own main nav
            # avoids it: this needs Python-side control over which tab's text
            # feeds the one editor instance below. Keyed with sql_lab_tabs_rev
            # so New/Close force a clean remount instead of fighting the
            # widget's own sticky session_state (same trick the primary nav
            # uses via nav_primary_pills — see its comment above).
            tab_pick_col, new_tab_col, close_tab_col = st.columns([6, 1, 1])
            tab_labels = {t["id"]: t["name"] for t in st.session_state.sql_lab_tabs}
            picker_key = f"sql_lab_tab_picker_{st.session_state.sql_lab_tabs_rev}"
            with tab_pick_col:
                default_index = (
                    list(tab_labels.keys()).index(st.session_state.sql_lab_active_tab_id)
                    if st.session_state.sql_lab_active_tab_id in tab_labels else 0
                )
                picked_id = st.selectbox(
                    "Open queries", options=list(tab_labels.keys()), format_func=lambda tid: tab_labels[tid],
                    index=default_index, key=picker_key, label_visibility="collapsed",
                )
            if picked_id != st.session_state.sql_lab_active_tab_id:
                st.session_state.sql_lab_active_tab_id = picked_id
                st.rerun()
            with new_tab_col:
                if st.button("+ New", key="sql_lab_new_tab", use_container_width=True):
                    new_id = f"t{uuid.uuid4().hex[:8]}"
                    n = len(st.session_state.sql_lab_tabs) + 1
                    st.session_state.sql_lab_tabs.append({"id": new_id, "name": f"Query {n}", "sql": ""})
                    st.session_state.sql_lab_active_tab_id = new_id
                    st.session_state.sql_lab_tabs_rev += 1
                    st.rerun()
            with close_tab_col:
                if st.button(
                    "✕ Close", key="sql_lab_close_tab", use_container_width=True,
                    disabled=len(st.session_state.sql_lab_tabs) <= 1,
                ):
                    st.session_state.sql_lab_tabs = [
                        t for t in st.session_state.sql_lab_tabs if t["id"] != st.session_state.sql_lab_active_tab_id
                    ]
                    st.session_state.sql_lab_active_tab_id = st.session_state.sql_lab_tabs[0]["id"]
                    st.session_state.sql_lab_tabs_rev += 1
                    st.rerun()

            active_tab = sql_lab_active_tab()

            def _sql_lab_inject(new_sql: str) -> None:
                """Programmatically replace the editor's content (example
                query, NL2SQL result, a loaded saved query/history entry, an
                AI fix suggestion). Bumps sql_lab_editor_rev so the editor
                widget remounts under a fresh key instead of trying to write
                to an already-instantiated widget's session_state — which
                Streamlit forbids, and which a button below the editor on
                the page would otherwise hit every time."""
                active_tab["sql"] = new_sql
                st.session_state.sql_lab_editor_rev += 1
                st.rerun()

            # ---- Example queries --------------------------------------------
            examples = sql_lab.build_example_queries(df, column_types)
            st.markdown("**Example Queries**")
            example_cols = st.columns(len(examples))
            for ex_col, (label, example_sql) in zip(example_cols, examples.items()):
                with ex_col:
                    if st.button(label, key=f"sql_example_{active_tab['id']}_{label}", use_container_width=True):
                        _sql_lab_inject(example_sql)

            # ---- NL-to-SQL ----------------------------------------------
            with st.expander("💬 Generate SQL from a question", expanded=False):
                st.text_input(
                    "Describe what you want", key="sql_lab_gen_sql_question",
                    placeholder="e.g. average order value by month for the last year",
                )
                if st.button("Generate SQL", key="sql_lab_generate_btn"):
                    question = st.session_state.sql_lab_gen_sql_question.strip()
                    if not question:
                        st.warning("Describe what you want first.")
                    else:
                        gen_model = ai_analyst.get_sql_model()
                        if gen_model is None:
                            st.warning(ai_analyst.GEMINI_SETUP_HELP)
                        else:
                            with st.spinner(ui.get_loading_message()):
                                generated_sql, gen_error = ai_analyst.generate_sql(gen_model, df, column_types, question)
                            if gen_error:
                                st.error(gen_error)
                            else:
                                _sql_lab_inject(generated_sql)

            # ---- Column chips — the practical stand-in for autocomplete;
            # no maintained Streamlit code-editor component exposes a real
            # completion hook (flagged in the approved plan). ----------------
            with st.expander("Insert a column name", expanded=False):
                col_names = list(df.columns)
                per_row = 4
                for i in range(0, len(col_names), per_row):
                    row_cols = st.columns(per_row)
                    for j, cname in enumerate(col_names[i:i + per_row]):
                        with row_cols[j]:
                            if st.button(cname, key=f"sql_colchip_{active_tab['id']}_{cname}", use_container_width=True):
                                _sql_lab_inject((active_tab["sql"].rstrip() + f' "{cname}"').lstrip())

            # ---- Editor -------------------------------------------------
            editor_key = f"sql_lab_editor_{active_tab['id']}_{st.session_state.sql_lab_editor_rev}"
            if st_ace is not None:
                query_text = st_ace(
                    value=active_tab["sql"], language="sql", theme="tomorrow_night",
                    key=editor_key, height=180, font_size=14, tab_size=2,
                    show_gutter=True, wrap=False, auto_update=True,
                    placeholder="SELECT * FROM data LIMIT 10;",
                )
            else:
                query_text = st.text_area(
                    "SQL query", value=active_tab["sql"], key=editor_key, height=180,
                    placeholder="SELECT * FROM data LIMIT 10;", label_visibility="collapsed",
                )
            active_tab["sql"] = query_text or ""

            lint_findings = sql_lab.lint_query(query_text)
            if lint_findings:
                st.markdown(
                    "".join(
                        f'<span class="prism-badge {"b-fail" if f["severity"] == "warn" else "b-txt"}" '
                        f'style="margin:2px 6px 2px 0;">{html.escape(f["message"])}</span>'
                        for f in lint_findings
                    ),
                    unsafe_allow_html=True,
                )

            # ---- Actions --------------------------------------------------
            run_col, explain_col, fix_col = st.columns(3)
            with run_col:
                run_clicked = st.button("Run Query", type="primary", use_container_width=True)
            with explain_col:
                explain_clicked = st.button("Explain This Query", use_container_width=True)
            with fix_col:
                # Not gated on `disabled=not st.session_state.sql_error` — Run Query sets
                # sql_error further down in this SAME script pass, after this row has
                # already rendered, so a disabled= computed here would always be one run
                # stale (permanently disabled the instant an error first appears, since a
                # browser-disabled button never sends the click that would re-render it
                # enabled). The empty-error case is instead handled inside the click branch.
                fix_clicked = st.button("Suggest a Fix", use_container_width=True)

            def _execute_sql_lab_query(query_text_run: str) -> None:
                result = sql_lab_run_query(query_text_run)
                st.session_state.sql_result_df = result["result_df"]
                st.session_state.sql_error = result["error"]
                st.session_state.sql_exec_time = result["elapsed_seconds"]
                st.session_state.sql_lab_truncated = result["truncated"]
                st.session_state.sql_lab_row_count_full = result["row_count_full"]
                st.session_state.sql_lab_fix_suggestion = ""
                st.session_state.sql_lab_fix_error = None
                history_entry = {
                    "sql": query_text_run,
                    "status": "error" if result["error"] else "ok",
                    "elapsed_seconds": result["elapsed_seconds"],
                    "rows": result["row_count_full"],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": sql_lab_live_backend() or "local",  # which backend actually ran it
                }
                st.session_state.sql_lab_history = ([history_entry] + st.session_state.sql_lab_history)[:50]

            if run_clicked:
                query_text_run = active_tab["sql"].strip()
                if not query_text_run:
                    st.warning("Write a query first — the editor is empty.")
                elif sql_lab_live_backend() and db_connect.is_destructive_statement(query_text_run):
                    st.session_state.db_pending_confirm_sql = query_text_run
                    st.rerun()
                else:
                    # A fresh, non-destructive run means the user has moved on —
                    # drop any stale staged confirmation from an earlier query so
                    # it doesn't linger on screen (or get run) against new intent.
                    st.session_state.db_pending_confirm_sql = None
                    _execute_sql_lab_query(query_text_run)

            # ---- Destructive-statement confirmation gate (live DB only) -----
            # Local/uploaded-data queries never reach here — they only ever run
            # against an ephemeral, non-writable DuckDB VIEW over a pandas
            # DataFrame, which INSERT/UPDATE/DELETE/DROP already fails against
            # at the DuckDB engine level regardless of anything this app does.
            if st.session_state.db_pending_confirm_sql:
                live_label_gate = db_connect.ENGINE_LABELS.get(
                    sql_lab_live_backend(), sql_lab_live_backend() or "the connected database"
                )
                st.warning(
                    f"This statement will modify live data in your connected {live_label_gate} database "
                    "and cannot be undone by Prism."
                )
                st.code(st.session_state.db_pending_confirm_sql, language="sql")
                gate_confirmed = st.checkbox("I understand this changes live data", key="db_confirm_checkbox")
                gate_col1, gate_col2 = st.columns(2)
                if gate_col1.button(
                    "Run Anyway", type="primary", use_container_width=True,
                    disabled=not gate_confirmed, key="db_confirm_run_btn",
                ):
                    _execute_sql_lab_query(st.session_state.db_pending_confirm_sql)
                    st.session_state.db_pending_confirm_sql = None
                    st.rerun()
                if gate_col2.button("Cancel", use_container_width=True, key="db_confirm_cancel_btn"):
                    st.session_state.db_pending_confirm_sql = None
                    st.rerun()

            # ---- Results ----------------------------------------------------
            if st.session_state.sql_error:
                st.error(st.session_state.sql_error)
                if fix_clicked:
                    fix_model = ai_analyst.get_sql_model()
                    if fix_model is None:
                        st.warning(ai_analyst.GEMINI_SETUP_HELP)
                    else:
                        with st.spinner(ui.get_loading_message()):
                            fix_sql, fix_error = ai_analyst.suggest_sql_fix(
                                fix_model, active_tab["sql"], st.session_state.sql_error
                            )
                        st.session_state.sql_lab_fix_suggestion = fix_sql
                        st.session_state.sql_lab_fix_error = fix_error
                if st.session_state.sql_lab_fix_error:
                    st.error(st.session_state.sql_lab_fix_error)
                elif st.session_state.sql_lab_fix_suggestion:
                    st.code(st.session_state.sql_lab_fix_suggestion, language="sql")
                    if st.button("Use This Fix", key="sql_lab_use_fix"):
                        _sql_lab_inject(st.session_state.sql_lab_fix_suggestion)
            elif st.session_state.sql_result_df is not None:
                result_df = st.session_state.sql_result_df
                cap_note = (
                    f" · showing first {len(result_df):,} of {st.session_state.sql_lab_row_count_full:,} rows"
                    if st.session_state.sql_lab_truncated else ""
                )
                st.caption(f"{len(result_df):,} rows · {st.session_state.sql_exec_time * 1000:.1f} ms{cap_note}")
                if st.session_state.sql_lab_truncated:
                    st.info(f"Result truncated to {sql_lab.DEFAULT_ROW_CAP:,} rows for display — export for the full result.")
                st.dataframe(result_df, use_container_width=True)

                exp_col1, exp_col2, viz_col, ai_col, load_col = st.columns(5)
                with exp_col1:
                    st.download_button(
                        "Download CSV", data=result_df.to_csv(index=False).encode("utf-8"),
                        file_name="prism_sql_result.csv", mime="text/csv", use_container_width=True,
                    )
                with exp_col2:
                    try:
                        parquet_bytes = result_df.to_parquet(index=False)
                    except Exception:
                        parquet_bytes = None
                    if parquet_bytes is not None:
                        st.download_button(
                            "Download Parquet", data=parquet_bytes, file_name="prism_sql_result.parquet",
                            mime="application/octet-stream", use_container_width=True,
                        )
                    else:
                        st.caption("Parquet export unavailable for this result.")
                with viz_col:
                    if st.button("Send to Visualize", use_container_width=True):
                        set_active_dataset(
                            result_df.copy(), result_df.copy(), "sql_lab_result",
                            cleaning_log=[{"description": "SQL Lab query result", "code": active_tab["sql"]}],
                        )
                        st.session_state.jump_to_tab = "Visualize"
                        st.rerun()
                with ai_col:
                    if st.button("Send to AI Analyst", use_container_width=True):
                        set_active_dataset(
                            result_df.copy(), result_df.copy(), "sql_lab_result",
                            cleaning_log=[{"description": "SQL Lab query result", "code": active_tab["sql"]}],
                        )
                        st.session_state.jump_to_tab = "AI Analyst"
                        st.rerun()
                with load_col:
                    # Reuses set_active_dataset() exactly like Send to Visualize/AI
                    # Analyst above and the Combine tab's "Use as Active Dataset" —
                    # no separate row-cap/browse-tables feature: volume is controlled
                    # by the user's own query LIMIT/WHERE, same as any other result here.
                    if st.button("Load as Active Dataset", use_container_width=True):
                        source_label = (
                            f"live:{sql_lab_live_backend()}" if sql_lab_live_backend() else "sql_lab_result"
                        )
                        set_active_dataset(
                            result_df.copy(), result_df.copy(), source_label,
                            cleaning_log=[{"description": "SQL Lab query result", "code": active_tab["sql"]}],
                        )
                        st.toast("Loaded as your active dataset — Clean/Visualize/AI Analyst can all use it now. 📊")
                        st.rerun()
            else:
                ui.render_empty_state(
                    "🗄️", "No query run yet", "Try an example query above, or write your own and click \"Run Query\"."
                )

            if explain_clicked:
                query_text_exp = active_tab["sql"].strip()
                if not query_text_exp:
                    st.warning("Write a query first — the editor is empty.")
                else:
                    gemini_model_sql = ai_analyst.get_sql_model()
                    if gemini_model_sql is None:
                        st.warning(ai_analyst.GEMINI_SETUP_HELP)
                    else:
                        with st.spinner(ui.get_loading_message()):
                            explanation, explain_error = ai_analyst.explain_sql(gemini_model_sql, query_text_exp)
                        st.session_state.sql_explanation = explanation
                        st.session_state.sql_explanation_error = explain_error

            if st.session_state.sql_explanation_error:
                st.error(st.session_state.sql_explanation_error)
            elif st.session_state.sql_explanation:
                st.info(st.session_state.sql_explanation)

            # ---- Data Tests -------------------------------------------------
            st.divider()
            st.markdown("#### Data Tests")
            st.caption("Assertions that check your query result — one failing check never blocks the others.")

            sugg_col, run_suite_col = st.columns(2)
            with sugg_col:
                if st.button("Auto-Suggest Assertions", use_container_width=True):
                    quality = data_engine.get_data_quality_report(df, column_types)
                    st.session_state.sql_lab_assertions = sql_lab.suggest_assertions(df, column_types, quality)
            with run_suite_col:
                if st.button(
                    "Run Test Suite", type="primary", use_container_width=True,
                    disabled=not st.session_state.sql_lab_assertions,
                ):
                    st.session_state.sql_lab_assertion_results = sql_lab.run_assertions(
                        tables, st.session_state.sql_lab_assertions
                    )

            if st.session_state.sql_lab_assertions:
                with st.expander(f"Current suite ({len(st.session_state.sql_lab_assertions)} checks)", expanded=False):
                    for i, a in enumerate(st.session_state.sql_lab_assertions):
                        acol, xcol = st.columns([8, 1])
                        acol.caption(f'`{a["name"]}` — {a["type"]}' + (f' on `{a["column"]}`' if a.get("column") else ""))
                        if xcol.button("✕", key=f"sql_lab_assertion_rm_{i}"):
                            st.session_state.sql_lab_assertions.pop(i)
                            st.rerun()

                    st.markdown("**Add a custom check**")
                    custom_name = st.text_input("Name", key="sql_lab_custom_assertion_name")
                    custom_expr = st.text_input(
                        "SQL that returns a single boolean", key="sql_lab_custom_assertion_expr",
                        placeholder="SELECT COUNT(*) = 0 FROM data WHERE amount < 0",
                    )
                    if st.button("Add Check", key="sql_lab_add_assertion"):
                        if not custom_expr.strip():
                            st.warning("Write a boolean SQL check first.")
                        else:
                            st.session_state.sql_lab_assertions.append({
                                "name": custom_name.strip() or "custom check",
                                "type": "custom_sql", "table": "data", "column": None,
                                "value": None, "sql_expr": custom_expr.strip(),
                            })
                            st.rerun()

                sc1, sc2 = st.columns(2)
                with sc1:
                    suite_name = st.text_input("Suite name", key="sql_lab_suite_name_input", value="my_test_suite")
                    st.download_button(
                        "Save Test Suite", data=sql_lab.save_test_suite(suite_name, st.session_state.sql_lab_assertions),
                        file_name=f"{suite_name or 'test_suite'}.json", mime="application/json", use_container_width=True,
                    )
                with sc2:
                    suite_file = st.file_uploader("Load Test Suite", type=["json"], key="sql_lab_suite_uploader")
                    if suite_file is not None:
                        loaded_suite, load_error = sql_lab.load_test_suite(suite_file.getvalue())
                        if load_error:
                            st.error(load_error)
                        elif st.button("Apply Loaded Suite", key="sql_lab_apply_suite"):
                            st.session_state.sql_lab_assertions = loaded_suite["assertions"]
                            st.rerun()

            if st.session_state.sql_lab_assertion_results:
                ui.render_assertion_results(st.session_state.sql_lab_assertion_results)
            elif not st.session_state.sql_lab_assertions:
                st.caption('No checks yet — click "Auto-Suggest Assertions" or add a custom one above.')

            # ---- Performance Analyzer -----------------------------------
            with st.expander("⚡ Performance Analyzer", expanded=False):
                st.caption("Runs EXPLAIN ANALYZE against the query above — executes it once more to profile it.")
                if sql_lab_live_backend() == "sqlserver":
                    st.caption("Not available for SQL Server connections yet — DuckDB's EXPLAIN doesn't reach that executor.")
                elif st.button("Analyze Performance", key="sql_lab_explain_btn"):
                    query_text_plan = active_tab["sql"].strip()
                    if not query_text_plan:
                        st.warning("Write a query first — the editor is empty.")
                    else:
                        plan_text, plan_error = sql_lab.explain_query(tables, query_text_plan, **(sql_lab_attach_info() or {}))
                        st.session_state.sql_lab_explain_plan = plan_text
                        st.session_state.sql_lab_explain_error = plan_error
                if st.session_state.sql_lab_explain_error:
                    st.error(st.session_state.sql_lab_explain_error)
                elif st.session_state.sql_lab_explain_plan:
                    st.code(st.session_state.sql_lab_explain_plan, language="text")

            # ---- Saved Queries --------------------------------------------
            with st.expander("💾 Saved Queries", expanded=False):
                name_col, save_col = st.columns([3, 1])
                query_name = name_col.text_input(
                    "Name this query", key="sql_lab_query_name_input",
                    label_visibility="collapsed", placeholder="Name this query",
                )
                save_col.download_button(
                    "Save", data=sql_lab.save_saved_query(query_name or active_tab["name"], active_tab["sql"]),
                    file_name=f"{(query_name or 'query').strip().replace(' ', '_')}.json", mime="application/json",
                    use_container_width=True,
                )

                loaded_query_file = st.file_uploader("Load a saved query", type=["json"], key="sql_lab_query_uploader")
                if loaded_query_file is not None:
                    loaded_query, load_q_error = sql_lab.load_saved_query(loaded_query_file.getvalue())
                    if load_q_error:
                        st.error(load_q_error)
                    elif st.button("Load Into Active Tab", key="sql_lab_load_query_btn"):
                        if not any(q["name"] == loaded_query["name"] for q in st.session_state.sql_lab_saved_queries):
                            st.session_state.sql_lab_saved_queries.append(loaded_query)
                        _sql_lab_inject(loaded_query["sql"])

                if st.session_state.sql_lab_saved_queries:
                    st.markdown("**This session**")
                    for q in st.session_state.sql_lab_saved_queries:
                        if st.button(q["name"], key=f"sql_lab_saved_pick_{q['name']}", use_container_width=True):
                            _sql_lab_inject(q["sql"])

                # ---- Persisted across sessions (MySQL-backed, optional) ----
                # A separate button (not piggybacked on the download button
                # above) so a plain local-file save never has a surprising
                # server-side side effect. Renders nothing at all when MySQL
                # isn't configured — see modules/app_db.py's docstring.
                if app_db.is_configured():
                    visitor_id = app_db.get_visitor_id()
                    if st.button(
                        "☁️ Save to My Account", key="sql_lab_save_to_account", use_container_width=True,
                    ):
                        acct_ok, acct_err = app_db.save_saved_query(
                            visitor_id, query_name or active_tab["name"], active_tab["sql"],
                        )
                        if acct_ok:
                            st.toast("Saved to your account. ☁️")
                        else:
                            st.error(acct_err)
                    account_queries = app_db.list_saved_queries(visitor_id)
                    if account_queries:
                        st.markdown("**Saved to your account**")
                        for q in account_queries:
                            qcol, delcol = st.columns([5, 1])
                            if qcol.button(q["name"], key=f"sql_lab_db_pick_{q['id']}", use_container_width=True):
                                _sql_lab_inject(q["sql_text"])
                            if delcol.button("🗑️", key=f"sql_lab_db_del_{q['id']}"):
                                app_db.delete_saved_query(visitor_id, q["id"])
                                st.rerun()

            # ---- Query History ----------------------------------------------
            with st.expander(f"🕘 Query History ({len(st.session_state.sql_lab_history)})", expanded=False):
                hcol1, hcol2 = st.columns(2)
                with hcol1:
                    st.download_button(
                        "Export History", data=sql_lab.save_query_history(st.session_state.sql_lab_history),
                        file_name="prism_sql_history.json", mime="application/json", use_container_width=True,
                        disabled=not st.session_state.sql_lab_history,
                    )
                with hcol2:
                    history_file = st.file_uploader("Import History", type=["json"], key="sql_lab_history_uploader")
                    if history_file is not None:
                        loaded_history, hist_error = sql_lab.load_query_history(history_file.getvalue())
                        if hist_error:
                            st.error(hist_error)
                        else:
                            st.session_state.sql_lab_history = (loaded_history + st.session_state.sql_lab_history)[:50]

                for idx, h in enumerate(st.session_state.sql_lab_history[:20]):
                    hrow1, hrow2 = st.columns([5, 1])
                    status_txt = "OK" if h["status"] == "ok" else "ERROR"
                    source = h.get("source", "local")  # older history entries predate this tag — default to local
                    source_txt = "" if source == "local" else f" · {db_connect.ENGINE_LABELS.get(source, source)} (live)"
                    hrow1.caption(
                        f'`{status_txt}` · {h["rows"]:,} rows · {h["elapsed_seconds"] * 1000:.0f} ms{source_txt} — {h["sql"][:80]}'
                    )
                    if hrow2.button("Reload", key=f"sql_lab_history_reload_{idx}", use_container_width=True):
                        _sql_lab_inject(h["sql"])

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
            # Same static, zero-extra-Gemini-call fact-check pass Run 10 wired
            # into Auto Analyst's "Run Full Analysis" findings — this button
            # is a second, separate Gemini call that quotes numbers straight
            # from the data and had no verification of its own until now.
            st.session_state.key_insights_verification = (
                insight_verifier.verify_findings(df, column_types, insights) if insights else []
            )

        if st.session_state.key_insights_error:
            st.error(st.session_state.key_insights_error)
        elif st.session_state.key_insights:
            caption = ui.build_verification_caption(st.session_state.key_insights_verification)
            if caption:
                st.caption(caption)
            st.markdown(
                ui.build_insight_cards_html(st.session_state.key_insights, st.session_state.key_insights_verification),
                unsafe_allow_html=True,
            )

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
                verification = st.session_state.auto_analyst_verification
                caption = ui.build_verification_caption(verification)
                if caption:
                    st.caption(caption)
                st.markdown(
                    ui.build_insight_cards_html(st.session_state.auto_analyst_findings, verification),
                    unsafe_allow_html=True,
                )

                hypothesis = auto_analyst.suggest_followup_hypothesis(df, column_types)
                if hypothesis:
                    st.info(f"🔬 **Suggested next step:** {hypothesis['reason']}")
                    if st.button(
                        f"Test '{hypothesis['col_a']}' vs '{hypothesis['col_b']}' in Stats Lab",
                        use_container_width=True, key="jump_to_stats_lab_hypothesis",
                    ):
                        st.session_state.stats_col_a = hypothesis["col_a"]
                        st.session_state.stats_col_b = hypothesis["col_b"]
                        st.session_state.pending_active_section = "Stats Lab"
                        st.rerun()

                if st.button("🎬 Story Mode", type="primary", use_container_width=True, key="enter_story_mode"):
                    # Story Mode (modules/story_mode.py) narrates
                    # st.session_state.key_insights — hand it this run's Auto
                    # Analyst findings so Atlas narrates what was just found here.
                    st.session_state.key_insights = st.session_state.auto_analyst_findings
                    st.session_state.key_insights_error = None
                    st.session_state.key_insights_verification = st.session_state.auto_analyst_verification
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

        st.divider()
        st.markdown("#### 🔎 Hypothesis Sweep — automated multi-test scan")
        st.caption(
            "Runs every viable pairwise test across the dataset automatically (instead of one "
            "pair at a time) and corrects for the multiple-comparisons problem with "
            "Benjamini-Hochberg false-discovery-rate correction, so the findings that survive "
            "are statistically defensible, not noise."
        )

        if st.button("Run Hypothesis Sweep", key="run_hypothesis_sweep_btn"):
            with st.spinner(ui.get_loading_message()):
                sweep_result_new = hypothesis_sweep.sweep_hypotheses(df, column_types)
                # Post-hoc power check on every significant row (t-test,
                # chi-square, ANOVA, Pearson correlation) — no extra
                # Gemini call, pure statsmodels/scipy.
                sweep_result_new = hypothesis_sweep.annotate_power(sweep_result_new)
                st.session_state.hypothesis_sweep_result = sweep_result_new
                # Agentic follow-up, same spinner: does the sweep's own strongest
                # finding hold up once you control for a third variable? No
                # extra Gemini call — see cross_check_confounders()'s docstring.
                st.session_state.hypothesis_sweep_confounder_check = hypothesis_sweep.cross_check_confounders(
                    df, column_types, sweep_result_new
                )
                # Second agentic follow-up, same spinner: does a significant
                # group difference (one-way ANOVA) actually depend on a third
                # categorical column, or does it hold up the same way for
                # everyone? Different question from the confounder check
                # above (no signed effect to flip here) — see
                # cross_check_interactions()'s docstring. No extra Gemini call.
                st.session_state.hypothesis_sweep_interaction_check = hypothesis_sweep.cross_check_interactions(
                    df, column_types, sweep_result_new
                )
                # Third agentic follow-up, same spinner: the chi-square analog
                # of the interaction check above — does the *association*
                # between two categorical columns itself depend on a third
                # categorical column? See cross_check_categorical_interactions()'s
                # docstring. No extra Gemini call.
                st.session_state.hypothesis_sweep_categorical_interaction_check = (
                    hypothesis_sweep.cross_check_categorical_interactions(
                        df, column_types, sweep_result_new
                    )
                )
            st.session_state.hypothesis_sweep_narration = None
            st.session_state.hypothesis_sweep_narration_fingerprint = None
            st.session_state.hypothesis_sweep_narration_verification = None
            st.session_state.hypothesis_sweep_confounder_narrations = {}

        sweep_result = st.session_state.hypothesis_sweep_result
        if sweep_result is None:
            ui.render_empty_state(
                "🔎", "No sweep run yet",
                'Click "Run Hypothesis Sweep" to automatically test every column pair.',
            )
        elif not sweep_result["tested"]:
            st.info("No column pairs were viable to test in this dataset.")
        else:
            sw1, sw2, sw3 = st.columns(3)
            sw1.metric("Tests run", sweep_result["n_tests_run"])
            sw2.metric("Significant after FDR correction", sweep_result["n_significant"])
            sw3.metric("Pairs skipped", sweep_result["n_pairs_skipped"])

            significant_rows = [r for r in sweep_result["tested"] if r["significant"]]
            if not significant_rows:
                st.info(
                    f"None of the {sweep_result['n_tests_run']} test(s) run stayed significant "
                    "after false-discovery-rate correction — no reliable relationships found."
                )
            else:
                def _power_badge(row: dict) -> str:
                    check = row.get("power_check")
                    if check is None:
                        return "—"
                    pct = f"{check['achieved_power']:.0%}"
                    return f"⚠️ {pct}" if check["underpowered"] else f"✅ {pct}"

                sweep_df = pd.DataFrame(
                    [
                        {
                            "Column A": r["col_a"],
                            "Column B": r["col_b"],
                            "Test": r["test_label"],
                            "Effect size": f"{r['effect_size']:.3f} ({r['effect_size_label']})",
                            "p (raw)": f"{r['p_value']:.4g}",
                            "p (FDR-adjusted)": f"{r['p_adj']:.4g}",
                            "n": r["n"],
                            "Power": _power_badge(r),
                        }
                        for r in significant_rows
                    ]
                )
                st.dataframe(sweep_df, use_container_width=True, hide_index=True)

                sweep_chart = hypothesis_sweep.build_sweep_chart(sweep_result)
                if sweep_chart is not None:
                    st.plotly_chart(sweep_chart, use_container_width=True)

                # Power check detail — a "Power" badge in the table above is
                # easy to skim past; underpowered findings (t-test, chi-square,
                # ANOVA, or Pearson correlation — see annotate_power()) get a
                # plain-English callout with a concrete follow-up sample size,
                # same "don't just flag it, tell them what to do next" pattern
                # as the confounder cross-check below.
                underpowered_rows = [
                    r for r in significant_rows
                    if r.get("power_check") and r["power_check"]["underpowered"]
                ]
                if underpowered_rows:
                    with st.expander(
                        f"⚠️ {len(underpowered_rows)} significant result"
                        f"{'s' if len(underpowered_rows) != 1 else ''} may be underpowered",
                        expanded=False,
                    ):
                        st.caption(
                            "A significant p-value from a small sample doesn't mean the effect "
                            "is trustworthy — these tests had low statistical power to detect an "
                            "effect this size in the first place, which is exactly the kind of "
                            "result that fails to replicate."
                        )
                        for r in underpowered_rows:
                            st.markdown(
                                f"**{r['col_a']} vs {r['col_b']}** — "
                                f"{experiment_design.interpret_power_check(r['power_check'])}"
                            )

                # Confounder cross-check — the sweep's own agentic follow-up
                # question ("does the strongest FDR-significant pair hold up
                # once you control for a third variable?"), same pattern as
                # Overview's Confounder Check panel but scoped to this sweep.
                sweep_confounder_scan = st.session_state.hypothesis_sweep_confounder_check
                if sweep_confounder_scan:
                    n_sweep_pairs = len(sweep_confounder_scan)
                    st.markdown(
                        f"**🧭 Confounder cross-check** — {n_sweep_pairs} significant "
                        f"pair{'s' if n_sweep_pairs != 1 else ''} worth a second look"
                    )
                    st.caption(
                        "Surviving FDR correction across many tests doesn't mean a pair is "
                        "causally clean — these still flip sign or weaken once a third "
                        "variable is controlled for."
                    )
                    for scan in sweep_confounder_scan:
                        x_col, y_col = scan["x"], scan["y"]
                        is_group_diff = scan.get("relationship") == "group_diff"
                        for finding in scan["findings"]:
                            verdict = finding["verdict"]
                            badge = "🔴 Paradox" if verdict == "paradox" else "🟡 Confounded"
                            relation_word = "differs by" if is_group_diff else "vs"
                            label = (
                                f"{badge} — **{x_col}** {relation_word} **{y_col}**, controlling for **{finding['confounder']}**"
                            )
                            with st.expander(label, expanded=False):
                                sweep_cache_key = (x_col, y_col, finding["confounder"], scan.get("relationship", "correlation"))
                                if is_group_diff:
                                    label1, label2 = finding["group_labels"]
                                    st.caption(
                                        f"Pooled ({label1} vs {label2}): Cohen's d = {finding['overall_d']:.2f}  •  "
                                        f"Adjusted: Cohen's d = {finding['adjusted_d']:.2f}"
                                    )
                                    sweep_group_df = pd.DataFrame(finding["detail"])[["group", "mean_diff", "d", "n"]]
                                    sweep_group_df.columns = [finding["confounder"], "mean diff within group", "d within group", "n"]
                                    st.dataframe(sweep_group_df, use_container_width=True, hide_index=True)
                                else:
                                    st.caption(
                                        f"Pooled correlation: r = {finding['overall_r']:.2f}  •  "
                                        f"Adjusted: r = {finding['adjusted_r']:.2f}"
                                    )
                                    if finding["type"] == "categorical":
                                        sweep_group_df = pd.DataFrame(finding["detail"])[["group", "r", "n"]]
                                        sweep_group_df.columns = [finding["confounder"], "r within group", "n"]
                                        st.dataframe(sweep_group_df, use_container_width=True, hide_index=True)
                                    else:
                                        st.caption(f"n = {finding['detail']['n']}")
                                sweep_cached = st.session_state.hypothesis_sweep_confounder_narrations.get(sweep_cache_key)
                                if sweep_cached:
                                    st.info(sweep_cached)
                                elif st.button(
                                    "✨ Explain this",
                                    key=f"sweep_confounder_narrate_{x_col}_{y_col}_{finding['confounder']}_{scan.get('relationship', 'correlation')}",
                                ):
                                    sweep_confounder_model = ai_analyst.get_model()
                                    with st.spinner("Gemini is interpreting this…"):
                                        narrate_fn = (
                                            confounder_detection.narrate_group_diff_confounder_finding
                                            if is_group_diff
                                            else confounder_detection.narrate_confounder_finding
                                        )
                                        sweep_conf_narration, sweep_conf_error = narrate_fn(
                                            sweep_confounder_model, x_col, y_col, finding
                                        )
                                    if sweep_conf_error:
                                        st.warning(sweep_conf_error)
                                    else:
                                        st.session_state.hypothesis_sweep_confounder_narrations[sweep_cache_key] = sweep_conf_narration
                                        st.rerun()

                # Interaction check — a different agentic follow-up than the
                # confounder cross-check above: does a significant group
                # difference (one-way ANOVA) actually depend on a third
                # categorical column, i.e. does the group effect only show up
                # for some segments? eta-squared has no sign to flip, so this
                # is a genuine two-way ANOVA interaction test, not a
                # derived-correlation check.
                sweep_interaction_scan = st.session_state.hypothesis_sweep_interaction_check
                if sweep_interaction_scan:
                    n_interactions = len(sweep_interaction_scan)
                    st.markdown(
                        f"**🧩 Interaction check** — {n_interactions} group effect"
                        f"{'s' if n_interactions != 1 else ''} that "
                        f"{'depends' if n_interactions == 1 else 'depend'} on a third column"
                    )
                    st.caption(
                        "A significant group difference doesn't always mean it holds the same way "
                        "for everyone — these effects change size (or disappear) depending on a "
                        "second categorical factor."
                    )
                    for finding in sweep_interaction_scan:
                        label = (
                            f"🔀 **{finding['numeric_col']}** varies by **{finding['cat_col']}** "
                            f"differently across **{finding['other_col']}**"
                        )
                        with st.expander(label, expanded=False):
                            st.caption(
                                f"Interaction p (FDR-adjusted) = {finding['interaction_p_adj']:.4g}"
                            )
                            means_df = pd.DataFrame(finding["group_means"]).T
                            means_df.index.name = finding["other_col"]
                            st.dataframe(means_df.round(3), use_container_width=True)

                # Categorical interaction check — the chi-square analog of the
                # panel above: does the *strength of association* between two
                # categorical columns itself depend on a third categorical
                # column? Tested via a log-linear (Poisson GLM) three-way
                # interaction term, since there's no numeric outcome here for
                # a two-way ANOVA to apply to.
                sweep_cat_interaction_scan = st.session_state.hypothesis_sweep_categorical_interaction_check
                if sweep_cat_interaction_scan:
                    n_cat_interactions = len(sweep_cat_interaction_scan)
                    st.markdown(
                        f"**🔗 Association interaction check** — {n_cat_interactions} categorical "
                        f"association{'s' if n_cat_interactions != 1 else ''} that "
                        f"{'varies' if n_cat_interactions == 1 else 'vary'} across a third column"
                    )
                    st.caption(
                        "A significant chi-square association doesn't always mean it holds the "
                        "same way everywhere — these associations get stronger or weaker "
                        "depending on a third categorical factor."
                    )
                    for finding in sweep_cat_interaction_scan:
                        label = (
                            f"🔗 **{finding['cat_a']}** ↔ **{finding['cat_b']}** association "
                            f"varies across **{finding['other_col']}**"
                        )
                        with st.expander(label, expanded=False):
                            st.caption(
                                f"Interaction p (FDR-adjusted) = {finding['interaction_p_adj']:.4g}"
                            )
                            cv_df = pd.DataFrame(
                                [
                                    {"level": level, "Cramer's V": round(v, 3)}
                                    for level, v in finding["cramers_v_by_level"].items()
                                ]
                            ).sort_values("Cramer's V", ascending=False)
                            cv_df.columns = [finding["other_col"], "Cramer's V"]
                            st.dataframe(cv_df, use_container_width=True, hide_index=True)

                # AI narration — cached per fingerprint of this exact sweep result,
                # same pattern as anomaly narration: only a genuinely different
                # sweep result invalidates the cache.
                current_sweep_fp = hypothesis_sweep.fingerprint_sweep(sweep_result)
                if (
                    st.session_state.hypothesis_sweep_narration
                    and st.session_state.hypothesis_sweep_narration_fingerprint == current_sweep_fp
                ):
                    st.info(f"🤖 {st.session_state.hypothesis_sweep_narration}")
                    caption = ui.build_verification_caption(
                        [st.session_state.hypothesis_sweep_narration_verification or {"status": "unverifiable"}]
                    )
                    if caption:
                        st.caption(caption)
                elif st.button(
                    "✨ Explain these findings with AI",
                    key="narrate_hypothesis_sweep_btn",
                    help="Ask Gemini to interpret the significant relationships and suggest a next step",
                ):
                    sweep_model = ai_analyst.get_model()
                    with st.spinner("Gemini is reviewing the sweep results…"):
                        narration, narr_error = hypothesis_sweep.narrate_sweep(sweep_model, sweep_result)
                    if narr_error:
                        st.warning(narr_error)
                    else:
                        st.session_state.hypothesis_sweep_narration = narration
                        st.session_state.hypothesis_sweep_narration_fingerprint = current_sweep_fp
                        # Fact-check the narration against the sweep's own numbers —
                        # same insight_verifier-backed safety net every other
                        # Gemini-written surface in the app already has.
                        st.session_state.hypothesis_sweep_narration_verification = (
                            hypothesis_sweep.verify_narration(narration, sweep_result)
                        )
                        st.rerun()

        st.markdown("#### 🧮 Experiment Design — sample size & power calculator")
        st.caption(
            "Plan an A/B test *before* running it: how many users per variant do you need to "
            "reliably detect a lift this size? Built on the same statsmodels power-analysis "
            "primitives (Cohen's h / Cohen's d) as the post-hoc power check above — no dataset "
            "required, this is a standalone planning tool."
        )
        exp_kind = st.radio(
            "Metric type",
            ["Conversion rate (e.g. signup %, click-through rate)", "Continuous metric (e.g. revenue, time on page)"],
            key="exp_design_kind",
            horizontal=True,
        )
        exp_c1, exp_c2, exp_c3 = st.columns(3)
        exp_alpha = exp_c1.selectbox("Significance level (α)", [0.01, 0.05, 0.10], index=1, key="exp_design_alpha")
        exp_power = exp_c2.selectbox("Desired power", [0.80, 0.90, 0.95], index=0, key="exp_design_power")
        exp_ratio = exp_c3.number_input(
            "Group B : Group A ratio", min_value=0.1, max_value=10.0, value=1.0, step=0.1, key="exp_design_ratio",
            help="1.0 = equal split between control and variant.",
        )

        if exp_kind.startswith("Conversion"):
            pc1, pc2 = st.columns(2)
            exp_baseline = pc1.number_input(
                "Baseline conversion rate (%)", min_value=0.1, max_value=99.9, value=20.0, step=0.5,
                key="exp_design_baseline",
            ) / 100.0
            exp_mde = pc2.number_input(
                "Minimum detectable lift (absolute pp)", min_value=0.1, max_value=99.0, value=5.0, step=0.5,
                key="exp_design_mde",
            ) / 100.0
            if st.button("Calculate sample size", key="exp_design_calc_proportions_btn"):
                exp_result = experiment_design.sample_size_two_proportions(
                    exp_baseline, exp_mde, alpha=exp_alpha, power=exp_power, ratio=exp_ratio,
                )
                if exp_result.get("error"):
                    st.warning(exp_result["error"])
                else:
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Group A (n)", f"{exp_result['n_group_a']:,}")
                    m2.metric("Group B (n)", f"{exp_result['n_group_b']:,}")
                    m3.metric("Total", f"{exp_result['total_n']:,}")
                    st.markdown(experiment_design.interpret_sample_size_proportions(exp_result))
        else:
            mc1, mc2 = st.columns(2)
            exp_mean_diff = mc1.number_input(
                "Minimum detectable mean difference", value=5.0, step=0.5, key="exp_design_mean_diff",
            )
            exp_std_dev = mc2.number_input(
                "Estimated standard deviation", min_value=0.0001, value=10.0, step=0.5, key="exp_design_std_dev",
            )
            if st.button("Calculate sample size", key="exp_design_calc_means_btn"):
                exp_result = experiment_design.sample_size_two_means(
                    exp_mean_diff, exp_std_dev, alpha=exp_alpha, power=exp_power, ratio=exp_ratio,
                )
                if exp_result.get("error"):
                    st.warning(exp_result["error"])
                else:
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Group A (n)", f"{exp_result['n_group_a']:,}")
                    m2.metric("Group B (n)", f"{exp_result['n_group_b']:,}")
                    m3.metric("Total", f"{exp_result['total_n']:,}")
                    st.caption(f"Cohen's d = {exp_result['cohens_d']:.2f}")
                    st.markdown(experiment_design.interpret_sample_size_means(exp_result))

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

        st.divider()
        st.markdown("#### Time Series Decomposition (STL)")
        st.caption(
            "Splits the series into trend, seasonal, and residual components — useful for "
            "understanding *why* a series moves the way it does before (or instead of) forecasting it."
        )
        if st.button("Run Decomposition", key="stl_decompose_btn", use_container_width=True):
            decomp_series, decomp_freq, decomp_prep_error = forecasting.prepare_series(df, forecast_dt_col, forecast_num_col)
            if decomp_prep_error:
                st.session_state.stl_decomp_result = None
                st.session_state.stl_decomp_error = decomp_prep_error
            else:
                ok, reason = forecasting.can_decompose(decomp_series, decomp_freq)
                if not ok:
                    st.session_state.stl_decomp_result = None
                    st.session_state.stl_decomp_error = reason
                else:
                    with st.spinner(ui.get_loading_message()):
                        decomp_outcome = forecasting.decompose_series(decomp_series, decomp_freq)
                    if decomp_outcome.get("error"):
                        st.session_state.stl_decomp_result = None
                        st.session_state.stl_decomp_error = decomp_outcome["error"]
                    else:
                        st.session_state.stl_decomp_result = decomp_outcome
                        st.session_state.stl_decomp_error = None

        if st.session_state.stl_decomp_error:
            st.error(st.session_state.stl_decomp_error)
        elif st.session_state.stl_decomp_result is None:
            ui.render_empty_state(
                "📈", "No decomposition yet", 'Click "Run Decomposition" to break the series into trend/seasonal/residual.'
            )
        else:
            decomp_result = st.session_state.stl_decomp_result
            st.markdown(forecasting.decomposition_verdict(decomp_result))
            decomp_fig = forecasting.build_decomposition_chart(decomp_result, f"{forecast_num_col} decomposition")
            st.plotly_chart(decomp_fig, use_container_width=True)

        st.divider()
        st.markdown("#### Structural Breaks (Changepoint Detection)")
        st.caption(
            "Finds points where the series' *level* permanently shifted — not a single-point anomaly, "
            "a lasting change (a policy, a system change, an external event). Uses penalized binary "
            "segmentation so it won't manufacture breaks out of ordinary noise."
        )
        if st.button("Detect Structural Breaks", key="changepoint_btn", use_container_width=True):
            cp_series, cp_freq, cp_prep_error = forecasting.prepare_series(df, forecast_dt_col, forecast_num_col)
            if cp_prep_error:
                st.session_state.changepoint_result = None
                st.session_state.changepoint_error = cp_prep_error
            else:
                with st.spinner(ui.get_loading_message()):
                    cp_outcome = forecasting.detect_changepoints(cp_series)
                if cp_outcome.get("error"):
                    st.session_state.changepoint_result = None
                    st.session_state.changepoint_error = cp_outcome["error"]
                else:
                    st.session_state.changepoint_result = cp_outcome
                    st.session_state.changepoint_error = None

        if st.session_state.changepoint_error:
            st.error(st.session_state.changepoint_error)
        elif st.session_state.changepoint_result is None:
            ui.render_empty_state(
                "🪢", "No break detection yet", 'Click "Detect Structural Breaks" to scan the series for level shifts.'
            )
        else:
            cp_result = st.session_state.changepoint_result
            st.markdown(forecasting.changepoint_verdict(cp_result))
            cp_chart_series, _, cp_chart_error = forecasting.prepare_series(df, forecast_dt_col, forecast_num_col)
            if cp_chart_error:
                st.error(cp_chart_error)
            else:
                cp_fig = forecasting.build_changepoint_chart(cp_chart_series, cp_result, f"{forecast_num_col} structural breaks")
                st.plotly_chart(cp_fig, use_container_width=True)

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

        st.divider()
        st.markdown("#### 🧭 Feature Selection Engine")
        st.caption(
            "Cross-checks Mutual Information, an L1-regularized linear model, and Recursive "
            "Feature Elimination (Random Forest) against each other — the same self-verifying-"
            "ensemble pattern used for anomaly detection, applied here to picking features. A "
            "feature's consensus score is how many of the 3 methods agree it matters."
        )
        if len(mllab_selected_features) < mllab.FEATURE_SELECTION_MIN_FEATURES:
            st.info(f"Pick at least {mllab.FEATURE_SELECTION_MIN_FEATURES} feature columns above to run selection.")
        elif st.button("Run Feature Selection", key="run_feature_selection_btn"):
            with st.spinner(ui.get_loading_message()):
                st.session_state.mllab_feature_selection_result = mllab.run_feature_selection(
                    df, mllab_selected_features, mllab_target_col, mllab_task_type
                )

        fs_result = st.session_state.mllab_feature_selection_result
        if fs_result is None:
            ui.render_empty_state(
                "🧭", "No selection run yet",
                'Click "Run Feature Selection" to rank the chosen feature columns.',
            )
        elif fs_result.get("error"):
            st.error(fs_result["error"])
        else:
            st.caption(
                f"{fs_result['n_features']} preprocessed feature(s) ranked "
                f"(categorical columns are one-hot expanded). Top {fs_result['top_k']} recommended below."
            )
            st.success(f"**Recommended features:** {', '.join(fs_result['recommended_features'])}")

            display_ranking = fs_result["ranking"].copy()
            display_ranking.index.name = "Feature"
            display_ranking = display_ranking.rename(
                columns={
                    "mutual_info": "Mutual Info",
                    "l1_coef_abs": "|L1 coef|",
                    "rfe_selected": "RFE selected",
                    "consensus_votes": "Consensus (/3)",
                    "consensus_rank": "Avg. rank",
                }
            )[["Mutual Info", "|L1 coef|", "RFE selected", "Consensus (/3)", "Avg. rank"]].round(4)
            st.dataframe(display_ranking, use_container_width=True)

            st.plotly_chart(mllab.build_feature_selection_chart(fs_result["ranking"]), use_container_width=True)

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

            # K-fold cross-validation — how stable is the single split's
            # score above across different train/test partitions? A single
            # 80/20 split is one draw from a distribution; this reports that
            # distribution's spread directly. Computed automatically inside
            # run_baseline_models(), no extra click.
            cv_results = baseline_result.get("cv_results")
            if cv_results and "error" not in cv_results:
                with st.expander(
                    f"📊 {cv_results['n_splits']}-fold cross-validation — how stable is that score?",
                    expanded=False,
                ):
                    st.caption(
                        "The metrics above come from one 80/20 split. This re-splits the data "
                        f"{cv_results['n_splits']} different ways and reports the mean ± standard "
                        "deviation per metric across folds — a wide spread means the single-split "
                        "number above shouldn't be trusted too literally."
                    )
                    cv_cols = st.columns(2)
                    for cv_col, (model_name, metrics) in zip(cv_cols, cv_results["results"].items()):
                        with cv_col:
                            st.markdown(f"**{model_name}**")
                            for metric_name, stat in metrics.items():
                                st.metric(metric_name.upper(), f"{stat['mean']:.3f} ± {stat['std']:.3f}")
            elif cv_results and "error" in cv_results:
                st.caption(f"Cross-validation skipped: {cv_results['error']}")

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

            if baseline_result["task_type"] == "regression":
                st.divider()
                st.markdown("#### Regression Diagnostics")
                st.caption(
                    "Fits its own OLS model (statsmodels, not the Random Forest above) on the same "
                    "features/target so the inferential statistics diagnostics need — standard errors, "
                    "residuals, VIF — are available. Categorical and zero-variance columns are excluded "
                    "automatically."
                )
                if st.button("Run Regression Diagnostics", key="regression_diag_btn", use_container_width=True):
                    with st.spinner("Fitting OLS and running the diagnostic battery…"):
                        diag_fit = regression_diagnostics.fit_ols(df, mllab_selected_features, mllab_target_col)
                        if "error" in diag_fit:
                            st.session_state.regression_diag_result = None
                            st.session_state.regression_diag_error = diag_fit["error"]
                        else:
                            st.session_state.regression_diag_result = diag_fit
                            st.session_state.regression_diag_error = None

                if st.session_state.regression_diag_error:
                    st.error(st.session_state.regression_diag_error)
                elif st.session_state.regression_diag_result is not None:
                    diag_fit = st.session_state.regression_diag_result

                    if diag_fit.get("dropped_categorical"):
                        st.caption(f"Excluded categorical column(s) (encode first for these to count): {', '.join(diag_fit['dropped_categorical'])}")
                    if diag_fit.get("dropped_zero_variance"):
                        st.caption(f"Excluded zero-variance column(s): {', '.join(diag_fit['dropped_zero_variance'])}")

                    fit_summary = regression_diagnostics.summarize_fit(diag_fit)
                    diag_metric_cols = st.columns(4)
                    diag_metric_cols[0].metric("R²", f"{fit_summary['r_squared']:.3f}")
                    diag_metric_cols[1].metric("Adj. R²", f"{fit_summary['adj_r_squared']:.3f}")
                    diag_metric_cols[2].metric("F-stat p-value", f"{fit_summary['f_pvalue']:.4g}")
                    diag_metric_cols[3].metric("N observations", fit_summary["n_obs"])

                    with st.expander("Coefficient Table", expanded=False):
                        st.dataframe(regression_diagnostics.coefficient_table(diag_fit), use_container_width=True)

                    diagnostics_run = regression_diagnostics.run_diagnostics(diag_fit)
                    vif_table = regression_diagnostics.compute_vif(diag_fit)

                    st.markdown("**Diagnostic Verdict**")
                    for verdict_line in regression_diagnostics.diagnostics_verdict(diagnostics_run, vif_table):
                        st.markdown(f"- {verdict_line}")

                    diag_plot_col1, diag_plot_col2 = st.columns(2)
                    with diag_plot_col1:
                        st.plotly_chart(regression_diagnostics.plot_residuals_vs_fitted(diagnostics_run), use_container_width=True)
                    with diag_plot_col2:
                        st.plotly_chart(regression_diagnostics.plot_qq(diagnostics_run), use_container_width=True)

                    diag_plot_col3, diag_plot_col4 = st.columns(2)
                    with diag_plot_col3:
                        st.plotly_chart(regression_diagnostics.plot_scale_location(diagnostics_run), use_container_width=True)
                    with diag_plot_col4:
                        vif_fig = regression_diagnostics.plot_vif_chart(vif_table)
                        if vif_fig is not None:
                            st.plotly_chart(vif_fig, use_container_width=True)
                        else:
                            ui.render_empty_state("📊", "VIF needs 2+ features", "Multicollinearity can't be assessed with a single feature.")

ui.render_footer()
