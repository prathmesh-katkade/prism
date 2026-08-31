"""Small process-local registry for immutable analytical-object history.

Phase 8C adds deterministic graph traversal on top of the direct `parent_refs`
links Phase 8A/8B already record: a maintained reverse child index, direct
parent/child lookup, and BFS-based ancestor/descendant/shortest-path
traversal. None of this infers a relationship AI-side or builds anything
beyond the direct-parent graph already present - it only makes that graph
walkable.
"""

from __future__ import annotations

from threading import RLock
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from .models import AnalyticalObject, ObjectKind

_Direction = str  # "ancestors" | "descendants" - internal traversal direction tag


class TraversalResult(NamedTuple):
    """One BFS traversal outcome. ``nodes`` excludes the requested root; each entry
    is ``(object, depth)`` with depth = hop count (>= 1) from the root, in
    deterministic ``(depth ASC, object_id ASC)`` order. ``edges`` is the set of
    direct parent -> child edges the traversal actually crossed, deduplicated and
    sorted the same way. ``truncated`` is True only when a supplied ``max_depth``
    cut the walk off while further, unexplored neighbors remained.
    """

    nodes: List[Tuple[AnalyticalObject, int]]
    edges: List[Tuple[str, str]]
    truncated: bool


class PathResult(NamedTuple):
    """A shortest-path outcome between two objects that both exist in the registry.

    ``found=False`` (with empty ``nodes``/``edges``) means both objects exist but no
    path connects them - a legitimate outcome, distinct from either object being
    unknown (which callers detect from ``shortest_path`` returning ``None``).
    ``nodes`` excludes the start object and includes the end object, ordered along
    the path with depth = 1-based hop index.
    """

    nodes: List[Tuple[AnalyticalObject, int]]
    edges: List[Tuple[str, str]]
    found: bool


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
        self._child_index: Dict[str, List[str]] = {}
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
            # Reverse index: every parent_ref this object declares gets this object
            # appended as one of that parent's children - maintained here, at the one
            # place new objects (and therefore new edges) enter the registry, so a
            # child lookup is a dict lookup rather than a full-registry scan. This is
            # keyed purely by object id string; it does not require the parent to
            # already be registered (see `get_parents`/traversal for how an
            # unregistered parent - a partial-graph gap - is handled safely).
            for parent in record.provenance.parent_refs:
                self._child_index.setdefault(parent.object_id, []).append(record.object_id)
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

    # -- Phase 8C: direct relationships -----------------------------------------

    def get_parents(self, object_id: str) -> Optional[List[AnalyticalObject]]:
        """Direct parents only (never transitive). ``None`` means ``object_id`` itself
        is not registered - callers should surface that as a 404, distinct from a
        root object that legitimately has no parents (``[]``).

        A parent_ref pointing at an object_id the registry does not currently hold
        (a partial-graph gap - see module docstring) is skipped, never invented.
        """
        with self._lock:
            record = self._records.get(object_id)
            if record is None:
                return None
            parent_ids = self._parent_ids(object_id)
            return [self._restore(self._records[parent_id]) for parent_id in parent_ids]

    def get_children(self, object_id: str) -> Optional[List[AnalyticalObject]]:
        """Direct children only (never transitive). ``None`` means ``object_id`` itself
        is not registered; a leaf object with no dependents returns ``[]``.
        """
        with self._lock:
            if object_id not in self._records:
                return None
            child_ids = self._child_ids(object_id)
            return [self._restore(self._records[child_id]) for child_id in child_ids]

    def _parent_ids(self, object_id: str) -> List[str]:
        record = self._records.get(object_id)
        if record is None:
            return []
        raw_ids = [ref["object_id"] for ref in record["provenance"]["parent_refs"]]
        # de-duplicate while preserving first-seen order, then keep only ids the
        # registry actually holds (a partial-graph gap is skipped, not invented),
        # then sort for deterministic output.
        seen_ids = [object_id for object_id in dict.fromkeys(raw_ids) if object_id in self._records]
        return sorted(seen_ids)

    def _child_ids(self, object_id: str) -> List[str]:
        return sorted(dict.fromkeys(self._child_index.get(object_id, [])))

    def _neighbor_ids(self, object_id: str, direction: _Direction) -> List[str]:
        return self._parent_ids(object_id) if direction == "ancestors" else self._child_ids(object_id)

    # -- Phase 8C: transitive traversal ------------------------------------------

    def ancestors(self, object_id: str, max_depth: Optional[int] = None) -> Optional[TraversalResult]:
        """Transitive upstream traversal (what this object depends on, at any depth).

        ``None`` means ``object_id`` is not registered. BFS, cycle-safe via a
        visited/depth map, so a malformed cyclic parent chain still terminates.
        """
        return self._traverse(object_id, "ancestors", max_depth)

    def descendants(self, object_id: str, max_depth: Optional[int] = None) -> Optional[TraversalResult]:
        """Transitive downstream traversal (what depends on this object, at any depth).

        ``None`` means ``object_id`` is not registered. BFS, cycle-safe via a
        visited/depth map, so a malformed cyclic parent chain still terminates.
        """
        return self._traverse(object_id, "descendants", max_depth)

    def _traverse(self, object_id: str, direction: _Direction, max_depth: Optional[int]) -> Optional[TraversalResult]:
        with self._lock:
            if object_id not in self._records:
                return None
            depths: dict[str, int] = {object_id: 0}
            edges: set[Tuple[str, str]] = set()
            frontier = [object_id]
            depth = 0
            truncated = False
            while frontier:
                if max_depth is not None and depth >= max_depth:
                    # Stop here; note whether anything real was left unexplored so the
                    # caller can report a genuine truncation, not just "the graph ended".
                    truncated = any(self._neighbor_ids(current, direction) for current in frontier)
                    break
                next_frontier: List[str] = []
                for current in frontier:
                    for neighbor in self._neighbor_ids(current, direction):
                        edge = (neighbor, current) if direction == "ancestors" else (current, neighbor)
                        edges.add(edge)
                        if neighbor not in depths:
                            depths[neighbor] = depth + 1
                            next_frontier.append(neighbor)
                if not next_frontier:
                    break
                depth += 1
                frontier = sorted(set(next_frontier))
            ordered_ids = sorted((oid for oid in depths if oid != object_id), key=lambda oid: (depths[oid], oid))
            nodes = [(self._restore(self._records[oid]), depths[oid]) for oid in ordered_ids]
            return TraversalResult(nodes=nodes, edges=sorted(edges), truncated=truncated)

    # -- Phase 8C: shortest path --------------------------------------------------

    def _combined_neighbors(self, object_id: str) -> List[Tuple[str, str]]:
        """Every directly connected object regardless of direction, tagged with how it
        connects (``"parent"``/``"child"`` of ``object_id``) so a path can be
        reconstructed with correct edge orientation afterward."""
        parents = [(oid, "parent") for oid in self._parent_ids(object_id)]
        children = [(oid, "child") for oid in self._child_ids(object_id)]
        return sorted(parents + children, key=lambda item: item[0])

    def shortest_path(self, from_object_id: str, to_object_id: str) -> Optional[PathResult]:
        """Deterministic shortest path connecting two objects, direction-agnostic
        (either may be upstream or downstream of the other, or several hops via a
        shared ancestor). ``None`` means one or both object ids are not registered.
        """
        with self._lock:
            if from_object_id not in self._records or to_object_id not in self._records:
                return None
            if from_object_id == to_object_id:
                return PathResult(nodes=[], edges=[], found=True)
            visited = {from_object_id}
            predecessor: dict[str, Tuple[str, str]] = {}
            queue = [from_object_id]
            found = False
            while queue and not found:
                next_queue: List[str] = []
                for current in queue:
                    for neighbor_id, edge_type in self._combined_neighbors(current):
                        if neighbor_id in visited:
                            continue
                        visited.add(neighbor_id)
                        predecessor[neighbor_id] = (current, edge_type)
                        if neighbor_id == to_object_id:
                            found = True
                            break
                        next_queue.append(neighbor_id)
                    if found:
                        break
                queue = sorted(next_queue)
            if not found:
                return PathResult(nodes=[], edges=[], found=False)
            chain = [to_object_id]
            cursor = to_object_id
            while cursor != from_object_id:
                cursor = predecessor[cursor][0]
                chain.append(cursor)
            chain.reverse()
            nodes = [(self._restore(self._records[oid]), depth) for depth, oid in enumerate(chain[1:], start=1)]
            edges: List[Tuple[str, str]] = []
            for index in range(1, len(chain)):
                prev_id, current_id = chain[index - 1], chain[index]
                edge_type = predecessor[current_id][1]
                edges.append((prev_id, current_id) if edge_type == "child" else (current_id, prev_id))
            return PathResult(nodes=nodes, edges=edges, found=True)
