"""
SQL Lab — run raw SQL either against the active dataset via DuckDB (in-memory,
no server), or against a live external database the user connects to
(currently MySQL). The DuckDB path registers the DataFrame as a table named
"data"; the external-database path opens a real network connection built
from credentials the user enters in the UI for that session only.

Security notes for the MySQL path (see build_mysql_engine / run_mysql_query):
  - Credentials are never hardcoded, written to disk, or committed — they
    live only in Streamlit's in-memory session_state for the current browser
    session, and are dropped on "Disconnect" or when the server process ends.
  - The password is passed to SQLAlchemy as a URL field, never string-
    concatenated into SQL or a DSN, so it can't leak via query text or
    accidental logging; error messages are scrubbed before display.
  - Queries are read-only by default — anything that looks like a write
    (INSERT/UPDATE/DELETE/DROP/...) is refused client-side unless the user
    explicitly opts in with "Allow write queries" for that run.
  - Connections use a short connect_timeout and results are capped at
    MYSQL_MAX_ROWS so a runaway query can't hang the app or exhaust memory.
  - This module has no bearing on server-side privileges: for real safety,
    the MySQL user you connect with should itself be a read-only account
    scoped to just the schema you need (see README).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Optional

import pandas as pd

try:
    import duckdb
except ImportError:  # the app should still load even if the package isn't installed yet
    duckdb = None

try:
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.engine import URL, Engine
except ImportError:  # MySQL support is optional — local SQL Lab still works without it
    create_engine = None
    inspect = None
    text = None
    URL = None
    Engine = None


# --------------------------------------------------------------------------
# Local (DuckDB) SQL Lab — unchanged behavior
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# External MySQL connections — opt-in, per-session, read-only by default
# --------------------------------------------------------------------------

MYSQL_DEFAULT_PORT = 3306
MYSQL_CONNECT_TIMEOUT_SECONDS = 10
MYSQL_MAX_ROWS = 10_000  # hard cap on rows pulled into the app, regardless of the query

# Anything that isn't a plain read gets refused unless the user opts in.
_WRITE_KEYWORDS = re.compile(
    r"^\s*(insert|update|delete|drop|alter|create|truncate|replace|grant|revoke|"
    r"lock|unlock|call|load\s+data|rename|set\s+global)\b",
    re.IGNORECASE,
)

# Only real column/table/DB identifiers — used to validate user-entered
# connection fields before they're handed to the driver.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")


@dataclass
class MySQLConnectionInfo:
    """Holds what's needed to build a SQLAlchemy engine. Deliberately plain
    (not a Pydantic/session-persisted model) — this is created fresh from
    UI form fields each time the user clicks "Connect" and is discarded
    (along with the engine) on "Disconnect". Never serialized to disk.
    """
    host: str
    port: int
    database: str
    user: str
    password: str
    label: str = ""


def mysql_available() -> bool:
    """Whether the optional sqlalchemy/pymysql dependencies are installed."""
    return create_engine is not None


def _clean_db_error(message: str) -> str:
    """Strip anything that looks like a credential out of a driver error
    message before it's ever shown in the UI."""
    message = re.sub(r"(password[=:]\s*)\S+", r"\1********", message, flags=re.IGNORECASE)
    message = re.sub(r"(://[^:]+:)[^@]+(@)", r"\1********\2", message)  # user:pass@host in a DSN
    return message


def validate_connection_fields(info: MySQLConnectionInfo) -> Optional[str]:
    """Basic sanity/allow-list checks on connection fields before they touch
    the network — catches obvious mistakes and stray injection attempts in
    the database name early, with a clear message instead of a raw driver
    error.
    """
    if not info.host or not info.host.strip():
        return "Host is required."
    if not info.database or not info.database.strip():
        return "Database name is required."
    if not info.user or not info.user.strip():
        return "Username is required."
    if not _IDENTIFIER_RE.match(info.database.strip()):
        return "Database name contains characters that aren't valid for a MySQL identifier."
    if info.port and not (1 <= info.port <= 65535):
        return "Port must be between 1 and 65535."
    return None


def build_mysql_engine(info: MySQLConnectionInfo) -> tuple[Optional["Engine"], Optional[str]]:
    """Build and immediately test a SQLAlchemy engine for a MySQL connection.

    On success returns (engine, None); on failure returns (None, message).
    The connection is tested with SELECT 1 right away so a bad host/user/
    password fails fast with a clear message rather than lazily on the
    first query the user runs.
    """
    if create_engine is None:
        return None, (
            "MySQL support needs the `sqlalchemy`, `pymysql`, and `cryptography` packages — "
            "run `pip install -r requirements.txt` and restart the app."
        )

    field_error = validate_connection_fields(info)
    if field_error:
        return None, field_error

    try:
        url = URL.create(
            "mysql+pymysql",
            username=info.user,
            password=info.password,
            host=info.host.strip(),
            port=info.port or MYSQL_DEFAULT_PORT,
            database=info.database.strip(),
        )
        engine = create_engine(
            url,
            connect_args={"connect_timeout": MYSQL_CONNECT_TIMEOUT_SECONDS},
            pool_pre_ping=True,
            pool_recycle=280,
        )
        with engine.connect() as con:
            con.execute(text("SELECT 1"))
    except Exception as e:
        return None, _clean_db_error(str(e))

    return engine, None


def close_mysql_engine(engine: Optional["Engine"]) -> None:
    """Dispose of the connection pool. Called on Disconnect and whenever a
    new connection replaces an old one, so stale sockets don't pile up."""
    if engine is not None:
        try:
            engine.dispose()
        except Exception:
            pass


def list_mysql_tables(engine: "Engine") -> tuple[list[str], Optional[str]]:
    """Return the table names visible to the connected user."""
    try:
        insp = inspect(engine)
        return sorted(insp.get_table_names()), None
    except Exception as e:
        return [], _clean_db_error(str(e))


def is_write_query(sql: str) -> bool:
    """True if any statement in `sql` looks like a write (INSERT/UPDATE/
    DELETE/DROP/ALTER/...) rather than a plain read. Used to block writes by
    default; this is a client-side convenience check, not a substitute for
    the database user itself having read-only privileges.
    """
    for stmt in sql.split(";"):
        if _WRITE_KEYWORDS.match(stmt):
            return True
    return False


def run_mysql_query(
    engine: "Engine",
    sql: str,
    allow_writes: bool = False,
    max_rows: int = MYSQL_MAX_ROWS,
) -> tuple[Optional[pd.DataFrame], Optional[str], float, bool]:
    """Execute `sql` against a live MySQL connection.

    Returns (result_df, error, elapsed_seconds, truncated). Read-only by
    default: unless `allow_writes` is True, anything that looks like a write
    is refused before it reaches the database. Row-returning results are
    capped at `max_rows`; `truncated` is True if more rows were available.
    """
    start = time.perf_counter()
    if not sql or not sql.strip():
        return None, "Query is empty.", time.perf_counter() - start, False

    if not allow_writes and is_write_query(sql):
        return (
            None,
            "This looks like a write query (INSERT/UPDATE/DELETE/DROP/...). "
            "Turn on \"Allow write queries\" above if you really mean to run it.",
            time.perf_counter() - start,
            False,
        )

    try:
        with engine.connect() as con:
            result = con.execute(text(sql))
            if result.returns_rows:
                rows: list[Any] = result.fetchmany(max_rows + 1)
                columns = list(result.keys())
                truncated = len(rows) > max_rows
                if truncated:
                    rows = rows[:max_rows]
                df = pd.DataFrame(rows, columns=columns)
                return df, None, time.perf_counter() - start, truncated
            else:
                con.commit()
                affected = pd.DataFrame({"rows_affected": [result.rowcount]})
                return affected, None, time.perf_counter() - start, False
    except Exception as e:
        return None, _clean_db_error(str(e)), time.perf_counter() - start, False
