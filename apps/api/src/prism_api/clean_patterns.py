"""Clean Pattern Review: deterministic, read-only discovery of format families and
compound-value structure within a column. See ADR 0025 for the boundaries this
module is built against.

Nothing here mutates data or claims correctness from frequency alone. A finding
reports "N of M examined rows matched family X" and nothing stronger; whether a
family is a legitimate convention is a decision the user records explicitly via
a PatternReviewDecision, never inferred by a detector.

No model dependency: PRISM_AI_PROVIDER is never consulted here.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Callable, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, status
from prism_api_contracts import (
    PatternDetectorKind,
    PatternExceptionPage,
    PatternExceptionPageRequest,
    PatternExceptionRow,
    PatternFamily,
    PatternFinding,
    PatternReviewDecision,
    PatternReviewDecisionKind,
    PatternReviewDecisionRequest,
    PatternScanRequest,
    PatternVerifyJobState,
    PatternVerifyJobStatus,
)

from .clean import _detect_ambiguous_dates, _require_column
from .durable_pattern_review_store import DurablePatternReviewStore
from .overview import store as overview_store
from .sql_jobs import QueryJob, QueryJobRuntime

router = APIRouter(prefix="/api/v1/clean", tags=["clean-patterns"])

# A bounded sample keeps discovery fast on a 100k-row column; this is a stated
# constant, not a silently-chosen number - see docs/clean-pattern-review-v1 for
# the measured timing this bound was picked against.
BOUNDED_SAMPLE_ROWS = 2000
MIN_FAMILY_SUPPORT = 2
MAX_FAMILIES = 6
MAX_EXCEPTION_EXAMPLES = 10
DETECTOR_VERSIONS: dict[PatternDetectorKind, int] = {
    PatternDetectorKind.IDENTIFIER_STRUCTURE: 1,
    PatternDetectorKind.NUMERIC_UNIT: 1,
    PatternDetectorKind.DELIMITED_COMPOUND: 1,
    PatternDetectorKind.DATE_AMBIGUITY: 1,
}

# Full-scan verification runs as a cancellable background job (see QueryJobRuntime,
# reused as-is from SQL Lab's job seam) instead of blocking the request thread.
# A detector's scan loop calls back into _checkpoint() every PROGRESS_CHECKPOINT_ROWS
# rows: that is where real, measured progress is recorded and where a cancellation
# actually takes effect - not a flag checked only after the full scan already
# finished. The checkpoint interval bounds how late a cancellation can land: at
# most PROGRESS_CHECKPOINT_ROWS rows of unnecessary work past the cancel request.
PROGRESS_CHECKPOINT_ROWS = 2000

# Test-only knob, read from the environment (like PRISM_REQUIRE_DURABLE_HISTORY
# elsewhere in this codebase) rather than exposed as an HTTP control - it can
# only be set at process startup, never toggled at runtime by any client. When
# non-zero, _checkpoint() sleeps this many milliseconds at every checkpoint, so
# a live test can deterministically land a cancel request inside an in-progress
# full scan instead of racing a sub-second completion. Unset (the production
# default) adds no delay anywhere.
def _test_checkpoint_delay_ms() -> int:
    return int(os.environ.get("PRISM_PATTERN_VERIFY_TEST_DELAY_MS", "0") or "0")


class _VerificationCancelled(Exception):
    """Raised from inside a detector's scan loop the moment cancellation is
    observed. Never escapes as an HTTP error - the job wrapper catches it and
    records state=cancelled, which verified=true can never follow."""


@dataclass
class _VerifyJobRecord:
    state: PatternVerifyJobState = PatternVerifyJobState.RUNNING
    rows_checked: int = 0
    rows_total: int = 0
    finding: PatternFinding | None = None
    error: str | None = None


_verify_runtime = QueryJobRuntime()
_verify_records: dict[str, _VerifyJobRecord] = {}
_verify_records_lock = Lock()

_LETTER_RUN = re.compile(r"[A-Za-z]+")
_DIGIT_RUN = re.compile(r"\d+")
_TOKEN_RUN = re.compile(r"[A-Za-z]+|\d+|[^A-Za-z0-9]+")
_NUMERIC_UNIT_PATTERN = re.compile(
    r"^\s*(?P<cmp><=|>=|<|>)?\s*(?P<sign>[+-])?(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z%°/]+)?\s*$"
)
_DELIMITER_CANDIDATES = [",", ";", "|", "/", ":", "-", "_"]


def _identifier_signature(value: str) -> str:
    """Canonicalize a value into a letter/digit-run token signature, e.g.
    "INV-000123" -> "L3-N6". Separator characters are kept literally; this is a
    detector-generated signature, never a client-supplied pattern."""
    tokens = []
    for match in _TOKEN_RUN.finditer(value):
        piece = match.group(0)
        if _LETTER_RUN.fullmatch(piece):
            tokens.append(f"L{len(piece)}")
        elif _DIGIT_RUN.fullmatch(piece):
            tokens.append(f"N{len(piece)}")
        else:
            tokens.append(piece)
    return "".join(tokens)


def _signature_label(signature: str) -> str:
    # The literal-run branch must stop before a position that starts a new L<digits>
    # or N<digits> run marker - otherwise it greedily swallows the marker letter
    # itself (e.g. "-N6" parsing as literal "-N" + stray "6" instead of literal "-"
    # followed by a 6-digit run).
    described = []
    for part in re.finditer(r"L(\d+)|N(\d+)|((?:(?!L\d)(?!N\d)[^\d])+)", signature):
        if part.group(1):
            described.append(f"{part.group(1)} letter{'s' if part.group(1) != '1' else ''}")
        elif part.group(2):
            described.append(f"{part.group(2)} digit{'s' if part.group(2) != '1' else ''}")
        else:
            described.append(f"{part.group(3)!r}")
    return ", ".join(described) if described else signature


NO_MATCH_SIGNATURE = "\x00NO_MATCH\x00"  # reserved: a value the detector's grammar does not describe at all


def _families_from_counts(counts: dict[str, int], examples: dict[str, list[str]], label_fn) -> tuple[list[PatternFamily], int, list[str]]:  # type: ignore[no-untyped-def]
    """Split signature counts into (families meeting minimum support, exception
    count, exception example values), ranked by count and capped at MAX_FAMILIES.
    NO_MATCH_SIGNATURE never becomes a family regardless of count - it means the
    detector's grammar could not describe the value at all, not a rare-but-real
    convention."""
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    families: list[PatternFamily] = []
    exception_count = 0
    exception_examples: list[str] = []
    for signature, count in ranked:
        if signature != NO_MATCH_SIGNATURE and count >= MIN_FAMILY_SUPPORT and len(families) < MAX_FAMILIES:
            families.append(PatternFamily(
                family_signature=signature, label=label_fn(signature),
                matching_count=count, example_values=examples.get(signature, [])[:5],
            ))
        else:
            exception_count += count
            if len(exception_examples) < MAX_EXCEPTION_EXAMPLES:
                exception_examples.extend(examples.get(signature, [])[:MAX_EXCEPTION_EXAMPLES - len(exception_examples)])
    return families, exception_count, exception_examples


def _checkpoint(position: int, cancel_check: "Callable[[], bool] | None", progress_cb: "Callable[[int], None] | None") -> None:
    """Called periodically (not every row - that would dominate the scan cost
    itself) from inside a detector's main scan loop. Raises _VerificationCancelled
    the moment a cancellation has been requested, so the caller unwinds without
    finishing the remaining rows - this is the "stops within a defined, tested
    bound" behavior, not a cosmetic flag checked only after the loop ends."""
    if position % PROGRESS_CHECKPOINT_ROWS != 0:
        return
    if progress_cb is not None:
        progress_cb(position)
    delay_ms = _test_checkpoint_delay_ms()
    if delay_ms:  # pragma: no cover - exercised only by the live cancellation test
        time.sleep(delay_ms / 1000)
    if cancel_check is not None and cancel_check():
        raise _VerificationCancelled()


def _collect_examples(series: pd.Series, signature_fn, cancel_check: "Callable[[], bool] | None" = None, progress_cb: "Callable[[int], None] | None" = None) -> tuple[dict[str, int], dict[str, list[str]], dict[str, list[str]]]:  # type: ignore[no-untyped-def]
    counts: dict[str, int] = {}
    examples: dict[str, list[str]] = {}
    source_rows: dict[str, list[str]] = {}
    for position, (index, value) in enumerate(series.items()):
        _checkpoint(position, cancel_check, progress_cb)
        text = str(value)
        signature = signature_fn(text) or NO_MATCH_SIGNATURE
        counts[signature] = counts.get(signature, 0) + 1
        examples.setdefault(signature, [])
        if len(examples[signature]) < 5:
            examples[signature].append(text)
        source_rows.setdefault(signature, [])
        if len(source_rows[signature]) < MAX_EXCEPTION_EXAMPLES:
            source_rows[signature].append(str(index))
    return counts, examples, source_rows


def _rows_with_exception_values(series: pd.Series, signature_fn, family_signatures: set[str],  # type: ignore[no-untyped-def]
                                cancel_check: "Callable[[], bool] | None", progress_cb: "Callable[[int], None] | None") -> tuple[list[str], list[str]]:
    values: list[str] = []
    rows: list[str] = []
    for position, (index, value) in enumerate(series.items()):
        _checkpoint(position, cancel_check, progress_cb)
        text = str(value)
        if (signature_fn(text) or NO_MATCH_SIGNATURE) in family_signatures:
            continue
        values.append(text)
        rows.append(str(index))
        if len(values) >= MAX_EXCEPTION_EXAMPLES:
            break
    return values, rows


def _detect_identifier_structure(series: pd.Series, cancel_check: "Callable[[], bool] | None" = None, progress_cb: "Callable[[int], None] | None" = None) -> tuple[list[PatternFamily], int, list[str], list[str]]:
    counts, examples, _source_rows = _collect_examples(series, _identifier_signature, cancel_check, progress_cb)
    families, exception_count, _exception_examples = _families_from_counts(counts, examples, _signature_label)
    family_signatures = {family.family_signature for family in families}
    values, rows = _rows_with_exception_values(series, _identifier_signature, family_signatures, cancel_check, progress_cb)
    return families, exception_count, values, rows


def _numeric_unit_signature(text: str) -> Optional[str]:
    match = _NUMERIC_UNIT_PATTERN.match(text)
    if not match:
        return None
    unit = match.group("unit") or "none"
    prefix = "limit:" if match.group("cmp") else ""
    return f"{prefix}unit:{unit}"


def _numeric_unit_label(signature: str) -> str:
    limit = signature.startswith("limit:")
    unit = signature.split("unit:", 1)[1]
    base = "a detection-limit value" if limit else "a plain value"
    return f"{base} with unit {unit!r}" if unit != "none" else f"{base} with no unit"


def _detect_numeric_unit(series: pd.Series, cancel_check: "Callable[[], bool] | None" = None, progress_cb: "Callable[[int], None] | None" = None) -> tuple[list[PatternFamily], int, list[str], list[str]]:
    counts, examples, _source_rows = _collect_examples(series, _numeric_unit_signature, cancel_check, progress_cb)
    families, exception_count, _exception_examples = _families_from_counts(counts, examples, _numeric_unit_label)
    family_signatures = {family.family_signature for family in families}
    values, rows = _rows_with_exception_values(series, _numeric_unit_signature, family_signatures, cancel_check, progress_cb)
    return families, exception_count, values, rows


def _detect_delimited_compound(series: pd.Series, cancel_check: "Callable[[], bool] | None" = None, progress_cb: "Callable[[int], None] | None" = None) -> tuple[list[PatternFamily], int, list[str], list[str]]:
    non_null = [str(value) for value in series.dropna()]
    best: tuple[str, dict[int, int], dict[int, list[str]]] | None = None
    best_coverage = 0
    for delimiter in _DELIMITER_CANDIDATES:
        part_counts: dict[int, int] = {}
        part_examples: dict[int, list[str]] = {}
        for position, text in enumerate(non_null):
            _checkpoint(position, cancel_check, progress_cb)
            if delimiter not in text:
                continue
            n_parts = len(text.split(delimiter))
            part_counts[n_parts] = part_counts.get(n_parts, 0) + 1
            part_examples.setdefault(n_parts, [])
            if len(part_examples[n_parts]) < 5:
                part_examples[n_parts].append(text)
        if not part_counts:
            continue
        dominant_count = max(part_counts.values())
        if dominant_count > best_coverage:
            best_coverage = dominant_count
            best = (delimiter, part_counts, part_examples)
    if best is None or best_coverage < max(MIN_FAMILY_SUPPORT, len(non_null) * 0.5):
        return [], 0, [], []
    delimiter, part_counts, part_examples = best
    counts = {f"delim:{delimiter}:parts:{n}": count for n, count in part_counts.items()}
    examples = {f"delim:{delimiter}:parts:{n}": values for n, values in part_examples.items()}
    families, exception_count, exception_examples = _families_from_counts(
        counts, examples, lambda sig: f"split on {delimiter!r} into {sig.rsplit(':', 1)[1]} parts")
    return families, exception_count, exception_examples, []


def _detect_date_ambiguity(series: pd.Series, cancel_check: "Callable[[], bool] | None" = None, progress_cb: "Callable[[int], None] | None" = None) -> tuple[list[PatternFamily], int, list[str], list[str]]:
    # date_ambiguity delegates to clean.py's shared, already-vectorized date
    # parser rather than a per-row Python loop, so it has no internal checkpoint
    # to interrupt mid-call - a bounded, documented scope decision (not a gap
    # discovered after the fact), consistent with this being the one detector
    # the 100k measurements never used to justify the synchronous design it is
    # replacing. Cancellation still takes effect at the checkpoint immediately
    # before and after the call.
    if cancel_check is not None and cancel_check():
        raise _VerificationCancelled()
    if progress_cb is not None:
        progress_cb(0)
    ambiguous_values = _detect_ambiguous_dates(series)
    if cancel_check is not None and cancel_check():
        raise _VerificationCancelled()
    if progress_cb is not None:
        progress_cb(len(series))
    if not ambiguous_values:
        return [], 0, [], []
    ambiguous_set = set(ambiguous_values)
    unambiguous_count = 0
    for value in series.dropna().unique():
        if str(value) not in ambiguous_set:
            unambiguous_count += 1
    families = [PatternFamily(
        family_signature="ambiguous_day_month", label="day/month order cannot be inferred from the value alone",
        matching_count=len(ambiguous_values), example_values=ambiguous_values[:5],
    )]
    return families, 0, [], []


_DETECTORS = {
    PatternDetectorKind.IDENTIFIER_STRUCTURE: _detect_identifier_structure,
    PatternDetectorKind.NUMERIC_UNIT: _detect_numeric_unit,
    PatternDetectorKind.DELIMITED_COMPOUND: _detect_delimited_compound,
    PatternDetectorKind.DATE_AMBIGUITY: _detect_date_ambiguity,
}


def _applicable_detectors(series: pd.Series) -> list[PatternDetectorKind]:
    """Which detectors are worth running on this column at all - avoids wasting a
    scan slot on an obviously-inapplicable detector (e.g. numeric-unit on a column
    that is already purely numeric, or identifier-structure on free text)."""
    non_null = series.dropna()
    if non_null.empty:
        return []
    sample_text = non_null.astype(str)
    applicable = []
    if sample_text.str.contains(r"[A-Za-z].*\d|\d.*[A-Za-z]", regex=True).mean() > 0.3:
        applicable.append(PatternDetectorKind.IDENTIFIER_STRUCTURE)
    if sample_text.str.match(_NUMERIC_UNIT_PATTERN).mean() > 0.3:
        applicable.append(PatternDetectorKind.NUMERIC_UNIT)
    if any(delimiter in value for value in sample_text.head(50) for delimiter in _DELIMITER_CANDIDATES):
        applicable.append(PatternDetectorKind.DELIMITED_COMPOUND)
    if _detect_ambiguous_dates(non_null):
        applicable.append(PatternDetectorKind.DATE_AMBIGUITY)
    return applicable


def _run_detector(dataset_id: str, frame: pd.DataFrame, column: str, detector_kind: PatternDetectorKind,
                  source_revision: int, source_fingerprint: str, full_scan: bool,
                  group_by_column: str | None = None, group_value: str | None = None,
                  cancel_check: "Callable[[], bool] | None" = None, progress_cb: "Callable[[int], None] | None" = None) -> PatternFinding:
    series = frame[column]
    total_rows = len(series)
    if full_scan:
        examined = series
    else:
        examined = series.head(BOUNDED_SAMPLE_ROWS)
    missing_count = int(examined.isna().sum())
    non_null = examined.dropna()
    detector_fn = _DETECTORS[detector_kind]
    families, exception_count, exception_examples, exception_source_rows = detector_fn(non_null, cancel_check, progress_cb)
    nonmatching_count = len(examined) - missing_count - sum(family.matching_count for family in families) - exception_count
    insufficient_evidence = len(non_null) < MIN_FAMILY_SUPPORT or (not families and exception_count == 0 and detector_kind != PatternDetectorKind.DATE_AMBIGUITY)
    return PatternFinding(
        finding_id=f"pattern_{uuid.uuid4().hex}", dataset_id=dataset_id, column=column,
        detector_kind=detector_kind, detector_version=DETECTOR_VERSIONS[detector_kind],
        source_revision=source_revision, source_fingerprint=source_fingerprint,
        rows_examined=len(examined), total_rows=total_rows,
        sampling_method="full_scan" if full_scan else "bounded_sample",
        verified=full_scan and len(examined) == total_rows,
        families=families, missing_count=missing_count, exception_count=exception_count,
        nonmatching_count=nonmatching_count,
        exception_examples=exception_examples, exception_source_rows=exception_source_rows,
        group_by_column=group_by_column, group_value=group_value,
        insufficient_evidence=insufficient_evidence, created_at=datetime.now(timezone.utc),
    )


def _scoped_frame(frame: pd.DataFrame, group_by_column: str | None, group_value: str | None) -> pd.DataFrame:
    if group_by_column is None:
        return frame
    _require_column(frame, group_by_column)
    if group_value is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="group_value is required when group_by_column is set.")
    return frame.loc[frame[group_by_column].astype(str) == group_value]


decisions = DurablePatternReviewStore()


def _passively_hidden_keys(dataset_id: str, source_revision: int, source_fingerprint: str) -> set[tuple[str, PatternDetectorKind | None]]:
    """(column, detector_kind) pairs the ranked shortlist should not surface passively.

    A suppressed rule stays hidden across revisions until explicitly revoked - that
    is the entire point of "suppress" versus "ignore": ignoring is scoped to the
    exact revision/fingerprint it was decided against (ADR 0025's "a revision-only
    ignore must not silently carry into a new upload"), suppressing is not. Neither
    ever hides a column from the deliberate column-explorer scan - only the passive
    ranked list.
    """
    hidden: set[tuple[str, PatternDetectorKind | None]] = set()
    for decision in decisions.list_for_dataset(dataset_id):
        if decision.revoked:
            continue
        if decision.revokes_decision_id:
            # A revoking decision's purpose is to cancel the one it references,
            # not to independently hide anything itself - otherwise "revoke" (which
            # the UI currently carries as an ignore_revision/accept_family record)
            # would re-hide the very finding it just restored.
            continue
        if decision.decision is PatternReviewDecisionKind.SUPPRESS_RULE:
            hidden.add((decision.column, decision.detector_kind))
        elif decision.decision is PatternReviewDecisionKind.IGNORE_REVISION:
            if decision.source_revision == source_revision and decision.source_fingerprint == source_fingerprint:
                hidden.add((decision.column, decision.detector_kind))
    return hidden


@router.post("/datasets/{dataset_id}/patterns/discover", response_model=list[PatternFinding])
def discover_patterns(dataset_id: str) -> list[PatternFinding]:
    """Dataset-wide bounded scan: the ranked shortlist. Runs every applicable
    detector against every column's bounded sample and returns every non-trivial
    finding, ranked by how much evidence it carries (largest non-exception family
    first). A finding the analyst suppressed or ignored for this exact revision is
    left out of this passive list - it stays reachable through the column explorer
    (/patterns/columns/{column}/scan), which never filters."""
    stored = overview_store.get(dataset_id)
    hidden = _passively_hidden_keys(dataset_id, stored.dataset.revision, stored.source_fingerprint)
    findings: list[PatternFinding] = []
    for column in stored.frame.columns:
        series = stored.frame[column].head(BOUNDED_SAMPLE_ROWS)
        for detector_kind in _applicable_detectors(series):
            if (column, detector_kind) in hidden or (column, None) in hidden:
                continue
            finding = _run_detector(dataset_id, stored.frame, column, detector_kind,
                                    stored.dataset.revision, stored.source_fingerprint, full_scan=False)
            if finding.families or finding.exception_count:
                findings.append(finding)
    findings.sort(key=lambda f: max((family.matching_count for family in f.families), default=0), reverse=True)
    return findings


@router.post("/datasets/{dataset_id}/patterns/columns/{column}/scan", response_model=list[PatternFinding])
def scan_column(dataset_id: str, column: str, request: PatternScanRequest) -> list[PatternFinding]:
    """Column explorer: bounded scan for deliberate investigation of one column,
    optionally scoped to a user-chosen group. Runs every applicable detector
    unless the caller already knows which one it wants."""
    stored = overview_store.get(dataset_id)
    _require_column(stored.frame, column)
    scoped = _scoped_frame(stored.frame, request.group_by_column, request.group_value)
    kinds = [request.detector_kind] if request.detector_kind else _applicable_detectors(scoped[column])
    return [
        _run_detector(dataset_id, scoped, column, kind, stored.dataset.revision, stored.source_fingerprint,
                     full_scan=False, group_by_column=request.group_by_column, group_value=request.group_value)
        for kind in kinds
    ]


@router.post("/datasets/{dataset_id}/patterns/columns/{column}/verify", response_model=PatternFinding)
def verify_column(dataset_id: str, column: str, request: PatternScanRequest) -> PatternFinding:
    """Full-dataset verification for one detector on one column, run to completion
    on the request thread. This remains for direct/programmatic callers (and the
    existing test suite) that want the result in one call with no polling. The
    UI itself calls the cancellable job endpoints below instead, since this form
    offers no way to stop a scan already in flight."""
    if request.detector_kind is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="detector_kind is required to verify.")
    stored = overview_store.get(dataset_id)
    _require_column(stored.frame, column)
    scoped = _scoped_frame(stored.frame, request.group_by_column, request.group_value)
    return _run_detector(dataset_id, scoped, column, request.detector_kind, stored.dataset.revision,
                         stored.source_fingerprint, full_scan=True,
                         group_by_column=request.group_by_column, group_value=request.group_value)


def _verify_job_status(job_id: str) -> PatternVerifyJobStatus:
    with _verify_records_lock:
        record = _verify_records.get(job_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such verification job (the server may have restarted since it ran).")
    return PatternVerifyJobStatus(job_id=job_id, state=record.state, rows_checked=record.rows_checked,
                                  rows_total=record.rows_total, finding=record.finding, error=record.error)


@router.post("/datasets/{dataset_id}/patterns/columns/{column}/verify/start", response_model=PatternVerifyJobStatus, status_code=status.HTTP_202_ACCEPTED)
def start_verify_job(dataset_id: str, column: str, request: PatternScanRequest) -> PatternVerifyJobStatus:
    """Start full-dataset verification as a cancellable background job instead
    of blocking the request thread. Reuses QueryJobRuntime (SQL Lab's existing
    interruptible-job seam) rather than inventing a second one. The scan itself
    is cooperative: it checks for cancellation roughly every PROGRESS_CHECKPOINT_ROWS
    rows (see _checkpoint) and stops there, not merely once the full scan ends."""
    if request.detector_kind is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="detector_kind is required to verify.")
    stored = overview_store.get(dataset_id)
    _require_column(stored.frame, column)
    scoped = _scoped_frame(stored.frame, request.group_by_column, request.group_value)
    total_rows = len(scoped[column])
    job_id = f"patternverify_{uuid.uuid4().hex}"
    record = _VerifyJobRecord(rows_total=total_rows)
    with _verify_records_lock:
        _verify_records[job_id] = record
    detector_kind, source_revision, source_fingerprint = request.detector_kind, stored.dataset.revision, stored.source_fingerprint
    group_by_column, group_value = request.group_by_column, request.group_value

    def work(job: QueryJob) -> None:
        def progress_cb(position: int) -> None:
            with _verify_records_lock:
                record.rows_checked = position
        try:
            finding = _run_detector(dataset_id, scoped, column, detector_kind, source_revision, source_fingerprint,
                                    full_scan=True, group_by_column=group_by_column, group_value=group_value,
                                    cancel_check=job.cancelled.is_set, progress_cb=progress_cb)
        except _VerificationCancelled:
            with _verify_records_lock:
                record.state = PatternVerifyJobState.CANCELLED
            return
        except Exception as error:  # noqa: BLE001 - reported through the job status, not raised in a background thread
            with _verify_records_lock:
                record.state, record.error = PatternVerifyJobState.FAILED, str(error)
            return
        with _verify_records_lock:
            # A cancellation requested after the scan's own last checkpoint but
            # before this line must still never be reported as a successful
            # verification - verified=true can only ever follow an uninterrupted
            # scan, so this is checked again right here, not assumed.
            if job.cancelled.is_set():
                record.state = PatternVerifyJobState.CANCELLED
            else:
                record.state, record.finding, record.rows_checked = PatternVerifyJobState.SUCCEEDED, finding, record.rows_total

    _verify_runtime.start(job_id, timeout_ms=120_000, work=work)
    return _verify_job_status(job_id)


@router.get("/datasets/{dataset_id}/patterns/columns/{column}/verify/jobs/{job_id}", response_model=PatternVerifyJobStatus)
def get_verify_job(dataset_id: str, column: str, job_id: str) -> PatternVerifyJobStatus:
    """Poll a verification job's real, current progress and state."""
    return _verify_job_status(job_id)


@router.post("/datasets/{dataset_id}/patterns/columns/{column}/verify/jobs/{job_id}/cancel", response_model=PatternVerifyJobStatus)
def cancel_verify_job(dataset_id: str, column: str, job_id: str) -> PatternVerifyJobStatus:
    """Request cancellation. Returns immediately; the job transitions to
    state=cancelled once its scan loop reaches its next checkpoint, which the
    caller observes by polling the job status - this endpoint does not itself
    block until that happens."""
    with _verify_records_lock:
        already_done = job_id in _verify_records and _verify_records[job_id].state != PatternVerifyJobState.RUNNING
    if not already_done:
        _verify_runtime.cancel(job_id)
    return _verify_job_status(job_id)


@router.post("/datasets/{dataset_id}/patterns/columns/{column}/exceptions", response_model=PatternExceptionPage)
def exception_page(dataset_id: str, column: str, request: PatternExceptionPageRequest) -> PatternExceptionPage:
    """Page through actual source rows on explicit request, against the exact
    reviewed revision. No exception values are persisted or silently rescanned
    during a UI render. The response size remains bounded at 100 rows."""
    stored = overview_store.get(dataset_id)
    _require_column(stored.frame, column)
    if (request.reviewed_source_revision != stored.dataset.revision
            or request.reviewed_source_fingerprint != stored.source_fingerprint):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="The dataset changed since this finding was reviewed; scan it again.")
    scoped = _scoped_frame(stored.frame, request.group_by_column, request.group_value)
    finding = _run_detector(dataset_id, scoped, column, request.detector_kind,
                            stored.dataset.revision, stored.source_fingerprint,
                            full_scan=request.verified,
                            group_by_column=request.group_by_column, group_value=request.group_value)
    series = scoped[column] if request.verified else scoped[column].head(BOUNDED_SAMPLE_ROWS)
    family_signatures = {family.family_signature for family in finding.families}
    delimiter = None
    if request.detector_kind is PatternDetectorKind.DELIMITED_COMPOUND and finding.families:
        delimiter = finding.families[0].family_signature[len("delim:")]
    rows: list[PatternExceptionRow] = []
    total = 0
    for index, value in series.dropna().items():
        value_text = str(value)
        if request.detector_kind is PatternDetectorKind.IDENTIFIER_STRUCTURE:
            signature = _identifier_signature(value_text) or NO_MATCH_SIGNATURE
        elif request.detector_kind is PatternDetectorKind.NUMERIC_UNIT:
            signature = _numeric_unit_signature(value_text) or NO_MATCH_SIGNATURE
        elif delimiter and delimiter in value_text:
            signature = f"delim:{delimiter}:parts:{len(value_text.split(delimiter))}"
        else:
            continue
        if signature in family_signatures:
            continue
        if request.offset <= total < request.offset + request.limit:
            rows.append(PatternExceptionRow(source_row=str(index), value=value_text))
        total += 1
    return PatternExceptionPage(total=total, offset=request.offset, limit=request.limit, rows=rows)


@router.post("/datasets/{dataset_id}/patterns/decisions", response_model=PatternReviewDecision, status_code=status.HTTP_201_CREATED)
def create_decision(dataset_id: str, request: PatternReviewDecisionRequest) -> PatternReviewDecision:
    stored = overview_store.get(dataset_id)
    _require_column(stored.frame, request.column)
    if request.decision is PatternReviewDecisionKind.ACCEPT_FAMILY and not request.family_signatures:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Accepting a family requires at least one family_signature.")
    if request.reviewed_source_revision is None or request.reviewed_source_fingerprint is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="reviewed_source_revision and reviewed_source_fingerprint are required: a decision must say which finding it is about.")
    if request.reviewed_source_revision != stored.dataset.revision or request.reviewed_source_fingerprint != stored.source_fingerprint:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="The dataset changed since this finding was computed; re-run discovery and review the current evidence before deciding.")
    if request.revokes_decision_id:
        target = decisions.get(request.revokes_decision_id)
        if target is None or target.dataset_id != dataset_id or target.column != request.column:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail="revokes_decision_id must reference an existing decision on the same dataset and column.")
    detector_version = request.detector_version
    if detector_version is None and request.detector_kind is not None:
        detector_version = DETECTOR_VERSIONS[request.detector_kind]
    request = request.model_copy(update={"detector_version": detector_version})
    return decisions.create(dataset_id, request, stored.dataset.revision, stored.source_fingerprint)


@router.get("/datasets/{dataset_id}/patterns/decisions", response_model=list[PatternReviewDecision])
def list_decisions(dataset_id: str) -> list[PatternReviewDecision]:
    return decisions.list_for_dataset(dataset_id)
