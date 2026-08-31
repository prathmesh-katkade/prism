"""Small process-local registry for immutable analytical-object history."""

from __future__ import annotations

from threading import RLock
from typing import Any, List, Optional

from .models import AnalyticalObject, ObjectKind


class AnalyticalObjectRegistry:
    """Append-only in-process registry; DatasetStore remains revision authority.

    Objects are serialized and reconstructed at the boundary so a caller cannot
    mutate a returned nested payload and silently change historical provenance.
    """

    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._dataset_index: dict[str, list[str]] = {}
        self._revision_index: dict[tuple[str, int], list[str]] = {}
        self._kind_index: dict[ObjectKind, list[str]] = {}
        self._lock = RLock()

    @staticmethod
    def _snapshot(record: AnalyticalObject) -> dict[str, Any]:
        return record.model_dump(mode="json")

    @staticmethod
    def _restore(snapshot: dict[str, Any]) -> AnalyticalObject:
        return AnalyticalObject.model_validate(snapshot)

    def register(self, record: AnalyticalObject) -> AnalyticalObject:
        """Append one record, rejecting duplicate identities and self-parenting."""
        if any(parent.object_id == record.object_id for parent in record.provenance.parent_refs):
            raise ValueError("An analytical object cannot reference itself as a parent.")
        with self._lock:
            if record.object_id in self._records:
                raise ValueError(f"Analytical object {record.object_id!r} is already registered.")
            snapshot = self._snapshot(record)
            self._records[record.object_id] = snapshot
            dataset = record.provenance.dataset
            self._dataset_index.setdefault(dataset.dataset_id, []).append(record.object_id)
            self._revision_index.setdefault((dataset.dataset_id, dataset.revision), []).append(record.object_id)
            self._kind_index.setdefault(record.kind, []).append(record.object_id)
            return self._restore(snapshot)

    def get(self, object_id: str) -> Optional[AnalyticalObject]:
        with self._lock:
            snapshot = self._records.get(object_id)
            return None if snapshot is None else self._restore(snapshot)

    def exists(self, object_id: str) -> bool:
        with self._lock:
            return object_id in self._records

    def list_for_dataset(
        self,
        dataset_id: str,
        revision: Optional[int] = None,
        kind: Optional[ObjectKind] = None,
    ) -> List[AnalyticalObject]:
        """Return immutable snapshots in deterministic newest-first order."""
        with self._lock:
            candidate_ids = self._dataset_index.get(dataset_id, []) if revision is None else self._revision_index.get((dataset_id, revision), [])
            if kind is not None:
                allowed = set(self._kind_index.get(kind, []))
                candidate_ids = [object_id for object_id in candidate_ids if object_id in allowed]
            snapshots = [self._records[object_id] for object_id in candidate_ids]
            snapshots.sort(key=lambda item: (item["provenance"]["created_at"], item["object_id"]), reverse=True)
            return [self._restore(snapshot) for snapshot in snapshots]
