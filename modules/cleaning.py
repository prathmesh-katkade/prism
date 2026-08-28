"""
Cleaning — pure functions that take a DataFrame and return a *new* DataFrame.
Nothing here mutates in place, so app.py can always keep the original
DataFrame around for before/after comparisons.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd


def handle_nulls(df: pd.DataFrame, column: str, strategy: str, custom_value: Optional[str] = None) -> pd.DataFrame:
    """Apply one null-handling strategy to a single column.

    strategy: one of "drop_rows", "fill_mean", "fill_median", "fill_mode", "fill_custom"
    """
    new_df = df.copy()

    if strategy == "drop_rows":
        new_df = new_df.dropna(subset=[column])
    elif strategy == "fill_mean":
        if not pd.api.types.is_numeric_dtype(new_df[column]):
            raise ValueError(f"Column '{column}' is not numeric — cannot fill with mean.")
        new_df[column] = new_df[column].fillna(new_df[column].mean())
    elif strategy == "fill_median":
        if not pd.api.types.is_numeric_dtype(new_df[column]):
            raise ValueError(f"Column '{column}' is not numeric — cannot fill with median.")
        new_df[column] = new_df[column].fillna(new_df[column].median())
    elif strategy == "fill_mode":
        mode_values = new_df[column].mode()
        if not mode_values.empty:
            new_df[column] = new_df[column].fillna(mode_values.iloc[0])
    elif strategy == "fill_custom":
        # Try to cast the custom value to the column's own dtype so a numeric
        # column doesn't silently become an object column full of strings.
        cast_value = custom_value
        if pd.api.types.is_numeric_dtype(new_df[column]):
            try:
                cast_value = float(custom_value)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"'{custom_value}' is not a valid number for numeric column '{column}'."
                ) from error
        new_df[column] = new_df[column].fillna(cast_value)
    else:
        raise ValueError(f"Unknown null-handling strategy: {strategy}")

    return new_df


def remove_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Drop exact duplicate rows. Returns the deduplicated frame and the count removed."""
    before = len(df)
    new_df = df.drop_duplicates().reset_index(drop=True)
    return new_df, before - len(new_df)


def drop_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Drop one or more columns entirely — mainly useful for all-null columns that can't be filled."""
    return df.drop(columns=columns, errors="ignore")


def convert_dtype(df: pd.DataFrame, column: str, target_type: str) -> tuple[pd.DataFrame, Optional[str]]:
    """Convert a column's dtype. target_type: 'numeric' | 'datetime' | 'text' | 'category'.

    Returns (new_df, error_message). On failure, new_df is the *original* df,
    unchanged, so a bad conversion never corrupts app state.
    """
    new_df = df.copy()
    try:
        if target_type == "numeric":
            converted = pd.to_numeric(new_df[column], errors="coerce")
        elif target_type == "datetime":
            converted = pd.to_datetime(new_df[column], errors="coerce", format="mixed")
        elif target_type == "text":
            converted = new_df[column].astype(str)
        elif target_type == "category":
            converted = new_df[column].astype("category")
        else:
            return df, f"Unknown target type: {target_type}"

        # If every value came out null, the conversion almost certainly doesn't
        # apply to this column (e.g. converting free text to numeric) — revert
        # rather than silently wiping the column.
        newly_null = converted.isna().sum() - new_df[column].isna().sum()
        if len(new_df) > 0 and newly_null == len(new_df):
            return df, f"Converting '{column}' to {target_type} produced all nulls — reverted."

        new_df[column] = converted
        return new_df, None
    except Exception as e:
        return df, f"Could not convert '{column}' to {target_type}: {e}"


# --------------------------------------------------------------------------
# Code generation — every function below turns one cleaning action into the
# equivalent runnable pandas line(s), so the sidebar's "Export as Python
# Script" button can reproduce the whole session as a standalone .py file.
# Each mirrors the behavior of its corresponding action function above.
# --------------------------------------------------------------------------


def nulls_code(column: str, strategy: str, custom_value: Optional[str] = None) -> str:
    """The pandas line equivalent to handle_nulls()."""
    if strategy == "drop_rows":
        return f"df = df.dropna(subset=[{column!r}])"
    if strategy == "fill_mean":
        return f"df[{column!r}] = df[{column!r}].fillna(df[{column!r}].mean())"
    if strategy == "fill_median":
        return f"df[{column!r}] = df[{column!r}].fillna(df[{column!r}].median())"
    if strategy == "fill_mode":
        return f"df[{column!r}] = df[{column!r}].fillna(df[{column!r}].mode().iloc[0])"
    if strategy == "fill_custom":
        return f"df[{column!r}] = df[{column!r}].fillna({custom_value!r})"
    return f"# Unknown strategy '{strategy}' for column {column!r}"


def duplicates_code() -> str:
    """The pandas line equivalent to remove_duplicates()."""
    return "df = df.drop_duplicates().reset_index(drop=True)"


def drop_columns_code(columns: list[str]) -> str:
    """The pandas line equivalent to drop_columns()."""
    return f"df = df.drop(columns={columns!r})"


def dtype_code(column: str, target_type: str) -> str:
    """The pandas line equivalent to convert_dtype()."""
    if target_type == "numeric":
        return f"df[{column!r}] = pd.to_numeric(df[{column!r}], errors='coerce')"
    if target_type == "datetime":
        return f"df[{column!r}] = pd.to_datetime(df[{column!r}], errors='coerce', format='mixed')"
    if target_type == "text":
        return f"df[{column!r}] = df[{column!r}].astype(str)"
    if target_type == "category":
        return f"df[{column!r}] = df[{column!r}].astype('category')"
    return f"# Unknown target type '{target_type}' for column {column!r}"


def datetime_features_code(column: str) -> str:
    """The pandas lines equivalent to datetime_intel.extract_datetime_features()."""
    var = f"_{column}_dt"
    return (
        f"{var} = pd.to_datetime(df[{column!r}], errors='coerce')\n"
        f"df[{column + '_year'!r}] = {var}.dt.year\n"
        f"df[{column + '_month'!r}] = {var}.dt.month\n"
        f"df[{column + '_day'!r}] = {var}.dt.day\n"
        f"df[{column + '_weekday'!r}] = {var}.dt.day_name()\n"
        f"df[{column + '_quarter'!r}] = {var}.dt.quarter"
    )


_TYPE_COERCION_HELPER = '''def _prism_parse_numeric(value):
    """Parse a formatted-number string (currency symbols, commas, %, K/M/B suffixes) to float."""
    import pandas as pd
    if pd.isna(value):
        return float("nan")
    text = str(value).strip()
    if not text:
        return float("nan")
    negative = text.startswith("-")
    text = text.lstrip("-").strip()
    for sym in "₹$€£¥":
        text = text.replace(sym, "")
    is_percent = "%" in text
    text = text.replace("%", "").replace(",", "").strip()
    multiplier = 1
    if text and text[-1].upper() in {"K": 1000, "M": 1000000, "B": 1000000000}:
        multiplier = {"K": 1000, "M": 1000000, "B": 1000000000}[text[-1].upper()]
        text = text[:-1].strip()
    if not text:
        return float("nan")
    try:
        result = float(text) * multiplier
    except ValueError:
        return float("nan")
    if is_percent:
        result = result / 100
    return -result if negative else result
'''


def type_coercion_code(column: str) -> str:
    """The pandas line equivalent to type_coercion.convert_column(). Assumes
    _prism_parse_numeric() is defined earlier in the script (see export_script)."""
    return f"df[{column!r}] = df[{column!r}].apply(_prism_parse_numeric)"


def anomaly_exclude_code(row_count: int) -> str:
    """A commented placeholder — flagged row indices are specific to this
    session's data, so they aren't meaningfully reproducible against a fresh
    load of the same file. Documents what happened without asserting fake
    portability.
    """
    return (
        f"# Excluded {row_count} row(s) flagged as anomalies by IsolationForest in this session.\n"
        f"# Indices are session-specific; re-run anomaly detection on your own data to reproduce."
    )


def join_code(second_filename: str, left_on: str, right_on: str, how: str) -> str:
    """The pandas lines equivalent to join_engine.join_dataframes()."""
    reader = "read_excel" if second_filename.lower().endswith((".xlsx", ".xls")) else "read_csv"
    return (
        f"df2 = pd.{reader}({second_filename!r})\n"
        f"df = df.merge(df2, how={how!r}, left_on={left_on!r}, right_on={right_on!r}, suffixes=('', '_2'))"
    )


def export_script(cleaning_log: list[dict], original_filename: Optional[str] = None) -> str:
    """Assemble every logged cleaning step into a single runnable .py file.

    cleaning_log is a list of {"description": str, "code": str} dicts, in
    the order the steps were applied.
    """
    needs_helper = any("_prism_parse_numeric" in step.get("code", "") for step in cleaning_log)

    lines = [
        '"""Auto-generated by Prism — reproduces the cleaning steps applied in this session."""',
        "import pandas as pd",
        "import numpy as np",
        "",
    ]
    if needs_helper:
        lines.append(_TYPE_COERCION_HELPER)
        lines.append("")

    source = original_filename or "your_file.csv"
    reader = "read_excel" if source.lower().endswith((".xlsx", ".xls")) else "read_csv"
    lines.append(f"df = pd.{reader}({source!r})  # replace with your actual file path")
    lines.append("")

    for i, step in enumerate(cleaning_log, start=1):
        lines.append(f"# Step {i}: {step['description']}")
        lines.append(step["code"])
        lines.append("")

    lines.append('df.to_csv("cleaned_output.csv", index=False)')
    return "\n".join(lines)


def compare_before_after(before: pd.DataFrame, after: pd.DataFrame) -> dict:
    """Summarize what changed between two DataFrame snapshots, for the Clean tab's diff view."""
    common_cols = [c for c in before.columns if c in after.columns]
    dtype_changes = {
        c: (str(before[c].dtype), str(after[c].dtype))
        for c in common_cols
        if str(before[c].dtype) != str(after[c].dtype)
    }
    return {
        "rows_before": len(before),
        "rows_after": len(after),
        "cols_before": before.shape[1],
        "cols_after": after.shape[1],
        "nulls_before": int(before.isna().sum().sum()),
        "nulls_after": int(after.isna().sum().sum()),
        "dtype_changes": dtype_changes,
    }
