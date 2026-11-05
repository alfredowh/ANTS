"""2D top-view projection (S3 + relation layer) of the oracle scene, for the console's side panel.

Same source data as `scene3d.py` (`contacts_scene.json`), projected flat: one footprint rectangle
per labelled object (from its box geoms' rotated corners, not just center +/- size, so a rotated
or diagonal part like the wine rack's posts isn't clipped), plus the simulator's own pairwise gaps
(`scene["gaps"]`) between those objects -- the same relation data `docs/synthesizer/proposal-
collision-context.md` calls the G layer. Deliberately does not include a robot trajectory: that
needs per-step execution data this static scene file doesn't have.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ants.studio.scene3d import ROBOT_PREFIXES, _category


def _corners_xy(
    pos: list[float], xmat: list[float], size: list[float]
) -> list[tuple[float, float]]:
    """World (x, y) of a box's 8 corners, from its half-extents and row-major rotation matrix."""
    hx, hy, hz = size[0], size[1], size[2]
    out = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                lx, ly, lz = sx * hx, sy * hy, sz * hz
                wx = pos[0] + xmat[0] * lx + xmat[1] * ly + xmat[2] * lz
                wy = pos[1] + xmat[3] * lx + xmat[4] * ly + xmat[5] * lz
                out.append((wx, wy))
    return out


RELATION_MAX_MM = 150  # drop far pairs so the illustration stays legible, not exhaustive


def project_2d(scene_path: Path) -> dict[str, Any]:
    raw = json.loads(scene_path.read_text(encoding="utf-8"))
    footprints: dict[str, dict[str, Any]] = {}
    for g in raw["geoms"]:
        body = g["body"]
        if body == "world" or body.startswith(ROBOT_PREFIXES):
            continue
        info = _category(body)
        if info is None:
            continue
        label, cat = info
        if (
            g["type"] != 6 or cat == "table"
        ):  # only boxes contribute a footprint; table is background
            continue
        fp = footprints.setdefault(
            label, {"label": label, "cat": cat, "x0": None, "x1": None, "y0": None, "y1": None}
        )
        for x, y in _corners_xy(g["pos"], g["xmat"], g["size"]):
            fp["x0"] = x if fp["x0"] is None else min(fp["x0"], x)
            fp["x1"] = x if fp["x1"] is None else max(fp["x1"], x)
            fp["y0"] = y if fp["y0"] is None else min(fp["y0"], y)
            fp["y1"] = y if fp["y1"] is None else max(fp["y1"], y)

    gap_min: dict[tuple[str, str], float] = {}
    for gap in raw.get("gaps", []):
        info_a, info_b = _category(gap["a"]), _category(gap["b"])
        la = info_a[0] if info_a else None
        lb = info_b[0] if info_b else None
        if la is None or lb is None or la == lb or la not in footprints or lb not in footprints:
            continue
        key = tuple(sorted((la, lb)))
        gap_min[key] = min(gap_min.get(key, gap["dist"]), gap["dist"])

    hand = raw["bodies"].get("gripper0_eef") or raw["bodies"].get("robot0_right_hand")
    gripper = {"x": hand["pos"][0], "y": hand["pos"][1]} if hand else None

    return {
        "objects": list(footprints.values()),
        "relations": [
            {"a": a, "b": b, "mm": round(d * 1000)}
            for (a, b), d in gap_min.items()
            if d * 1000 <= RELATION_MAX_MM
        ],
        "gripper": gripper,
        "as_of": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(scene_path.stat().st_mtime)),
        "source": str(scene_path),
    }
