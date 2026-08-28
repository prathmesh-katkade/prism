"""
DB Connect — bridges SQL Lab to real external databases.

MySQL, PostgreSQL, and SQLite go through DuckDB's own ATTACH extensions,
sharing one SQL namespace with locally `con.register()`-ed pandas tables —
a single query can JOIN a live MySQL table against the uploaded CSV. SQL
Server has no trustworthy DuckDB extension, so it gets a separate
SQLAlchemy + pyodbc path with its own executor; SQL Server tables cannot
be joined against local/other-engine tables in the same statement — a
disclosed limitation, not an oversight.

Connections are cached per-session via st.cache_resource (see
get_duckdb_attach_connection/get_sqlserver_engine), keyed on the
connection parameters — but the actual query-EXECUTION path
(sql_lab.run_query_multi's `attach` parameter) builds its OWN fresh ATTACH
per call rather than reusing the cached connection, to preserve
run_query_multi's existing per-call timeout/interrupt isolation (see its
docstring). The cached connection here is used only for Connect / Test
Connection / listing tables, never for running a user's query.

Credentials live in st.session_state only, for this session's lifetime —
confirmed safe against modules.session_io's "Save Session" export, which
takes explicit positional args (raw_df/working_df/cleaning_log/chat_history)
rather than dumping session_state generically. Never reuse
sql_lab.save_saved_query()'s JSON-download pattern for anything containing
a password — saved queries stay SQL-text-only, connection-agnostic.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Optional
from urllib.parse import quote_plus

import pandas as pd
import streamlit as st

try:
    import duckdb
except ImportError:  # the app should still load even if the package isn't installed yet
    duckdb = None

try:
    import sqlalchemy
except ImportError:  # SQL Server path only — everything else works without it
    sqlalchemy = None

SUPPORTED_ENGINES = ("mysql", "postgres", "sqlserver", "sqlite")
DUCKDB_ATTACH_ENGINES = ("mysql", "postgres", "sqlite")  # share one DuckDB namespace with local tables
ENGINE_LABELS = {"mysql": "MySQL", "postgres": "PostgreSQL", "sqlserver": "SQL Server", "sqlite": "SQLite"}
ENGINE_DEFAULT_PORTS = {"mysql": 3306, "postgres": 5432, "sqlserver": 1433}
_EXTENSION_FOR_ENGINE = {"mysql": "mysql", "postgres": "postgres", "sqlite": "sqlite"}

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_ROW_CAP = 5000


def _escape_sql_literal(value: str) -> str:
    """Escape single quotes for embedding inside a DuckDB single-quoted SQL
    string literal. Doesn't handle spaces-in-password inside the inner
    libmysqlclient/libpq key=value connection string — a known, documented
    MVP limitation, not silently swallowed."""
    return (value or "").replace("'", "''")


def build_connection_params_key(engine_type: str, params: dict) -> tuple:
    """Stable, hashable tuple of connection params (password included — it's
    part of the connection's identity) — the st.cache_resource key, and the
    UI's own "did the form change" check. sqlite uses a (engine_type, path)
    shape; the network engines use (engine_type, host, port, user, password,
    database). The cached get_*_connection/engine functions below reconstruct
    a params dict from this exact tuple layout — keep both in sync.
    """
    if engine_type == "sqlite":
        return (engine_type, params.get("path", ""))
    return (
        engine_type, params.get("host", ""), params.get("port"),
        params.get("user", ""), params.get("password", ""), params.get("database", ""),
    )


def _params_from_key(engine_type: str, params_key: tuple) -> dict:
    if engine_type == "sqlite":
        return {"path": params_key[1]}
    return {
        "host": params_key[1], "port": params_key[2], "user": params_key[3],
        "password": params_key[4], "database": params_key[5],
    }


def build_attach_clause(engine_type: str, params: dict, alias: str = "live") -> str:
    """DuckDB ATTACH clause for mysql/postgres/sqlite. Raises ValueError for
    sqlserver — that engine has no DuckDB extension, use build_sqlalchemy_url."""
    if engine_type == "mysql":
        # DuckDB's mysql extension parses this as a libmysqlclient-style DSN —
        # its accepted keys are host/user/passwd/db/port/socket, NOT the
        # password=/database= spelling postgres uses below. Confirmed via the
        # engine's own error: 'expected options are host, user, passwd, db,
        # port, socket'. Do not "fix" this back to password=/database=.
        conn_str = (
            f"host={params.get('host', '')} port={params.get('port') or ENGINE_DEFAULT_PORTS['mysql']} "
            f"user={params.get('user', '')} passwd={params.get('password', '')} "
            f"db={params.get('database', '')}"
        )
        return f"ATTACH '{_escape_sql_literal(conn_str)}' AS {alias} (TYPE mysql)"
    if engine_type == "postgres":
        conn_str = (
            f"host={params.get('host', '')} port={params.get('port') or ENGINE_DEFAULT_PORTS['postgres']} "
            f"user={params.get('user', '')} password={params.get('password', '')} "
            f"dbname={params.get('database', '')}"
        )
        return f"ATTACH '{_escape_sql_literal(conn_str)}' AS {alias} (TYPE postgres)"
    if engine_type == "sqlite":
        return f"ATTACH '{_escape_sql_literal(params.get('path', ''))}' AS {alias} (TYPE sqlite)"
    raise ValueError(f"build_attach_clause doesn't support engine_type={engine_type!r} — use build_sqlalchemy_url for sqlserver.")


def build_sqlalchemy_url(params: dict) -> str:
    """mssql+pyodbc:// URL — SQL Server only. Every field is percent-encoded
    so special characters in the password/user don't break URL parsing."""
    driver = quote_plus("ODBC Driver 17 for SQL Server")
    user = quote_plus(params.get("user", ""))
    password = quote_plus(params.get("password", ""))
    host = params.get("host", "")
    port = params.get("port") or ENGINE_DEFAULT_PORTS["sqlserver"]
    database = quote_plus(params.get("database", ""))
    return f"mssql+pyodbc://{user}:{password}@{host}:{port}/{database}?driver={driver}"


def extension_for_engine(engine_type: str) -> Optional[str]:
    """Public accessor for _EXTENSION_FOR_ENGINE — app.py needs this to build
    the attach_extension argument for sql_lab.run_query_multi/explain_query
    without reaching into a private module-level dict directly."""
    return _EXTENSION_FOR_ENGINE.get(engine_type)


def _ensure_extension_loaded(con, engine_type: str) -> None:
    """Defensive INSTALL/LOAD before ATTACH — DuckDB's Python client autoloads
    known extensions by default, but explicitly loading first is harmless
    (no-op if already loaded) and doesn't depend on that default staying on."""
    ext = _EXTENSION_FOR_ENGINE.get(engine_type)
    if not ext:
        return
    try:
        con.execute(f"INSTALL {ext}")
        con.execute(f"LOAD {ext}")
    except Exception:
        pass  # already loaded, or autoload will handle it on ATTACH anyway


def _friendly_db_error(engine_type: str, exc: Exception) -> str:
    """Wrap a raw driver exception with a Render/Streamlit-Cloud hint when it
    looks like a missing-ODBC-driver failure — the single most likely SQL
    Server failure mode on this app's deploy targets (see DEPLOYMENT.md)."""
    msg = str(exc)
    if engine_type == "sqlserver" and ("driver" in msg.lower() or "odbc" in msg.lower()):
        return (
            f"{msg}\n\nThis usually means the ODBC Driver for SQL Server isn't installed on this "
            "deployment. Streamlit Community Cloud has it pre-installed; Render's current deploy "
            "does not (it would need a Docker-based deploy to add it)."
        )
    return msg


def test_connection(engine_type: str, params: dict) -> tuple[bool, Optional[str]]:
    """Opens a throwaway connection and closes it immediately — never touches
    the cached resource, so testing never disturbs an already-connected
    session. Returns (ok, error_message)."""
    if engine_type not in SUPPORTED_ENGINES:
        return False, f"Unknown engine type '{engine_type}'."

    if engine_type == "sqlserver":
        if sqlalchemy is None:
            return False, "The `sqlalchemy`/`pyodbc` packages aren't installed."
        engine = None
        try:
            engine = sqlalchemy.create_engine(build_sqlalchemy_url(params), pool_pre_ping=True)
            with engine.connect() as conn:
                conn.execute(sqlalchemy.text("SELECT 1"))
            return True, None
        except Exception as e:
            return False, _friendly_db_error(engine_type, e)
        finally:
            if engine is not None:
                engine.dispose()

    if duckdb is None:
        return False, "The `duckdb` package isn't installed."
    con = None
    try:
        con = duckdb.connect(database=":memory:")
        _ensure_extension_loaded(con, engine_type)
        con.execute(build_attach_clause(engine_type, params, alias="probe"))
        con.execute("SELECT 1")
        return True, None
    except Exception as e:
        return False, _friendly_db_error(engine_type, e)
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:
                pass


@st.cache_resource(show_spinner="Connecting to database...")
def get_duckdb_attach_connection(engine_type: str, params_key: tuple):
    """Cached per params_key — used ONLY by Connect / Test Connection /
    table-listing, NOT by the query-execution path (sql_lab.run_query_multi
    builds its own fresh ATTACH per call — see this module's docstring)."""
    params = _params_from_key(engine_type, params_key)
    con = duckdb.connect(database=":memory:")
    _ensure_extension_loaded(con, engine_type)
    con.execute(build_attach_clause(engine_type, params, alias="live"))
    return con


@st.cache_resource(show_spinner="Connecting to database...")
def get_sqlserver_engine(params_key: tuple):
    """SQLAlchemy Engine with its own internal pool — thread-safe by design,
    no lock needed (unlike the DuckDB attach path, whose fresh-per-call
    executor sidesteps the concurrency question entirely instead)."""
    if sqlalchemy is None:
        raise RuntimeError("The `sqlalchemy`/`pyodbc` packages aren't installed.")
    params = _params_from_key("sqlserver", params_key)
    return sqlalchemy.create_engine(build_sqlalchemy_url(params), pool_pre_ping=True)


def disconnect(engine_type: str) -> None:
    """Clears the cached resource for this engine family. Calls .clear() on
    the SPECIFIC cached function, never the global st.cache_resource.clear()
    (which would also evict unrelated cached resources elsewhere in the
    app). Fine to clear every entry, not just one params_key — this app
    supports one live connection at a time by design."""
    try:
        if engine_type == "sqlserver":
            get_sqlserver_engine.clear()
        else:
            get_duckdb_attach_connection.clear()
    except Exception:
        pass


def is_destructive_statement(sql: str) -> bool:
    """True if ANY top-level statement in `sql` starts with a destructive
    keyword (DROP/DELETE/TRUNCATE/ALTER/UPDATE). Splits naively on ';' and
    checks EACH resulting statement, not just the first — a live database
    driver may not truncate a multi-statement batch the way DuckDB's local
    path does, so "SELECT 1; DROP TABLE x" must still be caught. INSERT is
    deliberately excluded — additive writes aren't gated, per the plan's
    documented boundary (rarely catastrophic, unlike the other five)."""
    if not sql or not sql.strip():
        return False
    for statement in sql.split(";"):
        if _DESTRUCTIVE_RE.match(statement):
            return True
    return False


_DESTRUCTIVE_RE = re.compile(r"^\s*(?:--[^\n]*\n\s*)*\b(DROP|DELETE|TRUNCATE|ALTER|UPDATE)\b", re.IGNORECASE)


def get_live_table_names(engine_type: str, conn, alias: str = "live") -> list[str]:
    """List tables visible on the live connection. `conn` is whatever
    get_duckdb_attach_connection/get_sqlserver_engine returned. Never raises
    — a listing failure degrades to an empty list, the caller shows that as
    'no tables found' rather than crashing the whole Database Connection panel."""
    try:
        if engine_type == "sqlserver":
            with conn.connect() as c:
                rows = c.execute(sqlalchemy.text(
                    "SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE'"
                )).fetchall()
            return [f"{r[0]}.{r[1]}" for r in rows]
        # SHOW ALL TABLES relies on duckdb_columns(), which doesn't support every
        # attached catalog type (confirmed: raises "Unsupported catalog type" against
        # an attached sqlite database) — information_schema.tables works uniformly
        # across mysql/postgres/sqlite attachments instead.
        #
        # table_schema is also filtered: a MySQL ATTACH exposes every schema on
        # the server (information_schema, mysql, performance_schema, sys, ...)
        # under this one table_catalog, not just the target database — confirmed
        # live (a fresh db with one user table listed ~80 tables without this
        # filter). Harmless no-op for sqlite/postgres, which don't expose those
        # schema names under a normal connection.
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_catalog = ? AND table_schema NOT IN "
            "('information_schema', 'pg_catalog', 'mysql', 'performance_schema', 'sys')",
            [alias],
        ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def get_live_table_sample(
    engine_type: str, conn, table_name: str, n: int = 20, alias: str = "live",
) -> tuple[Optional[pd.DataFrame], Optional[str]]:
    """SELECT the first n rows — used both for a lightweight preview and as
    schema-detection context for Atlas's NL-to-SQL prompt (feeds
    data_engine.detect_column_types on a live-only table with nothing
    materialized locally). Never used for bulk data movement. `table_name`
    is the bare name as returned by get_live_table_names (no alias prefix)
    — this function does the alias-qualification itself, quoting each part
    separately (a single quoted "alias.table" string is a single identifier
    to DuckDB, not two — this bit a first draft of this function)."""
    try:
        if engine_type == "sqlserver":
            with conn.connect() as c:
                result = c.execute(sqlalchemy.text(f"SELECT TOP {n} * FROM {table_name}"))
                return pd.DataFrame(result.fetchall(), columns=list(result.keys())), None
        return conn.execute(f'SELECT * FROM "{alias}"."{table_name}" LIMIT {n}').df(), None
    except Exception as e:
        return None, str(e)


def run_live_query_sqlserver(
    engine, sql: str, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS, row_cap: int = DEFAULT_ROW_CAP,
) -> dict:
    """SQL Server's own executor — same return shape as
    sql_lab.run_query_multi ({"result_df","error","elapsed_seconds",
    "truncated","row_count_full"}) for a drop-in swap at call sites. Runs
    via SQLAlchemy directly, no DuckDB involved — no local-table join
    capability, a disclosed limitation (see this module's docstring).

    Same daemon-thread-with-timeout shape as sql_lab.run_query_multi, but
    SQLAlchemy/pyodbc has no equivalent to DuckDB's con.interrupt() — on
    timeout the thread is abandoned, not killed (same documented limitation
    as ai_analyst.execute_code_safely): this bounds *this request's*
    latency, not the orphaned query's server-side execution.
    """
    start = time.perf_counter()
    empty = {"result_df": None, "error": None, "elapsed_seconds": 0.0, "truncated": False, "row_count_full": 0}
    if not sql or not sql.strip():
        return {**empty, "error": "Query is empty."}
    if sqlalchemy is None:
        return {**empty, "error": "The `sqlalchemy`/`pyodbc` packages aren't installed."}

    outcome: dict = {}

    def _run():
        try:
            with engine.connect() as conn:
                result_proxy = conn.execute(sqlalchemy.text(sql))
                if result_proxy.returns_rows:
                    outcome["result_df"] = pd.DataFrame(result_proxy.fetchall(), columns=list(result_proxy.keys()))
                else:
                    conn.commit()
                    outcome["result_df"] = pd.DataFrame()
        except Exception as e:
            outcome["error"] = str(e)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)
    elapsed = time.perf_counter() - start

    if thread.is_alive():
        return {
            **empty, "elapsed_seconds": elapsed,
            "error": f"Query took longer than {timeout_seconds:.0f}s and was abandoned — the server-side "
                     "query may still be running.",
        }
    if "error" in outcome:
        return {**empty, "elapsed_seconds": elapsed, "error": outcome["error"]}

    result_df = outcome.get("result_df", pd.DataFrame())
    row_count_full = len(result_df)
    truncated = row_count_full > row_cap
    if truncated:
        result_df = result_df.head(row_cap)
    return {
        "result_df": result_df, "error": None, "elapsed_seconds": elapsed,
        "truncated": truncated, "row_count_full": row_count_full,
    }
