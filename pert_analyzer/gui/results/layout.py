"""
Deterministic AON layout layer for the network canvas.

Computes presentation-only coordinates from the backend graph. Never
modifies GraphModel data; the layout is a view-level concern.

Uses a topological (Kahn) ordering, groups activities by their longest
logical level, and arranges rows deterministically by activity id.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Dict, List, Set, Tuple


NODE_WIDTH = 132
NODE_HEIGHT = 68
H_SPACING = 72
V_SPACING = 48
MARGIN = 40


def _back_edges(
    activity_ids: List[str],
    edge_pairs: List[Tuple[str, str]],
) -> Set[Tuple[str, str]]:
    """Edges that close a feedback loop, found by deterministic DFS.

    Roots and neighbours are visited in sorted order, so the detected
    back-edge set never depends on dict or insertion order. The layering
    ignores these edges: a cycle keeps its natural column order instead
    of spiralling, and its arrow renders as a return channel below.
    """
    succ: Dict[str, List[str]] = defaultdict(list)
    for src, tgt in edge_pairs:
        succ[src].append(tgt)

    WHITE, GRAY, BLACK = 0, 1, 2
    state: Dict[str, int] = {aid: WHITE for aid in activity_ids}
    back: Set[Tuple[str, str]] = set()
    for root in sorted(activity_ids):
        if state[root] != WHITE:
            continue
        state[root] = GRAY
        stack: List[Tuple[str, Any]] = [
            (root, iter(sorted(succ.get(root, []))))
        ]
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                if state[nxt] == GRAY:
                    back.add((node, nxt))
                elif state[nxt] == WHITE:
                    state[nxt] = GRAY
                    stack.append(
                        (nxt, iter(sorted(succ.get(nxt, []))))
                    )
                    advanced = True
                    break
            if not advanced:
                state[node] = BLACK
                stack.pop()
    return back


def _row_barycenter(
    aid: str,
    predecessors: Dict[str, List[str]],
    rows: Dict[str, int],
) -> float:
    """Row placement weight: mean row of already-placed predecessors.

    Roots (nothing placed yet) float to the top of their column; ties
    break by id, keeping the whole layout deterministic.
    """
    placed = [rows[p] for p in predecessors.get(aid, []) if p in rows]
    if not placed:
        return -1.0
    return sum(placed) / len(placed)


def build_layout(
    activity_ids: List[str],
    dependencies: List[Any],
    node_width: int = NODE_WIDTH,
    node_height: int = NODE_HEIGHT,
    h_spacing: int = H_SPACING,
    v_spacing: int = V_SPACING,
    margin: int = MARGIN,
) -> Dict[str, Tuple[float, float, float, float]]:
    """Return activity_id -> (x, y, width, height) presentation rects.

    ``dependencies`` accepts objects with ``source``/``target`` attributes
    or (source, target) tuples.
    """
    id_set = set(activity_ids)
    successors: Dict[str, List[str]] = defaultdict(list)
    predecessors: Dict[str, List[str]] = defaultdict(list)
    edge_pairs: List[Tuple[str, str]] = []
    for dep in dependencies:
        if isinstance(dep, tuple):
            src, tgt = dep
        else:
            src = getattr(dep, "source", None)
            tgt = getattr(dep, "target", None)
        if src is None or tgt is None:
            continue
        if src in id_set and tgt in id_set:
            edge_pairs.append((src, tgt))

    # Layering ignores feedback edges: they close loops, so feeding them
    # to Kahn's algorithm stalls it and the old fallback then re-processed
    # them, spiralling cycle columns out of order.
    layout_edges = [p for p in edge_pairs if p not in _back_edges(activity_ids, edge_pairs)]

    successors: Dict[str, List[str]] = defaultdict(list)
    predecessors: Dict[str, List[str]] = defaultdict(list)
    for src, tgt in layout_edges:
        successors[src].append(tgt)
        predecessors[tgt].append(src)

    indegree = {aid: 0 for aid in activity_ids}
    for src, tgt in layout_edges:
        indegree[tgt] += 1
    ready = deque(sorted(aid for aid in activity_ids if indegree[aid] == 0))
    topo_order: List[str] = []
    while ready:
        aid = ready.popleft()
        topo_order.append(aid)
        for nxt in sorted(successors.get(aid, [])):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
    # Pure safety net: any stray node (should be none once loops are
    # filtered) keeps a stable appendix without further propagation.
    for aid in sorted(activity_ids):
        if aid not in set(topo_order):
            topo_order.append(aid)

    level: Dict[str, int] = {aid: 0 for aid in activity_ids}
    for aid in topo_order:
        for nxt in successors.get(aid, []):
            level[nxt] = max(level[nxt], level[aid] + 1)

    by_level: Dict[int, List[str]] = defaultdict(list)
    for aid in topo_order:
        by_level[level[aid]].append(aid)

    col_step = node_width + h_spacing
    row_step = node_height + v_spacing
    positions: Dict[str, Tuple[float, float, float, float]] = {}
    rows: Dict[str, int] = {}
    for lvl in sorted(by_level):
        # Barycenter row order instead of plain alphabetical: nodes line
        # up under their predecessors, which removes most edge crossings
        # and gives real activity names their natural lanes back.
        ordered = sorted(
            by_level[lvl],
            key=lambda a: (_row_barycenter(a, predecessors, rows), a),
        )
        for row, aid in enumerate(ordered):
            rows[aid] = row
            x = margin + lvl * col_step
            y = margin + row * row_step
            positions[aid] = (float(x), float(y), float(node_width), float(node_height))

    return positions


def edge_points(
    positions: Dict[str, Tuple[float, float, float, float]],
    source: str,
    target: str,
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Return (start, end) points for a source->target dependency arrow."""
    sx, sy, sw, sh = positions[source]
    tx, ty, tw, th = positions[target]
    start = (sx + sw, sy + sh / 2)
    end = (tx, ty + th / 2)
    return start, end