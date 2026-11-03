"""exp05: can the current stack build the collision world from PERCEPTION instead of the simulator?

Offline study on the L1 start state (libero_goal_swap task 8, seed 51; rack behind the plate). No model
(Muse) call, no token spend: SAM 3 and depth run inside ASPIRE's services.

    # 1. perceive (needs ASPIRE's services; ~3 minutes): writes perception_start.json, perception_arm.json
    uv run python -m ants.orchestrator.perceived_scene --aspire ASPIRE --out data/runs/exp05_perceived_scene --probe
    # 2. analyse offline (pure Python): variants V0..V5, perceived world, S4 text, comparison with the oracle
    uv run python -m ants.orchestrator.perceived_scene --out data/runs/exp05_perceived_scene --analyse
    # 3. the HTML report
    uv run python -m ants.evalkit.perceived_report --out data/runs/exp05_perceived_scene

The oracle is the simulator dump of exp04 (`contacts_scene.json` of the same level). Perceived points are
in the robot base frame, like the oracle world, so no registration is needed. Points of one mask are
down-sampled to at most about 1000 by the probe (`data/scenes/perception_probe2.py`), which is enough
for boxes but not for fine shapes (see the caveats in docs/synthesizer/experiment-05-perceived-scene.md).
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path

from ants.adversary.collision_world import (
    ROUND_OBJECTS,
    TASK_OBJECTS,
    Box,
    CollisionWorld,
    WorldObject,
    describe,
    load_world,
    relations,
)
from ants.evalkit.panda import flange_position, spheres
from ants.synthesizer.sam_api import add_sam_model_arg, normalize_sam_model

Pt = tuple[float, float, float]
LEVEL_DUMP = Path("data/scenes/L1/contacts_scene.json")
OBJECTS: dict[str, list[str]] = {
    "bowl": ["bowl"],
    "plate": ["plate"],
    "wine bottle": ["wine bottle"],
    "cream cheese": ["cream cheese"],
    "wooden cabinet": ["wooden cabinet"],
    "flat stove": ["flat stove"],
    "wine rack": ["wine rack", "wine bottle rack", "wooden wine rack", "shelf"],
}
PLAUSIBLE = {
    "max_span_m": 0.45,
    "x": (0.15, 0.95),
    "max_abs_y": 0.5,
    "max_z": 0.6,
    "min_points": 30,
}
VARIANTS = {
    "V0": "a3 baseline: agent view, prompt = object name, best mask, estimate_geometry centre and extents",
    "V1": "V0 mask, box from the mask's own depth points (1st to 99th percentile)",
    "V2": "+ plausible-mask filter, prompt synonyms for the rack with consensus, masks claimed by another object removed",
    "V3": "+ hand camera masks fused (gated to 8 cm of the agent-view centre)",
    "V4": "+ table plane from the 'table' mask (trim points on it, heights above it) and robot-mask subtraction",
    "V5": "+ shape fit: circle for bowl and plate, oriented rectangle for the rest (final)",
}
VOXEL = 0.02
GATE_M = 0.08
CLAIM_FRAC = 0.5
FOUND_XY_M = 0.03
EXTENT_P = (0.005, 0.995)  # percentiles of the mask's depth points used as box extent
EXTENT_SWEEP = ((0.0, 1.0), (0.005, 0.995), (0.01, 0.99), (0.02, 0.98))


# ---------------------------------------------------------------- probe
def probe(args: argparse.Namespace) -> None:
    from ants.contracts import CaseSpec, Split
    from ants.evalkit.aspire_harness import CapHarness
    from ants.orchestrator.scene_context_exp import load_levels, scene_spec

    levels = load_levels(Path("data/scenes/levels.json"))
    for tag, script in (("start", "perception_probe2.py"), ("arm", "perception_probe3.py")):
        out = args.out.resolve() / f"probe_L1_{tag}"
        harness = CapHarness(
            args.aspire.resolve(),
            timeout_s=1800.0,
            launcher=Path("tools/aspire_launch.py").resolve(),
            scene=scene_spec(levels["L1"], out / "contacts.jsonl"),
        )
        case = CaseSpec(f"e5-{tag}", "libero_goal_swap", 8, 51, Split.ACCEPTANCE)
        trace = harness.run(
            case, (Path("data/scenes") / script).resolve(), out / "run", f"e5-{tag}"
        )
        if not trace.run_dir:
            raise RuntimeError(f"probe {tag} failed: {trace.error or trace.termination_reason}")
        shutil.copy(
            Path(trace.run_dir) / "source" / "program-result.json",
            args.out / f"perception_{tag}.json",
        )
        print(tag, "->", args.out / f"perception_{tag}.json", flush=True)


# ---------------------------------------------------------------- geometry helpers (stdlib only)
def pct(v: list[float], p: float) -> float:
    s = sorted(v)
    return s[min(len(s) - 1, max(0, round(p * (len(s) - 1))))]


def aabb(pts: list[Pt], lo_p: float = 0.0, hi_p: float = 1.0) -> tuple[Pt, Pt]:
    lo = tuple(pct([p[i] for p in pts], lo_p) for i in range(3))
    hi = tuple(pct([p[i] for p in pts], hi_p) for i in range(3))
    return lo, hi  # type: ignore[return-value]


def voxels(pts: list[Pt]) -> set[tuple[int, int, int]]:
    return {(int(p[0] // VOXEL), int(p[1] // VOXEL), int(p[2] // VOXEL)) for p in pts}


def median_xy(pts: list[Pt]) -> tuple[float, float]:
    return pct([p[0] for p in pts], 0.5), pct([p[1] for p in pts], 0.5)


def plausible(pts: list[Pt], table_z: float) -> bool:
    if len(pts) < PLAUSIBLE["min_points"]:
        return False
    lo, hi = aabb(pts, 0.01, 0.99)
    cx, cy = median_xy(pts)
    return (
        all(hi[i] - lo[i] <= PLAUSIBLE["max_span_m"] for i in range(3))
        and PLAUSIBLE["x"][0] <= cx <= PLAUSIBLE["x"][1]
        and abs(cy) <= PLAUSIBLE["max_abs_y"]
        and lo[2] >= table_z - 0.03
        and hi[2] <= PLAUSIBLE["max_z"]
    )


def min_area_rect(pts: list[Pt]) -> tuple[tuple[float, float], tuple[float, float], float]:
    """Smallest-area rectangle around the xy points: centre, (length, width), angle in rad."""
    best = None
    xy = [(p[0], p[1]) for p in pts]
    for k in range(0, 90, 2):
        a = math.radians(k)
        c, s = math.cos(a), math.sin(a)
        u = [c * x + s * y for x, y in xy]
        w = [-s * x + c * y for x, y in xy]
        u0, u1, w0, w1 = pct(u, 0.01), pct(u, 0.99), pct(w, 0.01), pct(w, 0.99)
        area = (u1 - u0) * (w1 - w0)
        if best is None or area < best[0]:
            cu, cw = (u0 + u1) / 2, (w0 + w1) / 2
            best = (area, ((c * cu - s * cw), (s * cu + c * cw)), (u1 - u0, w1 - w0), a)
    assert best is not None
    return best[1], best[2], best[3]


def circle_fit(pts: list[Pt]) -> tuple[float, float, float]:
    """Algebraic (Kasa) circle fit on the xy points: centre x, y and radius."""
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    suu = svv = suv = suuu = svvv = suvv = svuu = 0.0
    for p in pts:
        u, v = p[0] - mx, p[1] - my
        suu += u * u
        svv += v * v
        suv += u * v
        suuu += u**3
        svvv += v**3
        suvv += u * v * v
        svuu += v * u * u
    det = suu * svv - suv * suv
    if abs(det) < 1e-12:
        return mx, my, math.sqrt((suu + svv) / n)
    uc = (0.5 * (suuu + suvv) * svv - 0.5 * (svvv + svuu) * suv) / det
    vc = (0.5 * (svvv + svuu) * suu - 0.5 * (suuu + suvv) * suv) / det
    return mx + uc, my + vc, math.sqrt(uc * uc + vc * vc + (suu + svv) / n)


def rect_box(
    centre: tuple[float, float], size: tuple[float, float], ang: float, z0: float, z1: float
) -> Box:
    c, s = math.cos(ang), math.sin(ang)
    corners = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for z in (z0, z1):
                u, w = sx * size[0] / 2, sy * size[1] / 2
                corners.append((centre[0] + c * u - s * w, centre[1] + s * u + c * w, z))
    xs, ys = [p[0] for p in corners], [p[1] for p in corners]
    return Box((min(xs), min(ys), z0), (max(xs), max(ys), z1), tuple(corners))


def disc_boxes(cx: float, cy: float, r: float, z0: float, z1: float) -> tuple[Box, ...]:
    """A round object as two squares, one turned 45 degrees: all corners on the circle (an octagon)."""
    half = r / math.sqrt(2)
    return (
        rect_box((cx, cy), (2 * half, 2 * half), 0.0, z0, z1),
        rect_box((cx, cy), (2 * half, 2 * half), math.pi / 4, z0, z1),
    )


def aabb_box(lo: Pt, hi: Pt) -> Box:
    return rect_box(
        ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2),
        (hi[0] - lo[0], hi[1] - lo[1]),
        0.0,
        lo[2],
        hi[2],
    )


# ---------------------------------------------------------------- perception data
def load_hits(path: Path) -> dict:
    res = json.loads(path.read_text(encoding="utf-8"))["result"]
    for h in res["hits"]:
        if h.get("ok"):
            h["pts"] = [tuple(p) for p in h["pts"]]
    return res


def instances(res: dict, cam: str, prompts: list[str]) -> list[dict]:
    return [h for h in res["hits"] if h["ok"] and h["cam"] == cam and h["q"] in prompts]


def table_plane(res: dict) -> float:
    t = next(
        h
        for h in res["hits"]
        if h["ok"] and h["cam"] == "agentview" and h["q"] == "table" and h["i"] == 0
    )
    return pct([p[2] for p in t["pts"]], 0.5)


def robot_points(res: dict, min_score: float = 0.5) -> list[Pt]:
    out: list[Pt] = []
    for h in res["hits"]:
        if (
            h["ok"]
            and h["cam"] == "agentview"
            and h["q"] == "robot arm"
            and h["score"] >= min_score
        ):
            out += h["pts"]
    return out


def cluster(cands: list[dict]) -> list[list[dict]]:
    """Greedy grouping of masks whose median xy lies within 6 cm of the group's first (best-scoring) mask."""
    groups: list[list[dict]] = []
    for c in sorted(cands, key=lambda h: -h["score"]):
        cx, cy = median_xy(c["pts"])
        for g in groups:
            gx, gy = median_xy(g[0]["pts"])
            if math.hypot(cx - gx, cy - gy) <= 0.06:
                g.append(c)
                break
        else:
            groups.append([c])
    return groups


def select(res: dict, variant: int, table_z: float) -> dict[str, dict]:
    """Per object: the chosen point cloud, the cameras used, the evidence (which masks)."""
    chosen: dict[str, dict] = {}
    if variant <= 1:
        for name, prompts in OBJECTS.items():
            h = next((h for h in instances(res, "agentview", [prompts[0]]) if h["i"] == 0), None)
            if h is None:
                chosen[name] = {"found": False, "why": "no mask"}
                continue
            chosen[name] = {"found": True, "pts": h["pts"], "masks": [(h["cam"], h["q"], h["i"], h["score"])],
                            "geometry": (h["centre"], h["extents"])}  # fmt: skip
        return chosen
    order = sorted(
        OBJECTS,
        key=lambda n: (
            -max([h["score"] for h in instances(res, "agentview", OBJECTS[n][:1])] or [0])
        ),
    )
    claimed: set[tuple[int, int, int]] = set()
    for name in order:
        prompts = OBJECTS[name]
        cands = []
        for h in instances(res, "agentview", prompts):
            if not plausible(h["pts"], table_z):
                continue
            v = voxels(h["pts"])
            if v and len(v & claimed) / len(v) >= CLAIM_FRAC:
                continue
            cands.append(h)
        groups = cluster(cands)
        if not groups:
            chosen[name] = {"found": False, "why": "no plausible unclaimed mask"}
            continue
        best = max(groups, key=lambda g: (len({m["q"] for m in g}), sum(m["score"] for m in g)))
        pts = [p for m in best for p in m["pts"]]
        masks = [("agentview", m["q"], m["i"], m["score"]) for m in best]
        if variant >= 3:
            ax, ay = median_xy(pts)
            for h in instances(res, "robot0_eye_in_hand", prompts):
                if plausible(h["pts"], table_z) and h["score"] >= 0.1:
                    hx, hy = median_xy(h["pts"])
                    if math.hypot(hx - ax, hy - ay) <= GATE_M:
                        pts += h["pts"]
                        masks.append(("robot0_eye_in_hand", h["q"], h["i"], h["score"]))
        chosen[name] = {"found": True, "pts": pts, "masks": masks}
        claimed |= voxels(pts)
    return chosen


def build(
    res: dict, variant: int, ext_p: tuple[float, float] = EXTENT_P, robot: bool = True
) -> dict:
    """Perceived objects for one variant: boxes, plus the numbers that go into the comparison."""
    table_z = table_plane(res)
    chosen = select(res, variant, table_z)
    robot_vox = voxels(robot_points(res)) if variant >= 4 and robot else set()
    objs: dict[str, dict] = {}
    for name, c in chosen.items():
        if not c["found"]:
            objs[name] = {"found": False, "why": c["why"]}
            continue
        pts: list[Pt] = c["pts"]
        if variant >= 4:
            pts = [
                p for p in pts
                if p[2] >= table_z + 0.005
                and (int(p[0] // VOXEL), int(p[1] // VOXEL), int(p[2] // VOXEL)) not in robot_vox
            ]  # fmt: skip
        if len(pts) < 10:
            objs[name] = {"found": False, "why": "too few points after trimming"}
            continue
        entry: dict = {"found": True, "n_points": len(pts), "masks": c["masks"]}
        if variant == 0:
            ctr, ext = c["geometry"]
            lo = (ctr[0] - ext[0] / 2, ctr[1] - ext[1] / 2, ctr[2] - ext[2] / 2)
            hi = (ctr[0] + ext[0] / 2, ctr[1] + ext[1] / 2, ctr[2] + ext[2] / 2)
            boxes = [aabb_box(lo, hi)]
        else:
            lo, hi = aabb(pts, *ext_p)
            if variant >= 4:
                lo = (lo[0], lo[1], table_z)
            boxes = [aabb_box(lo, hi)]
            if variant >= 5:
                if name in ROUND_OBJECTS:
                    cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
                    r = ((hi[0] - lo[0]) + (hi[1] - lo[1])) / 4
                    boxes = list(disc_boxes(cx, cy, r, lo[2], hi[2]))
                    entry["circle"] = [cx, cy, r]
                else:
                    ctr, size, ang = min_area_rect(pts)
                    boxes = [rect_box(ctr, size, ang, lo[2], hi[2])]
        entry["boxes"] = [
            {"lo": list(b.lo), "hi": list(b.hi), "corners": [list(c) for c in b.corners]}
            for b in boxes
        ]
        entry["aabb"] = [list(min_over(boxes)), list(max_over(boxes))]
        entry["points"] = [list(p) for p in pts[::2]]
        objs[name] = entry
    return {"table_z": table_z, "objects": objs}


def min_over(boxes: list[Box]) -> Pt:
    return tuple(min(b.lo[i] for b in boxes) for i in range(3))  # type: ignore[return-value]


def max_over(boxes: list[Box]) -> Pt:
    return tuple(max(b.hi[i] for b in boxes) for i in range(3))  # type: ignore[return-value]


def to_world(built: dict) -> CollisionWorld:
    objs = []
    for name, o in built["objects"].items():
        if not o["found"]:
            continue
        boxes = tuple(
            Box(tuple(b["lo"]), tuple(b["hi"]), tuple(tuple(c) for c in b["corners"]))
            for b in o["boxes"]
        )
        objs.append(
            WorldObject(name, name, boxes, name in (*TASK_OBJECTS, "wine bottle", "cream cheese"))
        )
    return CollisionWorld(
        (0.0, 0.0, 0.0), built["table_z"], tuple(sorted(objs, key=lambda o: o.label))
    )


# ---------------------------------------------------------------- comparison with the oracle
def iou3(a: tuple[Pt, Pt], b: tuple[Pt, Pt]) -> float:
    inter = 1.0
    for i in range(3):
        inter *= max(0.0, min(a[1][i], b[1][i]) - max(a[0][i], b[0][i]))
    va = math.prod(a[1][i] - a[0][i] for i in range(3))
    vb = math.prod(b[1][i] - b[0][i] for i in range(3))
    return inter / (va + vb - inter) if va + vb - inter > 0 else 0.0


def compare_objects(built: dict, truth: CollisionWorld) -> list[dict]:
    rows = []
    for name in OBJECTS:
        t = truth.get(name).aabb
        tc, ts = t.centre, t.size
        o = built["objects"][name]
        row: dict = {"object": name, "found": o["found"], "truth_centre": [round(v, 4) for v in tc],
                     "truth_size_cm": [round(v * 100, 1) for v in ts], "truth_aabb": [list(t.lo), list(t.hi)]}  # fmt: skip
        if not o["found"]:
            row["why"] = o["why"]
            rows.append(row)
            continue
        lo, hi = o["aabb"]
        c = [(lo[i] + hi[i]) / 2 for i in range(3)]
        s = [hi[i] - lo[i] for i in range(3)]
        exy = math.hypot(c[0] - tc[0], c[1] - tc[1])
        row.update(
            seen_centre=[round(v, 4) for v in c],
            seen_size_cm=[round(v * 100, 1) for v in s],
            centre_err_cm=[round((c[i] - tc[i]) * 100, 1) for i in range(3)],
            centre_err_xy_cm=round(exy * 100, 1),
            size_err_cm=[round((s[i] - ts[i]) * 100, 1) for i in range(3)],
            height_err_cm=round((s[2] - ts[2]) * 100, 1),
            iou3=round(iou3((tuple(lo), tuple(hi)), (t.lo, t.hi)), 3),
            correct=exy <= FOUND_XY_M,
            masks=o["masks"], n_points=o["n_points"],
        )  # fmt: skip
        rows.append(row)
    return rows


def compare_relations(built: dict, truth: CollisionWorld) -> dict:
    tr = {frozenset((r.a, r.b)): r for r in relations(truth)}
    pr = {frozenset((r.a, r.b)): r for r in relations(to_world(built))}
    rows = []
    for key in sorted(set(tr) | set(pr), key=lambda k: sorted(k)):
        t, p = tr.get(key), pr.get(key)
        a, b = sorted(key)
        rows.append(
            {
                "pair": [a, b],
                "truth": t.kind if t else None,
                "truth_gap_mm": round(t.gap_m * 1000) if t else None,
                "seen": p.kind if p else None,
                "seen_gap_mm": round(p.gap_m * 1000) if p else None,
            }  # fmt: skip
        )

    def pr_rec(kinds: tuple[str, ...]) -> dict:
        t = {k for k, r in tr.items() if r.kind in kinds}
        p = {k for k, r in pr.items() if r.kind in kinds}
        return {"truth": len(t), "seen": len(p), "both": len(t & p),
                "precision": round(len(t & p) / len(p), 2) if p else None,
                "recall": round(len(t & p) / len(t), 2) if t else None}  # fmt: skip

    both = [
        (tr[k], pr[k])
        for k in tr
        if k in pr and tr[k].kind != "supported_by" and pr[k].kind != "supported_by"
    ]
    gap_err = [abs(a.gap_m - b.gap_m) * 1000 for a, b in both]
    support_t = {k for k, r in tr.items() if r.kind == "supported_by"}
    support_p = {k for k, r in pr.items() if r.kind == "supported_by"}
    return {
        "rows": rows,
        "touching": pr_rec(("touching",)),
        "touching_or_near": pr_rec(("touching", "near")),
        "touching_gap_within_30mm": {
            "truth_touching_pairs": [sorted(k) for k, r in tr.items() if r.kind == "touching"],
            "seen_gap_mm": {
                " + ".join(sorted(k)): (round(pr[k].gap_m * 1000) if k in pr else None)
                for k, r in tr.items()
                if r.kind == "touching"
            },
            "within_30mm": sum(
                1 for k, r in tr.items() if r.kind == "touching" and k in pr and pr[k].gap_m <= 0.03
            ),
        },
        "supported_by": {
            "truth": len(support_t),
            "seen": len(support_p),
            "both": len(support_t & support_p),
        },
        "mean_abs_gap_err_mm": round(sum(gap_err) / len(gap_err), 1) if gap_err else None,
    }


def robot_check(res: dict) -> dict:
    """Perceived robot mask against the cuRobo spheres at the recorded joint angles (the truth for the arm)."""
    q = res["q"]
    sph = spheres(q)
    pts = robot_points(res)

    def near(p: Pt, s: list, slack: float = 0.03) -> bool:
        return math.dist(p, (s[0], s[1], s[2])) <= s[3] + slack

    inside = sum(1 for p in pts if any(near(p, s) for s in sph))
    covered = sum(1 for s in sph if any(near(p, s) for p in pts))
    grip = [
        h for h in res["hits"] if h["ok"] and h["cam"] == "agentview" and h["q"] == "robot gripper"
    ]
    flange = flange_position(q)
    return {
        "mask_points": len(pts),
        "precision_in_spheres": round(inside / len(pts), 2) if pts else None,
        "spheres": len(sph),
        "spheres_covered": covered,
        "recall_spheres": round(covered / len(sph), 2),
        "gripper_best_score": round(max((h["score"] for h in grip), default=0.0), 3),
        "points": [[round(v, 3) for v in p] for p in pts[:: max(1, len(pts) // 400)]],
        "spheres_xyzr": [[s[0], s[1], s[2], s[3]] for s in sph],
        "tcp": [round(v, 4) for v in res["tcp"]],
        "flange_fk": [round(v, 4) for v in flange],
        "tcp_to_flange_cm": round(math.dist(res["tcp"], flange) * 100, 1),
    }


def rack_structure(built: dict, truth: CollisionWorld) -> dict:
    """z levels of the perceived rack points (1 cm bins) against the truth's horizontal boards."""
    o = built["objects"]["wine rack"]
    if not o["found"]:
        return {"found": False}
    zs = [p[2] for p in o["points"]]
    bins: dict[int, int] = {}
    for z in zs:
        bins[int(z // 0.01)] = bins.get(int(z // 0.01), 0) + 1
    peaks = [(k / 100, v) for k, v in sorted(bins.items()) if v >= max(6, 0.06 * len(zs))]
    boards = [
        [round(b.lo[2], 3), round(b.hi[2], 3)]
        for b in truth.get("wine rack").boxes
        if b.hi[2] - b.lo[2] < 0.1 and (b.hi[0] - b.lo[0]) * (b.hi[1] - b.lo[1]) > 0.01
    ]
    return {"found": True, "z_peaks_m": [[round(z, 2), n] for z, n in peaks], "truth_boards_z_m": boards,
            "perceived_top_m": round(max(zs), 3), "truth_top_m": round(truth.get("wine rack").aabb.hi[2], 3),
            "perceived_y_range_m": [round(min(p[1] for p in o["points"]), 3), round(max(p[1] for p in o["points"]), 3)],
            "truth_y_range_m": [round(truth.get("wine rack").aabb.lo[1], 3), round(truth.get("wine rack").aabb.hi[1], 3)]}  # fmt: skip


def prompt_table(res: dict, truth: CollisionWorld) -> list[dict]:
    """For each rack prompt and camera: does any of its masks sit on the rack (centre within 5 cm)?"""
    t = truth.get("wine rack").aabb
    out = []
    for cam in ("agentview", "robot0_eye_in_hand"):
        for q in OBJECTS["wine rack"] + ["wooden cabinet", "table"]:
            ms = [h for h in res["hits"] if h["ok"] and h["cam"] == cam and h["q"] == q]
            hit = []
            for h in ms:
                cx, cy = median_xy(h["pts"])
                if (
                    t.lo[0] - 0.05 <= cx <= t.hi[0] + 0.05
                    and t.lo[1] - 0.05 <= cy <= t.hi[1] + 0.05
                    and len(h["pts"]) < 1500
                ):
                    hit.append({"i": h["i"], "score": round(h["score"], 3)})
            out.append({"cam": cam, "prompt": q, "masks": len(ms), "on_rack": hit,
                        "top_score": round(max((h["score"] for h in ms), default=0), 3)})  # fmt: skip
    return out


def analyse(out: Path) -> dict:
    truth = load_world(json.loads(LEVEL_DUMP.read_text(encoding="utf-8")))
    result: dict = {
        "scene": "L1",
        "task": "libero_goal_swap/8 seed 51",
        "variants": VARIANTS,
        "state": {},
    }
    for state in ("start", "arm"):
        res = load_hits(out / f"perception_{state}.json")
        block: dict = {"variants": {}, "robot": robot_check(res)}
        for k in range(6):
            built = build(res, k)
            comp = compare_objects(built, truth)
            ok = [r for r in comp if r["found"]]
            block["variants"][f"V{k}"] = {
                "objects": comp,
                "relations": compare_relations(built, truth) if k >= 1 else None,
                "n_found": len(ok),
                "n_correct": sum(1 for r in ok if r.get("correct")),
                "mean_centre_xy_cm": round(sum(r["centre_err_xy_cm"] for r in ok) / len(ok), 1)
                if ok
                else None,
                "mean_abs_height_err_cm": round(
                    sum(abs(r["height_err_cm"]) for r in ok) / len(ok), 1
                )
                if ok
                else None,
                "mean_iou3": round(sum(r["iou3"] for r in ok) / len(ok), 3) if ok else None,
                "table_z": round(built["table_z"], 4),
            }
            if k == 5:
                block["final"] = built
                block["rack_structure"] = rack_structure(built, truth)
        block["extent_sweep"] = {}
        for ep in EXTENT_SWEEP:
            comp = [r for r in compare_objects(build(res, 5, ep), truth) if r["found"]]
            block["extent_sweep"][f"p{ep[0] * 100:g}-p{ep[1] * 100:g}"] = {
                "mean_centre_xy_cm": round(sum(r["centre_err_xy_cm"] for r in comp) / len(comp), 2),
                "mean_abs_height_err_cm": round(
                    sum(abs(r["height_err_cm"]) for r in comp) / len(comp), 2
                ),
                "mean_abs_size_err_cm": round(
                    sum(abs(e) for r in comp for e in r["size_err_cm"]) / (3 * len(comp)), 2
                ),
                "mean_iou3": round(sum(r["iou3"] for r in comp) / len(comp), 3),
            }
        block["robot_ablation"] = {}
        for tag, use in (("with_robot_subtraction", True), ("without_robot_subtraction", False)):
            built = build(res, 5, EXTENT_P, use)
            comp = [r for r in compare_objects(built, truth) if r["found"]]
            block["robot_ablation"][tag] = {
                "points_total": sum(o["n_points"] for o in built["objects"].values() if o["found"]),
                "mean_centre_xy_cm": round(sum(r["centre_err_xy_cm"] for r in comp) / len(comp), 2),
                "mean_iou3": round(sum(r["iou3"] for r in comp) / len(comp), 3),
            }
        block["rack_prompts"] = prompt_table(res, truth)
        result["state"][state] = block
    final = to_world(result["state"]["start"]["final"])
    s4_seen = describe(final, "combo")
    s4_true = describe(truth, "combo")
    (out / "s4_perceived.txt").write_text(s4_seen + "\n", encoding="utf-8")
    (out / "s4_oracle.txt").write_text(s4_true + "\n", encoding="utf-8")
    result["s4"] = {"perceived": s4_seen, "oracle": s4_true}
    result["truth"] = {
        "table_top_z": truth.table_top_z,
        "objects": {o.label: [[list(b.lo), list(b.hi)] for b in o.boxes] for o in truth.objects},
        "rack_boards": rack_structure(result["state"]["start"]["final"], truth),
    }
    (out / "analysis.json").write_text(json.dumps(result), encoding="utf-8")
    return result


def summary(result: dict) -> None:
    for state, block in result["state"].items():
        print(f"== {state}")
        for v, d in block["variants"].items():
            rel = d["relations"]
            print(f"  {v}: found {d['n_found']}/7 correct(<=3cm xy) {d['n_correct']}/7 "
                  f"xy {d['mean_centre_xy_cm']} cm |h| {d['mean_abs_height_err_cm']} cm iou {d['mean_iou3']}"
                  + (f" touching {rel['touching']['both']}/{rel['touching']['truth']} (seen {rel['touching']['seen']})" if rel else ""))  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--aspire", type=Path, default=Path("ASPIRE"))
    p.add_argument("--out", type=Path, default=Path("data/runs/exp05_perceived_scene"))
    p.add_argument(
        "--probe",
        action="store_true",
        help="run the SAM 3 probes in the simulator (needs ASPIRE services)",
    )
    p.add_argument(
        "--analyse", action="store_true", help="offline analysis of the saved perception"
    )
    add_sam_model_arg(p)
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "sam_model.json").write_text(
        json.dumps({"sam_model": normalize_sam_model(args.sam_model)}), encoding="utf-8"
    )
    if args.probe:
        probe(args)
    if args.analyse or not args.probe:
        summary(analyse(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
