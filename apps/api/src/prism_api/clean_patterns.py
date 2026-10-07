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

import re
import uuid
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, status
from prism_api_contracts import (
    PatternDetectorKind,
    PatternFamily,
    PatternFinding,
    PatternReviewDecision,
    PatternReviewDecisionKind,
    PatternReviewDecisionRequest,
    PatternScanRequest,
)

from .clean import _detect_ambiguous_dates, _require_column
from .durable_pattern_review_store import DurablePatternReviewStore
from .overview import store as overview_store

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


def _collect_examples(series: pd.Series, signature_fn) -> tuple[dict[str, int], dict[str, list[str]], dict[str, list[str]]]:  # type: ignore[no-untyped-def]
    counts: dict[str, int] = {}
    examples: dict[str, list[str]] = {}
    source_rows: dict[str, list[str]] = {}
    for index, value in series.items():
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


def _detect_identifier_structure(series: pd.Series) -> tuple[list[PatternFamily], int, list[str], list[str]]:
    counts, examples, source_rows = _collect_examples(series, _identifier_signature)
    families, exception_count, exception_examples = _families_from_counts(counts, examples, _signature_label)
    exception_source_rows: list[str] = []
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    family_signatures = {family.family_signature for family in families}
    for signature, _count in ranked:
        if signature not in family_signatures:
            exception_source_rows.extend(source_rows.get(signature, []))
            if len(exception_source_rows) >= MAX_EXCEPTION_EXAMPLES:
                break
    return families, exception_count, exception_examples, exception_source_rows[:MAX_EXCEPTION_EXAMPLES]


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


def _detect_numeric_unit(series: pd.Series) -> tuple[list[PatternFamily], int, list[str], list[str]]:
    counts, examples, source_rows = _collect_examples(series, _numeric_unit_signature)
    families, exception_count, exception_examples = _families_from_counts(counts, examples, _numeric_unit_label)
    exception_source_rows: list[str] = []
    family_signatures = {family.family_signature for family in families}
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    for signature, _count in ranked:
        if signature not in family_signatures:
            exception_source_rows.extend(source_rows.get(signature, []))
    return families, exception_count, exception_examples, exception_source_rows[:MAX_EXCEPTION_EXAMPLES]


def _detect_delimited_compound(series: pd.Series) -> tuple[list[PatternFamily], int, list[str], list[str]]:
    non_null = [str(value) for value in series.dropna()]
    best: tuple[str, dict[int, int], dict[int, list[str]]] | None = None
    best_coverage = 0
    for delimiter in _DELIMITER_CANDIDATES:
        part_counts: dict[int, int] = {}
        part_examples: dict[int, list[str]] = {}
        for text in non_null:
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


def _detect_date_ambiguity(series: pd.Series) -> tuple[list[PatternFamily], int, list[str], list[str]]:
    ambiguous_values = _detect_ambiguous_dates(series)
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
                  group_by_column: str | None = None, group_value: str | None = None) -> PatternFinding:
    series = frame[column]
    total_rows = len(series)
    if full_scan:
        examined = series
    else:
        examined = series.head(BOUNDED_SAMPLE_ROWS)
    missing_count = int(examined.isna().sum())
    non_null = examined.dropna()
    detector_fn = _DETECTORS[detector_kind]
    families, exception_count, exception_examples, exception_source_rows = detector_fn(non_null)
    insufficient_evidence = len(non_null) < MIN_FAMILY_SUPPORT or (not families and exception_count == 0 and detector_kind != PatternDetectorKind.DATE_AMBIGUITY)
    return PatternFinding(
        finding_id=f"pattern_{uuid.uuid4().hex}", dataset_id=dataset_id, column=column,
        detector_kind=detector_kind, detector_version=DETECTOR_VERSIONS[detector_kind],
        source_revision=source_revision, source_fingerprint=source_fingerprint,
        rows_examined=len(examined), total_rows=total_rows,
        sampling_method="full_scan" if full_scan else "bounded_sample",
        verified=full_scan and len(examined) == total_rows,
        families=families, missing_count=missing_count, exception_count=exception_count,
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
    """Full-dataset verification for one detector on one column. Deterministic
    vectorized/row-wise computation over the full frame - no background job
    infrastructure: see docs/clean-pattern-review-v1/performance.md for the
    measured full-scan timing this synchronous design was checked against."""
    if request.detector_kind is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="detector_kind is required to verify.")
    stored = overview_store.get(dataset_id)
    _require_column(stored.frame, column)
    scoped = _scoped_frame(stored.frame, request.group_by_column, request.group_value)
    return _run_detector(dataset_id, scoped, column, request.detector_kind, stored.dataset.revision,
                         stored.source_fingerprint, full_scan=True,
                         group_by_column=request.group_by_column, group_value=request.group_value)


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
