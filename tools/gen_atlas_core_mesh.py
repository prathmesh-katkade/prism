#!/usr/bin/env python3
"""Generates the SVG markup for Atlas's "neural mesh" core visual
(apps/desktop-shell/dist/index.html, #atlas-core).

Replaced the old concentric-ring/orbiting-electron "arc reactor" look with
a golden-angle phyllotaxis scatter of synapse nodes, a sparse k-nearest-
neighbour link mesh (not an all-pairs mesh — that reads as a tangled blob
at this size), and a handful of signal dots that travel live edges via CSS
`offset-path`.

Run it and paste the three printed blocks (nodes+lines, pulse circles,
pulse offset-path CSS) into index.html by hand — this script is a design
tool, not part of the build; the SVG is static markup. Re-run and re-paste
if you want to change node count or the layout formula, rather than
hand-editing the generated coordinates in place.

    python3 tools/gen_atlas_core_mesh.py
"""

from __future__ import annotations

import math

GOLDEN_ANGLE = math.radians(137.507764)
VIEWBOX_CENTER = (50.0, 50.0)
MAX_RADIUS = 46.0  # stay inside the old core-boundary ring


def node_positions(n: int) -> list[tuple[float, float, float]]:
    """Returns (x, y, r) for n nodes in a golden-angle spiral, r = distance
    from center. The sqrt(i) radial term keeps node density roughly even
    per unit area (true phyllotaxis), rather than bunching near the rim."""
    cx, cy = VIEWBOX_CENTER
    points = []
    for i in range(n):
        r = 8.5 + math.sqrt(i) * 9.6
        theta = i * GOLDEN_ANGLE
        points.append((cx + r * math.cos(theta), cy + r * math.sin(theta), r))
    assert max(p[2] for p in points) < MAX_RADIUS, "node escaped the boundary ring"
    return points


def tier(r: float) -> str:
    if r < 20:
        return "inner"
    if r < 34:
        return "mid"
    return "outer"


RADIUS_BY_TIER = {"inner": 2.0, "mid": 1.6, "outer": 1.25}


def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def knn_mesh(nodes: list[tuple[float, float, float]]) -> set[tuple[int, int]]:
    """Sparse k-nearest-neighbour link set: each synapse node links to its 2
    nearest neighbours, the nucleus (index 0) to its 4 nearest — a real
    graph, not a solid mesh, so individual edges stay legible at 132px."""
    pts = [VIEWBOX_CENTER] + [(x, y) for x, y, _ in nodes]
    edges: set[tuple[int, int]] = set()
    for i, p in enumerate(pts):
        ranked = sorted((dist(p, q), j) for j, q in enumerate(pts) if j != i)
        k = 4 if i == 0 else 2
        for _, j in ranked[:k]:
            edges.add((min(i, j), max(i, j)))
    return edges


def main(n: int = 15) -> None:
    nodes = node_positions(n)
    pts = [VIEWBOX_CENTER] + [(x, y) for x, y, _ in nodes]
    edges = sorted(knn_mesh(nodes))

    print("<!-- nodes + mesh -->")
    for i, j in edges:
        x1, y1 = pts[i]
        x2, y2 = pts[j]
        print(f'<line class="core-mesh-line" x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}"/>')
    for idx, (x, y, r) in enumerate(nodes):
        t = tier(r)
        delay = (idx * 0.257) % 3.6
        print(
            f'<circle class="core-node core-node-{t}" cx="{x:.2f}" cy="{y:.2f}" '
            f'r="{RADIUS_BY_TIER[t]}" style="animation-delay:{delay:.2f}s"/>'
        )

    edge_list = [(i, j, *pts[i], *pts[j]) for i, j in edges]
    by_length = sorted(edge_list, key=lambda e: dist((e[2], e[3]), (e[4], e[5])))
    picks = [by_length[1], by_length[len(by_length) // 3], by_length[2 * len(by_length) // 3], by_length[-2]]

    print("\n<!-- pulses -->")
    for n_ in range(1, 5):
        print(f'<circle class="core-pulse core-pulse-{n_}" r="1.1"/>')

    print("\n<!-- pulse offset-path CSS -->")
    for n_, (_, _, x1, y1, x2, y2) in enumerate(picks, start=1):
        print(f".core-pulse-{n_}{{offset-path:path('M{x1:.2f},{y1:.2f} L{x2:.2f},{y2:.2f}')}}")


if __name__ == "__main__":
    main()
