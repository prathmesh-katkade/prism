"""
AI Analyst — turns plain-English questions into pandas code via the Google
Gemini API, executes that code in a restricted sandbox, and returns the
result for display. Also generates 5 analyst-style key findings.

Architecture (safe execution):
    question --> Gemini (schema + sample + stats + chat history, NEVER the
    full dataset) --> ```python code block --> restricted exec() (only df,
    pd, np in scope; import/eval/exec/dunder/subprocess/requests rejected
    outright, pd/np's own file-and-network I/O surface stripped via a
    proxy so `pd.read_csv(url)` can't be used to read local secrets or
    exfiltrate data over the network, and a hard wall-clock timeout so a
    runaway or hallucinated infinite loop can't hang the app) --> on
    failure, the error is sent back to Gemini exactly once for a corrected
    version ("self-healing retry") --> final result.

Setup: put GEMINI_API_KEY=... in a .env file at the project root (see
.env.example). Get a free key at https://aistudio.google.com/apikey.
"""

from __future__ import annotations

import json
import os
import re
import threading
from typing import Optional

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dotenv import load_dotenv

try:
    from google import genai as genai_client
    from google.genai import types as genai_types
except ImportError:  # the app should still load even if the package isn't installed yet
    genai_client = None
    genai_types = None

# Populate os.environ from a .env file in the project root, if one exists.
# Safe to call even when no .env is present — it's then a no-op.
load_dotenv()

# Google's alias for the current-gen free-tier Flash-Lite model. Auto-tracks whatever
# generation Google currently recommends (avoids re-breaking every time a pinned generation,
# e.g. the old "gemini-2.5-flash", gets deprecated for new API keys). Flash-Lite over plain
# Flash deliberately: it has a meaningfully higher free-tier daily request quota, and every
# Gemini call Prism makes — schema-to-pandas-code generation, JSON intent classification,
# short narration — is a bounded, structured task well within a lite-tier model's depth.
MODEL_NAME = "gemini-flash-lite-latest"

GEMINI_SETUP_HELP = (
    "**Add your free Gemini API key to unlock AI features.**\n\n"
    "Locally: create a `.env` file in the project root with `GEMINI_API_KEY=your_key_here` "
    "(see `.env.example`), then restart the app.\n\n"
    "On Streamlit Community Cloud: add `GEMINI_API_KEY` under your app's "
    "**Settings → Secrets** (see `DEPLOYMENT.md`).\n\n"
    "[Get a free key at aistudio.google.com](https://aistudio.google.com/apikey)"
)

# Belt-and-suspenders keyword blocklist, checked before anything is executed.
# The restricted exec() namespace (safe builtins + the pd/np proxies below)
# is the real safety boundary — this list just rejects obviously hostile
# code earlier, with a clearer error message than a raised NameError.
#
# The to_*()/tofile( entries matter more than they look: pd.read_csv/read_*
# are blocked structurally below (the proxy strips them off the `pd` object
# entirely), but `df.to_csv(path)` etc. are *instance* methods on the
# DataFrame object itself — not attributes of `pd` — so the proxy can't
# reach them without wrapping every DataFrame the sandbox ever produces.
# Blocking the call text here is safe specifically because getattr/eval/
# dunder access are all unavailable in this namespace: generated code has
# no way to construct one of these calls except by writing the literal
# method name in source, which this list catches regardless of how the
# call is invoked.
_FORBIDDEN_PATTERNS = [
    "import os", "import sys", "open(", "eval(", "exec(", "__",
    "subprocess", "requests", "socket", "shutil", "compile(",
    "to_csv(", "to_excel(", "to_pickle(", "to_json(", "to_parquet(",
    "to_hdf(", "to_feather(", "to_sql(", "to_stata(", "to_gbq(",
    "to_clipboard(", "tofile(",
]

# pd/np attributes that read from or write to the filesystem or network.
# Generated code is given `df` already loaded — it has no legitimate reason
# to reach a *new* external data source or write anything to disk; every
# real question is answered by transforming `df` and assigning `result`.
# Proven necessary, not theoretical: pd.read_csv(local_path) reads arbitrary
# files off the server's disk (including a real .env/secrets.toml sitting
# next to the app) and pd.read_csv(url) makes a genuine outbound HTTP
# request, letting generated code exfiltrate `df`'s contents by encoding
# them into the URL — neither is caught by the keyword blocklist above,
# since it's blocking source text, not what pandas' own I/O layer can do.
_BLOCKED_PANDAS_ATTRS = frozenset({
    "read_csv", "read_excel", "read_json", "read_html", "read_pickle",
    "read_parquet", "read_sql", "read_sql_query", "read_sql_table",
    "read_hdf", "read_feather", "read_orc", "read_stata", "read_sas",
    "read_spss", "read_gbq", "read_clipboard", "read_fwf", "read_table",
    "read_xml", "ExcelFile", "ExcelWriter", "HDFStore",
})
_BLOCKED_NUMPY_ATTRS = frozenset({
    "load", "save", "savez", "savez_compressed", "fromfile", "tofile",
    "memmap", "genfromtxt", "loadtxt", "DataSource",
})


class _RestrictedModuleProxy:
    """Wraps `pd`/`np` so generated code gets the normal computation API
    (groupby, merge, pivot_table, corr, ...) but can never reach the
    functions in `blocked` — enforced at attribute lookup, so it can't be
    bypassed by however the code spells the access. The only way around
    an attribute-lookup guard would be getattr()/importlib, both already
    absent from this sandbox's builtins.
    """

    __slots__ = ("_module", "_blocked")

    def __init__(self, module, blocked: frozenset):
        object.__setattr__(self, "_module", module)
        object.__setattr__(self, "_blocked", blocked)

    def __getattr__(self, name: str):
        if name in self._blocked:
            raise AttributeError(
                f"'{name}' is disabled in this sandbox — the dataframe is already loaded "
                f"as `df`; generated code analyzes it, it never loads a new data source "
                f"or writes files."
            )
        return getattr(self._module, name)


# Wall-clock cap on generated code — without this, a hallucinated infinite
# loop (or one steered by an indirect prompt injection hidden in a cell
# value) hangs the request forever. Streamlit Community Cloud runs a single
# process per app, so one hung request degrades the app for every
# concurrent user, not just the one who triggered it.
_EXEC_TIMEOUT_SECONDS = 10

# The only builtins the generated code is allowed to call. Everything that
# touches the filesystem, network, process, or Python internals is excluded.
_ALLOWED_BUILTIN_NAMES = [
    "len", "range", "min", "max", "sum", "sorted", "list", "dict", "set",
    "tuple", "str", "int", "float", "bool", "round", "zip", "enumerate",
    "abs", "all", "any", "reversed", "map", "filter",
]

CODE_SYSTEM_PROMPT = (
    "You are a data analyst assistant embedded in a Streamlit app. The user has a "
    "pandas DataFrame called `df` already loaded in memory. Given the dataframe's "
    "schema, a sample, and summary statistics, write Python code that answers the "
    "user's question.\n\n"
    "Rules:\n"
    "- Use only `df`, `pd` (pandas), and `np` (numpy) — nothing else is available.\n"
    "- Do not import anything, read/write files, or use network/system calls.\n"
    "- Assign the final answer to a variable named `result`. It should be a "
    "DataFrame, Series, or scalar — whichever best answers the question.\n"
    "- Return ONLY a single ```python code block, no prose before or after it."
)

# Keywords that suggest a chat answer would benefit from a chart alongside the
# raw table/number — used by question_implies_chart() below.
_TREND_KEYWORDS = [
    "trend", "over time", "compare", "comparison", "vs", "versus", " by ",
    "growth", "change", "correlation", "distribution", "group", "across", "per ",
]


def get_api_key() -> str:
    """Read GEMINI_API_KEY — st.secrets first (how Streamlit Community Cloud
    injects secrets), then the environment (populated from .env by
    load_dotenv() above, for local dev). A lazy streamlit import keeps this
    module usable outside a Streamlit run context (e.g. in plain scripts/tests).
    """
    try:
        import streamlit as st

        secret_key = st.secrets.get("GEMINI_API_KEY")
        if secret_key:
            return secret_key
    except Exception:
        pass  # no secrets.toml locally, or not running inside Streamlit — fall through
    return os.getenv("GEMINI_API_KEY", "")


class _GeminiModel:
    """Adapter presenting the old `google-generativeai` GenerativeModel
    interface (`model.generate_content(contents) -> response` with a
    `.text` property) on top of the current `google-genai` Client SDK.

    Why this exists: `google-generativeai` ended upstream support (it now
    raises a FutureWarning on import) and its successor, `google-genai`, has
    a different shape — a single `Client` you call `client.models.generate_
    content(model=..., contents=..., config=...)` on, rather than a
    per-model object. Every one of the ~15 call sites across the app only
    ever touches `model.generate_content(contents)` (never SDK internals
    directly — `call_gemini()` is the sole choke point), so wrapping the new
    Client behind this adapter kept the migration to this file and
    `modules/atlas.py`'s router model, instead of a rewrite of every caller.
    """

    __slots__ = ("_client", "_model_name", "_system_instruction")

    def __init__(self, client, model_name: str, system_instruction: Optional[str] = None):
        self._client = client
        self._model_name = model_name
        self._system_instruction = system_instruction

    def generate_content(self, contents):
        config = (
            genai_types.GenerateContentConfig(system_instruction=self._system_instruction)
            if self._system_instruction
            else None
        )
        return self._client.models.generate_content(
            model=self._model_name, contents=contents, config=config
        )


def build_model(model_name: str, system_instruction: Optional[str] = None, api_key: Optional[str] = None):
    """Generic model factory — build a Client-backed `_GeminiModel` for any
    model name/system instruction, or None if unavailable (no key, or the
    google-genai package isn't installed). get_model()/get_sql_model() below
    are this app's two standing configurations; modules.atlas's intent
    router calls this directly for its own system prompt.
    """
    key = get_api_key() if api_key is None else api_key
    if not key or genai_client is None:
        return None
    return _GeminiModel(genai_client.Client(api_key=key), model_name, system_instruction)


def get_model(api_key: Optional[str] = None):
    """Build a configured Gemini model instance, or None if unavailable."""
    return build_model(MODEL_NAME, system_instruction=CODE_SYSTEM_PROMPT, api_key=api_key)


def get_sql_model(api_key: Optional[str] = None):
    """A second model instance for SQL Lab's AI features (explain_sql,
    generate_sql, suggest_sql_fix) — deliberately WITHOUT CODE_SYSTEM_PROMPT.

    That system instruction hard-codes "write Python code... assign to a
    variable named `result`... return ONLY a python code block" — fine for
    ask_question's pandas pipeline, but it overrides a plain per-request
    prompt asking for SQL instead: generate_sql/suggest_sql_fix were
    observed returning pandas snippets (`result = df[...]`) instead of SQL
    when built on get_model(), because the system instruction outranks a
    same-shaped "return only code" request in the user turn. Each of these
    three functions puts its full task instructions directly in the prompt,
    so no system instruction is needed here at all.
    """
    return build_model(MODEL_NAME, system_instruction=None, api_key=api_key)


def generate_df_metadata(df: pd.DataFrame, column_types: Optional[dict[str, str]] = None) -> str:
    """Compact, structured description of a dataframe's shape and contents —
    shape, per-column dtype, per-column missing count, min/mean/max for
    numeric columns, and unique-value counts for categorical/text columns.

    This exists specifically so no caller ever has a reason to hand Gemini
    raw rows to "describe" the dataset: this function IS the description.
    It's deliberately narrower than the old `df.describe(include="all")`
    dump this replaced (no percentiles/std/mode) — those rarely change a
    generated pandas answer but reliably bloat every single request's token
    count, on every dataset, on every question.

    column_types is optional (falls back to inferring numeric-vs-categorical
    from pandas dtypes directly) so this is usable standalone, without first
    calling data_engine.detect_column_types.
    """
    n_rows, n_cols = df.shape
    dtypes = {col: str(dtype) for col, dtype in df.dtypes.items()}
    missing_counts = df.isna().sum()

    lines = [f"Shape: {n_rows} rows x {n_cols} columns", "", "Columns (dtype, missing count):"]
    for col in df.columns:
        lines.append(f"- {col}: {dtypes[col]}, missing={int(missing_counts[col])}")

    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if numeric_cols:
        lines.append("")
        lines.append("Numeric columns (min / mean / max):")
        for col in numeric_cols:
            series = df[col].dropna()
            if series.empty:
                lines.append(f"- {col}: (no non-null values)")
            else:
                def fmt(v: float) -> str:
                    # ':.4g' flips to scientific notation on ordinary round salary/revenue figures.
                    return f"{int(v):,}" if float(v).is_integer() else f"{v:,.2f}"

                lines.append(f"- {col}: {fmt(series.min())} / {fmt(series.mean())} / {fmt(series.max())}")

    if column_types:
        categorical_cols = [c for c in df.columns if column_types.get(c) in ("categorical", "text")]
    else:
        categorical_cols = [c for c in df.columns if c not in numeric_cols]
    if categorical_cols:
        lines.append("")
        lines.append("Categorical/text columns (unique value count):")
        for col in categorical_cols:
            lines.append(f"- {col}: {df[col].nunique()} unique")

    return "\n".join(lines)


def build_data_context(
    df: pd.DataFrame,
    column_types: dict[str, str],
    pii_findings: Optional[dict] = None,
    strict_mode: bool = False,
    dataset_fingerprint: Optional[dict] = None,
) -> str:
    """Combine generate_df_metadata() with a strictly-limited 3-row markdown
    sample into the sole description of the dataframe sent to Gemini.

    This — never the full dataset — is what goes to Gemini on every request.
    When strict_mode is True and pii_findings flags any columns (Indian PII
    Vault), the sample rows are redacted for those columns first — the
    model still sees the column exists in the schema, never its values.

    dataset_fingerprint, if the uploaded data matched a known public
    dataset's column signature (modules.dataset_knowledge), folds its
    curated known-issue tips into the prompt — so a question like "what
    should I watch out for" gets the actual documented quirks of e.g. the
    Kaggle Titanic dataset, not a generic guess from the sample rows alone.
    """
    metadata = generate_df_metadata(df, column_types)
    if strict_mode and pii_findings:
        from modules import pii_detector
        sample_df = pii_detector.build_safe_sample(df, pii_findings, n=3)
    else:
        sample_df = df.head(3)
    try:
        sample = sample_df.to_markdown(index=False)
    except ImportError:
        sample = sample_df.to_string(index=False)  # tabulate not installed — fall back rather than fail the request

    fingerprint_block = ""
    if dataset_fingerprint:
        tips = "\n".join(f"- {t}" for t in dataset_fingerprint["tips"])
        fingerprint_block = (
            f"\nThis data appears to be the {dataset_fingerprint['name']} — known quirks to keep in mind:\n{tips}\n"
        )

    return f"{metadata}\n{fingerprint_block}\nSample rows (first 3):\n{sample}"


def history_to_contents(chat_history: list[dict]) -> list[dict]:
    """Convert app-level chat history into Gemini's {role, parts} turn format.

    Assistant turns are represented by the code they produced (or the error,
    if the request itself failed) rather than the full result — enough for
    Gemini to keep continuity across follow-up questions without resending data.
    """
    contents = []
    for msg in chat_history:
        if msg["role"] == "user":
            contents.append({"role": "user", "parts": [{"text": msg["content"]}]})
        else:
            if msg.get("ask_error"):
                text = "(The previous request failed and was not shown to the user.)"
            elif msg.get("code"):
                text = f"```python\n{msg['code']}\n```"
            else:
                text = "(no code generated)"
            contents.append({"role": "model", "parts": [{"text": text}]})
    return contents


_CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)


def extract_code(response_text: str) -> str:
    """Pull the first ```python ...``` block out of Gemini's reply, or fall back to the raw text."""
    match = _CODE_BLOCK_RE.search(response_text)
    return match.group(1).strip() if match else response_text.strip()


# Every Gemini call in Prism shares one API key, and the app has no login —
# any anonymous visitor can exhaust the shared free-tier daily quota for
# everyone else. This doesn't fix that (only auth or BYOK really would),
# but it raises the bar: no single browser session can burn through the
# whole day's quota on its own.
_MAX_GEMINI_CALLS_PER_SESSION_PER_HOUR = 30
_RATE_LIMIT_WINDOW_SECONDS = 3600


def _check_rate_limit() -> Optional[str]:
    """Returns an error message if this Streamlit session has hit its
    hourly Gemini call cap, else None. Silently a no-op outside a real
    browser session (eval harnesses, tools/corpus_gauntlet.py, plain
    scripts) — there's no per-visitor session to bound there.

    Checking get_script_run_ctx() (not just whether st.session_state
    *works*) matters: Streamlit's "bare mode" session_state is a real,
    functioning dict even with no browser attached — it just persists for
    the whole process instead of per-visitor. A long-running script making
    many sequential Gemini calls (tools/corpus_gauntlet.py processing 12
    datasets in one run) would trip this limiter against itself, mistaken
    for one browser session hammering the app. Caught by running the
    corpus gauntlet after adding this limiter — it started failing at
    exactly the questions past the cap.
    """
    try:
        import time as _time

        import streamlit as st
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        if get_script_run_ctx() is None:
            return None

        now = _time.time()
        window_start = st.session_state.get("_gemini_window_start", now)
        call_count = st.session_state.get("_gemini_call_count", 0)
        if now - window_start > _RATE_LIMIT_WINDOW_SECONDS:
            window_start, call_count = now, 0
        if call_count >= _MAX_GEMINI_CALLS_PER_SESSION_PER_HOUR:
            return (
                f"You've reached this session's limit of {_MAX_GEMINI_CALLS_PER_SESSION_PER_HOUR} "
                f"AI requests per hour — this keeps the shared free-tier quota available for "
                f"everyone using the app right now. Try again in a bit."
            )
        st.session_state["_gemini_window_start"] = window_start
        st.session_state["_gemini_call_count"] = call_count + 1
        return None
    except Exception:
        return None


def call_gemini(model, contents) -> tuple[str, Optional[str]]:
    """Shared error handling around model.generate_content — used by every
    Gemini call in the app (chat, key-insights, Atlas's router, Auto
    Analyst, ...) so quota/auth failures and the per-session rate limit
    read the same way everywhere.
    """
    limit_error = _check_rate_limit()
    if limit_error:
        return "", limit_error
    try:
        response = model.generate_content(contents)
    except Exception as e:
        # google.genai.errors.APIError (and its ClientError/ServerError
        # subclasses) carry the HTTP-style status as `.code` — matching on
        # that is simpler and more robust than importing every specific
        # exception subclass, and degrades gracefully (falls through to the
        # generic message below) for exceptions that don't have one at all
        # (network errors, or the SDK being unavailable in a way that still
        # let a call reach here).
        code = getattr(e, "code", None)
        if code == 429:
            return "", (
                "Daily free-tier quota exceeded for the Gemini API. Try again later, "
                "or check your usage at https://aistudio.google.com/."
            )
        if code in (400, 401, 403):
            return "", (
                "Gemini rejected the request — GEMINI_API_KEY is set but isn't a valid Generative "
                "Language API key (these start with 'AIzaSy...'; a Google OAuth token or another "
                "kind of credential pasted in by mistake will fail the same way). Get a fresh one "
                "at https://aistudio.google.com/apikey and update it wherever this app reads it "
                "from — a local .env file, or Settings → Secrets on Streamlit Community Cloud, or "
                "your host's environment variables."
            )
        return "", f"Gemini request failed: {e}"
    # Guard against safety-filtered or empty responses. Unlike the old SDK
    # (which raised ValueError/AttributeError on `.text` access), google-genai's
    # `.text` property returns None outright when every candidate was
    # safety-filtered or the response has no text parts — check the value,
    # not for an exception.
    text = getattr(response, "text", None)
    if not text:
        return "", "Gemini returned an empty or safety-filtered response — try rephrasing your question."
    return text, None


def explain_sql(model, sql: str) -> tuple[str, Optional[str]]:
    """Ask Gemini to explain a SQL query in plain English — the SQL Lab tab's
    "Explain this query" button. Kept independent of the pandas chat/insights
    flows since it doesn't touch the dataframe at all, only the query text.
    """
    prompt = (
        "Explain what the following SQL query does, in plain English, in 2-4 sentences, "
        "for a non-technical stakeholder. Do not restate the raw SQL back verbatim.\n\n"
        f"```sql\n{sql}\n```"
    )
    text, error = call_gemini(model, prompt)
    if error:
        return "", error
    return text.strip(), None


def _strip_sql_fence(text: str) -> str:
    """Defensive cleanup for generate_sql/suggest_sql_fix: both prompts ask
    for raw SQL with no markdown fences, but models don't always comply.
    extract_code() isn't reusable here — its regex only optionally strips a
    'python' tag, not 'sql', and would leave a literal "sql\\n" behind.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:sql)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def generate_sql(
    model, df: pd.DataFrame, column_types: dict[str, str], question: str, table_name: str = "data"
) -> tuple[str, Optional[str]]:
    """Natural-language-to-SQL for the SQL Lab tab's "Generate SQL" button.
    One-shot prompt-in/text-out, same minimal shape as explain_sql — not
    ask_question's multi-turn pandas pipeline, since this only has to
    produce a query, not run one.
    """
    context = build_data_context(df, column_types)
    prompt = (
        f"You write DuckDB SQL. The dataset is registered as a table named `{table_name}`.\n\n"
        f"{context}\n\n"
        f"Write a single DuckDB SQL query that answers this question: {question}\n\n"
        "Return ONLY the raw SQL query — no explanation, no markdown code fences, no comments."
    )
    text, error = call_gemini(model, prompt)
    if error:
        return "", error
    return _strip_sql_fence(text), None


def suggest_sql_fix(model, sql: str, error_message: str, table_name: str = "data") -> tuple[str, Optional[str]]:
    """Given a query that failed and DuckDB's own error text, ask for a
    corrected query — the SQL Lab tab's "Suggest a Fix" button, shown
    alongside the existing error banner rather than replacing it."""
    prompt = (
        f"The following DuckDB SQL query (against a table named `{table_name}`) failed.\n\n"
        f"```sql\n{sql}\n```\n\n"
        f"DuckDB's error message:\n{error_message}\n\n"
        "Return ONLY the corrected raw SQL query — no explanation, no markdown code fences, no comments."
    )
    text, error = call_gemini(model, prompt)
    if error:
        return "", error
    return _strip_sql_fence(text), None


_SQL_PLAN_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def generate_sql_plan(model, df: pd.DataFrame, column_types: dict[str, str], goal: str, table_name: str = "data") -> list[dict]:
    """SQL-flavored sibling of auto_analyst.generate_analysis_plan: ask Gemini
    for 2-4 ordered {"title","question"} steps that together answer an
    open-ended/diagnostic `goal` via SQL against `table_name` — the Atlas
    "multi" chained-query path. Same never-fails shape as
    generate_analysis_plan: falls back to a single step wrapping `goal`
    itself (a degraded "multi" run that's really a "single" run) on any
    parse/model failure, since a plan-generation hiccup shouldn't block
    the whole request.
    """
    fallback = [{"title": (goal[:40] or "Query"), "question": goal}]
    if model is None:
        return fallback

    context = build_data_context(df, column_types)
    prompt = (
        "You are a senior data analyst breaking an open-ended question into 2 to 4 "
        "ordered SQL sub-questions that together answer it. Each sub-question must be "
        f"answerable as a single DuckDB SQL query against a table named `{table_name}`.\n\n"
        f"{context}\n\n"
        f'Open-ended question: "{goal}"\n\n'
        'Return ONLY a JSON array, each element {"title": "3-6 words", "question": '
        '"a specific, self-contained question answerable with one SQL query"}. '
        "No prose, no markdown code fences."
    )
    text, error = call_gemini(model, prompt)
    if error:
        return fallback

    match = _SQL_PLAN_JSON_ARRAY_RE.search(text)
    if not match:
        return fallback
    try:
        raw_plan = json.loads(match.group(0))
    except json.JSONDecodeError:
        return fallback

    cleaned = [
        {"title": str(step.get("title") or f"Step {i + 1}"), "question": str(step["question"])}
        for i, step in enumerate(raw_plan)
        if isinstance(step, dict) and step.get("question")
    ]
    return cleaned or fallback


def _summarize_sql_result(result_df: Optional[pd.DataFrame]) -> str:
    """Stringify a chained-query step's result compactly for a follow-up prompt."""
    if result_df is None:
        return "(no result)"
    return result_df.head(10).to_string()


def synthesize_sql_findings(model, step_outcomes: list[dict]) -> tuple[str, Optional[str]]:
    """Turn a chained-SQL run's step outcomes ({"title","sql","result_df","error"},
    one per modules.sql_lab.run_query_multi call) into ONE short spoken
    paragraph. Unlike auto_analyst.synthesize_findings' 5 numbered bullets,
    this gets read aloud by Atlas, so it must be continuous prose (2-4
    sentences) citing concrete numbers from the results — not a list.
    Steps that errored are excluded from the summary prompt, same
    discipline as synthesize_findings. Returns (narrative, error);
    narrative is "" only when every step failed.
    """
    if model is None:
        return "", "No Gemini model available."

    summaries = [
        f"- {outcome['title']} (`{outcome.get('sql', '')}`): {_summarize_sql_result(outcome.get('result_df'))}"
        for outcome in step_outcomes
        if not outcome.get("error")
    ]
    if not summaries:
        return "", "No successful queries to summarize."

    prompt = (
        "You just ran the following SQL queries against a dataset and got these "
        f"results:\n\n{chr(10).join(summaries)}\n\n"
        "You are a senior data analyst speaking your findings out loud to someone who "
        "can't see the screen. Summarize the overall answer in 2 to 4 continuous "
        "sentences of plain spoken prose, citing the concrete numbers from the results "
        "above. No bullet points, no markdown, no headers — just the sentences as "
        "you'd say them."
    )
    text, error = call_gemini(model, prompt)
    if error:
        return "", error
    return text.strip(), None


def summarize_sql_result(model, question: str, result_df: Optional[pd.DataFrame]) -> tuple[str, Optional[str]]:
    """Given the question and a single query's result, return ONE spoken
    sentence stating the actual number/finding — not a description of the
    query or its shape. Used for the "single" complexity voice narration
    after an Atlas-triggered SQL query runs (see app.py's
    _process_atlas_sql_question).
    """
    if model is None:
        return "", "No Gemini model available."
    if result_df is None or result_df.empty:
        return "That query didn't return any rows.", None

    prompt = (
        f'Question: "{question}"\n\n'
        f"Query result:\n{result_df.head(20).to_string()}\n\n"
        "Answer the question in exactly ONE spoken sentence, stating the actual "
        "number or finding from the result above — not a description of the query. "
        "No markdown, just the sentence as you'd say it out loud."
    )
    text, error = call_gemini(model, prompt)
    if error:
        return "", error
    return text.strip(), None


def ask_question(
    model,
    df: pd.DataFrame,
    column_types: dict[str, str],
    question: str,
    chat_history: list[dict],
    pii_findings: Optional[dict] = None,
    strict_mode: bool = False,
    dataset_fingerprint: Optional[dict] = None,
) -> tuple[str, Optional[str]]:
    """Ask Gemini to translate a plain-English question into pandas code.

    Returns (code, error). On an API error, code is "" and error explains why.
    strict_mode (Indian PII Vault) redacts flagged columns' sample values —
    see build_data_context. dataset_fingerprint — see build_data_context.
    """
    context = build_data_context(df, column_types, pii_findings, strict_mode, dataset_fingerprint)
    user_turn = {"role": "user", "parts": [{"text": f"Data context:\n{context}\n\nQuestion: {question}"}]}
    contents = history_to_contents(chat_history) + [user_turn]

    text, error = call_gemini(model, contents)
    if error:
        return "", error
    return extract_code(text), None


def execute_code_safely(code: str, df: pd.DataFrame):
    """Run Gemini-generated pandas code in a locked-down namespace.

    Returns (result, error). `result` is whatever the generated code assigned
    to `result` — typically a DataFrame, Series, or scalar. `df` is exposed
    directly; `pd`/`np` are exposed through a proxy that strips their file
    and network I/O surface (see _RestrictedModuleProxy) — no import, file,
    network, or dunder access. Bounded to _EXEC_TIMEOUT_SECONDS wall-clock.
    """
    lowered = code.lower()
    for pattern in _FORBIDDEN_PATTERNS:
        if pattern in lowered:
            return None, f"Generated code was rejected — it contains a disallowed operation ('{pattern.strip()}')."

    import builtins

    safe_builtins = {name: getattr(builtins, name) for name in _ALLOWED_BUILTIN_NAMES}

    exec_globals = {
        "__builtins__": safe_builtins,
        "pd": _RestrictedModuleProxy(pd, _BLOCKED_PANDAS_ATTRS),
        "np": _RestrictedModuleProxy(np, _BLOCKED_NUMPY_ATTRS),
        "df": df.copy(),  # never let generated code mutate the app's real DataFrame
    }
    exec_locals: dict = {}
    outcome: dict = {}

    def _run():
        try:
            exec(code, exec_globals, exec_locals)
        except Exception as e:
            outcome["error"] = f"The generated code raised an error: {e}"

    # Run on a daemon thread so a runaway/hallucinated infinite loop can be
    # abandoned instead of hanging the request — or the whole interpreter —
    # forever. daemon=True specifically matters here: a non-daemon thread
    # left running past its timeout blocks process shutdown entirely (a
    # plain ThreadPoolExecutor's workers are non-daemon by default, which
    # is what a first pass at this fix got wrong). This bounds *this
    # request's* latency; it still can't reclaim the CPU the orphaned
    # thread keeps burning (Python has no way to forcibly kill a thread) —
    # true resource isolation would need a subprocess or container, which
    # is a bigger infra change than this sandbox alone can provide.
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=_EXEC_TIMEOUT_SECONDS)
    if thread.is_alive():
        return None, (
            f"Generated code took longer than {_EXEC_TIMEOUT_SECONDS}s and was stopped — "
            f"likely an unbounded loop or a very expensive operation. Try rephrasing the "
            f"question more specifically (e.g. filter to fewer rows/columns first)."
        )
    if "error" in outcome:
        return None, outcome["error"]

    if "result" not in exec_locals:
        return None, "The generated code did not assign a `result` variable."

    return exec_locals["result"], None


def ask_and_execute(
    model,
    df: pd.DataFrame,
    column_types: dict[str, str],
    question: str,
    chat_history: list[dict],
    pii_findings: Optional[dict] = None,
    strict_mode: bool = False,
    dataset_fingerprint: Optional[dict] = None,
) -> dict:
    """Full round trip: ask Gemini for code, run it, and self-heal once on failure.

    Returns a dict with keys:
      code          — the (possibly corrected) generated code, or None if the Gemini request itself failed
      result        — the executed result, or None
      error         — the *execution* error after the retry, if it still failed
      ask_error     — set only if the Gemini request itself failed (bad key, quota, network, ...)
      retried       — True if the first attempt failed and a self-healing retry was made
      original_error — the first attempt's error, kept for display when retried is True

    strict_mode (Indian PII Vault) keeps flagged columns' sample values out
    of every prompt in this round trip, including the self-healing retry.
    dataset_fingerprint — see build_data_context.
    """
    code, ask_error = ask_question(
        model, df, column_types, question, chat_history, pii_findings, strict_mode, dataset_fingerprint
    )
    if ask_error:
        return {"code": None, "result": None, "error": None, "ask_error": ask_error, "retried": False}

    result, exec_error = execute_code_safely(code, df)
    if not exec_error:
        return {"code": code, "result": result, "error": None, "ask_error": None, "retried": False}

    # Self-healing retry: send the failing code + its error back to Gemini once.
    retry_prompt = (
        f"The following code raised an error when executed:\n```python\n{code}\n```\n"
        f"Error: {exec_error}\n\n"
        "Return a corrected version that fixes this error, following the same rules "
        "(use only df/pd/np, assign the answer to `result`, and return only a single "
        "```python code block)."
    )
    contents = history_to_contents(chat_history + [{"role": "user", "content": question}])
    contents.append({"role": "user", "parts": [{"text": retry_prompt}]})

    text, retry_ask_error = call_gemini(model, contents)
    if retry_ask_error:
        return {
            "code": code, "result": None, "error": exec_error,
            "ask_error": f"Retry request failed: {retry_ask_error}", "retried": True, "original_error": exec_error,
        }

    corrected_code = extract_code(text)
    corrected_result, corrected_error = execute_code_safely(corrected_code, df)
    return {
        "code": corrected_code,
        "result": corrected_result,
        "error": corrected_error,
        "ask_error": None,
        "retried": True,
        "original_error": exec_error,
    }


def question_implies_chart(question: str) -> bool:
    """Heuristic: does this question ask for a trend/comparison worth also charting?"""
    q = question.lower()
    return any(kw in q for kw in _TREND_KEYWORDS)


def build_chart_from_result(result, title: str) -> Optional[go.Figure]:
    """Best-effort auto-chart for a pandas result. Returns None if the result
    doesn't lend itself to a chart (e.g. a scalar, or a single-row frame).

    This runs on the *already-computed* result — never on AI-generated code —
    so it's outside the sandbox and free to use Plotly directly.
    """
    try:
        if isinstance(result, pd.Series):
            series = result.dropna()
            if len(series) < 2:
                return None
            if pd.api.types.is_datetime64_any_dtype(series.index):
                fig = px.line(x=series.index, y=series.values, title=title)
            else:
                fig = px.bar(x=series.index.astype(str), y=series.values, title=title)
            fig.update_layout(margin=dict(t=50, b=10, l=10, r=10))
            return fig

        if isinstance(result, pd.DataFrame):
            if result.shape[0] < 2:
                return None
            numeric_cols = result.select_dtypes(include=np.number).columns.tolist()
            if not numeric_cols:
                return None
            y_col = numeric_cols[0]
            if pd.api.types.is_datetime64_any_dtype(result.index):
                fig = px.line(result, x=result.index, y=y_col, title=title)
            else:
                fig = px.bar(result, x=result.index.astype(str), y=y_col, title=title)
            fig.update_layout(margin=dict(t=50, b=10, l=10, r=10))
            return fig
    except Exception:
        return None
    return None


_INSIGHTS_PROMPT_TEMPLATE = (
    "{context}\n\n"
    "Missing values by column: {missing_summary}\n"
    "Outliers by column (IQR method): {outlier_summary}\n"
    "Duplicate rows: {duplicate_rows}\n"
    "Top correlations: {correlation_summary}\n\n"
    "You are a senior data analyst. Based only on the information above, write "
    "exactly 5 concise, analyst-style findings a business stakeholder would care "
    "about. Each finding MUST reference at least one concrete number from the "
    "statistics above (a mean, a percentage, a correlation coefficient, a count, "
    "etc.) — do not write vague statements. Format your response as exactly 5 "
    "lines, each starting with '1. ' through '5. ', with no other text before or after."
)

_BULLET_RE = re.compile(r"^\s*\d+[.)]\s*(.+)$")
_CODE_FENCE_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)
_QUOTED_STRING_RE = re.compile(r'''["']([^"'\\]*(?:\\.[^"'\\]*)*)["']''')
_LIST_SYNTAX_LINE_RE = re.compile(r"^\s*(\w+\s*=\s*)?[\[\]]\s*,?\s*$")


def _clean_bullet_text(text: str) -> str:
    """Strip a leading numbered prefix and stray quoting a single bullet may
    carry — used after quoted-string extraction, where the quote content
    itself is still e.g. '1. The dataset contains...' rather than clean text.
    """
    text = text.strip().rstrip(",").strip()
    # Strip any run of stray quote characters, not just one matched pair —
    # a model occasionally leaves an extra "" or a triple-quote """ dangling
    # (e.g. wavering between a plain string and a Python docstring) rather
    # than exactly one open/close quote each side.
    text = text.strip("\"'").strip()
    m = _BULLET_RE.match(text)
    return m.group(1).strip() if m else text


def parse_numbered_bullets(text: str) -> list[str]:
    """Extract up to 5 plain-text bullets from a "respond in N numbered
    lines" prompt's response.

    The model's system instruction (CODE_SYSTEM_PROMPT — see get_model())
    biases it toward code, so a plain-text request sometimes still comes
    back as a ```python fenced Python list literal (`findings = ["1. ...",
    ...]`) instead of bare numbered lines. Handled in three passes, each
    only tried if the previous one found nothing: numbered lines directly;
    a code-fenced Python list's quoted string literals; then any non-empty,
    non-list-syntax line as a last resort.
    """
    fence_match = _CODE_FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1)

    bullets = [m.group(1).strip() for line in text.splitlines() if (m := _BULLET_RE.match(line))]
    if bullets:
        return [_clean_bullet_text(b) for b in bullets][:5]

    quoted = [q.strip() for q in _QUOTED_STRING_RE.findall(text) if len(q.strip()) > 3]
    if quoted:
        return [_clean_bullet_text(q) for q in quoted][:5]

    # Last resort: any non-empty line that isn't Python list/assignment syntax.
    bullets = [
        line.strip("-*\t ") for line in text.splitlines()
        if line.strip() and not _LIST_SYNTAX_LINE_RE.match(line)
    ]
    return [_clean_bullet_text(b) for b in bullets][:5]


def generate_key_insights(
    model,
    df: pd.DataFrame,
    quality_report: dict,
    column_types: dict[str, str],
    top_correlations: Optional[list[tuple[str, str, float]]] = None,
) -> tuple[list[str], Optional[str]]:
    """Ask Gemini for 5 analyst-style, number-referencing findings.

    Returns (bullets, error) — bullets is a list of up to 5 plain-text
    findings with their leading numbering already stripped, ready to render
    as cards.
    """
    context = build_data_context(df, column_types)
    missing_summary = (
        ", ".join(f"{col}: {pct}%" for col, pct in quality_report["missing_by_column"].items() if pct > 0) or "none"
    )
    outlier_summary = (
        ", ".join(
            f"{col}: {info['count']} ({info['pct']}%)"
            for col, info in quality_report["outliers"].items()
            if info["count"] > 0
        )
        or "none"
    )
    correlation_summary = (
        ", ".join(f"{a} vs {b}: {v:.2f}" for a, b, v in top_correlations) if top_correlations else "none"
    )

    prompt = _INSIGHTS_PROMPT_TEMPLATE.format(
        context=context,
        missing_summary=missing_summary,
        outlier_summary=outlier_summary,
        duplicate_rows=quality_report["duplicate_rows"],
        correlation_summary=correlation_summary,
    )

    text, error = call_gemini(model, prompt)
    if error:
        return [], error
    return parse_numbered_bullets(text), None
