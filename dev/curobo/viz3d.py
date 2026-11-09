"""3D replay of one attach-mode run: the planner's scene cloud and every planned trajectory.

For each `plan_motion` call of the run it shows the cloud cuRobo planned on (`clouds/cloud_XXX.npy`,
before the held-object removal), the fused occupancy map if the run used `--fuse`
(`clouds/fused_XXX.npy`), the goal pose, and the planned arm motion drawn as cuRobo's collision
spheres (forward kinematics of the logged joint trajectory). A refused call shows the start pose
and the unreached goal in red. Writes one self-contained HTML page (three.js from a CDN).

    ASPIRE/.venv-libero/bin/python dev/curobo/viz3d.py data/runs/curobo/replay_c0e/attach/exp10_nodemo_a1_s52
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from ants.evalkit.panda import flange_position, spheres  # noqa: E402

BOX = np.array([[-0.2, -0.6, -0.05], [1.0, 0.6, 0.6]])  # workspace crop, robot base frame


def arr(v, trace: Path | None = None):
    if isinstance(v, dict) and "$array" in v:  # large arrays live in trace payloads
        return np.load(trace / v["$array"])
    return np.asarray(v["$array_inline"] if isinstance(v, dict) else v, dtype=float)


def crop(points: np.ndarray, n: int, rng) -> list[int]:
    keep = points[np.all((points >= BOX[0]) & (points <= BOX[1]), axis=1)]
    if len(keep) > n:
        keep = keep[rng.choice(len(keep), n, replace=False)]
    return np.round(keep * 1000).astype(int).ravel().tolist()  # mm


def arm(q) -> list[list[float]]:
    return [[float(c) for c in s[:4]] for s in spheres(list(q))]


def build(run: Path, n_points: int) -> dict:
    rng = np.random.default_rng(0)
    trace = next(run.glob("run/libero-pro/*/*/*/run-*"))
    calls = sorted(trace.glob("trace/calls/*-plan-motion"))
    frames = []
    for i, call in enumerate(calls):
        inp = json.loads((call / "input.json").read_text(encoding="utf-8"))
        out = json.loads((call / "output.json").read_text(encoding="utf-8"))
        goal = inp["args"][0]
        frame = {
            "i": i,
            "ok": bool(out.get("ok")),
            "error": (out.get("error") or {}).get("code"),
            "goal": arr(goal["position"]).round(4).tolist(),
            "points": [],
            "fused": [],
            "arm": [],
        }
        for key, name in (("points", "cloud"), ("fused", "fused")):
            f = run / "clouds" / f"{name}_{i:03d}.npy"
            if f.is_file():
                frame[key] = crop(np.load(f), n_points, rng)
        traj = out.get("trajectory")
        if traj:
            q = arr(traj["joint_positions"], trace)[:, :7]
            idx = np.unique(np.linspace(0, len(q) - 1, min(len(q), 24)).astype(int))
            frame["arm"] = [arm(q[j]) for j in idx]
            frame["ee"] = [[round(c, 4) for c in flange_position(list(qj))] for qj in q]
        else:  # refused: show where the robot was
            prev = next((f for f in reversed(frames) if f["arm"]), None)
            frame["arm"] = [prev["arm"][-1]] if prev else []
        frames.append(frame)
    bowl = run / "attach_debug" / "bowl_points.npy"
    result = json.loads((run / "result.json").read_text(encoding="utf-8"))
    return {
        "name": run.name,
        "experiment": run.parent.parent.name,
        "success": result.get("task_success"),
        "frames": frames,
        "bowl": crop(np.load(bowl), 3000, rng) if bowl.is_file() else [],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("runs", nargs="+", type=Path, help="run folders (attach mode)")
    ap.add_argument(
        "--out", type=Path, default=None, help="HTML file (default: first run/viz3d.html)"
    )
    ap.add_argument("--points", type=int, default=12000, help="max cloud points per frame")
    args = ap.parse_args()
    data = [build(r, args.points) for r in args.runs]
    html = (Path(__file__).with_name("viz3d.html")).read_text(encoding="utf-8")
    out = args.out or args.runs[0] / "viz3d.html"
    out.write_text(html.replace("/*DATA*/null", json.dumps(data, separators=(",", ":"))), "utf-8")
    print(out, f"{out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
