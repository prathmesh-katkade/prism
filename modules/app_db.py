"""
App DB — persistent MySQL-backed storage for exactly three pieces of app
data: saved SQL queries, cleaning recipes, and full session snapshots.
Scoped to an anonymous per-visitor identity (get_visitor_id()) — no login,
no shared/global data; each browser only ever sees its own rows.

Deliberately separate from modules/db_connect.py: that module is SQL Lab's
external, per-session, user-entered database *connection* feature (someone
else's data, credentials typed into a form, never cached beyond a session —
see its own docstring). This module owns one server-configured, long-lived
connection to Prism's OWN storage, shared by every visitor's browser
session — rows are isolated by visitor_id, the connection/pool itself is
not. Nothing in modules/db_connect.py is touched or reused here.

Every public function degrades gracefully: if MySQL isn't configured or is
unreachable, list_*() return [], save_*()/delete_*() return
(False, "friendly reason"), load_*() return (None, "friendly reason") —
never raise into app.py. Same non-AI-fallback convention every AI feature
in this app already follows: the feature quietly isn't there instead of
crashing the page.
"""

from __future__ import annotations

import os
import uuid
from typing import Optional

import streamlit as st

try:
    import sqlalchemy
    from sqlalchemy import text
except ImportError:  # requires the `pymysql` driver too — see requirements.txt
    sqlalchemy = None
    text = None

MAX_SNAPSHOTS_PER_VISITOR = 10
_VISITOR_COOKIE_NAME = "prism_visitor_id"
_VISITOR_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 730  # ~2 years


# ---------------------------------------------------------------------------
# Config — mirrors ai_analyst.get_api_key()'s st.secrets-then-.env pattern
# exactly, just with five fields instead of one.
# ---------------------------------------------------------------------------
def get_mysql_config() -> Optional[dict]:
    """st.secrets["mysql"] sub-table first (how Streamlit Community Cloud
    injects secrets), falling back per-field to MYSQL_HOST/MYSQL_PORT/
    MYSQL_USER/MYSQL_PASSWORD/MYSQL_DATABASE env vars (populated from .env
    locally, or Render's flat envVars — Render has no TOML sub-table
    concept). Returns None, not a half-filled dict, if host or database is
    missing, so callers do one `if config is None` check instead of
    validating fields themselves.
    """
    secrets_cfg: dict = {}
    try:
        secrets_cfg = dict(st.secrets.get("mysql", {}))
    except Exception:
        pass  # no secrets.toml locally, or not running inside Streamlit — fall through

    host = secrets_cfg.get("host") or os.getenv("MYSQL_HOST", "")
    database = secrets_cfg.get("database") or os.getenv("MYSQL_DATABASE", "")
    if not host or not database:
        return None
    return {
        "host": host,
        "port": secrets_cfg.get("port") or int(os.getenv("MYSQL_PORT", "3306")),
        "user": secrets_cfg.get("user") or os.getenv("MYSQL_USER", ""),
        "password": secrets_cfg.get("password") or os.getenv("MYSQL_PASSWORD", ""),
        "database": database,
    }


def is_configured() -> bool:
    """Cheap presence check, no connection attempt — gates whether the new
    'Save to My Account' UI blocks render at all. Unconfigured means those
    blocks don't render, not that they render broken."""
    return get_mysql_config() is not None


# ---------------------------------------------------------------------------
# Connection — one long-lived pooled Engine per deployment, not per session.
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def _get_engine():
    """No-arg cache key: one app-owned MySQL target per deployment, unlike
    db_connect's per-session user-entered params_key. Returns None on any
    failure (missing driver, missing config, connection/schema error) —
    never raises, so every call site can just check `if engine is None`.
    pool_pre_ping=True guards against MySQL's wait_timeout silently
    dropping idle connections (confirmed real via the broken-connection
    verification pass — restarting MySQL mid-session must recover on the
    next query, not stay wedged); pool_recycle=280 proactively retires
    connections before the common 300s default wait_timeout too.
    """
    if sqlalchemy is None:
        return None
    config = get_mysql_config()
    if config is None:
        return None
    url = (
        f"mysql+pymysql://{config['user']}:{config['password']}"
        f"@{config['host']}:{config['port']}/{config['database']}"
    )
    try:
        engine = sqlalchemy.create_engine(url, pool_pre_ping=True, pool_recycle=280)
        _ensure_schema(engine)
        return engine
    except Exception:
        return None


def get_engine():
    """Public wrapper around _get_engine() — mirrors db_connect's own
    get_duckdb_attach_connection/get_sqlserver_engine call-site shape."""
    return _get_engine()


def _ensure_schema(engine) -> None:
    """Three idempotent CREATE TABLE IF NOT EXISTS statements — the whole
    'schema management' story for this module. No migration framework, no
    version table: three tables this small don't need one. Does NOT create
    the database itself (CREATE DATABASE IF NOT EXISTS) — the target
    database is expected to already exist; the user's MySQL account may
    not have server-level CREATE DATABASE privileges even if it can create
    tables inside one it's already scoped to.
    """
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prism_saved_queries (
                id          BIGINT AUTO_INCREMENT PRIMARY KEY,
                visitor_id  VARCHAR(36)  NOT NULL,
                name        VARCHAR(255) NOT NULL,
                sql_text    MEDIUMTEXT   NOT NULL,
                created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_visitor_query_name (visitor_id, name)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prism_recipes (
                id           BIGINT AUTO_INCREMENT PRIMARY KEY,
                visitor_id   VARCHAR(36)  NOT NULL,
                name         VARCHAR(255) NOT NULL,
                recipe_json  MEDIUMTEXT   NOT NULL,
                created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_visitor_recipe_name (visitor_id, name)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prism_session_snapshots (
                id            BIGINT AUTO_INCREMENT PRIMARY KEY,
                visitor_id    VARCHAR(36)  NOT NULL,
                name          VARCHAR(255) NOT NULL,
                session_json  LONGTEXT     NOT NULL,
                row_count     INT NULL,
                created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_visitor (visitor_id)
            )
        """))
        # SQL Lab's *external* live-database connections (db_connect.py) —
        # deliberately a separate table from the three above: this one stores
        # someone else's database credentials, not Prism's own app data. Column
        # named db_name, not "database" — DATABASE is a reserved word in MySQL
        # and would need backtick-quoting everywhere otherwise. sqlite has no
        # row here — its "connection" is an uploaded file materialized to a
        # process-local temp path (see app._materialize_sqlite_upload), which
        # isn't durable/meaningful to save across sessions.
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prism_saved_connections (
                id           BIGINT AUTO_INCREMENT PRIMARY KEY,
                visitor_id   VARCHAR(36)  NOT NULL,
                name         VARCHAR(255) NOT NULL,
                engine_type  VARCHAR(20)  NOT NULL,
                host         VARCHAR(255) NULL,
                port         INT NULL,
                user         VARCHAR(255) NULL,
                password     VARCHAR(255) NULL,
                db_name      VARCHAR(255) NULL,
                created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_visitor_connection_name (visitor_id, name)
            )
        """))


# ---------------------------------------------------------------------------
# Visitor identity — anonymous, cookie-backed, no login.
# ---------------------------------------------------------------------------
def get_visitor_id() -> str:
    """Resolved once per session and cached in st.session_state.visitor_id.

    Reads st.context.cookies.get(_VISITOR_COOKIE_NAME) — if present, that's
    the visitor's long-lived id from a previous visit. If absent, mints a
    fresh uuid4, caches it, and writes it back to the browser via a
    components.html() snippet.

    That snippet MUST target window.parent.document.cookie, not a bare
    document.cookie — components.html() renders inside a sandboxed iframe,
    so a bare document.cookie would set a cookie on the iframe's own
    document, invisible to st.context.cookies on the next connection.
    Reaching into window.parent.document is this codebase's own established
    technique for exactly this constraint (see modules/atlas.py's
    neuron-background injection and modules/ui.py's render_tab_jump_script).

    Deliberately reads st.context.cookies only ONCE per session (cached in
    session_state, not re-read every rerun) — it's snapshotted at
    WebSocket-connect time, so a cookie set via JS mid-session won't
    reappear there until the next real page load/reconnect.
    """
    if st.session_state.get("visitor_id"):
        return st.session_state.visitor_id

    cookie_id = None
    try:
        cookie_id = st.context.cookies.get(_VISITOR_COOKIE_NAME)
    except Exception:
        pass  # older Streamlit without st.context.cookies, or no request context yet

    if cookie_id:
        st.session_state.visitor_id = cookie_id
        return cookie_id

    new_id = str(uuid.uuid4())
    st.session_state.visitor_id = new_id
    _set_visitor_cookie(new_id)
    return new_id


def _set_visitor_cookie(visitor_id: str) -> None:
    import streamlit.components.v1 as components

    components.html(
        f"""
        <script>
        window.parent.document.cookie =
            "{_VISITOR_COOKIE_NAME}={visitor_id}; max-age={_VISITOR_COOKIE_MAX_AGE_SECONDS}; path=/; SameSite=Lax";
        </script>
        """,
        height=0,
    )


# ---------------------------------------------------------------------------
# Saved queries — plain columns (name, sql_text), not sql_lab.py's JSON
# envelope, so the DB-backed list renders without parsing JSON and this
# module never needs to import sql_lab.
# ---------------------------------------------------------------------------
def list_saved_queries(visitor_id: str) -> list[dict]:
    engine = get_engine()
    if engine is None:
        return []
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id, name, sql_text, updated_at FROM prism_saved_queries "
                     "WHERE visitor_id = :vid ORDER BY updated_at DESC"),
                {"vid": visitor_id},
            ).mappings().all()
        return [dict(r) for r in rows]
    except Exception:
        return []


def save_saved_query(visitor_id: str, name: str, sql: str) -> tuple[bool, Optional[str]]:
    engine = get_engine()
    if engine is None:
        return False, "MySQL isn't configured or isn't reachable right now — this stays in your browser session only."
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO prism_saved_queries (visitor_id, name, sql_text)
                VALUES (:vid, :name, :sql_text)
                ON DUPLICATE KEY UPDATE sql_text = :sql_text, updated_at = CURRENT_TIMESTAMP
            """), {"vid": visitor_id, "name": name, "sql_text": sql})
        return True, None
    except Exception as e:
        return False, str(e)


def delete_saved_query(visitor_id: str, query_id: int) -> tuple[bool, Optional[str]]:
    engine = get_engine()
    if engine is None:
        return False, "MySQL isn't configured or isn't reachable right now."
    try:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM prism_saved_queries WHERE id = :id AND visitor_id = :vid"),
                {"id": query_id, "vid": visitor_id},
            )
        return True, None
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Recipes — stores the *exact* JSON string recipes.save_recipe() already
# produces, so the read path is recipes.load_recipe(json_string) unchanged.
# ---------------------------------------------------------------------------
def list_recipes(visitor_id: str) -> list[dict]:
    engine = get_engine()
    if engine is None:
        return []
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id, name, updated_at FROM prism_recipes "
                     "WHERE visitor_id = :vid ORDER BY updated_at DESC"),
                {"vid": visitor_id},
            ).mappings().all()
        return [dict(r) for r in rows]
    except Exception:
        return []


def save_recipe_to_db(visitor_id: str, name: str, recipe_json: str) -> tuple[bool, Optional[str]]:
    engine = get_engine()
    if engine is None:
        return False, "MySQL isn't configured or isn't reachable right now — this stays in your browser session only."
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO prism_recipes (visitor_id, name, recipe_json)
                VALUES (:vid, :name, :recipe_json)
                ON DUPLICATE KEY UPDATE recipe_json = :recipe_json, updated_at = CURRENT_TIMESTAMP
            """), {"vid": visitor_id, "name": name, "recipe_json": recipe_json})
        return True, None
    except Exception as e:
        return False, str(e)


def load_recipe_from_db(visitor_id: str, recipe_id: int) -> tuple[Optional[str], Optional[str]]:
    engine = get_engine()
    if engine is None:
        return None, "MySQL isn't configured or isn't reachable right now."
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT recipe_json FROM prism_recipes WHERE id = :id AND visitor_id = :vid"),
                {"id": recipe_id, "vid": visitor_id},
            ).first()
        if row is None:
            return None, "That recipe wasn't found — it may have been deleted."
        return row[0], None
    except Exception as e:
        return None, str(e)


def delete_recipe(visitor_id: str, recipe_id: int) -> tuple[bool, Optional[str]]:
    engine = get_engine()
    if engine is None:
        return False, "MySQL isn't configured or isn't reachable right now."
    try:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM prism_recipes WHERE id = :id AND visitor_id = :vid"),
                {"id": recipe_id, "vid": visitor_id},
            )
        return True, None
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Session snapshots — stores the exact JSON string session_io.save_session()
# already produces, so the read path is session_io.load_session(bytes)
# unchanged. No unique-name constraint (every save is a new artifact,
# matching "Save Session" download semantics) — unbounded growth is capped
# here instead, by pruning beyond MAX_SNAPSHOTS_PER_VISITOR after each save.
# ---------------------------------------------------------------------------
def list_session_snapshots(visitor_id: str) -> list[dict]:
    engine = get_engine()
    if engine is None:
        return []
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id, name, row_count, created_at FROM prism_session_snapshots "
                     "WHERE visitor_id = :vid ORDER BY created_at DESC"),
                {"vid": visitor_id},
            ).mappings().all()
        return [dict(r) for r in rows]
    except Exception:
        return []


def save_session_snapshot(
    visitor_id: str, name: str, session_json: str, row_count: int
) -> tuple[bool, Optional[str]]:
    engine = get_engine()
    if engine is None:
        return False, "MySQL isn't configured or isn't reachable right now — this stays as a local download only."
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO prism_session_snapshots (visitor_id, name, session_json, row_count)
                VALUES (:vid, :name, :session_json, :row_count)
            """), {"vid": visitor_id, "name": name, "session_json": session_json, "row_count": row_count})
            # Prune beyond MAX_SNAPSHOTS_PER_VISITOR, oldest first — keeps this
            # table bounded without a separate delete UI for snapshots.
            conn.execute(text("""
                DELETE FROM prism_session_snapshots
                WHERE visitor_id = :vid AND id NOT IN (
                    SELECT id FROM (
                        SELECT id FROM prism_session_snapshots
                        WHERE visitor_id = :vid
                        ORDER BY created_at DESC
                        LIMIT :keep
                    ) AS keep_ids
                )
            """), {"vid": visitor_id, "keep": MAX_SNAPSHOTS_PER_VISITOR})
        return True, None
    except Exception as e:
        return False, str(e)


def load_session_snapshot(visitor_id: str, snapshot_id: int) -> tuple[Optional[str], Optional[str]]:
    engine = get_engine()
    if engine is None:
        return None, "MySQL isn't configured or isn't reachable right now."
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT session_json FROM prism_session_snapshots WHERE id = :id AND visitor_id = :vid"),
                {"id": snapshot_id, "vid": visitor_id},
            ).first()
        if row is None:
            return None, "That saved session wasn't found — it may have been pruned or deleted."
        return row[0], None
    except Exception as e:
        return None, str(e)


# ---------------------------------------------------------------------------
# Saved external-database connections — SQL Lab's "🔌 Database Connection"
# panel (modules/db_connect.py), NOT Prism's own data. Stores the password
# in plain text, same as everything else in this table's neighbors (no
# field-level encryption anywhere in this app) and consistent with this
# app's existing trust model for the *live* connection already held in
# st.session_state.db_connection for the session's duration — this just
# extends that same plaintext-credential posture across sessions instead of
# adding a new one. mysql/postgres/sqlserver only; sqlite has nothing
# meaningful to save here (see _ensure_schema's comment on this table).
# ---------------------------------------------------------------------------
def list_saved_connections(visitor_id: str) -> list[dict]:
    """Does NOT include the password — this is for the picker list, not for
    actually connecting. Use load_connection() to get the full row."""
    engine = get_engine()
    if engine is None:
        return []
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id, name, engine_type, host, port, user, db_name, updated_at "
                     "FROM prism_saved_connections WHERE visitor_id = :vid ORDER BY updated_at DESC"),
                {"vid": visitor_id},
            ).mappings().all()
        return [dict(r) for r in rows]
    except Exception:
        return []


def save_connection(
    visitor_id: str, name: str, engine_type: str, host: str, port: int, user: str, password: str, db_name: str,
) -> tuple[bool, Optional[str]]:
    engine = get_engine()
    if engine is None:
        return False, "MySQL isn't configured or isn't reachable right now — this connection won't be remembered."
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO prism_saved_connections
                    (visitor_id, name, engine_type, host, port, user, password, db_name)
                VALUES (:vid, :name, :engine_type, :host, :port, :user, :password, :db_name)
                ON DUPLICATE KEY UPDATE
                    engine_type = :engine_type, host = :host, port = :port, user = :user,
                    password = :password, db_name = :db_name, updated_at = CURRENT_TIMESTAMP
            """), {
                "vid": visitor_id, "name": name, "engine_type": engine_type, "host": host,
                "port": port, "user": user, "password": password, "db_name": db_name,
            })
        return True, None
    except Exception as e:
        return False, str(e)


def load_connection(visitor_id: str, connection_id: int) -> tuple[Optional[dict], Optional[str]]:
    """Returns the FULL row including password — only call this right before
    actually connecting, never to populate a list display."""
    engine = get_engine()
    if engine is None:
        return None, "MySQL isn't configured or isn't reachable right now."
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT engine_type, host, port, user, password, db_name FROM prism_saved_connections "
                     "WHERE id = :id AND visitor_id = :vid"),
                {"id": connection_id, "vid": visitor_id},
            ).mappings().first()
        if row is None:
            return None, "That saved connection wasn't found — it may have been deleted."
        return dict(row), None
    except Exception as e:
        return None, str(e)


def delete_connection(visitor_id: str, connection_id: int) -> tuple[bool, Optional[str]]:
    engine = get_engine()
    if engine is None:
        return False, "MySQL isn't configured or isn't reachable right now."
    try:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM prism_saved_connections WHERE id = :id AND visitor_id = :vid"),
                {"id": connection_id, "vid": visitor_id},
            )
        return True, None
    except Exception as e:
        return False, str(e)
