"""Task phases of "put the bowl on the plate", derived from logged signals.

The logs hold no ground-truth object poses, so these are proxies built from the gripper width,
the end-effector track and the perception estimate of the bowl and plate centres (the first
successful `localize_object` call of each rollout). A rollout is scored by the furthest stage it
reached; with several grasp attempts the best one counts.

Stages (a failed rollout stops at the first one that did not hold):
  1 gripper closed            2 closed within `NEAR_BOWL_M` of the bowl     3 bowl held (gripper
  stopped on an object)       4 lifted by `LIFT_M`                          5 over the plate at
  release (or at the end)     6 released                                   7 task success
"""

from __future__ import annotations

import json
import math
from pathlib import Path

CLOSED = 0.5  # gripper state below this counts as closed (open is ~1.0)
HELD_WIDTH = 0.03  # a closed gripper that stays wider than this is holding something
NEAR_BOWL_M = 0.10
LIFT_M = 0.05
OVER_PLATE_M = 0.12

STAGES = [
    "gripper closed",
    "closed at the bowl",
    "bowl held",
    "bowl lifted",
    "over the plate",
    "released",
    "task success",
]
FAIL_LABELS = [
    "never closed the gripper",
    "closed away from the bowl",
    "grasp missed (closed on nothing)",
    "bowl not lifted",
    "carried but not over the plate",
    "not released over the plate",
    "released over the plate, task not done",
]


def targets_from_run(run: Path) -> dict[str, list[float]]:
    """Estimated bowl and plate centres from the first successful localization of each."""
    found: dict[str, list[float]] = {}
    for d in sorted((run / "trace" / "calls").glob("call-*-localize-object")):
        try:
            query = str(json.loads((d / "input.json").read_text(encoding="utf-8"))["args"][0])
            out = json.loads((d / "output.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError, IndexError):
            continue
        pos = ((out.get("geometry") or {}).get("pose") or {}).get("position")
        pos = pos["$array_inline"] if isinstance(pos, dict) else pos
        for name in ("bowl", "plate"):
            if name in query and name not in found and out.get("ok") and pos:
                found[name] = pos
    return found


def _grasps(grip: list[float]) -> list[tuple[int, int | None]]:
    """(close index, release index or None) for every closure of the gripper."""
    spans, i = [], 0
    while i < len(grip):
        if grip[i] < CLOSED:
            j = next((k for k in range(i, len(grip)) if grip[k] >= CLOSED), None)
            spans.append((i, j))
            i = j if j is not None else len(grip)
        else:
            i += 1
    return spans


def task_phases(
    t: list[float],
    pos: list[list[float] | None],
    grip: list[float | None],
    targets: dict[str, list[float]],
    success: bool,
) -> dict | None:
    """Furthest stage reached, its label and the numbers behind it; None without a full track."""
    if not t or any(p is None for p in pos) or any(g is None for g in grip):
        return None
    bowl, plate = targets.get("bowl"), targets.get("plate")
    xy = lambda a, b: math.dist(a[:2], b[:2])  # noqa: E731
    best: dict = {"depth": 0}
    grasps = _grasps(grip)
    for n, (ic, ir) in enumerate(grasps):
        end = ir if ir is not None else len(grip) - 1
        window = sorted(grip[ic + 15 : ic + 40] or grip[ic + 5 :] or grip[ic:])
        width = window[len(window) // 2]
        bowl_m = xy(pos[ic], bowl) if bowl else None
        lift = max(p[2] for p in pos[ic : end + 1]) - pos[ic][2]
        plate_m = xy(pos[end], plate) if plate else None
        ok = [
            True,
            bowl_m is None or bowl_m <= NEAR_BOWL_M,
            width >= HELD_WIDTH,
            lift >= LIFT_M,
            plate_m is None or plate_m <= OVER_PLATE_M,
            ir is not None,
        ]
        depth = next((k for k, v in enumerate(ok) if not v), len(ok))
        if n == 0 or depth > best["depth"]:
            best = {
                "depth": depth,
                "close_t": round(t[ic], 3),
                "release_t": None if ir is None else round(t[ir], 3),
                "bowl_cm": None if bowl_m is None else round(bowl_m * 100, 1),
                "hold_width": round(width, 3),
                "lift_cm": round(lift * 100, 1),
                "plate_cm": None if plate_m is None else round(plate_m * 100, 1),
            }
    best["grasps"] = len(grasps)
    if success:
        best["depth"] = len(FAIL_LABELS)
    best["label"] = "success" if success else FAIL_LABELS[best["depth"]]
    return best
