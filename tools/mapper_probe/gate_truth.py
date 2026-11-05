"""Sim-ready gate, stage 1: ground truth of one LIBERO object (mass, pose, world vertices).

Runs under ASPIRE's .venv-libero. Writes truth.json and truth_vertices.npy for
gate_extract.py (curobo venv) and gate_settle.py (libero venv). Standalone probe.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("LIBERO_CONFIG_PATH", str(REPO_ROOT / "ASPIRE" / ".libero"))


def quat_to_mat(q: np.ndarray) -> np.ndarray:
    w, x, y, z = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", default="libero_goal_swap")
    parser.add_argument("--task-id", type=int, default=8)
    parser.add_argument("--seed", type=int, default=51)
    parser.add_argument("--body", default="akita_black_bowl_1_main")
    parser.add_argument(
        "--out-dir", type=Path, default=REPO_ROOT / "data" / "runs" / "mapper_probe" / "gate"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sys.path.insert(0, str(REPO_ROOT / "ASPIRE" / "src"))
    import mujoco
    from cap_harness.libero.adapter import LiberoAdapter
    from cap_harness.libero.registry import LiberoSuiteRegistry

    adapter = LiberoAdapter(
        registry=LiberoSuiteRegistry(), init_mode="seeded", camera_height=64, camera_width=64
    )
    adapter.reset((args.suite, args.task_id), seed=args.seed)
    model = adapter.native_env.sim.model._model
    data = adapter.native_env.sim.data._data
    body = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, args.body)
    table = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "table")
    base = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "robot0_base")

    verts = []
    for g in range(model.ngeom):
        if model.geom_bodyid[g] != body or model.geom_type[g] != mujoco.mjtGeom.mjGEOM_MESH:
            continue
        if model.geom_group[g] != 1:  # visual mesh group in robosuite objects
            continue
        mid = model.geom_dataid[g]
        adr, num = model.mesh_vertadr[mid], model.mesh_vertnum[mid]
        v = model.mesh_vert[adr : adr + num].astype(np.float64)
        verts.append(data.geom_xpos[g] + v @ data.geom_xmat[g].reshape(3, 3).T)
    if not verts:
        raise SystemExit(f"no visual mesh geoms found for {args.body}")
    world = np.concatenate(verts)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    np.save(args.out_dir / "truth_vertices.npy", world.astype(np.float32))
    table_top = float(data.xpos[table][2])
    truth = {
        "body": args.body,
        "mass_kg": float(model.body_mass[body]),
        "pos": data.xpos[body].tolist(),
        "aabb_min": world.min(axis=0).tolist(),
        "aabb_max": world.max(axis=0).tolist(),
        "table_body_z": table_top,
        "robot_joints": [
            float(data.qpos[i]) for i in adapter.native_env.env.robots[0]._ref_joint_pos_indexes
        ],
        "robot_base_pos": data.xpos[base].tolist(),
        "robot_base_mat": data.xmat[base].reshape(3, 3).tolist(),
        "n_vertices": int(len(world)),
        "scene": [args.suite, args.task_id, args.seed],
    }
    (args.out_dir / "truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
    print(json.dumps(truth, indent=2))


if __name__ == "__main__":
    main()
