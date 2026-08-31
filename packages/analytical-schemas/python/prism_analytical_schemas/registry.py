"""Small process-local registry for immutable analytical-object history."""

from __future__ import annotations

from threading import RLock
from typing import Any, List, Optional

from .models import AnalyticalObject


class AnalyticalObjectRegistry:
    """Append-only in-process registry; DatasetStore remains revision authority.

    Objects are serialized and reconstructed at the boundary so a caller cannot
    mutate a returned nested payload and silently change historical provenance.
    """

    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []
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
            self._order.append(record.object_id)
            return self._restore(snapshot)

    def get(self, object_id: str) -> Optional[AnalyticalObject]:
        with self._lock:
            snapshot = self._records.get(object_id)
            return None if snapshot is None else self._restore(snapshot)

    def exists(self, object_id: str) -> bool:
        with self._lock:
            return object_id in self._records

    def list_for_dataset(self, dataset_id: str, revision: Optional[int] = None) -> List[AnalyticalObject]:
        with self._lock:
            return [
                self._restore(self._records[object_id])
                for object_id in self._order
                if self._records[object_id]["provenance"]["dataset"]["dataset_id"] == dataset_id
                and (revision is None or self._records[object_id]["provenance"]["dataset"]["revision"] == revision)
            ]
