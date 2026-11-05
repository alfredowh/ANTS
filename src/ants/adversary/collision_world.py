"""A collision world: the scene's objects as boxes in the robot base frame, plus the text the
generator is given about it.

The input is the scene dump that `tools/aspire_launch.py` writes after a reset (every body pose and
every collision geom). Everything here is plain geometry on that dump: no model writes any shape or
relation. The dump is simulator truth ("oracle"); a perceived world (SAM 3 + depth) would build the
same `CollisionWorld` from a point cloud.

Frame: `robot_base` (x forward, y left, z up), metres. World coordinates are translated by the
base position (the base is not rotated).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, replace

ROBOT_PREFIXES = ("robot0", "gripper0", "mount0")
LABELS = {
    "akita_black_bowl": "bowl",
    "plate": "plate",
    "wine_rack": "wine rack",
    "wine_bottle": "wine bottle",
    "cream_cheese": "cream cheese",
    "wooden_cabinet": "wooden cabinet",
    "flat_stove": "flat stove",
}
TASK_OBJECTS = ("bowl", "plate")
ROUND_OBJECTS = ("bowl", "plate")
TOUCH_M = 0.003  # gaps at or below this count as touching
RELATION_RANGE_M = 0.12  # pairs farther apart than this get no relation
HAND = (
    "Gripper (Franka Panda hand): the hand body is about 21 cm wide across the fingers and "
    "10 cm deep; its underside sits about 3 cm above the end-effector point (measured from one "
    "replay), and the 1.6 cm fingertips reach below it."
)


@dataclass(frozen=True)
class Box:
    lo: tuple[float, float, float]
    hi: tuple[float, float, float]
    corners: tuple[tuple[float, float, float], ...] = ()  # oriented corners, when known

    @property
    def centre(self) -> tuple[float, float, float]:
        return tuple((a + b) / 2 for a, b in zip(self.lo, self.hi, strict=True))  # type: ignore[return-value]

    @property
    def size(self) -> tuple[float, float, float]:
        return tuple(b - a for a, b in zip(self.lo, self.hi, strict=True))  # type: ignore[return-value]

    def gap(self, other: Box) -> float:
        """Euclidean distance between two boxes; 0 when they touch or overlap."""
        d = [max(0.0, other.lo[i] - self.hi[i], self.lo[i] - other.hi[i]) for i in range(3)]
        return math.sqrt(sum(v * v for v in d))

    def points(self, k: int = 4) -> list[tuple[float, float, float]]:
        """A k x k x k grid of points on and in the (oriented) box, from its corners."""
        c = self.corners
        if len(c) != 8:
            c = tuple(
                (x, y, z) for x in (self.lo[0], self.hi[0]) for y in (self.lo[1], self.hi[1])
                for z in (self.lo[2], self.hi[2])
            )  # fmt: skip
        steps = [i / (k - 1) for i in range(k)]
        out = []
        for u in steps:
            for v in steps:
                for w in steps:
                    out.append(
                        tuple(
                            c[0][i] * (1 - u) * (1 - v) * (1 - w) + c[1][i] * (1 - u) * (1 - v) * w
                            + c[2][i] * (1 - u) * v * (1 - w) + c[3][i] * (1 - u) * v * w
                            + c[4][i] * u * (1 - v) * (1 - w) + c[5][i] * u * (1 - v) * w
                            + c[6][i] * u * v * (1 - w) + c[7][i] * u * v * w
                            for i in range(3)
                        )
                    )  # fmt: skip
        return out  # type: ignore[return-value]

    def moved(self, dx: float, dy: float) -> Box:
        lo = (self.lo[0] + dx, self.lo[1] + dy, self.lo[2])
        hi = (self.hi[0] + dx, self.hi[1] + dy, self.hi[2])
        return Box(lo, hi, tuple((c[0] + dx, c[1] + dy, c[2]) for c in self.corners))


@dataclass(frozen=True)
class WorldObject:
    name: str  # simulator body name
    label: str
    boxes: tuple[Box, ...]
    movable: bool

    @property
    def aabb(self) -> Box:
        lo = tuple(min(b.lo[i] for b in self.boxes) for i in range(3))
        hi = tuple(max(b.hi[i] for b in self.boxes) for i in range(3))
        return Box(lo, hi)  # type: ignore[arg-type]

    def gap(self, other: WorldObject) -> float:
        """Nearest distance between the two objects, from a grid of points on their boxes."""
        pairs = [(a, b) for a in self.boxes for b in other.boxes]
        best = min(a.gap(b) for a, b in pairs)  # bounding boxes: a lower bound on the true gap
        if best > RELATION_RANGE_M:
            return best
        pts_b = {id(b): b.points() for _, b in pairs}
        pts_a = {id(a): a.points() for a, _ in pairs}
        out = math.inf
        for a, b in pairs:
            if a.gap(b) >= out:
                continue
            for p in pts_a[id(a)]:
                for q in pts_b[id(b)]:
                    d = (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2
                    if d < out * out if out != math.inf else True:
                        out = math.sqrt(d)
        return out

    def moved(self, dx: float, dy: float) -> WorldObject:
        return replace(self, boxes=tuple(b.moved(dx, dy) for b in self.boxes))


@dataclass(frozen=True)
class Relation:
    a: str
    b: str
    kind: str  # touching | near | supported_by
    gap_m: float


@dataclass(frozen=True)
class CollisionWorld:
    base_world: tuple[float, float, float]
    table_top_z: float
    objects: tuple[WorldObject, ...]
    gaps: tuple[tuple[str, str, float], ...] = ()  # exact simulator gaps by body name

    def get(self, label: str) -> WorldObject:
        return next(o for o in self.objects if o.label == label)

    def shifted(self, label: str, dx: float, dy: float) -> CollisionWorld:
        """The same world with one object moved (used for the placebo variant)."""
        moved = self.get(label).name
        return replace(
            self,
            objects=tuple(o.moved(dx, dy) if o.label == label else o for o in self.objects),
            gaps=tuple(g for g in self.gaps if moved not in g[:2]),  # stale; recomputed from boxes
        )

    def gap(self, a: WorldObject, b: WorldObject) -> float:
        for x, y, d in self.gaps:
            if {x, y} == {a.name, b.name}:
                return d
        return a.gap(b)


def _label(root: str) -> str:
    stem = root.removesuffix("_main")
    stem = stem[: stem.rfind("_")] if stem.rsplit("_", 1)[-1].isdigit() else stem
    return LABELS.get(stem, stem.replace("_", " "))


def _geom_box(geom: dict) -> Box:
    """World-aligned bounding box (and oriented corners for boxes) of one collision geom."""
    size, kind, r = geom["size"], geom["type"], geom["xmat"]
    rot = [r[0:3], r[3:6], r[6:9]]
    c = geom["pos"]
    corners: tuple[tuple[float, float, float], ...] = ()
    if kind == 6:  # box: half sizes
        half = [sum(abs(rot[i][j]) * size[j] for j in range(3)) for i in range(3)]
        corners = tuple(
            tuple(c[i] + sum(rot[i][j] * s[j] * size[j] for j in range(3)) for i in range(3))
            for s in itertools.product((-1, 1), repeat=3)
        )  # type: ignore[assignment]
    elif kind == 2:  # sphere
        half = [size[0]] * 3
    elif kind in (3, 5):  # capsule, cylinder: radius, half length along local z
        half = [
            abs(rot[i][2]) * size[1] + size[0] * math.sqrt(max(0.0, 1 - rot[i][2] ** 2))
            for i in range(3)
        ]
    else:
        raise ValueError(f"unsupported geom type {kind} ({geom['name']})")
    lo = tuple(c[i] - half[i] for i in range(3))
    hi = tuple(c[i] + half[i] for i in range(3))
    return Box(lo, hi, corners)  # type: ignore[arg-type]


def load_world(dump: dict) -> CollisionWorld:
    """Build the world from the launcher's scene dump (`*_scene.json`)."""
    bodies = dump["bodies"]
    base = tuple(bodies["robot0_base"]["pos"])
    by_root: dict[str, list[Box]] = {}
    table_top = -math.inf
    for g in dump["geoms"]:
        if g["contype"] + g["conaffinity"] == 0 or g["type"] == 0:
            continue
        root = bodies[g["body"]]["root"]
        if root == "world" or root.startswith(ROBOT_PREFIXES):
            continue
        box = _geom_box(g)
        if root == "table":
            table_top = max(table_top, box.hi[2] - base[2])
            continue
        shift = tuple(-v for v in base)
        by_root.setdefault(root, []).append(
            Box(
                tuple(box.lo[i] + shift[i] for i in range(3)),  # type: ignore[arg-type]
                tuple(box.hi[i] + shift[i] for i in range(3)),  # type: ignore[arg-type]
                tuple(tuple(p[i] + shift[i] for i in range(3)) for p in box.corners),  # type: ignore[misc]
            )
        )
    objects = tuple(
        WorldObject(root, _label(root), tuple(boxes), bodies[root]["mass"] > 0)
        for root, boxes in sorted(by_root.items())
    )
    gaps = tuple((g["a"], g["b"], g["dist"]) for g in dump.get("gaps", []))
    return CollisionWorld(base, table_top, objects, gaps)  # type: ignore[arg-type]


def radial_profile(
    obj: WorldObject, bins: int = 5
) -> tuple[tuple[float, float], list[tuple[float, float]]]:
    """Axis (x, y) and outer radius at heights above the object's bottom, for a round object."""
    a = obj.aabb
    axis = ((a.lo[0] + a.hi[0]) / 2, (a.lo[1] + a.hi[1]) / 2)
    rings = []
    for i in range(bins + 1):
        z = a.lo[2] + (a.hi[2] - a.lo[2]) * i / bins
        r = 0.0
        for b in obj.boxes:
            if b.lo[2] - 1e-9 <= z <= b.hi[2] + 1e-9:
                pts = b.corners or (b.lo, b.hi)
                r = max(r, max(math.hypot(p[0] - axis[0], p[1] - axis[1]) for p in pts))
        if r > 0:
            rings.append((round(z - a.lo[2], 4), round(r, 4)))
    return axis, rings


def relations(world: CollisionWorld) -> list[Relation]:
    out: list[Relation] = []
    for o in world.objects:
        d = next((g[2] for g in world.gaps if {g[0], g[1]} == {o.name, "table"}), None)
        if d is None:
            d = o.aabb.lo[2] - world.table_top_z
        if abs(d) <= TOUCH_M:
            out.append(Relation(o.label, "table", "supported_by", max(0.0, d)))
    for i, a in enumerate(world.objects):
        for b in world.objects[i + 1 :]:
            g = world.gap(a, b)
            if g <= TOUCH_M:
                out.append(Relation(a.label, b.label, "touching", g))
            elif g <= RELATION_RANGE_M:
                out.append(Relation(a.label, b.label, "near", g))
    return out


def _p(v: float) -> str:
    return f"{v:.3f}"


def _xyz(t: tuple[float, float, float]) -> str:
    return "(" + ", ".join(_p(v) for v in t) + ")"


def _ext(b: Box) -> str:
    s = b.size
    return f"{s[0] * 100:.0f} x {s[1] * 100:.0f} x {s[2] * 100:.0f} cm (x, y, z)"


LEVELS = ("positions", "extents", "graph", "combo")


def describe(world: CollisionWorld, level: str) -> str:
    """The scene section of the prompt; each level adds to the one before it (see LEVELS)."""
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}")
    lines = [
        "Scene, measured before the arm moves (robot_base frame: x forward, y left, z up; metres):",
        f"- table top: z = {_p(world.table_top_z)}",
    ]
    rels = relations(world)
    for o in world.objects:
        a = o.aabb
        if level == "positions":
            lines.append(f"- {o.label}: centre {_xyz(a.centre)}")
            continue
        head = f"- {o.label}: centre {_xyz(a.centre)}, size {_ext(a)}"
        if level == "combo" and o.label in ROUND_OBJECTS:
            axis, rings = radial_profile(o)
            head = (
                f"- {o.label} (round): axis ({_p(axis[0])}, {_p(axis[1])}), outer radius by height "
                "above its bottom: "
                + ", ".join(f"{h * 100:.1f} cm: {r * 100:.1f} cm" for h, r in rings)
            )
        elif level == "combo" and 1 < len(o.boxes) <= 12:
            parts = "; ".join(f"{_xyz(b.lo)} to {_xyz(b.hi)}" for b in o.boxes)
            head += f". Made of {len(o.boxes)} boxes (lo to hi): {parts}"
        lines.append(head)
    if level in ("graph", "combo"):
        lines.append("Relations (gap = nearest distance between the objects):")
        for r in rels:
            if r.kind == "supported_by":
                lines.append(f"- {r.a} rests on the {r.b}")
            else:
                lines.append(f"- {r.a} and {r.b}: {r.kind}, gap {max(0.0, r.gap_m) * 1000:.0f} mm")
    if level == "combo":
        lines.append(HAND)
    return "\n".join(lines)


def view(world: CollisionWorld) -> dict:
    """Plain data for the run viewer's scene tab."""
    objs = []
    for o in world.objects:
        item = {
            "label": o.label,
            "movable": o.movable,
            "task": o.label in TASK_OBJECTS,
            "aabb": [list(o.aabb.lo), list(o.aabb.hi)],
            "boxes": [[list(b.lo), list(b.hi)] for b in o.boxes],
            "profile": None,
        }
        if o.label in ROUND_OBJECTS:
            axis, rings = radial_profile(o)
            item["profile"] = {"axis": list(axis), "rings": [list(r) for r in rings]}
        objs.append(item)
    return {
        "table_top_z": world.table_top_z,
        "objects": objs,
        "relations": [
            {"a": r.a, "b": r.b, "kind": r.kind, "gap_m": round(r.gap_m, 4)}
            for r in relations(world)
        ],
    }
