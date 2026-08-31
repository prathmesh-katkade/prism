"""Phase 8C: composes registry traversal primitives into typed lineage responses.

Pure composition over ``AnalyticalObjectRegistry`` - no FastAPI/HTTP concerns here,
so it stays unit-testable on its own and keeps ``lineage.py``'s routes a thin
HTTP-shape wrapper (404 translation, query-param validation) around it. Each
function returns ``None`` exactly when the requested root object (or, for a path,
either endpoint) is not registered, mirroring the registry's own ``None`` convention.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from prism_analytical_schemas import (
    AnalyticalObject,
    AnalyticalObjectRegistry,
    LineageDirection,
    LineageEdge,
    LineageNode,
    LineagePath,
    LineageTraversal,
)


def _nodes(pairs: List[Tuple[AnalyticalObject, int]]) -> List[LineageNode]:
    return [LineageNode(object=item, depth=depth) for item, depth in pairs]


def _edges(pairs: List[Tuple[str, str]]) -> List[LineageEdge]:
    return [LineageEdge(parent_object_id=parent_id, child_object_id=child_id) for parent_id, child_id in pairs]


def build_ancestors(registry: AnalyticalObjectRegistry, object_id: str, max_depth: Optional[int]) -> Optional[LineageTraversal]:
    result = registry.ancestors(object_id, max_depth=max_depth)
    if result is None:
        return None
    return LineageTraversal(
        root_object_id=object_id,
        direction=LineageDirection.UPSTREAM,
        nodes=_nodes(result.nodes),
        edges=_edges(result.edges),
        max_depth=max_depth,
        truncated=result.truncated,
    )


def build_descendants(registry: AnalyticalObjectRegistry, object_id: str, max_depth: Optional[int]) -> Optional[LineageTraversal]:
    result = registry.descendants(object_id, max_depth=max_depth)
    if result is None:
        return None
    return LineageTraversal(
        root_object_id=object_id,
        direction=LineageDirection.DOWNSTREAM,
        nodes=_nodes(result.nodes),
        edges=_edges(result.edges),
        max_depth=max_depth,
        truncated=result.truncated,
    )


def build_graph(
    registry: AnalyticalObjectRegistry,
    object_id: str,
    direction: LineageDirection,
    max_depth: Optional[int],
) -> Optional[LineageTraversal]:
    """The compact graph endpoint: a thin merge of the same ancestor/descendant
    traversal already used above, with the root itself included at depth 0 - the one
    place in this module's contract where the root is not excluded (see
    ``LineageTraversal``'s docstring for the convention this follows)."""
    root = registry.get(object_id)
    if root is None:
        return None
    nodes: dict[str, LineageNode] = {object_id: LineageNode(object=root, depth=0)}
    edges: dict[Tuple[str, str], LineageEdge] = {}
    truncated = False
    if direction in (LineageDirection.UPSTREAM, LineageDirection.BOTH):
        upstream = registry.ancestors(object_id, max_depth=max_depth)
        if upstream is not None:
            for item, depth in upstream.nodes:
                nodes.setdefault(item.object_id, LineageNode(object=item, depth=depth))
            for parent_id, child_id in upstream.edges:
                edges[(parent_id, child_id)] = LineageEdge(parent_object_id=parent_id, child_object_id=child_id)
            truncated = truncated or upstream.truncated
    if direction in (LineageDirection.DOWNSTREAM, LineageDirection.BOTH):
        downstream = registry.descendants(object_id, max_depth=max_depth)
        if downstream is not None:
            for item, depth in downstream.nodes:
                nodes.setdefault(item.object_id, LineageNode(object=item, depth=depth))
            for parent_id, child_id in downstream.edges:
                edges[(parent_id, child_id)] = LineageEdge(parent_object_id=parent_id, child_object_id=child_id)
            truncated = truncated or downstream.truncated
    ordered_nodes = sorted(nodes.values(), key=lambda node: (node.depth, node.object.object_id))
    ordered_edges = sorted(edges.values(), key=lambda edge: (edge.parent_object_id, edge.child_object_id))
    return LineageTraversal(
        root_object_id=object_id,
        direction=direction,
        nodes=ordered_nodes,
        edges=ordered_edges,
        max_depth=max_depth,
        truncated=truncated,
    )


def build_path(registry: AnalyticalObjectRegistry, from_object_id: str, to_object_id: str) -> Optional[LineagePath]:
    result = registry.shortest_path(from_object_id, to_object_id)
    if result is None:
        return None
    return LineagePath(
        from_object_id=from_object_id,
        to_object_id=to_object_id,
        found=result.found,
        nodes=_nodes(result.nodes),
        edges=_edges(result.edges),
    )
