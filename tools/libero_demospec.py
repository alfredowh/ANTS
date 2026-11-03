"""Summarise LIBERO human demonstrations of one task as an object-relative DemoSpec (JSON).

Replays the stored simulator states of every demo (no rendering, no policy) and measures,
in the frames of the objects: where the gripper grasped the object, how the object was
tilted while carried, and where it was released relative to the target fixture.
Statistics are the median and the 10th-90th percentile over all demos.

Run with ASPIRE's LIBERO Python, from the ASPIRE checkout:

    LIBERO_CONFIG_PATH=$PWD/.libero .venv-libero/bin/python <ANTS>/tools/libero_demospec.py \
        <ANTS>/data/libero_demos/book_under_shelf_demo.hdf5 \
        --object yellow_book_1 --target wooden_two_layer_shelf_1 \
        --out <ANTS>/data/demospecs/libero_book_under_shelf.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import h5py
import numpy as np
from scipy.spatial.transform import Rotation


def _bddl_path(attr_bddl: str) -> str:
    try:
        from libero import get_libero_path
    except ImportError:
        from libero.libero import get_libero_path

    rel = attr_bddl.split("bddl_files/", 1)[1].replace("libero_100", "libero_90")
    return str(Path(get_libero_path("bddl_files")) / rel)


def _stats(values: list[float]) -> dict:
    a = np.asarray(values, dtype=float)
    return {
        "median": round(float(np.median(a)), 3),
        "p10": round(float(np.percentile(a, 10)), 3),
        "p90": round(float(np.percentile(a, 90)), 3),
    }


def summarise(h5: Path, obj: str, target: str, max_demos: int) -> dict:
    try:
        from libero.envs import OffScreenRenderEnv
    except ImportError:
        from libero.libero.envs import OffScreenRenderEnv

    f = h5py.File(h5, "r")
    attrs = f["data"].attrs
    env = OffScreenRenderEnv(
        bddl_file_name=_bddl_path(attrs["bddl_file_name"]),
        has_offscreen_renderer=False,
        use_camera_obs=False,
        camera_heights=64,
        camera_widths=64,
    )
    env.reset()
    sim = env.sim
    b_obj, b_tgt = sim.model.body_name2id(f"{obj}_main"), sim.model.body_name2id(f"{target}_main")
    lang = json.loads(attrs["problem_info"])["language_instruction"]
    per_demo = []
    keys = sorted(f["data"].keys(), key=lambda k: int(k.split("_")[1]))[:max_demos]
    for key in keys:
        demo = f["data"][key]
        states, ee_pos = demo["states"][()], demo["obs"]["ee_pos"][()]
        grip = demo["obs"]["gripper_states"][()]  # two finger joint positions
        width = np.abs(grip[:, 0] - grip[:, 1])
        obj_pos, obj_quat, tgt_pos, tgt_quat = [], [], [], []
        for s in states:
            sim.set_state_from_flattened(s)
            sim.forward()
            obj_pos.append(sim.data.body_xpos[b_obj].copy())
            obj_quat.append(sim.data.body_xquat[b_obj].copy())
            tgt_pos.append(sim.data.body_xpos[b_tgt].copy())
            tgt_quat.append(sim.data.body_xquat[b_tgt].copy())
        obj_pos, tgt_pos = np.array(obj_pos), np.array(tgt_pos)
        lifted = np.where(obj_pos[:, 2] > obj_pos[0, 2] + 0.01)[0]
        if not len(lifted):
            continue
        t_lift = int(lifted[0])
        closed = np.where(width[: t_lift + 1] < width[0] - 0.01)[0]
        t_grasp = int(closed[0]) if len(closed) else t_lift
        opening = np.where(width[t_lift:] > width[t_lift] + 0.01)[0]
        t_release = t_lift + int(opening[0]) if len(opening) else len(states) - 1

        def rot(q):  # MuJoCo quaternions are w, x, y, z
            return Rotation.from_quat([q[1], q[2], q[3], q[0]])

        r0 = rot(obj_quat[t_grasp])
        grasp_in_obj = r0.inv().apply(ee_pos[t_grasp] - obj_pos[t_grasp])
        tilt = [
            float(np.degrees((rot(obj_quat[t]) * r0.inv()).magnitude()))
            for t in range(t_grasp, t_release + 1)
        ]
        rel_tgt = rot(tgt_quat[t_release]).inv().apply(obj_pos[t_release] - tgt_pos[t_release])
        per_demo.append(
            {
                "grasp_in_object_frame_m": grasp_in_obj.tolist(),
                "object_tilt_at_release_deg": tilt[-1],
                "object_tilt_max_deg": max(tilt),
                "release_object_in_target_frame_m": rel_tgt.tolist(),
                "carry_max_lift_m": float(
                    obj_pos[t_grasp : t_release + 1, 2].max() - obj_pos[0, 2]
                ),
                "steps_grasp_to_release": t_release - t_grasp,
            }
        )
    n = len(per_demo)
    summary = {
        "n_demos": n,
        "grasp_in_object_frame_m": {
            ax: _stats([d["grasp_in_object_frame_m"][i] for d in per_demo])
            for i, ax in enumerate("xyz")
        },
        "object_tilt_at_release_deg": _stats([d["object_tilt_at_release_deg"] for d in per_demo]),
        "object_tilt_max_deg": _stats([d["object_tilt_max_deg"] for d in per_demo]),
        "release_object_in_target_frame_m": {
            ax: _stats([d["release_object_in_target_frame_m"][i] for d in per_demo])
            for i, ax in enumerate("xyz")
        },
        "carry_max_lift_m": _stats([d["carry_max_lift_m"] for d in per_demo]),
        "steps_grasp_to_release_at_20hz": _stats([d["steps_grasp_to_release"] for d in per_demo]),
    }
    env.close()
    return {
        "source": f"libero_demo:{h5.name}",
        "task_text": lang,
        "objects": [{"name": obj, "poses_world": {}}, {"name": target, "poses_world": {}}],
        "keyframes": [],
        "ee_path_obj": {},
        "aperture": [],
        "steps": [
            "grasp the book",
            "lift",
            "move to the shelf",
            "insert under the shelf",
            "release",
        ],
        "quality": {"demos_used": n, "demos_in_file": len(keys)},
        "summary": summary,
        "per_demo": per_demo,
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("hdf5", type=Path)
    p.add_argument("--object", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--max-demos", type=int, default=50)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    spec = summarise(args.hdf5, args.object, args.target, args.max_demos)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    print(json.dumps(spec["summary"], indent=1))


if __name__ == "__main__":
    main()
