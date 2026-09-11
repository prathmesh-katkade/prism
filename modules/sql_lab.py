"""
SQL Lab — run raw SQL against the active dataset via DuckDB. The DataFrame is
registered as a table named "data"; DuckDB queries it in-memory with no disk
I/O and no separate database server.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from typing import Optional, Union

import pandas as pd

try:
    import duckdb
except ImportError:  # the app should still load even if the package isn't installed yet
    duckdb = None

DEFAULT_TIMEOUT_SECONDS = 10.0  # mirrors ai_analyst._EXEC_TIMEOUT_SECONDS
DEFAULT_ROW_CAP = 5000
FORMAT_VERSION = 1


def run_query(df: pd.DataFrame, sql: str) -> tuple[Optional[pd.DataFrame], Optional[str], float]:
    """Execute a raw SQL query against `df` (registered as table `data`) via DuckDB.

    Returns (result_df, error, elapsed_seconds). On failure, result_df is None
    and error holds DuckDB's message; elapsed_seconds is measured either way.
    """
    start = time.perf_counter()
    if not sql or not sql.strip():
        return None, "Query is empty.", time.perf_counter() - start

    con = None
    try:
        con = duckdb.connect(database=":memory:")
        con.register("data", df)
        result = con.execute(sql).df()
        return result, None, time.perf_counter() - start
    except Exception as e:
        return None, str(e), time.perf_counter() - start
    finally:
        if con is not None:
            con.close()


def _safe_alias(name: str) -> str:
    """Turn an arbitrary column name into a valid, readable SQL alias fragment."""
    return re.sub(r"\W+", "_", name).strip("_") or "value"


def build_example_queries(df: pd.DataFrame, column_types: dict[str, str]) -> dict[str, str]:
    """Build 4 ready-to-run example queries using the dataset's real column
    names, falling back sensibly when a needed column type isn't present
    (e.g. no categorical column for a GROUP BY).
    """
    cols = df.columns.tolist()
    numeric_cols = [c for c, t in column_types.items() if t == "numeric"]
    categorical_cols = [c for c, t in column_types.items() if t == "categorical"]

    examples: dict[str, str] = {"SELECT *": 'SELECT *\nFROM data\nLIMIT 10;'}

    if categorical_cols and numeric_cols:
        cat, num = categorical_cols[0], numeric_cols[0]
        examples["GROUP BY aggregation"] = (
            f'SELECT "{cat}", COUNT(*) AS row_count, AVG("{num}") AS avg_{_safe_alias(num)}\n'
            f'FROM data\nGROUP BY "{cat}"\nORDER BY row_count DESC;'
        )
    elif categorical_cols:
        cat = categorical_cols[0]
        examples["GROUP BY aggregation"] = (
            f'SELECT "{cat}", COUNT(*) AS row_count\nFROM data\nGROUP BY "{cat}"\nORDER BY row_count DESC;'
        )
    elif numeric_cols:
        num = numeric_cols[0]
        examples["GROUP BY aggregation"] = (
            f'SELECT ROUND("{num}") AS {_safe_alias(num)}_rounded, COUNT(*) AS row_count\n'
            f'FROM data\nGROUP BY 1\nORDER BY row_count DESC;'
        )
    else:
        col0 = cols[0]
        examples["GROUP BY aggregation"] = (
            f'SELECT "{col0}", COUNT(*) AS row_count\nFROM data\nGROUP BY "{col0}"\nORDER BY row_count DESC;'
        )

    if numeric_cols:
        num = numeric_cols[0]
        median_val = df[num].median()
        threshold = 0.0 if pd.isna(median_val) else round(float(median_val), 2)
        examples["WHERE filter"] = f'SELECT *\nFROM data\nWHERE "{num}" > {threshold}\nLIMIT 20;'
        examples["ORDER BY + LIMIT"] = f'SELECT *\nFROM data\nORDER BY "{num}" DESC\nLIMIT 10;'
    else:
        col0 = cols[0]
        examples["WHERE filter"] = f'SELECT *\nFROM data\nWHERE "{col0}" IS NOT NULL\nLIMIT 20;'
        examples["ORDER BY + LIMIT"] = f'SELECT *\nFROM data\nORDER BY "{col0}"\nLIMIT 10;'

    return examples


def run_query_multi(
    tables: dict[str, pd.DataFrame],
    sql: str,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    row_cap: int = DEFAULT_ROW_CAP,
    attach_clause: Optional[str] = None,
    attach_extension: Optional[str] = None,
) -> dict:
    """Execute `sql` against every {name: df} pair, each registered as a
    DuckDB table on a fresh in-memory connection — the multi-table version
    of run_query(), used once more than one table is registered (the active
    dataset plus anything added via "Registered Tables").

    attach_clause/attach_extension optionally bring a live external database
    (MySQL/Postgres/SQLite, via modules.db_connect) into the SAME connection
    as the local tables, so one query can JOIN a live table against a local
    one. Deliberately just raw strings, not a modules.db_connect import —
    sql_lab.py stays a pure-logic, zero-Streamlit-import module (matching
    join_engine.py's own stated convention); the caller (app.py, via
    db_connect.build_attach_clause()) builds these strings, this function
    only executes them. A fresh ATTACH is built on THIS call's own
    connection rather than reusing any cached connection elsewhere, so the
    existing per-call timeout/interrupt isolation below is unaffected by
    live-DB queries — see modules/db_connect.py's docstring for why the
    cached connection there is never reused for actual query execution.

    Runs on a daemon thread bounded by timeout_seconds; con.interrupt() is
    called if it overruns — DuckDB's own cancel hook, safe to call from
    another thread while a query executes (this is its documented purpose,
    unlike ai_analyst.execute_code_safely's pandas-exec case, which has no
    equivalent and can only abandon the runaway thread).

    Returns {"result_df", "error", "elapsed_seconds", "truncated",
    "row_count_full"}. The result is truncated to row_cap rows *after*
    fetching, not by rewriting the SQL to inject a LIMIT — splicing
    arbitrary user SQL (CTEs, UNIONs, multiple statements) is unreliable;
    truncating the already-materialized result is correct for every query
    shape.
    """
    start = time.perf_counter()
    empty = {"result_df": None, "error": None, "elapsed_seconds": 0.0, "truncated": False, "row_count_full": 0}

    if not sql or not sql.strip():
        return {**empty, "error": "Query is empty."}
    if duckdb is None:
        return {**empty, "error": "The `duckdb` package isn't installed."}

    con = duckdb.connect(database=":memory:")
    if attach_clause:
        try:
            if attach_extension:
                con.execute(f"INSTALL {attach_extension}")
                con.execute(f"LOAD {attach_extension}")
        except Exception:
            pass  # already loaded, or autoload will handle it on ATTACH anyway
        try:
            con.execute(attach_clause)
        except Exception as e:
            con.close()
            return {**empty, "elapsed_seconds": time.perf_counter() - start, "error": f"Couldn't connect to the live database: {e}"}
    for name, table_df in tables.items():
        con.register(name, table_df)

    outcome: dict = {}

    def _run():
        try:
            outcome["result_df"] = con.execute(sql).df()
        except Exception as e:
            outcome["error"] = str(e)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)
    elapsed = time.perf_counter() - start

    if thread.is_alive():
        try:
            con.interrupt()
        except Exception:
            pass
        return {
            **empty,
            "elapsed_seconds": elapsed,
            "error": (
                f"Query took longer than {timeout_seconds:.0f}s and was interrupted — "
                f"try narrowing it down (fewer rows/columns, an added filter) or simplifying any joins."
            ),
        }

    try:
        con.close()
    except Exception:
        pass

    if "error" in outcome:
        return {**empty, "elapsed_seconds": elapsed, "error": outcome["error"]}

    result_df = outcome.get("result_df")
    row_count_full = len(result_df) if result_df is not None else 0
    truncated = row_count_full > row_cap
    if truncated:
        result_df = result_df.head(row_cap)
    return {
        "result_df": result_df, "error": None, "elapsed_seconds": elapsed,
        "truncated": truncated, "row_count_full": row_count_full,
    }


def explain_query(
    tables: dict[str, pd.DataFrame], sql: str,
    attach_clause: Optional[str] = None, attach_extension: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Run EXPLAIN ANALYZE against the same registered tables (falls back to
    a plain EXPLAIN if ANALYZE errors — e.g. a non-SELECT statement). This
    is opt-in/manual with no timeout wrapper: ANALYZE runs the query once
    already, so there's no point double-bounding it. Returns (plan_text, error).

    attach_clause/attach_extension — see run_query_multi's docstring; same
    raw-string contract, same reasoning for not importing modules.db_connect here.
    """
    if duckdb is None:
        return None, "The `duckdb` package isn't installed."
    if not sql or not sql.strip():
        return None, "Query is empty."

    con = None
    try:
        con = duckdb.connect(database=":memory:")
        if attach_clause:
            if attach_extension:
                try:
                    con.execute(f"INSTALL {attach_extension}")
                    con.execute(f"LOAD {attach_extension}")
                except Exception:
                    pass
            con.execute(attach_clause)
        for name, table_df in tables.items():
            con.register(name, table_df)
        try:
            rows = con.execute(f"EXPLAIN ANALYZE {sql}").fetchall()
        except Exception:
            rows = con.execute(f"EXPLAIN {sql}").fetchall()
        plan_text = "\n".join(str(row[-1]) for row in rows)
        return plan_text, None
    except Exception as e:
        return None, str(e)
    finally:
        if con is not None:
            con.close()


def lint_query(sql: str) -> list[dict]:
    """Pure text/regex heuristics — advisory only, never blocks a run.
    Returns [{"severity": "warn"|"info", "message": str}, ...].
    """
    findings: list[dict] = []
    if not sql or not sql.strip():
        return findings

    stripped = sql.strip()
    upper = stripped.upper()

    if re.search(r"SELECT\s+\*", upper):
        findings.append({
            "severity": "info",
            "message": "SELECT * returns every column — naming columns explicitly is easier to read and cheaper to run.",
        })
    if upper.startswith("SELECT") and "LIMIT" not in upper:
        findings.append({
            "severity": "info",
            "message": "No LIMIT clause — results are still capped automatically, but LIMIT makes exploration faster.",
        })
    if re.search(r"=\s*NULL\b", upper):
        findings.append({"severity": "warn", "message": "'= NULL' never matches anything in SQL — use IS NULL instead."})
    if re.search(r"\b(UPDATE|DELETE)\b", upper) and "WHERE" not in upper:
        findings.append({"severity": "warn", "message": "UPDATE/DELETE with no WHERE clause affects every row in the table."})
    if stripped.count("'") % 2 != 0:
        findings.append({"severity": "warn", "message": "Unbalanced single quotes — likely an unterminated string literal."})
    if stripped.count("(") != stripped.count(")"):
        findings.append({"severity": "warn", "message": "Unbalanced parentheses."})
    semi_positions = [m.start() for m in re.finditer(";", stripped)]
    if semi_positions and semi_positions[-1] < len(stripped.rstrip()) - 1:
        findings.append({
            "severity": "warn",
            "message": "Content follows a ';' — DuckDB only runs the first statement, the rest is ignored.",
        })

    return findings


def suggest_assertions(df: pd.DataFrame, column_types: dict[str, str], quality: Optional[dict] = None) -> list[dict]:
    """Auto-suggest a starter set of data-assertion specs from the schema
    and (optionally) a modules.data_engine.get_data_quality_report() dict:
    a row-count floor at the dataset's current size, a uniqueness check for
    every id-like column, and a no-null check for every column currently at
    0% missing. Purely advisory — the caller edits/removes before running.
    """
    from modules.profiling import (
        get_id_like_columns,  # local import keeps sql_lab light for callers that only need run_query
    )

    suggestions: list[dict] = [{
        "name": "row_count_min", "type": "row_count_min", "table": "data",
        "column": None, "value": len(df), "sql_expr": None,
    }]

    for col in get_id_like_columns(df):
        suggestions.append({
            "name": f"{col}: unique", "type": "unique", "table": "data",
            "column": col, "value": None, "sql_expr": None,
        })

    missing_by_column = (quality or {}).get("missing_by_column", {})
    for col in column_types:
        if missing_by_column.get(col) == 0:
            suggestions.append({
                "name": f"{col}: no nulls", "type": "no_null", "table": "data",
                "column": col, "value": None, "sql_expr": None,
            })

    return suggestions


def run_assertions(tables: dict[str, pd.DataFrame], assertions: list[dict]) -> list[dict]:
    """Execute each assertion spec independently via DuckDB — one failing or
    erroring assertion never aborts the rest (same per-step isolation as
    recipes.apply_recipe's applied/skipped-with-detail log). Assertion spec
    shape: {"name", "type": "row_count_min"|"row_count_exact"|"no_null"|
    "unique"|"custom_sql", "table", "column", "value", "sql_expr"}.
    Returns [{"name", "type", "status": "pass"|"fail"|"error", "detail"}, ...].
    """
    if duckdb is None:
        return [
            {"name": a.get("name", "?"), "type": a.get("type", "?"), "status": "error",
             "detail": "The `duckdb` package isn't installed."}
            for a in assertions
        ]

    con = duckdb.connect(database=":memory:")
    try:
        for name, table_df in tables.items():
            con.register(name, table_df)

        results = []
        for a in assertions:
            name = a.get("name", "(unnamed)")
            a_type = a.get("type", "")
            table = a.get("table") or "data"
            column = a.get("column")
            value = a.get("value")
            sql_expr = a.get("sql_expr")
            try:
                if a_type == "row_count_min":
                    actual = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                    status = "pass" if actual >= (value or 0) else "fail"
                    detail = f"{actual:,} rows (minimum {int(value or 0):,})"
                elif a_type == "row_count_exact":
                    actual = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                    status = "pass" if actual == value else "fail"
                    detail = f"{actual:,} rows (expected exactly {int(value or 0):,})"
                elif a_type == "no_null":
                    actual = con.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" IS NULL').fetchone()[0]
                    status = "pass" if actual == 0 else "fail"
                    detail = "no nulls found" if actual == 0 else f"{actual:,} null value(s) found"
                elif a_type == "unique":
                    dupes = con.execute(
                        f'SELECT COUNT(*) FROM (SELECT "{column}" FROM "{table}" GROUP BY "{column}" HAVING COUNT(*) > 1)'
                    ).fetchone()[0]
                    status = "pass" if dupes == 0 else "fail"
                    detail = "all values unique" if dupes == 0 else f"{dupes:,} duplicate value(s) found"
                elif a_type == "custom_sql":
                    if not sql_expr or not sql_expr.strip():
                        status, detail = "error", "No SQL provided for this custom check."
                    else:
                        row = con.execute(sql_expr).fetchone()
                        passed = bool(row and row[0])
                        status = "pass" if passed else "fail"
                        detail = "condition met" if passed else "condition not met"
                else:
                    status, detail = "error", f"Unknown assertion type '{a_type}'."
            except Exception as e:
                status, detail = "error", str(e)
            results.append({"name": name, "type": a_type, "status": status, "detail": detail})
        return results
    finally:
        con.close()


def _build_envelope(kind: str, name: str, payload: dict) -> str:
    """Shared JSON envelope for every save_X()/load_X() pair below — same
    named-artifact shape as modules.recipes.save_recipe (format_version +
    name + created_at), factored out once instead of tripled across saved
    queries, test suites, and query history.
    """
    envelope = {
        "format_version": FORMAT_VERSION,
        "kind": kind,
        "name": name or f"unnamed_{kind}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    return json.dumps(envelope, indent=2)


def _parse_envelope(raw: Union[bytes, str], expected_kind: str) -> tuple[dict, Optional[str]]:
    try:
        envelope = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return {}, f"Not a valid file: {e}"
    if not isinstance(envelope, dict) or envelope.get("kind") != expected_kind or "payload" not in envelope:
        return {}, f"Not a valid Prism SQL Lab '{expected_kind}' file."
    return envelope, None


def save_saved_query(name: str, sql: str) -> str:
    return _build_envelope("saved_query", name, {"sql": sql})


def load_saved_query(raw: Union[bytes, str]) -> tuple[dict, Optional[str]]:
    envelope, error = _parse_envelope(raw, "saved_query")
    if error:
        return {}, error
    return {"name": envelope["name"], "sql": envelope["payload"].get("sql", "")}, None


def save_test_suite(name: str, assertions: list[dict]) -> str:
    return _build_envelope("test_suite", name, {"assertions": assertions})


def load_test_suite(raw: Union[bytes, str]) -> tuple[dict, Optional[str]]:
    envelope, error = _parse_envelope(raw, "test_suite")
    if error:
        return {}, error
    return {"name": envelope["name"], "assertions": envelope["payload"].get("assertions", [])}, None


def save_query_history(history: list[dict]) -> str:
    return _build_envelope("query_history", "history", {"history": history})


def load_query_history(raw: Union[bytes, str]) -> tuple[list[dict], Optional[str]]:
    envelope, error = _parse_envelope(raw, "query_history")
    if error:
        return [], error
    return envelope["payload"].get("history", []), None
