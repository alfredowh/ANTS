"""What cuRobo saw at each plan call of one run: cloud, robot spheres, straight vs planned path.

Needs numpy and scipy, so run it with ASPIRE's Python from the ANTS root:

    PYTHONPATH=src ../ASPIRE/.venv-libero/bin/python dev/curobo/plan_data.py RUN_DIR CLOUD_DIR OUT.json

RUN_DIR is the harness run folder (has trace/ and payloads/), CLOUD_DIR the `cloud_dir` of the
launcher's `planner` spec (one cloud per plan call, in call order). For every
`curobo-plan-to-joints` call the output holds the start and goal spheres, which spheres touch
cloud points, the straight joint interpolation start to goal (what a planner without collision
checks would do) and cuRobo's path when it found one, with the number of colliding spheres along each.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from ants.evalkit.panda import flange_position, link_frames, spheres


def arr(x):
    if isinstance(x, dict) and "$array_inline" in x:
        return np.asarray(x["$array_inline"], dtype=float)
    return x


CLEARANCE_M = 0.015  # cuRobo checks a voxelised cloud: count points this close to a sphere
CARVE_M = 0.01  # the service carves max(voxel 0.01 m, ANTS_CARVE_MARGIN_M); the margin was 0.0


def carve(cloud: np.ndarray, q, width: float) -> np.ndarray:
    """The cuRobo service deletes cloud points within CARVE_M of the robot spheres at the start."""
    keep = np.ones(len(cloud), dtype=bool)
    for cx, cy, cz, r, _ in spheres(list(q), width):
        keep &= np.linalg.norm(cloud - [cx, cy, cz], axis=1) - r >= CARVE_M
    return cloud[keep]


BOWL_BOX = (0.12, 0.12, 0.04, 0.22)  # hand frame: |x|, |y| below, z from, z to (m) along the fingers
MIN_Z = 0.06  # base frame: the plate top is at about 0.02 to 0.05 m, the table at -0.01
ATTACH_R = 0.025  # radius of the spheres that stand in for the held bowl
HELD_BELOW = 0.5  # normalised gripper state: closed on the bowl is about 0.05, open is 1


def hand_frame(q, width: float) -> np.ndarray:
    return np.asarray(link_frames(list(q), width)["panda_hand"], dtype=float)


def bowl_points(cloud: np.ndarray, q, width: float) -> np.ndarray:
    """Cloud points inside the box where the bowl hangs under the hand (hand frame)."""
    t = hand_frame(q, width)
    local = (cloud - t[:3, 3]) @ t[:3, :3]
    bx, by, z0, z1 = BOWL_BOX
    inside = (np.abs(local[:, 0]) < bx) & (np.abs(local[:, 1]) < by)
    inside &= (local[:, 2] > z0) & (local[:, 2] < z1)
    return inside & (cloud[:, 2] > MIN_Z)  # not the table or the plate under it


def attach_spheres(local_pts: np.ndarray) -> np.ndarray:
    """Cover the bowl's points with spheres on a grid of ATTACH_R, in the hand frame."""
    cells = np.unique(np.floor(local_pts / ATTACH_R).astype(int), axis=0)
    return (cells + 0.5) * ATTACH_R


def world_spheres(local: np.ndarray, q, width: float) -> np.ndarray:
    t = hand_frame(q, width)
    return local @ t[:3, :3].T + t[:3, 3]


def attached_flags(local: np.ndarray, q, width: float, tree: cKDTree) -> list[bool]:
    """For each attached sphere at pose `q`: does it touch a cloud point?"""
    centres = world_spheres(local, q, width)
    return [bool(tree.query_ball_point(c, ATTACH_R + CLEARANCE_M)) for c in centres]


def attached_hits(local: np.ndarray, q, width: float, tree: cKDTree) -> int:
    return sum(attached_flags(local, q, width, tree))


def colliding(q, width: float, tree: cKDTree, pts: np.ndarray) -> list[dict]:
    out = []
    for cx, cy, cz, r, link in spheres(list(q), width):
        idx = tree.query_ball_point([cx, cy, cz], r + CLEARANCE_M)
        if idx:
            out.append({"link": link, "n": len(idx), "pts": pts[idx[:200]].round(3).tolist()})
    return out


def path_report(qs, width: float, tree, pts) -> dict:
    hits = [len(colliding(q, width, tree, pts)) for q in qs]
    return {
        "tcp": [[round(v, 4) for v in flange_position(list(q))] for q in qs],
        "hits": hits,
        "first_hit": next((i for i, h in enumerate(hits) if h), None),
    }


def main(run: Path, clouds: Path, out: Path) -> None:
    calls = sorted((run / "trace" / "calls").glob("*curobo-plan-to-joints"))
    plans = []
    for i, call in enumerate(calls):
        inp = json.loads((call / "input.json").read_text(encoding="utf-8"))
        res = json.loads((call / "output.json").read_text(encoding="utf-8"))
        state, goal = inp["args"][0], arr(inp["args"][1])
        q0 = arr(state["joint_positions"]["primary"])
        opening = float(state["gripper_positions"]["primary"])
        width = 0.04 * min(1.0, opening)  # the state is normalised: 1 open, 0 closed
        raw = np.load(clouds / f"cloud_{i:03d}.npy")
        cloud = carve(raw, q0, width)
        tree = cKDTree(cloud)
        t = np.linspace(0, 1, 40)[:, None]
        plan = {
            "call": call.name,
            "ok": bool(res.get("ok")),
            "message": (res.get("error") or {}).get("message"),
            "start": [s[:5] for s in spheres(list(q0), width)],
            "goal": [s[:5] for s in spheres(list(goal), width)],
            "start_hits": colliding(q0, width, tree, cloud),
            "goal_hits": colliding(goal, width, tree, cloud),
            "straight": path_report(q0 + t * (goal - q0), width, tree, cloud),
            "gripper": width,
            "n_points": len(raw),
            "n_carved": len(raw) - len(cloud),
        }
        if res.get("ok"):
            qs = np.load(run / res["trajectory"]["joint_positions"]["$array"])
            plan["planned"] = path_report(qs[:, :7], width, tree, cloud)
        if opening < HELD_BELOW:
            mask = bowl_points(cloud, q0, width)
            local = (cloud[mask] - hand_frame(q0, width)[:3, 3]) @ hand_frame(q0, width)[:3, :3]
            rest = cloud[~mask]
            att = attach_spheres(local)
            near = cKDTree(world_spheres(att, q0, width)).query(rest)[0]
            rest = rest[near > ATTACH_R + CARVE_M]  # the start-pose carve also covers the bowl
            tree2 = cKDTree(rest)
            n_steps = 40
            t = np.linspace(0, 1, n_steps)[:, None]
            straight_q = q0 + t * (goal - q0)
            after = {
                "held": True,
                "removed": cloud[mask].round(3).tolist(),
                "attached_local": att.round(4).tolist(),
                "attached_start": world_spheres(att, q0, width).round(4).tolist(),
                "attached_goal": world_spheres(att, goal, width).round(4).tolist(),
                "goal_hits": colliding(goal, width, tree2, rest),
                "attached_goal_hits": attached_hits(att, goal, width, tree2),
                "attached_goal_flags": attached_flags(att, goal, width, tree2),
                "straight_hits": [
                    len(colliding(q, width, tree2, rest)) + attached_hits(att, q, width, tree2)
                    for q in straight_q
                ],
            }
            if res.get("ok"):
                after["planned_hits"] = [
                    len(colliding(q, width, tree2, rest)) + attached_hits(att, q, width, tree2)
                    for q in qs[:, :7]
                ]
            plan["after"] = after
        else:
            plan["after"] = {"held": False}
        keep = cloud[(cloud[:, 0] > -0.1) & (cloud[:, 0] < 1.0) & (abs(cloud[:, 1]) < 0.7) & (cloud[:, 2] < 0.9)]
        cells = np.unique(np.floor(keep / 0.02).astype(int), axis=0)
        plan["cloud"] = (cells * 2 + 1).tolist()  # centimetres, 2 cm grid
        plans.append(plan)
    out.write_text(json.dumps({"run": str(run), "plans": plans}), encoding="utf-8")
    bad = [p for p in plans if not p["ok"]]
    print(f"{len(plans)} plans, {len(bad)} failed -> {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
