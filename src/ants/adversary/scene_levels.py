"""Harder variants of the bowl-on-plate scene, built from the path a working program took.

A level moves existing free objects (pose offsets in the launcher) so that the wine rack sits on
the path of the hand without overlapping anything. Placement is a grid search on the oracle
collision world; every candidate keeps a clearance from all other objects and stays on the table.
The hand is modelled as a keep-out rectangle (21 cm along y, 10 cm along x, plus 1 cm margin) from
3 cm to 10 cm above the TCP, swept along the path with the gripper's yaw fixed at 0 (the working
program closes its fingers along y); this is a stated approximation, not the hand's real shape.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ants.adversary.collision_world import Box, CollisionWorld

HAND_HALF_XY_M = (0.049 + 0.01, 0.104 + 0.01)
HAND_Z_M = (0.03, 0.10)  # above the TCP
CLEARANCE_M = 0.01
TABLE_X = (0.19, 1.13)  # table is 1.0 x 1.2 m, centred 0.66 m in front of the base; 3 cm margin
TABLE_Y = (-0.57, 0.57)
MAX_DISPLACEMENT_M = 0.6

Point = tuple[float, float, float]


def densify(polyline: list[Point], step: float = 0.03) -> list[Point]:
    out: list[Point] = []
    for a, b in zip(polyline, polyline[1:], strict=False):
        n = max(1, int(math.dist(a, b) / step))
        out += [tuple(a[i] + (b[i] - a[i]) * k / n for i in range(3)) for k in range(n)]  # type: ignore[misc]
    out.append(polyline[-1])
    return out


def _frame(b: Box) -> tuple[Point, list[Point], Point]:
    """Centre, three unit axes and half sizes of a box (oriented when its corners are known)."""
    c = b.corners
    if len(c) != 8:
        return (
            b.centre,
            [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
            tuple(s / 2 for s in b.size),
        )  # type: ignore[return-value]
    centre = tuple(sum(p[i] for p in c) / 8 for i in range(3))
    axes, half = [], []
    for hi, lo in ((c[4], c[0]), (c[2], c[0]), (c[1], c[0])):  # corner order: product of +-1 signs
        v = tuple(hi[i] - lo[i] for i in range(3))
        n = math.sqrt(sum(x * x for x in v))
        axes.append(tuple(x / n for x in v))
        half.append(n / 2)
    return centre, axes, tuple(half)  # type: ignore[return-value]


def apart(a: Box, b: Box, margin: float) -> bool:
    """True when the two boxes are separated by at least `margin` (separating-axis test)."""
    ca, aa, ha = _frame(a)
    cb, ab, hb = _frame(b)
    d = tuple(cb[i] - ca[i] for i in range(3))
    cands = [*aa, *ab]
    for u in aa:
        for v in ab:
            w = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
            n = math.sqrt(sum(x * x for x in w))
            if n > 1e-9:
                cands.append(tuple(x / n for x in w))
    for ax in cands:
        ra = sum(ha[i] * abs(sum(aa[i][k] * ax[k] for k in range(3))) for i in range(3))
        rb = sum(hb[i] * abs(sum(ab[i][k] * ax[k] for k in range(3))) for i in range(3))
        if abs(sum(d[k] * ax[k] for k in range(3))) > ra + rb + margin:
            return True
    return False


def hits_hand(box: Box, p: Point) -> bool:
    """Does `box` intersect the hand's keep-out rectangle placed at the TCP position `p`?"""
    if box.hi[2] < p[2] + HAND_Z_M[0] or box.lo[2] > p[2] + HAND_Z_M[1]:
        return False
    return (
        box.lo[0] <= p[0] + HAND_HALF_XY_M[0]
        and box.hi[0] >= p[0] - HAND_HALF_XY_M[0]
        and box.lo[1] <= p[1] + HAND_HALF_XY_M[1]
        and box.hi[1] >= p[1] - HAND_HALF_XY_M[1]
    )


@dataclass(frozen=True)
class Placement:
    dx: float
    dy: float
    hits: int  # path points the rack blocks
    of: int  # path points checked
    min_clearance_m: float


def place(
    world: CollisionWorld, label: str, path: list[Point], step_cm: int = 2
) -> Placement | None:
    """The smallest move of one object that blocks the most path points, clear of everything."""
    rack = world.get(label)
    others = [b for o in world.objects if o.label != label for b in o.boxes]
    pts = densify(path)
    best: tuple[tuple[int, float], Placement] | None = None
    steps = [i / 100 for i in range(-60, 61, step_cm)]
    for dx in steps:
        for dy in steps:
            moved = [b.moved(dx, dy) for b in rack.boxes]
            lo_x = min(b.lo[0] for b in moved)
            hi_x = max(b.hi[0] for b in moved)
            lo_y = min(b.lo[1] for b in moved)
            hi_y = max(b.hi[1] for b in moved)
            if lo_x < TABLE_X[0] or hi_x > TABLE_X[1] or lo_y < TABLE_Y[0] or hi_y > TABLE_Y[1]:
                continue
            hits = sum(any(hits_hand(m, p) for m in moved) for p in pts)
            if hits == 0 or (best is not None and hits < -best[0][0]):
                continue
            # bounding boxes first (a lower bound on the gap), the exact test only for near pairs
            if not all(
                m.gap(o) >= CLEARANCE_M or apart(m, o, CLEARANCE_M) for m in moved for o in others
            ):
                continue
            clear = CLEARANCE_M
            key = (-hits, math.hypot(dx, dy))
            if best is None or key < best[0]:
                best = (key, Placement(dx, dy, hits, len(pts), clear))
    return best[1] if best else None
