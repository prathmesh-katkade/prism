"""
Auto Cleaner — Prism v5's flagship feature: scan the active dataset with
every existing Hell Mode detector, turn the findings into a concrete action
plan, auto-apply everything that's lossless/reversible, and surface the
judgment calls as approve/reject cards instead of guessing on your behalf.

Deliberately NOT "send findings to Gemini and execute whatever comes back":
the SAFE/REVIEW risk tier is a fixed property of the *action type*, decided
here in Python, not inferred per-instance by the model. Gemini's only job
is the one-line narration ("Scan complete. N safe fixes applied...") — the
plan itself, and every action's execution, is fully deterministic. That
means Auto Cleaner works correctly with zero Gemini API key configured
(same fallback philosophy as the rest of Prism), and a bad LLM response can
never talk its way into a destructive action being marked safe.

    scan()          -> raw findings from the Hell Mode detectors
    build_plan()     -> deterministic list of {action, column, detail, risk, reason, params}
    narrate_plan()   -> Atlas's one-line summary (Gemini if available, templated otherwise)
    apply_action()   -> execute exactly one action, safe or review
    execute_safe_actions() -> auto-apply every SAFE action in the plan
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from modules import cleaning, hellmode
from modules.ai_analyst import call_gemini

# Fixed, not model-decided — see module docstring.
SAFE_ACTIONS = {
    "trim_whitespace", "convert_disguised_nulls", "parse_indian_number",
    "standardize_dates", "remove_exact_duplicates",
}
REVIEW_ACTIONS = {
    "resolve_ambiguous_dates", "impute_missing", "fuzzy_merge_category", "remove_outliers",
    "normalize_units", "convert_zero_sentinel", "split_multi_value",
}

ACTION_LABELS = {
    "trim_whitespace": "Trim whitespace",
    "convert_disguised_nulls": "Convert disguised nulls",
    "parse_indian_number": "Parse Indian-formatted numbers",
    "standardize_dates": "Standardize date format",
    "remove_exact_duplicates": "Remove exact duplicates",
    "resolve_ambiguous_dates": "Resolve ambiguous dates",
    "impute_missing": "Fill missing values",
    "fuzzy_merge_category": "Merge near-duplicate categories",
    "remove_outliers": "Remove statistical outliers",
    "normalize_units": "Normalize mixed units",
    "convert_zero_sentinel": "Convert placeholder zeros to missing",
    "split_multi_value": "Surface multi-value cells (count + primary)",
}


# ==========================================================================
# Step 1 — SCAN: run every Hell Mode detector, collect raw findings.
# ==========================================================================
def scan(df: pd.DataFrame, column_types: dict[str, str], quality_report: dict) -> dict:
    disguised_nulls = hellmode.scan_disguised_nulls(df, column_types)
    indian_numbers = hellmode.detect_indian_number_candidates(df, column_types)

    date_like_cols = []
    for col, ctype in column_types.items():
        if ctype not in ("text", "categorical"):
            continue
        formats = hellmode.detect_date_formats(df[col])
        total = sum(formats.values())
        recognized = sum(v for k, v in formats.items() if k != "unrecognized")
        if total and recognized / total >= 0.6:
            date_like_cols.append(col)

    mixed_date_formats = {col: hellmode.detect_date_formats(df[col]) for col in date_like_cols}
    ambiguous_dates = {
        col: rows for col in date_like_cols if (rows := hellmode.find_ambiguous_dates(df[col]))
    }

    fuzzy_groups = {}
    for col, ctype in column_types.items():
        if ctype != "categorical":
            continue
        groups = hellmode.suggest_fuzzy_groups(df[col])
        if groups:
            fuzzy_groups[col] = groups

    whitespace_cols = []
    for col, ctype in column_types.items():
        if ctype not in ("text", "categorical"):
            continue
        non_null = df[col].dropna().astype(str)
        if not non_null.empty and (non_null != non_null.str.strip()).any():
            whitespace_cols.append(col)

    return {
        "disguised_nulls": disguised_nulls,
        "indian_numbers": indian_numbers,
        "mixed_date_formats": mixed_date_formats,
        "ambiguous_dates": ambiguous_dates,
        "fuzzy_groups": fuzzy_groups,
        "mixed_units": hellmode.detect_mixed_units(df, column_types),
        "zero_sentinels": hellmode.detect_zero_sentinel_candidates(df, column_types),
        "multi_value_columns": hellmode.detect_multi_value_columns(df, column_types),
        "exact_duplicates": int(df.duplicated().sum()),
        "whitespace_cols": whitespace_cols,
        "missing_by_column": quality_report["missing_by_column"],
        "outliers": quality_report["outliers"],
    }


# ==========================================================================
# Step 2 — PLAN: deterministic action list from the scan, then Gemini for
# the one-line narration only (never for deciding risk or execution).
# ==========================================================================
def build_plan(df: pd.DataFrame, column_types: dict[str, str], scan_results: dict) -> list[dict]:
    plan: list[dict] = []

    for col in scan_results["whitespace_cols"]:
        plan.append({
            "action": "trim_whitespace", "column": col,
            "detail": "leading/trailing whitespace found", "risk": "SAFE",
            "reason": f"Whitespace-padded values in '{col}' can silently break group-bys and joins.",
            "params": {},
        })

    for col, counts in scan_results["disguised_nulls"].items():
        total = sum(counts.values())
        plan.append({
            "action": "convert_disguised_nulls", "column": col,
            "detail": f"{total} disguised null marker(s)", "risk": "SAFE",
            "reason": f"'{col}' has {total} value(s) like 'NA' or '-' pandas doesn't treat as missing by default.",
            "params": {"synonyms": hellmode.DEFAULT_NULL_SYNONYMS},
        })

    for cand in scan_results["indian_numbers"]:
        plan.append({
            "action": "parse_indian_number", "column": cand["column"],
            "detail": f"{cand['match_pct']}% parse as Indian-formatted numbers", "risk": "SAFE",
            "reason": f"'{cand['column']}' is text (₹/lakh/crore-formatted) but is really numeric.",
            "params": {},
        })

    for col in scan_results["mixed_date_formats"]:
        if col in scan_results["ambiguous_dates"]:
            examples = scan_results["ambiguous_dates"][col][:3]
            sample = examples[0]["value"] if examples else "?"
            plan.append({
                "action": "resolve_ambiguous_dates", "column": col,
                "detail": f"{len(scan_results['ambiguous_dates'][col])} ambiguous value(s), e.g. {sample!r}",
                "risk": "REVIEW",
                "reason": f"'{col}' has dates like {sample!r} where day-first vs month-first genuinely disagree.",
                "params": {"day_first": True, "examples": examples},
            })
        else:
            plan.append({
                "action": "standardize_dates", "column": col,
                "detail": "mixed but unambiguous date formats", "risk": "SAFE",
                "reason": f"'{col}' mixes formats (e.g. DD/MM/YYYY and YYYY-MM-DD) that all parse to one clear date.",
                "params": {"day_first": True},
            })

    if scan_results["exact_duplicates"] > 0:
        plan.append({
            "action": "remove_exact_duplicates", "column": None,
            "detail": f"{scan_results['exact_duplicates']} exact duplicate row(s)", "risk": "SAFE",
            "reason": f"{scan_results['exact_duplicates']} row(s) are byte-for-byte duplicates — safe to drop.",
            "params": {},
        })

    for col, groups in scan_results["fuzzy_groups"].items():
        merge_map = {m["value"]: g["canonical"] for g in groups for m in g["members"] if m["value"] != g["canonical"]}
        if not merge_map:
            continue
        example = groups[0]
        plan.append({
            "action": "fuzzy_merge_category", "column": col,
            "detail": f"{len(groups)} near-duplicate group(s), e.g. {example['members'][-1]['value']!r} ~ {example['canonical']!r}",
            "risk": "REVIEW",
            "reason": f"'{col}' has category spellings that look like the same value — merging needs a human check.",
            "params": {"merge_map": merge_map, "groups": groups},
        })

    for finding in scan_results["mixed_units"]:
        col, family = finding["column"], finding["family"]
        target_unit = hellmode.UNIT_FAMILIES[family]["base_unit"]
        units_summary = ", ".join(f"{u} ({n})" for u, n in finding["units_found"].items())
        plan.append({
            "action": "normalize_units", "column": col,
            "detail": f"mixed {family} units — {units_summary}", "risk": "REVIEW",
            "reason": f"'{col}' mixes {family} units ({units_summary}) — converting to one unit needs your OK.",
            "params": {"family": family, "target_unit": target_unit},
        })

    for finding in scan_results["zero_sentinels"]:
        col = finding["column"]
        plan.append({
            "action": "convert_zero_sentinel", "column": col,
            "detail": f"{finding['zero_count']} zero(s) ({finding['zero_pct']}%) look like disguised nulls",
            "risk": "REVIEW",
            "reason": (
                f"'{col}' has {finding['zero_pct']}% exact-zero values but its name and range suggest "
                f"zero isn't physically possible here — likely a placeholder for 'not recorded' "
                f"(the well-known Glucose/BMI=0 pattern), not a real reading."
            ),
            "params": {},
        })

    for finding in scan_results["multi_value_columns"]:
        col, delim = finding["column"], finding["delimiter"]
        delim_label = {",": "comma", "|": "pipe", ";": "semicolon"}.get(delim, delim)
        plan.append({
            "action": "split_multi_value", "column": col,
            "detail": f"~{finding['avg_values']} {delim_label}-separated value(s) per cell", "risk": "REVIEW",
            "reason": (
                f"'{col}' looks like it packs multiple values per cell ({finding['match_pct']}% contain a "
                f"{delim_label}, averaging {finding['avg_values']} values) — treating each combination as one "
                f"category hides the real tags. Adding a count + primary-value column surfaces the structure "
                f"without guessing how you want it fully split."
            ),
            "params": {"delimiter": delim},
        })

    # A column that's 90%+ missing has so few non-null values that
    # detect_column_types's cardinality heuristic can misclassify it as
    # "text" rather than "categorical" (n_unique/len(non_null) skews high
    # when len(non_null) is tiny) — exactly the columns meaningful-NA is
    # meant to catch. So this check runs independent of the numeric/
    # categorical gate below, rather than being folded into that loop.
    meaningful_na_cols = set(hellmode.detect_meaningful_na_candidates(column_types, scan_results["missing_by_column"]))
    for col in meaningful_na_cols:
        pct = scan_results["missing_by_column"][col]
        plan.append({
            "action": "impute_missing", "column": col,
            "detail": f"{pct}% missing — likely means 'not applicable', not unknown", "risk": "REVIEW",
            "reason": (
                f"'{col}' is {pct}% missing — that's concentrated enough that it more likely means "
                f"the attribute doesn't apply to most rows (e.g. a 'no pool'-style gap) than random "
                f"data loss. Filling with the column's mode would manufacture a fake majority value; "
                f"marking it as its own '{hellmode.MEANINGFUL_NA_PLACEHOLDER}' category preserves that signal."
            ),
            "params": {"strategy": "constant", "custom_value": hellmode.MEANINGFUL_NA_PLACEHOLDER},
        })

    for col, pct in scan_results["missing_by_column"].items():
        if col in meaningful_na_cols:
            continue
        if pct > 0 and column_types.get(col) in ("numeric", "categorical"):
            strategy = "median" if column_types.get(col) == "numeric" else "mode"
            plan.append({
                "action": "impute_missing", "column": col,
                "detail": f"{pct}% missing", "risk": "REVIEW",
                "reason": f"'{col}' is {pct}% missing — filling changes real values, so it needs your strategy choice.",
                "params": {"strategy": strategy},
            })

    for col, info in scan_results["outliers"].items():
        if info["count"] > 0:
            plan.append({
                "action": "remove_outliers", "column": col,
                "detail": f"{info['count']} outlier row(s) ({info['pct']}%)", "risk": "REVIEW",
                "reason": f"'{col}' has {info['count']} statistical outlier(s) — could be real extreme values, not errors.",
                "params": {},
            })

    return plan


_NARRATION_PROMPT = (
    "Auto Cleaner just scanned a dataset and built this action plan:\n{plan_summary}\n\n"
    "There are {safe_count} safe fix(es) and {review_count} that need review.\n\n"
    "You are Atlas, Prism's data-cleaning assistant, speaking directly to the user. Write ONE "
    "plain-English sentence (max 25 words) narrating that result, for example: "
    '"Scan complete. 3 safe fixes applied. 2 need your judgment."\n'
    "Return ONLY that sentence, written in plain English with the real numbers substituted in — "
    "never Python code, never an f-string, never a code block, never a variable name."
)


def narrate_plan(model, plan: list[dict], health_score: Optional[int] = None) -> str:
    """Atlas's one-line summary of the plan. Falls back to a templated line
    (same wording style) if no model is configured or the call fails —
    Auto Cleaner never depends on Gemini being available to work.
    """
    safe_count = sum(1 for a in plan if a["risk"] == "SAFE")
    review_count = sum(1 for a in plan if a["risk"] == "REVIEW")
    if not plan:
        score_part = f" — health score {health_score}" if health_score is not None else ""
        return f"Scan complete. Nothing to fix{score_part}."
    default = (
        f"Scan complete. {safe_count} safe fix(es) applied. "
        + (f"{review_count} need your judgment." if review_count else "Nothing else needs review.")
    )
    if model is None:
        return default

    plan_summary = "\n".join(f"- [{a['risk']}] {a['action']} on {a['column']}: {a['detail']}" for a in plan)
    prompt = _NARRATION_PROMPT.format(plan_summary=plan_summary, safe_count=safe_count, review_count=review_count)
    text, error = call_gemini(model, prompt)
    if error or not text or len(text) > 300:
        return default
    cleaned = text.strip().strip('"')
    # Reject anything that looks like code, not prose — a model can ignore
    # instructions, but Auto Cleaner's narration must never leak an f-string
    # or code fence into what's supposed to be a spoken/displayed sentence.
    code_markers = ("```", "= f", "=f", "\n", "def ", "result =", "python")
    if any(marker in cleaned for marker in code_markers):
        return default
    return cleaned


# ==========================================================================
# Step 3 — EXECUTE: one executor per action type, dispatched by name.
# ==========================================================================
def _exec_trim_whitespace(df, column_types, action):
    col = action["column"]
    new_df = df.copy()
    new_df[col] = new_df[col].apply(lambda v: v.strip() if isinstance(v, str) else v)
    code = f"df[{col!r}] = df[{col!r}].apply(lambda v: v.strip() if isinstance(v, str) else v)"
    return new_df, column_types, f"Auto Clean: trimmed whitespace in '{col}'", code


def _exec_convert_disguised_nulls(df, column_types, action):
    col, synonyms = action["column"], action["params"]["synonyms"]
    new_df = hellmode.convert_disguised_nulls(df, [col], synonyms)
    code = hellmode.disguised_nulls_code([col], synonyms)
    return new_df, column_types, f"Auto Clean: converted disguised nulls in '{col}'", code


def _exec_parse_indian_number(df, column_types, action):
    col = action["column"]
    new_df, new_col = hellmode.convert_indian_column(df, col, add_unit_suffix=False)
    code = hellmode.indian_number_code(col, new_col)
    new_types = dict(column_types)
    new_types[new_col] = "numeric"
    return new_df, new_types, f"Auto Clean: parsed Indian-formatted numbers in '{col}'", code


def _exec_standardize_dates(df, column_types, action):
    col = action["column"]
    day_first = action["params"].get("day_first", True)
    parsed, failed = hellmode.resolve_dates(df[col], day_first=day_first)
    new_df = df.copy()
    new_df[col] = parsed
    code = hellmode.date_resolver_code(col, day_first)
    new_types = dict(column_types)
    new_types[col] = "datetime"
    note = f" ({len(failed)} value(s) could not be parsed)" if failed else ""
    return new_df, new_types, f"Auto Clean: standardized dates in '{col}'{note}", code


def _exec_remove_exact_duplicates(df, column_types, action):
    new_df, removed = cleaning.remove_duplicates(df)
    return new_df, column_types, f"Auto Clean: removed {removed} exact duplicate row(s)", cleaning.duplicates_code()


def _exec_fuzzy_merge_category(df, column_types, action):
    col, merge_map = action["column"], action["params"]["merge_map"]
    new_df = hellmode.apply_fuzzy_merge(df, col, merge_map)
    code = hellmode.fuzzy_merge_code(col, merge_map)
    n = len(merge_map)
    return new_df, column_types, f"Auto Clean: merged {n} near-duplicate categor{'y' if n == 1 else 'ies'} in '{col}'", code


def _exec_impute_missing(df, column_types, action):
    col, strategy = action["column"], action["params"].get("strategy", "median")
    custom_value = action["params"].get("custom_value")
    new_df, error = hellmode.impute_column(df, col, strategy, custom_value=custom_value)
    if error:
        return df, column_types, f"Auto Clean: could not impute '{col}' ({error})", f"# {error}"
    label = f"marked as {custom_value!r}" if strategy == "constant" else strategy
    code = hellmode.impute_code(col, strategy, custom_value=custom_value)
    return new_df, column_types, f"Auto Clean: filled missing values in '{col}' ({label})", code


def _exec_remove_outliers(df, column_types, action):
    col = action["column"]
    series = df[col]
    q1, q3 = series.quantile(0.25), series.quantile(0.75)
    iqr = q3 - q1
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    mask = series.between(lower, upper) | series.isna()
    new_df = df[mask].reset_index(drop=True)
    removed = len(df) - len(new_df)
    code = (
        f"_q1, _q3 = df[{col!r}].quantile(0.25), df[{col!r}].quantile(0.75)\n"
        f"_iqr = _q3 - _q1\n"
        f"df = df[df[{col!r}].between(_q1 - 1.5*_iqr, _q3 + 1.5*_iqr) | df[{col!r}].isna()].reset_index(drop=True)"
    )
    return new_df, column_types, f"Auto Clean: removed {removed} outlier row(s) in '{col}'", code


def _exec_normalize_units(df, column_types, action):
    col = action["column"]
    family, target_unit = action["params"]["family"], action["params"]["target_unit"]
    new_series, description = hellmode.normalize_units(df[col], family, target_unit)
    new_df = df.copy()
    new_df[col] = new_series
    code = hellmode.unit_normalize_code(col, family, target_unit)
    new_types = dict(column_types)
    new_types[col] = "numeric"
    return new_df, new_types, f"Auto Clean: normalized '{col}' to {target_unit} ({description})", code


def _exec_convert_zero_sentinel(df, column_types, action):
    col = action["column"]
    before = int((df[col] == 0).sum())
    new_df = hellmode.convert_zero_sentinel_to_null(df, col)
    code = hellmode.zero_sentinel_code(col)
    return new_df, column_types, f"Auto Clean: converted {before} placeholder zero(s) to missing in '{col}'", code


def _exec_split_multi_value(df, column_types, action):
    col, delimiter = action["column"], action["params"]["delimiter"]
    new_df = hellmode.split_multi_value_column(df, col, delimiter)
    code = hellmode.multi_value_split_code(col, delimiter)
    new_types = dict(column_types)
    new_types[f"{col}_count"] = "numeric"
    new_types[f"{col}_primary"] = "categorical"
    desc = f"Auto Clean: added '{col}_count' and '{col}_primary' from multi-value column '{col}'"
    return new_df, new_types, desc, code


_EXECUTORS = {
    "trim_whitespace": _exec_trim_whitespace,
    "convert_disguised_nulls": _exec_convert_disguised_nulls,
    "parse_indian_number": _exec_parse_indian_number,
    "standardize_dates": _exec_standardize_dates,
    "resolve_ambiguous_dates": _exec_standardize_dates,  # same mechanics; day_first comes from the user's REVIEW choice
    "remove_exact_duplicates": _exec_remove_exact_duplicates,
    "fuzzy_merge_category": _exec_fuzzy_merge_category,
    "impute_missing": _exec_impute_missing,
    "remove_outliers": _exec_remove_outliers,
    "normalize_units": _exec_normalize_units,
    "convert_zero_sentinel": _exec_convert_zero_sentinel,
    "split_multi_value": _exec_split_multi_value,
}


def apply_action(
    df: pd.DataFrame, column_types: dict[str, str], action: dict
) -> tuple[pd.DataFrame, dict[str, str], str, str]:
    """Execute exactly one plan action (SAFE or approved REVIEW). Returns
    (new_df, new_column_types, log_description, export_code).
    """
    executor = _EXECUTORS.get(action["action"])
    if executor is None:
        return df, column_types, f"Unknown action '{action['action']}' — skipped.", f"# Unknown action '{action['action']}'"
    return executor(df, column_types, action)


def execute_safe_actions(
    df: pd.DataFrame, column_types: dict[str, str], plan: list[dict]
) -> tuple[pd.DataFrame, dict[str, str], list[dict], int]:
    """Auto-apply every SAFE action in plan order. Returns (new_df,
    new_column_types, log_entries, applied_count) — log_entries are
    {"description", "code"} dicts, ready to extend the cleaning history.
    """
    new_df, new_types = df, column_types
    log_entries: list[dict] = []
    applied = 0
    for action in plan:
        if action["risk"] != "SAFE":
            continue
        new_df, new_types, description, code = apply_action(new_df, new_types, action)
        log_entries.append({"description": description, "code": code})
        applied += 1
    return new_df, new_types, log_entries, applied


def health_delta_line(before: int, after: int) -> str:
    delta = after - before
    sign = "+" if delta >= 0 else ""
    return f"Data Health: {before} → {after} ({sign}{delta})"
