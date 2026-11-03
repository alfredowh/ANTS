"""Read a run's simulator contact log: which arm part pressed on which object, and when.

Input: `contacts.jsonl` (one line per env step, written by `tools/aspire_launch.py` when the scene
spec has a `contacts` key), the scene dump next to it, and the ASPIRE run directory (`episode/`,
`source/program-result.json`). Output: a plain dict used by the experiment runner, the prompt text
and the run viewer. The simulator is the only source; nothing here is estimated by a model.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

from ants.adversary.collision_world import _label
from ants.evalkit.panda import spheres

ROBOT = ("robot0", "gripper0", "mount0")
MIN_STEPS = 10  # a pair in contact for fewer steps than this is a touch, not a block
MIN_FORCE_N = 5.0


def part_name(body: str) -> str:
    """A readable name for a robot body."""
    if body.startswith("robot0_link"):
        return "arm link " + body.removeprefix("robot0_link")
    if "tip" in body:
        return "fingertip"
    if "finger" in body:
        return "finger"
    if body.startswith("gripper0"):
        return "hand"
    return body


def _rows(run_dir: Path) -> list[dict]:
    path = run_dir / "episode" / "steps.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def analyse(
    contacts: Path,
    run_dir: Path,
    scene: dict,
    base: tuple[float, float, float],
    arm_every: int = 12,
) -> dict:
    """Summarise one rollout. `scene` is the scene dump, `base` the robot base position (world)."""
    roots = {n: b["root"] for n, b in scene["bodies"].items()}
    geom_top = {}
    for g in scene["geoms"]:
        geom_top[g["name"]] = g["pos"][2] + max(abs(v) for v in g["size"][:3])  # rough, see `top_m`
    lines = [json.loads(x) for x in contacts.read_text(encoding="utf-8").splitlines() if x]
    pairs: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"steps": [], "fn": [], "pts": [], "geoms": defaultdict(int)}
    )
    for ln in lines:
        seen = set()
        for c in ln["contacts"]:
            r1, r2 = c["b1"].startswith(ROBOT), c["b2"].startswith(ROBOT)
            if r1 == r2:
                continue
            body_r, body_o, geom_o = (
                (c["b1"], c["b2"], c["g2"]) if r1 else (c["b2"], c["b1"], c["g1"])
            )
            if body_r.startswith("mount0"):
                continue
            key = (part_name(body_r), _label(roots.get(body_o, body_o)))
            rec = pairs[key]
            if (key, ln["step"]) not in seen:
                rec["steps"].append(ln["step"])
                seen.add((key, ln["step"]))
            rec["fn"].append(c["fn"])
            rec["pts"].append([c["pos"][i] - base[i] for i in range(3)])
            rec["geoms"][str(geom_o)] += 1
    events = []
    for (part, obj), rec in pairs.items():
        steps = sorted(set(rec["steps"]))
        expected = obj == "bowl" and part in ("finger", "fingertip")
        n = len(rec["fn"])
        geom = max(rec["geoms"], key=rec["geoms"].get)
        events.append(
            {
                "part": part,
                "object": obj,
                "geom": geom,
                "steps": [steps[0], steps[-1]],
                "n_steps": len(steps),
                "fn_mean": round(sum(rec["fn"]) / n, 2),
                "fn_max": round(max(rec["fn"]), 2),
                "point": [round(sum(p[i] for p in rec["pts"]) / n, 3) for i in range(3)],
                "expected": expected,
                "blocking": (not expected)
                and len(steps) >= MIN_STEPS
                and sum(rec["fn"]) / n >= MIN_FORCE_N,
            }
        )
    events.sort(key=lambda e: -e["n_steps"])
    rows = _rows(run_dir)
    q = [r["robot_state"]["joint_positions"]["primary"]["$array_inline"] for r in rows]
    tcp = [
        r["robot_state"]["end_effector_poses"]["primary"]["position"]["$array_inline"] for r in rows
    ]
    grip = [r["robot_state"]["gripper_positions"]["primary"] for r in rows]
    tgt = [r["action"]["arms"]["primary"]["target"]["$array_inline"] for r in rows]
    err = [
        max(abs(a - b) for a, b in zip(t, qq, strict=True)) for t, qq in zip(tgt, q, strict=True)
    ]
    for e in events:
        zs = [tcp[i][2] for i in range(e["steps"][0] - 1, min(e["steps"][1], len(tcp)))]
        e["tcp_z"] = [round(min(zs), 3), round(max(zs), 3)] if zs else None
    result = json.loads((run_dir / "source" / "program-result.json").read_text(encoding="utf-8"))
    failed = [
        {
            "call": c["index"],
            "tool": c["tool"],
            "status": (c.get("outputs_summary") or {}).get("status") or c.get("failure_code"),
            "steps": (c.get("outputs_summary") or {}).get("steps_executed"),
        }
        for c in result.get("calls", [])
        if not c.get("ok")
    ]
    outcome = json.loads((run_dir / "outcome.json").read_text(encoding="utf-8"))
    limits = ((-2.8973, 2.8973), (-1.7628, 1.7628), (-2.8973, 2.8973), (-3.0718, -0.0698),
              (-2.8973, 2.8973), (-0.0175, 3.7525), (-2.8973, 2.8973))  # fmt: skip
    margin = min(
        (min(v - lo, hi - v) for row in q for v, (lo, hi) in zip(row, limits, strict=True)),
        default=0.0,
    )  # no steps: the program never moved the arm
    overlay_events = [e for e in events if e["blocking"] or not e["expected"] and e["n_steps"] >= 3]
    return {
        "success": bool(outcome.get("task_success")),
        "reason": outcome.get("termination_reason"),
        "steps": len(rows),
        "failed_calls": failed,
        "events": events,
        "blocking": [e for e in events if e["blocking"]],
        "blocked_steps": len({s for e in events if e["blocking"] for s in range(e["steps"][0], e["steps"][1] + 1)}),
        "joint_margin_rad": round(margin, 3),
        "tcp_range_z": [round(min(p[2] for p in tcp), 3), round(max(p[2] for p in tcp), 3)] if tcp else None,
        "overlay": {
            "path": [[i, *[round(v, 4) for v in tcp[i]], round(err[i], 3), round(grip[i], 3)] for i in range(0, len(rows), 3)],
            "arm": [{"step": i, "spheres": spheres(q[i], 0.04 * min(1.0, max(0.0, grip[i])))} for i in range(0, len(rows), arm_every)],
            "events": overlay_events,
            "failed_calls": failed,
        },
    }  # fmt: skip


def rail_top_m(scene: dict, geom_name: str, base_z: float) -> float | None:
    """Top of one collision geom (box) in the base frame; used to name the thing that was hit."""
    for g in scene["geoms"]:
        if g["name"] == geom_name and g["type"] == 6:
            r = g["xmat"]
            half = sum(abs(r[6 + j]) * g["size"][j] for j in range(3))
            return round(g["pos"][2] + half - base_z, 3)
    return None


def evidence_text(a: dict, scene: dict, base_z: float, level: int = 1) -> str:
    """The contact evidence for a repair message. level 1: contacts; 3 adds the stall readings."""
    lines = [
        "Simulator contact log for the failed run above (robot_base frame, metres; "
        f"the run lasted {a['steps']} simulation steps):"
    ]
    fc = a["failed_calls"]
    if fc:
        lines.append(
            "- Failed calls: "
            + ", ".join(
                f"#{c['call']} {c['tool']} ({c['status']} after {c['steps']} steps)" for c in fc
            )
        )
    for e in a["blocking"]:
        top = rail_top_m(scene, e["geom"], base_z)
        part = f"{e['part']} body" if e["part"] == "hand" else e["part"]
        lines.append(
            f"- Unexpected contact: the gripper {part} pressed on the {e['object']} "
            f"(simulator geom {e['geom']}) during steps {e['steps'][0]} to {e['steps'][1]} "
            f"({e['n_steps']} steps in contact), mean normal force {e['fn_mean']:.0f} N, "
            f"max {e['fn_max']:.0f} N, mean contact point ({e['point'][0]:.3f}, {e['point'][1]:.3f}, "
            f"{e['point'][2]:.3f})"
            + (f"; the top of that geom is at z = {top:.3f}" if top else "")
            + "."
        )
    exp = [e for e in a["events"] if e["expected"]]
    if exp:
        lines.append(
            "- Expected contact (grasp, not a problem): "
            + ", ".join(f"{e['part']} on the {e['object']}" for e in exp)
            + "."
        )
    others = [e for e in a["events"] if not e["expected"] and not e["blocking"]]
    if others:
        lines.append(
            "- Brief touches: "
            + ", ".join(f"{e['part']} on {e['object']} ({e['n_steps']} steps)" for e in others)
            + "."
        )
    if level >= 3:
        for e in a["blocking"]:
            if e["tcp_z"]:
                lines.append(
                    f"- While blocked, the end-effector point (the point between the fingertips) was at "
                    f"z = {e['tcp_z'][0]} to {e['tcp_z'][1]}; the contact point on the {e['object']} was "
                    f"at z = {e['point'][2]}."
                )
        lines.append(
            "- No other arm part was blocked, and the joints were not at a limit "
            f"(smallest margin {a['joint_margin_rad']} rad)."
        )
    return "\n".join(lines)


def shifted_evidence(a: dict, dx: float, dy: float) -> dict:
    """Copy of the analysis with every contact point moved (for the placebo variant)."""
    out = json.loads(json.dumps(a))
    for key in ("events", "blocking"):
        for e in out[key]:
            e["point"] = [round(e["point"][0] + dx, 3), round(e["point"][1] + dy, 3), e["point"][2]]
    return out


def distance(a: list[float], b: list[float]) -> float:
    return math.dist(a, b)
