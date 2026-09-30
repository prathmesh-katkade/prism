"""Atlas's declared statistical work through the tested Stats Lab service."""

from __future__ import annotations

import multiprocessing
import time
from multiprocessing.connection import Connection
from typing import Callable

from fastapi import HTTPException
from prism_api_contracts import (
    AtlasStatAnalysis,
    StatSuggestionResponse,
    StatTestKind,
    StatTestRequest,
    StatTestResult,
)

from . import stats
from .overview import StoredDataset
from .overview import store as dataset_store

POLICY_VERSION = "atlas-declared-stat-v1"
MAX_ROWS = 10_000
MAX_INPUT_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 12.0
DESIGNS = {
    StatTestKind.TTEST: "independent_groups",
    StatTestKind.ANOVA: "one_way_groups",
    StatTestKind.PEARSON: "linear_association",
    StatTestKind.CHI2: "categorical_association",
}


def validate_analysis(dataset_id: str, analysis: AtlasStatAnalysis) -> StatSuggestionResponse:
    stored = dataset_store.get(dataset_id)
    if analysis.col_a == analysis.col_b:
        raise ValueError("Choose two distinct columns for a statistical test.")
    for name in (analysis.col_a, analysis.col_b):
        if name not in stored.frame.columns:
            raise ValueError(f"Column {name!r} is not in the active dataset schema.")
    if DESIGNS[analysis.test] != analysis.design:
        raise ValueError(f"{analysis.test.value} requires the {DESIGNS[analysis.test]} design declaration.")
    suggestion = stats.suggest_test(stored.frame, analysis.col_a, analysis.col_b)
    if suggestion.error or suggestion.test is not analysis.test:
        raise ValueError(suggestion.error or f"The declared {analysis.test.value} method does not match these column types and groups.")
    return suggestion


def _compute_in_worker(connection: Connection, stored: StoredDataset, request: StatTestRequest) -> None:
    """Only the tested Stats Lab calculation runs in the disposable worker."""
    try:
        connection.send(("succeeded", stats.compute_test(stored, request).model_dump(mode="json")))
    except HTTPException as error:
        connection.send(("failed", str(error.detail)))
    except BaseException:
        connection.send(("failed", "Statistical worker failed."))
    finally:
        connection.close()


def execute_declared_test(dataset_id: str, analysis: AtlasStatAnalysis,
                          cancelled: Callable[[], bool]) -> dict[str, object]:
    stored = dataset_store.get(dataset_id)
    before = stored.dataset
    suggestion = validate_analysis(dataset_id, analysis)
    request = StatTestRequest(
        test=analysis.test, col_a=analysis.col_a, col_b=analysis.col_b,
        numeric_col=suggestion.numeric_col, cat_col=suggestion.cat_col,
    )
    if len(stored.frame) > MAX_ROWS:
        raise ValueError(f"Statistical input exceeds the {MAX_ROWS:,}-row Atlas limit; narrow the dataset first.")
    selected = stored.frame[[analysis.col_a, analysis.col_b]].copy()
    if int(selected.memory_usage(deep=True).sum()) > MAX_INPUT_BYTES:
        raise ValueError("Statistical input exceeds the 8 MiB Atlas worker limit; narrow the dataset first.")
    if cancelled():
        raise RuntimeError("Statistical execution was cancelled before dispatch.")
    worker_stored = StoredDataset(before, selected, stored.source_fingerprint)
    context = multiprocessing.get_context("spawn")
    receiving, sending = context.Pipe(duplex=False)
    process = context.Process(target=_compute_in_worker, args=(sending, worker_stored, request), daemon=True)
    started = time.monotonic()
    process_started = False
    try:
        process.start()
        process_started = True
        sending.close()
        deadline = started + TIMEOUT_SECONDS
        while True:
            if cancelled():
                raise RuntimeError("Statistical execution was cancelled or disabled while active.")
            if receiving.poll(0.05):
                state, payload = receiving.recv()
                if state != "succeeded":
                    raise ValueError(str(payload))
                result = StatTestResult.model_validate(payload)
                break
            if not process.is_alive():
                raise RuntimeError("Statistical worker exited without a result.")
            if time.monotonic() >= deadline:
                raise TimeoutError("Statistical execution exceeded its 12 second limit.")
    finally:
        if process_started:
            if process.is_alive():
                process.terminate()
            process.join(timeout=1)
        receiving.close()
        sending.close()
    if cancelled():
        raise RuntimeError("Statistical execution was cancelled before evidence registration.")
    after = dataset_store.get(dataset_id).dataset
    if before.revision != after.revision or before.source_fingerprint != after.source_fingerprint:
        raise ValueError("Dataset revision changed during statistical execution; result is stale.")
    analytical_object = stats.register_statistical_test(stored, result)
    analyzed = result.n if result.n is not None else sum(result.groups.values())
    return {
        "execution_ref": analytical_object.object_id,
        "policy_version": POLICY_VERSION,
        "execution_state": "succeeded",
        "duration_ms": round((time.monotonic() - started) * 1000),
        "dataset_id": dataset_id,
        "dataset_revision": before.revision,
        "source_fingerprint": before.source_fingerprint,
        "method": analysis.test.value,
        "design": analysis.design,
        "col_a": analysis.col_a,
        "col_b": analysis.col_b,
        "input_rows": len(stored.frame),
        "analyzed_rows": analyzed,
        "excluded_rows": len(stored.frame) - analyzed,
        "result": result.model_dump(mode="json"),
        "limitations": ["Observational association does not establish causality.", *result.warnings],
    }
