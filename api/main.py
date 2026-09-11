"""
Prism API — a thin FastAPI wrapper around Prism's existing analysis modules
(modules/data_engine.py, modules/profiling.py, modules/sql_lab.py), exposed
as JSON endpoints so Atlas can call into it as a tool. The Streamlit app
(app.py) is untouched and keeps working independently — this is an
additional interface onto the same core logic, not a replacement.

Datasets live in memory only (DATASETS dict below), keyed by a short id
handed back from /upload. There is deliberately no persistence: Render's
free tier disk is ephemeral anyway, and a dataset shouldn't outlive the
process regardless. If the server restarts, re-upload.
"""

from __future__ import annotations

import base64
import io
import sys
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# modules/ is a sibling of this file's parent directory (prism/modules, this
# file is prism/api/main.py) — make it importable without installing Prism
# as a package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from modules import data_engine, profiling, sql_lab, type_coercion  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

app = FastAPI(title="Prism API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATASETS: dict[str, dict[str, Any]] = {}


def to_native(obj: Any) -> Any:
    """Recursively convert numpy/pandas scalar types to native Python so the
    stdlib json encoder (which FastAPI's default JSONResponse uses) doesn't
    choke on numpy.int64/float64/bool_ or NaN."""
    if isinstance(obj, dict):
        return {k: to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_native(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        v = float(obj)
        return None if v != v else v  # NaN -> null
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, float) and obj != obj:
        return None
    return obj


class _UploadWrapper:
    """Adapts raw upload bytes to the (.name, .seek(), .read()) interface
    modules/data_engine.py expects — that module was built for Streamlit's
    UploadedFile, this gives FastAPI's UploadFile the same shape.

    Delegates everything else to the underlying BytesIO via __getattr__
    rather than hand-picking methods: pandas' Excel engine (openpyxl,
    reading .xlsx as a zip archive) reaches for .tell() internally, which a
    seek()/read()-only shim doesn't provide — that gap silently broke every
    Excel upload through this API (CSV never exercised that code path, so
    it went unnoticed). Full delegation means any other BytesIO method a
    future pandas/openpyxl version wants also just works.
    """

    def __init__(self, filename: str, data: bytes):
        self.name = filename
        self._buf = io.BytesIO(data)

    def __getattr__(self, attr):
        return getattr(self._buf, attr)


def _auto_convert_numeric_looking_columns(df: pd.DataFrame, column_types: dict[str, str]) -> tuple[pd.DataFrame, dict[str, str], list[str]]:
    """The Streamlit app's Smart Type Coercion (modules/type_coercion.py) is
    an opt-in, preview-before-you-commit Cleaning Controls action — there's
    a human looking at a before/after sample before it applies. Atlas has no
    equivalent confirmation step in a tool call, and the alternative is
    worse: silently leaving "$1,234.56"/"85%"-style columns as text means
    query_dataset/chart_dataset/profile_dataset just can't do anything
    numeric with them. So the API path auto-applies every candidate
    type_coercion finds and reports exactly what changed in the warnings
    list — Atlas surfaces that in conversation, which is this app's version
    of "showing the user what happened" without a UI to click through.
    """
    candidates = type_coercion.detect_numeric_candidates(df, column_types)
    if not candidates:
        return df, column_types, []

    converted_names = []
    for c in candidates:
        df, _ = type_coercion.convert_column(df, c["column"])
        converted_names.append(c["column"])

    updated_types = data_engine.detect_column_types(df)
    note = (
        f"Converted {', '.join(repr(c) for c in converted_names)} to numeric "
        "(they were formatted as currency/percent/thousands-separated text)."
    )
    return df, updated_types, [note]


def _get_dataset(dataset_id: str) -> dict[str, Any]:
    ds = DATASETS.get(dataset_id)
    if not ds:
        raise HTTPException(
            404,
            f"Dataset '{dataset_id}' not found — it may have expired or the server restarted. Upload again.",
        )
    return ds


@app.get("/health")
def health():
    return {"ok": True, "datasets": len(DATASETS)}


@app.post("/upload")
async def upload(file: UploadFile = File(...), sheet: str | None = None):  # noqa: B008 - FastAPI dependency declaration
    raw = await file.read()
    wrapped = _UploadWrapper(file.filename or "upload.csv", raw)
    df, error, warnings = data_engine.load_data(wrapped, sheet_name=sheet if sheet else 0)
    if error:
        raise HTTPException(400, error)

    sheet_names = data_engine.get_excel_sheet_names(_UploadWrapper(file.filename or "upload.csv", raw))
    active_sheet = sheet if sheet else (sheet_names[0] if sheet_names else None)

    column_types = data_engine.detect_column_types(df)
    df, column_types, coercion_warnings = _auto_convert_numeric_looking_columns(df, column_types)
    warnings = warnings + coercion_warnings

    dataset_id = uuid.uuid4().hex[:12]
    # raw bytes are kept (not just the parsed df) so switch_sheet can re-parse
    # the same upload against a different sheet without Prathmesh re-picking
    # the file from his device — Atlas can just ask for a different sheet by
    # name mid-conversation.
    DATASETS[dataset_id] = {
        "df": df,
        "column_types": column_types,
        "name": file.filename,
        "raw_bytes": raw,
        "active_sheet": active_sheet,
        "sheet_names": sheet_names,
    }

    return to_native({
        "datasetId": dataset_id,
        "name": file.filename,
        "rows": df.shape[0],
        "columns": list(df.columns),
        "warnings": warnings,
        "sheetNames": sheet_names,
        "activeSheet": active_sheet,
    })


class SwitchSheetRequest(BaseModel):
    sheet: str


@app.post("/switch-sheet/{dataset_id}")
def switch_sheet(dataset_id: str, req: SwitchSheetRequest):
    ds = _get_dataset(dataset_id)
    if not ds.get("sheet_names"):
        raise HTTPException(400, "This dataset isn't a multi-sheet workbook — nothing to switch.")
    if req.sheet not in ds["sheet_names"]:
        raise HTTPException(
            400, f"Sheet '{req.sheet}' not found. Available sheets: {', '.join(ds['sheet_names'])}."
        )

    wrapped = _UploadWrapper(ds["name"] or "upload.xlsx", ds["raw_bytes"])
    df, error, warnings = data_engine.load_data(wrapped, sheet_name=req.sheet)
    if error:
        raise HTTPException(400, error)

    column_types = data_engine.detect_column_types(df)
    df, column_types, coercion_warnings = _auto_convert_numeric_looking_columns(df, column_types)
    warnings = warnings + coercion_warnings

    ds["df"] = df
    ds["column_types"] = column_types
    ds["active_sheet"] = req.sheet

    return to_native({
        "datasetId": dataset_id,
        "name": ds["name"],
        "rows": df.shape[0],
        "columns": list(df.columns),
        "warnings": warnings,
        "sheetNames": ds["sheet_names"],
        "activeSheet": req.sheet,
    })


@app.get("/summary/{dataset_id}")
def summary(dataset_id: str):
    ds = _get_dataset(dataset_id)
    df, column_types = ds["df"], ds["column_types"]
    quality = data_engine.get_data_quality_report(df, column_types)
    sample = json_safe_records(df.head(5))
    return to_native({
        "name": ds["name"],
        "rows": quality["n_rows"],
        "columns": [{"name": c, "type": column_types[c]} for c in df.columns],
        "missingPct": quality["total_missing_pct"],
        "duplicateRows": quality["duplicate_rows"],
        "sample": sample,
    })


@app.get("/profile/{dataset_id}")
def profile(dataset_id: str):
    ds = _get_dataset(dataset_id)
    df, column_types = ds["df"], ds["column_types"]
    quality = data_engine.get_data_quality_report(df, column_types)
    columns = profiling.profile_all_columns(df, column_types, quality)
    return to_native({"quality": quality, "columns": columns})


class SqlRequest(BaseModel):
    sql: str


def json_safe_records(df: pd.DataFrame) -> list[dict]:
    """Convert a DataFrame to JSON-safe records via pandas' own encoder
    (handles numpy dtypes and Timestamps correctly), then back to Python
    objects so it can be embedded in a regular dict response."""
    import json
    return json.loads(df.to_json(orient="records", date_format="iso"))


@app.post("/sql/{dataset_id}")
def sql(dataset_id: str, req: SqlRequest):
    ds = _get_dataset(dataset_id)
    result, error, elapsed = sql_lab.run_query(ds["df"], req.sql)
    if error:
        raise HTTPException(400, error)

    truncated = len(result) > 200
    return to_native({
        "rows": json_safe_records(result.head(200)),
        "rowCount": len(result),
        "truncated": truncated,
        "elapsedSeconds": round(elapsed, 3),
    })


class ChartRequest(BaseModel):
    column: str


@app.post("/chart/{dataset_id}")
def chart(dataset_id: str, req: ChartRequest):
    ds = _get_dataset(dataset_id)
    df, column_types = ds["df"], ds["column_types"]
    if req.column not in df.columns:
        raise HTTPException(400, f"Column '{req.column}' not found.")

    ctype = column_types.get(req.column, "text")
    fig, ax = plt.subplots(figsize=(7, 4), facecolor="#020C18")
    ax.set_facecolor("#0a1a2e")
    for spine in ax.spines.values():
        spine.set_color("#0094FF")
    ax.tick_params(colors="#E0F4FF")
    ax.title.set_color("#E0F4FF")
    ax.xaxis.label.set_color("#E0F4FF")
    ax.yaxis.label.set_color("#E0F4FF")

    if ctype == "numeric":
        df[req.column].dropna().plot(kind="hist", bins=30, ax=ax, color="#0094FF")
        ax.set_title(f"Distribution of {req.column}")
    elif ctype == "categorical":
        counts = df[req.column].value_counts().head(15)
        counts.plot(kind="bar", ax=ax, color="#0094FF")
        ax.set_title(f"{req.column} — top values")
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right", color="#E0F4FF")
    elif ctype == "datetime":
        s = pd.to_datetime(df[req.column], errors="coerce").dropna()
        s.dt.to_period("M").value_counts().sort_index().plot(kind="line", ax=ax, color="#00E5FF")
        ax.set_title(f"{req.column} over time")
    else:
        plt.close(fig)
        raise HTTPException(
            400,
            f"Column '{req.column}' (type: {ctype}) isn't directly chartable — try a numeric, categorical, or datetime column.",
        )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    png_b64 = base64.b64encode(buf.read()).decode("ascii")
    return {"image": f"data:image/png;base64,{png_b64}"}
