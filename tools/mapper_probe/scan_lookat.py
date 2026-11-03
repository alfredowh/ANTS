"""Look-at arm scan: IK-drive the Franka so its wrist camera fixates a scene
target from several viewpoints, and save RGB-D + pose per waypoint for
fuse_mapper.py.

Unlike scan_arm.py (joint-space raster), waypoints here are camera poses in
the world: positions on an arc around a target point (the bowl), each
oriented to look at it. Each camera pose becomes an end-effector pose via the
fixed camera-in-hand transform measured at reset, solved with the PyRoki IK
service (needs ``scripts/supervise_services.sh --providers pyroki`` on port
8116), seeded with the current joints, then driven with the same closed-loop
delta-joint formula scan_arm.py uses.

Runs under ASPIRE's .venv-libero (see docs/runbook/commands.json, command
``scene_recon.scan_lookat``). Standalone probe.
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
MAX_STEPS_PER_WAYPOINT = 150


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", default="libero_goal_swap")
    parser.add_argument("--task-id", type=int, default=8)
    parser.add_argument("--seed", type=int, default=51)
    parser.add_argument("--image-size", type=int, default=256)
    parser.add_argument(
        "--azimuths-deg",
        type=float,
        nargs="+",
        default=[-60.0, -20.0, 20.0, 60.0],
        help="Azimuths around the look-at target, 0 = behind the robot.",
    )
    parser.add_argument(
        "--heights-m",
        type=float,
        nargs="+",
        default=[0.35, 0.55],
        help="Camera heights above the look-at target per azimuth.",
    )
    parser.add_argument(
        "--radius-m", type=float, default=0.55, help="Horizontal distance from the target."
    )
    parser.add_argument(
        "--target-body",
        default="bowl",
        help="Substring matching the look-at target body (fallback: plate).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "data" / "runs" / "mapper_probe" / "frames_lookat",
    )
    return parser.parse_args()


def matrix_to_quat_wxyz(matrix: np.ndarray) -> np.ndarray:
    m = np.asarray(matrix, dtype=np.float64)
    trace = float(np.trace(m))
    if trace > 0.0:
        s = 0.5 / np.sqrt(trace + 1.0)
        return np.array(
            [0.25 / s, (m[2, 1] - m[1, 2]) * s, (m[0, 2] - m[2, 0]) * s, (m[1, 0] - m[0, 1]) * s]
        )
    if m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = 2.0 * np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])
        return np.array(
            [(m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s]
        )
    if m[1, 1] > m[2, 2]:
        s = 2.0 * np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2])
        return np.array(
            [(m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s]
        )
    s = 2.0 * np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1])
    return np.array(
        [(m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s]
    )


def quat_wxyz_to_matrix(quat: np.ndarray) -> np.ndarray:
    w, x, y, z = (float(v) for v in np.asarray(quat, dtype=np.float64).reshape(-1))
    n = np.sqrt(w * w + x * x + y * y + z * z)
    w, x, y, z = w / n, x / n, y / n, z / n
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def look_at_matrix(cam_pos: np.ndarray, target: np.ndarray) -> np.ndarray:
    """World-frame camera rotation whose -Z looks from cam_pos at target (MuJoCo convention)."""
    z_cam = cam_pos - target
    z_cam = z_cam / np.linalg.norm(z_cam)
    up = np.array([0.0, 0.0, 1.0])
    x_cam = np.cross(up, z_cam)
    if np.linalg.norm(x_cam) < 1e-6:
        x_cam = np.array([1.0, 0.0, 0.0])
    x_cam = x_cam / np.linalg.norm(x_cam)
    y_cam = np.cross(z_cam, x_cam)
    return np.column_stack((x_cam, y_cam, z_cam))


def main() -> None:
    args = parse_args()
    sys.path.insert(0, str(REPO_ROOT / "ASPIRE" / "src"))
    from cap_harness.libero.adapter import BASE_FRAME, LiberoAdapter
    from cap_harness.libero.registry import LiberoSuiteRegistry
    from cap_harness.providers.pyroki.client import PyRokiProvider

    args.out_dir.mkdir(parents=True, exist_ok=True)

    ik = PyRokiProvider()
    if not ik.health():
        raise SystemExit(
            "PyRoki IK service is not healthy at 127.0.0.1:8116 -- start it with:\n"
            "  cd ASPIRE && scripts/supervise_services.sh --profile a5500 --providers pyroki"
        )

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

    bodies = [sim.model.body_id2name(i) for i in range(sim.model.nbody)]
    match = next((b for b in bodies if args.target_body.lower() in b.lower()), None)
    if match is None:
        match = next((b for b in bodies if "plate" in b.lower()), None)
    if match is None:
        raise SystemExit(f"no body matching {args.target_body!r} or 'plate' in {bodies}")
    target_world = np.asarray(sim.data.body_xpos[sim.model.body_name2id(match)], dtype=np.float64)
    print(f"[scan-lookat] target body {match} at {target_world.round(3)}")

    cam_name = "robot0_eye_in_hand"
    cam_id = sim.model.camera_name2id(cam_name)

    def world_from_body(body_name: str) -> np.ndarray:
        body_id = sim.model.body_name2id(body_name)
        matrix = np.eye(4)
        matrix[:3, :3] = sim.data.body_xmat[body_id].reshape(3, 3)
        matrix[:3, 3] = sim.data.body_xpos[body_id]
        return matrix

    def world_from_eef_obs() -> np.ndarray:
        raw = env.env._get_observations()
        pos = np.asarray(raw["robot0_eef_pos"], dtype=np.float64)
        quat_xyzw = np.asarray(raw["robot0_eef_quat"], dtype=np.float64)
        quat_wxyz = np.array([quat_xyzw[3], quat_xyzw[0], quat_xyzw[1], quat_xyzw[2]])
        matrix = np.eye(4)
        matrix[:3, :3] = quat_wxyz_to_matrix(quat_wxyz)
        matrix[:3, 3] = pos
        return matrix

    def world_from_cam() -> np.ndarray:
        matrix = np.eye(4)
        matrix[:3, :3] = sim.data.cam_xmat[cam_id].reshape(3, 3)
        matrix[:3, 3] = sim.data.cam_xpos[cam_id]
        return matrix

    # Fixed camera-in-hand transform, measured once at reset.
    cam_in_eef = np.linalg.inv(world_from_eef_obs()) @ world_from_cam()
    base_from_world = np.linalg.inv(world_from_body("robot0_base"))

    def current_gripper_native() -> float:
        qpos = np.asarray(env.env._get_observations()["robot0_gripper_qpos"], dtype=np.float64)
        normalized = float(np.clip(qpos[0] / adapter.gripper_max_opening_m, 0.0, 1.0))
        return float(np.clip(normalized * 2.0 - 1.0, -1.0, 1.0))

    from cap_harness.contracts import Pose

    gripper_native = current_gripper_native()
    fovy = float(np.asarray(sim.model.cam_fovy)[cam_id])
    manifest = []
    wp_i = 0
    for az_deg in args.azimuths_deg:
        az = np.deg2rad(az_deg)
        for height in args.heights_m:
            cam_pos = target_world + np.array(
                [args.radius_m * np.sin(az), -args.radius_m * np.cos(az), height]
            )
            cam_rot = look_at_matrix(cam_pos, target_world)
            world_cam = np.eye(4)
            world_cam[:3, :3] = cam_rot
            world_cam[:3, 3] = cam_pos
            world_eef = world_cam @ np.linalg.inv(cam_in_eef)
            base_eef = base_from_world @ world_eef

            state = adapter.get_robot_state()
            target_pose = Pose(
                position=base_eef[:3, 3],
                quaternion_wxyz=matrix_to_quat_wxyz(base_eef[:3, :3]),
                frame=BASE_FRAME,
            )
            result = ik.solve_ik(target_pose, state)
            if not result.ok:
                print(f"[scan-lookat] waypoint {wp_i:02d}: IK failed ({result.error}) -- skipped")
                wp_i += 1
                continue
            target_joints = np.asarray(result.joint_positions, dtype=np.float64)

            for _ in range(MAX_STEPS_PER_WAYPOINT):
                current = np.array([sim.data.qpos[i] for i in idx], dtype=np.float64)
                if np.max(np.abs(target_joints - current)) < JOINT_TOLERANCE_RAD:
                    break
                native = np.empty(8, dtype=np.float64)
                native[:7] = (target_joints - current) * control_frequency
                native[7] = gripper_native
                native = np.clip(native, low, high)
                env.env.step(native)

            final = np.array([sim.data.qpos[i] for i in idx], dtype=np.float64)
            err = float(np.max(np.abs(target_joints - final)))

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

            height_px, width_px = rgb.shape[:2]
            focal = 0.5 * height_px / np.tan(np.deg2rad(fovy) / 2.0)
            intrinsics = np.array(
                [[focal, 0.0, 0.5 * width_px], [0.0, focal, 0.5 * height_px], [0.0, 0.0, 1.0]],
                dtype=np.float64,
            )

            actual = world_from_cam()
            opengl_to_image = np.diag((1.0, -1.0, -1.0, 1.0))
            world_from_cam_cv = actual @ opengl_to_image

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
                f"[scan-lookat] waypoint {wp_i:02d}: az={az_deg:+.0f} h={height:.2f} "
                f"joint_err={err:.4f} cam_pos={actual[:3, 3].round(3)} "
                f"depth[min,max]=({depth_m.min():.3f},{depth_m.max():.3f})"
            )
            wp_i += 1

    (args.out_dir / "manifest.txt").write_text("\n".join(manifest), encoding="utf-8")
    print(f"[scan-lookat] saved {len(manifest)} frames to {args.out_dir}")


if __name__ == "__main__":
    main()
