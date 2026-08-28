"""Phase 5 native AI Analyst: compact, evidence-first analytical assistance.

The deterministic path is deliberately useful without a model credential. Optional Ollama is
server-side only and may enrich routing telemetry, but it never receives raw datasets or changes
the evidence/provenance contract.
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from prism_api_contracts import (
    AiAnalystOutcome,
    AiAnalystRequest,
    AiAnalystResponse,
    AiContextPacket,
    AiEvidence,
    AiProviderStatus,
)

from .overview import get_profile
from .overview import store as overview_store
from .sql_lab import store as sql_store
from .transport import ServerSentEvent, sse_response

router = APIRouter(prefix="/api/v1/ai-analyst", tags=["ai-analyst"])
PROMPT_VERSION = "ai-analyst/evidence-first-v1"
CONFIG_VERSION = "phase-5.1"
MAX_SAMPLE_ROWS = 12
MAX_CONTEXT_CHARS = 8_000
_runs: dict[str, threading.Event] = {}
_runs_lock = threading.RLock()


def _compact(value: str, limit: int = 480) -> str:
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _quoted_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _mentions_any(text: str, terms: tuple[str, ...]) -> bool:
    """Match analytical intent as complete words or phrases, not substrings."""
    return any(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE) for term in terms)


def _choose_dataset(dataset_id: Optional[str]) -> str:
    if dataset_id is not None:
        return dataset_id
    latest = overview_store.latest()
    if latest is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Load a dataset in native Overview before asking AI Analyst.",
        )
    return latest.dataset.dataset_id


def _sql_evidence(result_run_id: Optional[str], active_source_fingerprint: str) -> tuple[list[AiEvidence], Optional[str]]:
    if result_run_id is None:
        return [], None
    run = sql_store.get_run(result_run_id).response
    if run.provenance.source_fingerprint != active_source_fingerprint:
        return [AiEvidence(
            kind="limitation",
            label="SQL result",
            value="The selected SQL result belongs to a different dataset and was excluded from this analysis.",
            provenance_ref=result_run_id,
        )], None
    if run.state.value != "succeeded":
        return [AiEvidence(kind="limitation", label="SQL result", value="The selected SQL run did not succeed.", provenance_ref=result_run_id)], result_run_id
    fingerprint = run.provenance.result_fingerprint or "unavailable"
    value = f"{run.returned_row_count:,} returned rows; result fingerprint {fingerprint[:16]}."
    return [AiEvidence(kind="sql_result", label="SQL Lab result", value=value, provenance_ref=result_run_id)], result_run_id


def _draft_sql(question: str, columns: list[str]) -> str:
    requested = next((column for column in columns if re.search(rf"\b{re.escape(column)}\b", question, re.I)), None)
    if requested is not None and any(word in question.lower() for word in ("count", "group", "segment", "category")):
        quoted = _quoted_identifier(requested)
        return f"SELECT {quoted}, COUNT(*) AS row_count\nFROM \"data\"\nGROUP BY {quoted}\nORDER BY row_count DESC\nLIMIT 100;"
    return "SELECT COUNT(*) AS row_count\nFROM \"data\";"


def _try_ollama(context: AiContextPacket, question: str) -> bool:
    """Check a local optional provider without exposing it or falling back to cloud routing."""
    if os.environ.get("PRISM_AI_PROVIDER", "deterministic").lower() != "ollama":
        return False
    base_url = os.environ.get("PRISM_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.environ.get("PRISM_OLLAMA_MODEL", "llama3.2:3b")
    payload = {
        "model": model,
        "stream": False,
        "options": {"num_predict": 32, "temperature": 0},
        "prompt": (
            "Return READY only. This is a connectivity check for an evidence-first data analyst. "
            f"Dataset has {context.row_count} rows and {context.column_count} columns. Question: {_compact(question, 160)}"
        ),
    }
    try:
        timeout_seconds = float(os.environ.get("PRISM_OLLAMA_TIMEOUT_SECONDS", "45"))
        response = httpx.post(f"{base_url}/api/generate", json=payload, timeout=timeout_seconds)
        return response.is_success
    except httpx.HTTPError:
        return False


def analyze(request: AiAnalystRequest, request_id: Optional[str] = None) -> AiAnalystResponse:
    dataset_id = _choose_dataset(request.dataset_id)
    profile = get_profile(dataset_id)
    columns = [column.name for column in profile.columns]
    sql_evidence, selected_run = _sql_evidence(request.result_run_id, profile.provenance.source_fingerprint)
    context = AiContextPacket(
        dataset_id=dataset_id,
        source_fingerprint=profile.provenance.source_fingerprint,
        row_count=profile.quality.n_rows,
        column_count=profile.quality.n_cols,
        raw_sample_rows=0,
        token_budget=MAX_CONTEXT_CHARS,
        prompt_version=PROMPT_VERSION,
        config_version=CONFIG_VERSION,
        result_run_id=selected_run,
    )
    evidence = [
        AiEvidence(kind="dataset", label="Dataset", value=f"{profile.quality.n_rows:,} rows × {profile.quality.n_cols} columns", provenance_ref=dataset_id),
        AiEvidence(kind="quality", label="Data health", value=f"{profile.health.total}/100; {profile.quality.total_missing_pct:.2f}% missing cells", provenance_ref="overview-profile"),
    ]
    evidence.extend(AiEvidence(kind="column", label=column.name, value=f"{column.semantic_type}; {column.missing_pct:.2f}% missing; {column.unique_count:,} unique", provenance_ref="overview-profile") for column in profile.columns[:20])
    evidence.extend(sql_evidence)
    question = _compact(request.question, 4_000)
    lower = question.lower()
    causal = _mentions_any(lower, ("cause", "causal", "causes", "effect of", "impact of"))
    sql_intent = _mentions_any(lower, ("sql", "query", "count", "group", "segment", "total", "sum"))
    provider_requested = os.environ.get("PRISM_AI_PROVIDER", "deterministic").lower()
    ollama_ready = _try_ollama(context, question)
    provider = (
        AiProviderStatus.OLLAMA
        if ollama_ready
        else AiProviderStatus.FALLBACK
        if provider_requested == "ollama"
        else AiProviderStatus.DETERMINISTIC
    )
    provenance: dict[str, Any] = {
        "prompt_version": PROMPT_VERSION,
        "config_version": CONFIG_VERSION,
        "provider_requested": provider_requested,
        "provider_used": provider.value,
        "raw_dataset_sent": False,
        "raw_sample_rows": 0,
        "context_char_cap": MAX_CONTEXT_CHARS,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if causal:
        limitations = ["The available dataset is observational and contains no controlled comparison or causal design metadata."]
        evidence.append(AiEvidence(kind="limitation", label="Causal limit", value=limitations[0], provenance_ref="analysis-policy"))
        return AiAnalystResponse(
            request_id=request_id or f"ai_{uuid.uuid4().hex}", outcome=AiAnalystOutcome.INSUFFICIENT_EVIDENCE,
            answer="PRISM cannot claim that one variable caused another from this evidence alone.",
            uncertainty="Unknown is not no effect: the current evidence cannot estimate a causal effect.",
            limiting_factors=limitations,
            recommended_next_step="Define a treatment/control comparison or collect time-ordered confounders, then run a preregistered causal analysis.",
            evidence=evidence, context=context, provider=provider, provenance=provenance,
        )
    if sql_intent:
        draft = _draft_sql(question, columns)
        return AiAnalystResponse(
            request_id=request_id or f"ai_{uuid.uuid4().hex}", outcome=AiAnalystOutcome.SQL_READY,
            answer="I prepared a schema-grounded, read-only SQL draft. Review and edit it in SQL Lab before execution.",
            uncertainty="The draft is limited to the active dataset schema and has not been executed.",
            limiting_factors=["SQL Lab safety checks and runtime capabilities remain authoritative."],
            recommended_next_step="Open SQL Lab, inspect the draft, and run it through the native guarded runtime.",
            evidence=evidence, context=context, provider=provider, sql_draft=draft,
            sql_connection_id=f"local:{dataset_id}", provenance={**provenance, "sql_execution": "not_attempted"},
        )
    health = profile.health.total
    missing = profile.quality.total_missing_pct
    answer = f"The active dataset has {profile.quality.n_rows:,} rows, {profile.quality.n_cols} columns, and a health score of {health}/100."
    return AiAnalystResponse(
        request_id=request_id or f"ai_{uuid.uuid4().hex}", outcome=AiAnalystOutcome.ANSWERED,
        answer=answer,
        uncertainty=f"This summary describes the loaded data; it does not establish causation. Missingness is {missing:.2f}%.",
        limiting_factors=["Only compact schema and statistical summaries were used; full raw rows were not sent to a provider."],
        recommended_next_step="Inspect the highest-missingness column in Overview or ask for a guarded SQL breakdown.",
        evidence=evidence, context=context, provider=provider, provenance={**provenance, "result_run_id": selected_run},
    )


@router.post("/analyze", response_model=AiAnalystResponse)
def analyze_question(request: AiAnalystRequest) -> AiAnalystResponse:
    return analyze(request)


@router.post("/runs/{request_id}/cancel")
def cancel_run(request_id: str) -> dict[str, str]:
    with _runs_lock:
        cancelled = _runs.get(request_id)
        if cancelled is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI Analyst stream was not found.")
        cancelled.set()
    return {"request_id": request_id, "state": "cancellation_requested"}


@router.post("/stream")
async def stream_analysis(payload: AiAnalystRequest, http_request: Request):  # type: ignore[no-untyped-def]
    request_id = f"ai_{uuid.uuid4().hex}"
    cancelled = threading.Event()
    with _runs_lock:
        _runs[request_id] = cancelled

    async def events() -> AsyncIterator[str]:
        try:
            yield ServerSentEvent(event="atlas.state", id=request_id, data={"request_id": request_id, "state": "context_selecting"}).encode()
            await asyncio.sleep(0)
            if cancelled.is_set() or await http_request.is_disconnected():
                yield ServerSentEvent(event="atlas.cancelled", id=request_id, data={"request_id": request_id}).encode()
                return
            analysis_task = asyncio.create_task(asyncio.to_thread(analyze, payload, request_id=request_id))
            while not analysis_task.done():
                if cancelled.is_set() or await http_request.is_disconnected():
                    analysis_task.cancel()
                    yield ServerSentEvent(event="atlas.cancelled", id=request_id, data={"request_id": request_id}).encode()
                    return
                await asyncio.sleep(0.02)
            response = await analysis_task
            yield ServerSentEvent(event="atlas.state", id=request_id, data={"request_id": request_id, "state": "routing", "provider": response.provider.value}).encode()
            for token in response.answer.split(" "):
                if cancelled.is_set() or await http_request.is_disconnected():
                    yield ServerSentEvent(event="atlas.cancelled", id=request_id, data={"request_id": request_id}).encode()
                    return
                yield ServerSentEvent(event="atlas.token", id=request_id, data={"request_id": request_id, "token": f"{token} "}).encode()
                await asyncio.sleep(0)
            if response.outcome is AiAnalystOutcome.SQL_READY:
                yield ServerSentEvent(event="atlas.tool_wait", id=request_id, data={"request_id": request_id, "tool": "sql-lab", "state": "review_required"}).encode()
            yield ServerSentEvent(
                event="atlas.state",
                id=request_id,
                data={"request_id": request_id, "state": "verifying", "verification": "evidence_and_provenance"},
            ).encode()
            yield ServerSentEvent(event="atlas.complete", id=request_id, data=response.model_dump(mode="json")).encode()
        except HTTPException as error:
            yield ServerSentEvent(event="atlas.failure", id=request_id, data={"request_id": request_id, "detail": str(error.detail), "fallback": "none"}).encode()
        finally:
            with _runs_lock:
                _runs.pop(request_id, None)

    return sse_response(events())
