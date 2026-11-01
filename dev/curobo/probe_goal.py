"""Which scene points make a cuRobo goal infeasible? Re-plan it with parts of the cloud removed.

    python dev/curobo/probe_goal.py CLOUD.npy TRACE_CALLS_DIR   X Y Z   (needs requests, numpy)

The start state and the joint goal come from the last curobo_plan_to_joints call in the trace;
X Y Z is where to look for culprit points (robot-base frame, e.g. the grasp TCP).
"""

from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path

import numpy as np
import requests

URL = "http://127.0.0.1:8118/plan"


def enc(a: np.ndarray) -> str:
    b = io.BytesIO()
    np.save(b, np.ascontiguousarray(a.astype(np.float32)), allow_pickle=False)
    return base64.b64encode(b.getvalue()).decode()


def last_request(calls: Path) -> tuple[list[float], list[float]]:
    d = sorted(calls.glob("call-*-curobo-plan-to-joints"))[-1]
    args = json.loads((d / "input.json").read_text(encoding="utf-8"))["args"]
    return args[0]["joint_positions"]["primary"]["$array_inline"], args[1]["$array_inline"]


def post(q: list[float], goal_q: list[float], cloud: np.ndarray | None) -> str:
    p = {
        "base_frame": "robot_base",
        "model": "panda",
        "arm": "primary",
        "joint_positions": {"primary": q},
        "joint_names": {"primary": [f"panda_joint{i}" for i in range(1, 8)]},
        "base_transforms": {"primary": np.eye(4).tolist()},
        "end_effector_links": {"primary": "panda_hand"},
        "target": {"type": "joints", "joint_positions": goal_q},
    }
    if cloud is not None:
        p["scene_points_base64"] = enc(cloud)
        p["voxel_size_m"] = 0.01
    r = requests.post(URL, json=p, timeout=300)
    if r.status_code == 200:
        return "FEASIBLE"
    detail = (
        r.json().get("detail")
        if r.headers.get("content-type", "").startswith("application/json")
        else r.text
    )
    return f"HTTP {r.status_code}: {str(detail)[:160]}"


def main() -> None:
    cloud = np.load(sys.argv[1])
    calls = Path(sys.argv[2])
    q, goal_q = last_request(calls)
    goal = np.array([float(v) for v in sys.argv[3:6]])
    d = np.linalg.norm(cloud - goal, axis=1)
    variants = {
        "full cloud": cloud,
        "no scene": None,
        "without table (z < 0.02)": cloud[cloud[:, 2] >= 0.02],
        "without points within 6 cm of goal": cloud[d > 0.06],
        "without points within 10 cm of goal": cloud[d > 0.10],
    }
    for name, c in variants.items():
        print(f"{name:40s} {post(q, goal_q, c)}")


if __name__ == "__main__":
    main()
