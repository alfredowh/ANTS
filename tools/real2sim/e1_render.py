"""Render the E1 twins (`e1_twin.py`) in the LIBERO scene and measure what the simulator built.

Each `<twins>/<clip>/twin.json` is loaded through the launcher's `"twin"` key in a fresh
`libero_goal_swap` task 8 environment (bowl on plate, acceptance seed), settled with a few no-ops,
rendered from every camera in `--cameras`, and the simulated size and position are compared with the
spec. Writes `<twins>/<clip>/<camera>.png` and `<twins>/render.json`.

    MUJOCO_GL=egl LIBERO_CONFIG_PATH=ASPIRE/.libero ASPIRE/.venv-libero/bin/python \\
        tools/real2sim/e1_render.py data/runs/real2sim_e1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aspire_launch import PerturbedEnv, body_aabb  # noqa: E402


def make_env(size: int, seed: int, spec: dict):
    from libero import benchmark, get_libero_path
    from libero.envs import OffScreenRenderEnv

    task = benchmark.get_benchmark_dict()["libero_goal_swap"]().get_task(8)
    bddl = Path(get_libero_path("bddl_files")) / task.problem_folder / task.bddl_file
    inner = OffScreenRenderEnv(bddl_file_name=str(bddl), camera_heights=size, camera_widths=size)
    inner.seed(seed)
    return PerturbedEnv(inner, spec), task.language


def render_clip(twin_path: Path, cameras: list[str], size: int, seed: int) -> dict:
    twin = json.loads(twin_path.read_text(encoding="utf-8"))
    env, language = make_env(size, seed, {"twin": {"bodies": twin["bodies"]}})
    env.reset()
    for _ in range(20):
        env.step(np.array([0.0] * 6 + [-1.0]))
    inner = env._inner.env
    sim = inner.sim
    base = sim.data.body_xpos[sim.model.body_name2id("robot0_base")]
    measured = {}
    for name, want in twin["bodies"].items():
        lo, hi = body_aabb(inner, sim.model.body_name2id(name))
        xy = (lo[:2] + hi[:2]) / 2 - base[:2]
        measured[name] = {
            "diameter_m": round(float(np.mean((hi - lo)[:2])), 4),
            "xy_base": [round(float(v), 4) for v in xy],
            "xy_error_mm": round(1000 * float(np.linalg.norm(xy - want["xy_base"])), 1),
            "z_top_m": round(float(hi[2]), 4),
        }
    for cam in cameras:
        img = sim.render(height=size, width=size, camera_name=cam)[::-1]
        Image.fromarray(img).save(twin_path.parent / f"{cam}.png")
    env._inner.close()
    return {"clip": twin_path.parent.name, "task": language, "measured": measured}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("twins", type=Path, help="e1_twin.py output folder")
    ap.add_argument("--cameras", nargs="+", default=["agentview", "birdview"])
    ap.add_argument("--size", type=int, default=480)
    ap.add_argument("--seed", type=int, default=51, help="acceptance seed for the scene")
    ap.add_argument("--limit", type=int, default=None, help="only the first N clips")
    args = ap.parse_args()
    rows = []
    for path in sorted(args.twins.glob("*/twin.json"))[: args.limit]:
        rows.append(render_clip(path, args.cameras, args.size, args.seed))
        print(json.dumps(rows[-1]["measured"]), flush=True)
    (args.twins / "render.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
