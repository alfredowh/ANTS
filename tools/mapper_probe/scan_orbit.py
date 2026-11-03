"""Orbit-scan a LIBERO scene and save RGB-D + world-frame camera pose per frame.

Runs under ASPIRE's .venv-libero (see docs/runbook/commands.json, command
`scene_recon.scan`). Produces the frames `fuse_mapper.py` consumes to fuse a
cuRobo Mapper TSDF/ESDF and extract a mesh of the scene.

Standalone probe: not part of synthesizer/ or adversary/, imports cap_harness
read-only to reuse its proven camera conventions (adapter.py's
`_camera_observation`) instead of re-deriving them.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]

os.environ.setdefault("LIBERO_CONFIG_PATH", str(REPO_ROOT / "ASPIRE" / ".libero"))


def quat_wxyz_from_matrix(mat: np.ndarray) -> np.ndarray:
    m = mat
    t = np.trace(m)
    if t > 0:
        s = np.sqrt(t + 1.0) * 2.0
        w = 0.25 * s
        x = (m[2, 1] - m[1, 2]) / s
        y = (m[0, 2] - m[2, 0]) / s
        z = (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2.0
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2.0
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2.0
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s
    q = np.array([w, x, y, z], dtype=np.float64)
    return q / np.linalg.norm(q)


def look_at_rotation(eye: np.ndarray, target: np.ndarray, world_up=(0.0, 0.0, 1.0)) -> np.ndarray:
    """MuJoCo/OpenGL camera convention: local forward = -z, local up = +y."""
    f = target - eye
    f = f / np.linalg.norm(f)
    up = np.asarray(world_up, dtype=np.float64)
    s = np.cross(f, up)
    s = s / np.linalg.norm(s)
    u = np.cross(s, f)
    return np.column_stack([s, u, -f])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", default="libero_goal_swap")
    parser.add_argument("--task-id", type=int, default=8)
    parser.add_argument("--seed", type=int, default=51)
    parser.add_argument(
        "--camera", default="agentview", choices=["agentview", "robot0_eye_in_hand"]
    )
    parser.add_argument("--n-frames", type=int, default=16)
    parser.add_argument("--image-size", type=int, default=256)
    parser.add_argument("--target-x", type=float, default=0.0)
    parser.add_argument("--target-y", type=float, default=0.0)
    parser.add_argument("--target-z", type=float, default=0.85, help="scene look-at height (m)")
    parser.add_argument(
        "--radius",
        type=float,
        default=None,
        help="orbit radius (m); default from the camera's own distance",
    )
    parser.add_argument(
        "--height",
        type=float,
        default=None,
        help="orbit camera height (m); default from the camera's own height",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "data" / "runs" / "mapper_probe" / "frames",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sys.path.insert(0, str(REPO_ROOT / "ASPIRE" / "src"))
    from cap_harness.libero.adapter import LiberoAdapter
    from cap_harness.libero.registry import LiberoSuiteRegistry

    args.out_dir.mkdir(parents=True, exist_ok=True)

    adapter = LiberoAdapter(
        registry=LiberoSuiteRegistry(),
        init_mode="seeded",
        camera_height=args.image_size,
        camera_width=args.image_size,
    )
    adapter.reset((args.suite, args.task_id), seed=args.seed)
    env = adapter.native_env
    sim = env.sim

    cam_name = args.camera
    cam_id = sim.model.camera_name2id(cam_name)
    parent_body = int(sim.model.cam_bodyid[cam_id])
    body_name = (
        sim.model.body_id2name(parent_body) if hasattr(sim.model, "body_id2name") else parent_body
    )
    print(f"[scan] camera {cam_name!r} parent body: {body_name} (id={parent_body})")
    if body_name != "world":
        print(
            f"[scan] WARNING: {cam_name!r} is not parented to a static body "
            "(cam_pos/cam_quat will be interpreted relative to its moving parent, not world)"
        )

    orig_pos = sim.model.cam_pos[cam_id].copy()
    target = np.array([args.target_x, args.target_y, args.target_z])
    radius = (
        args.radius
        if args.radius is not None
        else max(0.55, float(np.linalg.norm(orig_pos[:2] - target[:2])))
    )
    cam_height = args.height if args.height is not None else max(0.95, float(orig_pos[2]))

    fovy = float(np.asarray(sim.model.cam_fovy)[cam_id])
    manifest = []
    for i in range(args.n_frames):
        theta = 2.0 * np.pi * i / args.n_frames
        eye = target + np.array(
            [radius * np.cos(theta), radius * np.sin(theta), cam_height - target[2]]
        )
        rot = look_at_rotation(eye, target)
        sim.model.cam_pos[cam_id] = eye
        sim.model.cam_quat[cam_id] = quat_wxyz_from_matrix(rot)
        sim.forward()

        actual_pos = sim.data.cam_xpos[cam_id].copy()
        actual_rot = sim.data.cam_xmat[cam_id].reshape(3, 3).copy()

        raw = env.env._get_observations(force_update=True)
        rgb = np.ascontiguousarray(np.asarray(raw[f"{cam_name}_image"])[::-1])
        depth_raw = np.asarray(raw[f"{cam_name}_depth"], dtype=np.float64)
        if depth_raw.ndim == 3 and depth_raw.shape[2] == 1:
            depth_raw = depth_raw[:, :, 0]
        depth_raw = np.ascontiguousarray(depth_raw[::-1])

        extent = sim.model.stat.extent
        far = sim.model.vis.map.zfar * extent
        near = sim.model.vis.map.znear * extent
        depth_m = near / (1.0 - depth_raw * (1.0 - near / far))

        height, width = rgb.shape[:2]
        focal = 0.5 * height / np.tan(np.deg2rad(fovy) / 2.0)
        intrinsics = np.array(
            [[focal, 0.0, 0.5 * width], [0.0, focal, 0.5 * height], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )

        opengl_to_image = np.diag((1.0, -1.0, -1.0, 1.0))
        world_from_cam_mj = np.eye(4)
        world_from_cam_mj[:3, :3] = actual_rot
        world_from_cam_mj[:3, 3] = actual_pos
        world_from_cam_cv = world_from_cam_mj @ opengl_to_image

        frame_path = args.out_dir / f"frame_{i:03d}.npz"
        np.savez(
            frame_path,
            rgb=rgb.astype(np.uint8),
            depth_m=depth_m.astype(np.float32),
            intrinsics=intrinsics.astype(np.float32),
            world_from_cam=world_from_cam_cv.astype(np.float32),
        )
        manifest.append(frame_path.name)
        print(
            f"[scan] frame {i:02d}: eye={eye.round(3)} "
            f"depth[min,max]=({depth_m.min():.3f},{depth_m.max():.3f}) "
            f"rgb_mean={rgb.mean():.1f}"
        )

    (args.out_dir / "manifest.txt").write_text("\n".join(manifest), encoding="utf-8")
    print(f"[scan] saved {len(manifest)} frames to {args.out_dir}")


if __name__ == "__main__":
    main()
