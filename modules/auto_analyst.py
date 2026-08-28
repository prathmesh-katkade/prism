"""
Auto Analyst — the agentic "Run Full Analysis" flow. Gemini first drafts an
ordered analysis plan (JSON: quality check -> distributions -> segments ->
correlations -> time trends if a datetime column exists -> conclusions),
then each step's pandas code is generated and run through the same
safe-execution sandbox as the AI Analyst chat tab, and finally Gemini
synthesizes the accumulated results into 5 headline findings.

Reuses modules.ai_analyst's Gemini plumbing (build_data_context, call_gemini,
ask_and_execute, parse_numbered_bullets) instead of duplicating any of it —
this module only adds the plan generation and multi-step orchestration on top.
"""

from __future__ import annotations

import json
import re
from typing import Optional

import pandas as pd

from modules.ai_analyst import (
    ask_and_execute,
    build_data_context,
    call_gemini,
    parse_numbered_bullets,
)

PLAN_SYSTEM_PROMPT = (
    "You are a senior data analyst planning an exploratory analysis of a pandas "
    "DataFrame called `df`. Given the dataframe's schema, a sample, and summary "
    "statistics, produce an ORDERED analysis plan as a JSON array. Each element "
    "must be an object with keys \"title\" (3-6 words) and \"question\" (a specific, "
    "self-contained analysis question that could be answered with pandas code, "
    "written the way a user would type it into a chat box).\n\n"
    "Cover, in this order, whichever are relevant to the data:\n"
    "1) a data quality check (missing values, duplicates, outliers)\n"
    "2) distributions of the key numeric/categorical columns\n"
    "3) interesting segments or groups (group-by comparisons)\n"
    "4) correlations between numeric columns\n"
    "5) time trends, ONLY if a datetime column exists\n"
    "6) a final synthesis step summarizing conclusions\n\n"
    "Return 4 to 6 steps total. Return ONLY the JSON array, no prose, no markdown "
    "code fences."
)

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)

_FINDINGS_PROMPT_TEMPLATE = (
    "You just ran the following exploratory analysis steps on a pandas DataFrame "
    "and got these results:\n\n{step_summaries}\n\n"
    "You are a senior data analyst. Based only on the results above, write exactly "
    "5 concise, business-relevant findings. Each finding MUST reference a concrete "
    "number from the results above — do not write vague statements. Format your "
    "response as exactly 5 lines, each starting with '1. ' through '5. ', with no "
    "other text before or after."
)


def _default_plan(column_types: dict[str, str]) -> list[dict]:
    """Fallback plan used when Gemini is unavailable or its JSON can't be parsed.

    Auto Analyst is a one-click feature — a plan-generation hiccup shouldn't
    block the whole run, so this always returns something runnable.
    """
    values = column_types.values()
    has_datetime = "datetime" in values
    has_categorical = "categorical" in values
    has_numeric = "numeric" in values

    plan = [
        {
            "title": "Data quality check",
            "question": "Summarize missing values, duplicate rows, and outliers in df.",
        }
    ]
    if has_numeric:
        plan.append(
            {
                "title": "Distributions",
                "question": "Describe the distribution (mean, median, std, min, max) of each numeric column in df.",
            }
        )
    if has_categorical:
        plan.append(
            {
                "title": "Segments",
                "question": (
                    "For each categorical column with a manageable number of categories, show the count "
                    "per category, and if a numeric column exists, the average of the main numeric column "
                    "per category."
                ),
            }
        )
    if has_numeric:
        plan.append(
            {
                "title": "Correlations",
                "question": "Compute the correlation matrix between numeric columns in df and identify the strongest pairwise correlation.",
            }
        )
    if has_datetime:
        plan.append(
            {
                "title": "Time trends",
                "question": "Show how the main numeric column trends over time, grouped by the datetime column at a sensible frequency.",
            }
        )
    plan.append(
        {
            "title": "Conclusions",
            "question": "Summarize the overall shape of df: row/column count, key data quality issues, and the single most notable pattern found.",
        }
    )
    return plan


def generate_analysis_plan(model, df: pd.DataFrame, column_types: dict[str, str]) -> list[dict]:
    """Ask Gemini for an ordered analysis plan.

    Always returns a usable plan — falls back to a sensible default built
    from column_types on any error, bad JSON, or empty response, since the
    whole point of this feature is a single button that "just works".
    """
    if model is None:
        return _default_plan(column_types)

    context = build_data_context(df, column_types)
    prompt = f"{PLAN_SYSTEM_PROMPT}\n\nData context:\n{context}"
    text, error = call_gemini(model, prompt)
    if error:
        return _default_plan(column_types)

    match = _JSON_ARRAY_RE.search(text)
    if not match:
        return _default_plan(column_types)

    try:
        raw_plan = json.loads(match.group(0))
    except json.JSONDecodeError:
        return _default_plan(column_types)

    cleaned = [
        {"title": str(step.get("title") or f"Step {i + 1}"), "question": str(step["question"])}
        for i, step in enumerate(raw_plan)
        if isinstance(step, dict) and step.get("question")
    ]
    return cleaned or _default_plan(column_types)


def run_plan_step(model, df: pd.DataFrame, column_types: dict[str, str], step: dict, chat_history: list[dict]) -> dict:
    """Execute one plan step through the existing self-healing chat pipeline.

    Returns the same dict shape as ai_analyst.ask_and_execute (code, result,
    error, ask_error, retried, original_error) plus "title" and "question"
    for display in the progress panel.
    """
    outcome = ask_and_execute(model, df, column_types, step["question"], chat_history)
    outcome["title"] = step["title"]
    outcome["question"] = step["question"]
    return outcome


def _summarize_result(result) -> str:
    """Stringify a step's result compactly enough to fit in a follow-up prompt."""
    if result is None:
        return "(no result)"
    if isinstance(result, (pd.DataFrame, pd.Series)):
        return result.head(10).to_string()
    return str(result)


def synthesize_findings(model, step_outcomes: list[dict]) -> tuple[list[str], Optional[str]]:
    """Ask Gemini to turn the accumulated step results into 5 headline findings.

    Returns (bullets, error). Steps that failed or errored are excluded from
    the summary prompt so a single bad step doesn't sink the whole synthesis.
    """
    if model is None:
        return [], "No Gemini model available."

    summaries = [
        f"- {outcome['title']}: {_summarize_result(outcome.get('result'))}"
        for outcome in step_outcomes
        if not outcome.get("error") and not outcome.get("ask_error")
    ]
    if not summaries:
        return [], "No successful analysis steps to summarize."

    prompt = _FINDINGS_PROMPT_TEMPLATE.format(step_summaries="\n\n".join(summaries))
    text, error = call_gemini(model, prompt)
    if error:
        return [], error
    return parse_numbered_bullets(text), None
