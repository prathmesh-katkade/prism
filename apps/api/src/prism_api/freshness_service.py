"""Phase 8D: contextual freshness/staleness assessment.

Freshness is never stored on an ``AnalyticalObject`` - historical evidence stays
immutable (object id, provenance, parameters, evidence, timestamp, and parent
links are never rewritten). Instead, every read recomputes freshness on the fly
by comparing an object's own recorded dataset identity against whatever
DatasetStore currently holds as active for that dataset_id - fully deterministic,
no propagation state to keep in sync, no risk of drift between the two stores.

"Propagation" (old revision -> its descendants -> now stale) needs no separate
graph walk of its own: every producer already pins the exact
(dataset_id, revision, source_fingerprint) identity it consumed into its own
``provenance.dataset`` (see Phase 8A/8B's ``_derived_from``), so a plain
per-object identity comparison already gives the same answer 8C's descendant
traversal would. The dataset-level endpoint below does still call
``registry.descendants()`` directly - to size the reason text on a superseded
dataset-revision object ("N objects still depend on this revision") - reusing
Phase 8C's own traversal rather than writing a second graph engine.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from fastapi import HTTPException
from prism_analytical_schemas import (
    AnalyticalObject,
    AnalyticalObjectRegistry,
    FreshnessAssessment,
    FreshnessState,
    ObjectKind,
)

from .overview import DatasetStore


def _active_identity(overview_store: DatasetStore, dataset_id: str) -> Tuple[Optional[int], Optional[str], bool]:
    """The dataset identity DatasetStore currently considers active for
    ``dataset_id``, or ``(None, None, False)`` if this process-local store no
    longer knows about it (partial history, e.g. after a restart) - never
    guessed, never fabricated."""
    try:
        stored = overview_store.get(dataset_id)
    except HTTPException:
        return None, None, False
    return stored.dataset.revision, stored.source_fingerprint, True


def _assess(record: AnalyticalObject, overview_store: DatasetStore, registry: AnalyticalObjectRegistry) -> FreshnessAssessment:
    ref = record.provenance.dataset
    active_revision, active_fingerprint, known = _active_identity(overview_store, ref.dataset_id)
    now = datetime.now(timezone.utc)
    if not known:
        return FreshnessAssessment(
            object_id=record.object_id,
            state=FreshnessState.UNKNOWN,
            freshness_known=False,
            dataset_id=ref.dataset_id,
            object_revision=ref.revision,
            object_fingerprint=ref.source_fingerprint,
            active_revision=None,
            active_fingerprint=None,
            reason_code="dataset_not_in_store",
            reason=(
                f"Dataset {ref.dataset_id!r} has no active identity in this process's DatasetStore "
                "(a restart resets in-memory history) - freshness cannot be determined, and is not "
                "guessed as current or stale."
            ),
            assessed_at=now,
        )
    matches_active = ref.revision == active_revision and ref.source_fingerprint == active_fingerprint
    if matches_active:
        return FreshnessAssessment(
            object_id=record.object_id,
            state=FreshnessState.CURRENT,
            freshness_known=True,
            dataset_id=ref.dataset_id,
            object_revision=ref.revision,
            object_fingerprint=ref.source_fingerprint,
            active_revision=active_revision,
            active_fingerprint=active_fingerprint,
            reason_code="matches_active_identity",
            reason="This is the exact dataset revision and content currently active for this dataset.",
            assessed_at=now,
        )
    if record.kind is ObjectKind.DATASET_REVISION:
        if ref.revision == active_revision:
            reason_code = "fingerprint_diverged_same_revision"
            reason = (
                f"Revision {ref.revision} was reused for different data after an undo/redo; the "
                "currently active data at this revision number is a different branch than this "
                "one recorded."
            )
        else:
            reason_code = "revision_superseded"
            # `record` was already fetched from this same registry, so it is guaranteed to exist -
            # this reuses Phase 8C's own descendant traversal rather than a second graph engine.
            descendants = registry.descendants(record.object_id)
            descendant_count = len(descendants.nodes) if descendants is not None else 0
            reason = (
                f"Revision {ref.revision} is no longer active; revision {active_revision} is. "
                f"{descendant_count} recorded object(s) still depend on this revision."
            )
        return FreshnessAssessment(
            object_id=record.object_id,
            state=FreshnessState.SUPERSEDED,
            freshness_known=True,
            dataset_id=ref.dataset_id,
            object_revision=ref.revision,
            object_fingerprint=ref.source_fingerprint,
            active_revision=active_revision,
            active_fingerprint=active_fingerprint,
            reason_code=reason_code,
            reason=reason,
            assessed_at=now,
        )
    return FreshnessAssessment(
        object_id=record.object_id,
        state=FreshnessState.STALE,
        freshness_known=True,
        dataset_id=ref.dataset_id,
        object_revision=ref.revision,
        object_fingerprint=ref.source_fingerprint,
        active_revision=active_revision,
        active_fingerprint=active_fingerprint,
        reason_code="upstream_revision_changed",
        reason=(
            f"This result was produced from revision {ref.revision}, which is no longer the active "
            f"dataset state (revision {active_revision} is now active). The result itself is unchanged "
            "and remains valid historical evidence."
        ),
        assessed_at=now,
    )


def assess_object(
    registry: AnalyticalObjectRegistry, overview_store: DatasetStore, object_id: str
) -> Optional[FreshnessAssessment]:
    """``None`` means ``object_id`` itself is not registered (caller -> 404)."""
    record = registry.get(object_id)
    if record is None:
        return None
    return _assess(record, overview_store, registry)


def assess_dataset(registry: AnalyticalObjectRegistry, overview_store: DatasetStore, dataset_id: str) -> List[FreshnessAssessment]:
    """Every registered object for ``dataset_id``, newest-first (the same order
    ``list_for_dataset`` already uses) - an empty list for a dataset with no
    registered objects, never a 404 (mirrors ``list_objects``'s own behavior)."""
    records = registry.list_for_dataset(dataset_id)
    return [_assess(record, overview_store, registry) for record in records]
