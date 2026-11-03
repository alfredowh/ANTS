"""Real arm-driven scan: sweep the Franka's own joints (not a camera teleport)
and save robot0_eye_in_hand RGB-D + world-frame camera pose per waypoint, for
fuse_mapper.py to reconstruct.

Drives the robot with the exact delta-joint-controller formula
cap_harness.libero.codec.LiberoActionCodec.encode uses
(``native = (target - current) * control_frequency``, clipped to the native
action bounds) so this is genuine closed-loop robot motion, not a kinematic
hack -- robot0_eye_in_hand is rigidly attached to the gripper, so its
cam_xpos/cam_xmat only move correctly through real forward kinematics.

Runs under ASPIRE's .venv-libero (see docs/runbook/commands.json, command
`scene_recon.scan_arm`). Standalone probe, see scan_orbit.py's docstring.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("LIBERO_CONFIG_PATH", str(REPO_ROOT / "ASPIRE" / ".libero"))

JOINT_TOLERANCE_RAD = 0.01
MAX_STEPS_PER_WAYPOINT = 120


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", default="libero_goal_swap")
    parser.add_argument("--task-id", type=int, default=8)
    parser.add_argument("--seed", type=int, default=51)
    parser.add_argument("--image-size", type=int, default=256)
    parser.add_argument(
        "--pan-offsets",
        type=float,
        nargs="+",
        default=[-0.5, -0.25, 0.0, 0.25, 0.5],
        help="Radians added to the reset shoulder-pan joint (robot0_joint1) per waypoint.",
    )
    parser.add_argument(
        "--lift-offsets",
        type=float,
        nargs="+",
        default=[-0.15, 0.0, 0.15],
        help=(
            "Radians added to the reset shoulder-lift joint (robot0_joint2) per waypoint. "
            "Waypoints are the pan x lift grid, rastered tilt-minor (pan outer, lift inner)."
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "data" / "runs" / "mapper_probe" / "frames_arm_full",
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
    robot = env.env.robots[0]
    idx = robot._ref_joint_pos_indexes
    low, high = adapter.action_bounds
    control_frequency = adapter.control_frequency

    home = np.array([sim.data.qpos[i] for i in idx], dtype=np.float64)
    print(f"[scan-arm] home joints: {home.round(3)}")

    cam_name = "robot0_eye_in_hand"
    cam_id = sim.model.camera_name2id(cam_name)
    fovy = float(np.asarray(sim.model.cam_fovy)[cam_id])

    def current_gripper_native() -> float:
        qpos = np.asarray(env.env._get_observations()["robot0_gripper_qpos"], dtype=np.float64)
        normalized = float(np.clip(qpos[0] / adapter.gripper_max_opening_m, 0.0, 1.0))
        return float(np.clip(normalized * 2.0 - 1.0, -1.0, 1.0))

    gripper_native = current_gripper_native()
    waypoints = [(pan, lift) for pan in args.pan_offsets for lift in args.lift_offsets]
    print(f"[scan-arm] {len(waypoints)} waypoints (pan x lift grid)")
    manifest = []
    for wp_i, (pan_offset, lift_offset) in enumerate(waypoints):
        target = home.copy()
        target[0] = home[0] + pan_offset
        target[1] = home[1] + lift_offset

        for _ in range(MAX_STEPS_PER_WAYPOINT):
            current = np.array([sim.data.qpos[i] for i in idx], dtype=np.float64)
            if np.max(np.abs(target - current)) < JOINT_TOLERANCE_RAD:
                break
            native = np.empty(8, dtype=np.float64)
            native[:7] = (target - current) * control_frequency
            native[7] = gripper_native
            native = np.clip(native, low, high)
            env.env.step(native)

        final = np.array([sim.data.qpos[i] for i in idx], dtype=np.float64)
        err = float(np.max(np.abs(target - final)))

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

        actual_pos = sim.data.cam_xpos[cam_id].copy()
        actual_rot = sim.data.cam_xmat[cam_id].reshape(3, 3).copy()
        opengl_to_image = np.diag((1.0, -1.0, -1.0, 1.0))
        world_from_cam_mj = np.eye(4)
        world_from_cam_mj[:3, :3] = actual_rot
        world_from_cam_mj[:3, 3] = actual_pos
        world_from_cam_cv = world_from_cam_mj @ opengl_to_image

        frame_path = args.out_dir / f"frame_{wp_i:03d}.npz"
        np.savez(
            frame_path,
            rgb=rgb.astype(np.uint8),
            depth_m=depth_m.astype(np.float32),
            intrinsics=intrinsics.astype(np.float32),
            world_from_cam=world_from_cam_cv.astype(np.float32),
        )
        manifest.append(frame_path.name)
        print(
            f"[scan-arm] waypoint {wp_i:02d}: pan={pan_offset:+.2f} lift={lift_offset:+.2f} "
            f"joint_err={err:.4f} cam_pos={actual_pos.round(3)} "
            f"depth[min,max]=({depth_m.min():.3f},{depth_m.max():.3f})"
        )

    (args.out_dir / "manifest.txt").write_text("\n".join(manifest), encoding="utf-8")
    print(f"[scan-arm] saved {len(manifest)} frames to {args.out_dir}")


if __name__ == "__main__":
    main()
