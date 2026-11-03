"""Plan against the fused ESDF mesh instead of a single-frame point cloud.

A/B probe for the scene-reconstruction hypothesis, reusing the exact planner
construction ASPIRE's curobo service uses (``MotionPlannerCfg.create`` with
robot ``franka.yml``, ``update_world(Scene(mesh=...))``) but swapping the
obstacle:

- arm A (fused): orbit-scan frames -> cuRobo Mapper TSDF -> ESDF ->
  extracted triangle mesh, converted to a curobo ``Mesh`` obstacle.
- arm B (single-frame, today's path): one orbit frame back-projected to
  world points -> ASPIRE's own ``_voxelized_scene_mesh`` (the patched
  winding version the live service uses).

Same planner, same query (home -> home + 0.5 rad shoulder pan, an elbow
sweep over the table the real arm physically executed during the scans, so
the goal is kinematically valid). Reports success/failure and path length
per arm. Planning only -- nothing is executed in MuJoCo.

Runs under ASPIRE's .venv-curobo (see docs/runbook/commands.json, command
``scene_recon.plan_esdf``). Standalone probe: not part of synthesizer/ or
adversary/.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ASPIRE" / "src"))

HOME_JOINTS = np.array([0.0, -0.161, 0.0, -2.445, 0.0, 2.227, 0.785])
GOAL_PAN_OFFSET = 0.5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--frames-dir", type=Path, default=REPO_ROOT / "data" / "runs" / "mapper_probe" / "frames"
    )
    parser.add_argument("--voxel-size", type=float, default=0.01)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument(
        "--baseline-frame",
        default="middle",
        help="'middle' manifest entry, or an explicit frame filename.",
    )
    return parser.parse_args()


def fuse_mesh(frames_dir: Path, voxel_size: float, device: str):
    import torch
    from curobo.perception import Mapper, MapperCfg
    from curobo.types import CameraObservation, Pose

    manifest = (frames_dir / "manifest.txt").read_text(encoding="utf-8").splitlines()
    sample = np.load(frames_dir / manifest[0])
    height, width = sample["rgb"].shape[:2]
    config = MapperCfg(
        voxel_size=voxel_size,
        extent_meters_xyz=(2.0, 2.0, 1.5),
        grid_center=torch.tensor((0.0, 0.0, 0.85), device=device),
        truncation_distance=0.04,
        depth_minimum_distance=0.05,
        depth_maximum_distance=3.5,
        minimum_tsdf_weight=0.5,
        enable_static=False,
        num_cameras=1,
        image_height=height,
        image_width=width,
        device=device,
    )
    mapper = Mapper(config)
    for name in manifest:
        d = np.load(frames_dir / name)
        obs = CameraObservation(
            name="scan",
            rgb_image=torch.from_numpy(d["rgb"]).to(device=device, dtype=torch.uint8).unsqueeze(0),
            depth_image=torch.from_numpy(d["depth_m"])
            .to(device=device, dtype=torch.float32)
            .unsqueeze(0),
            pose=Pose.from_matrix(
                torch.from_numpy(d["world_from_cam"]).to(device=device, dtype=torch.float32)
            ),
            intrinsics=torch.from_numpy(d["intrinsics"])
            .to(device=device, dtype=torch.float32)
            .unsqueeze(0),
            depth_to_meter=1.0,
        )
        mapper.integrate(camera_observation=obs)
    mapper.compute_esdf()
    return mapper, mapper.extract_mesh(refine_iterations=2, surface_only=True), manifest


def to_numpy(value) -> np.ndarray:
    import torch

    if isinstance(value, torch.Tensor):
        return value.detach().cpu().numpy()
    return np.asarray(value)


def backproject_frame(frames_dir: Path, name: str) -> np.ndarray:
    """World-frame point cloud from one saved RGB-D frame (matches Mapper input range)."""
    d = np.load(frames_dir / name)
    depth = d["depth_m"].astype(np.float64)
    valid = (depth >= 0.05) & (depth <= 3.5)
    height, width = depth.shape
    K = d["intrinsics"].astype(np.float64)
    # Saved pose is cv convention (OpenGL flip applied); undo it for projection.
    flip = np.diag((1.0, -1.0, -1.0, 1.0))
    world_from_cam = d["world_from_cam"].astype(np.float64) @ flip
    Kinv = np.linalg.inv(K)
    u, v = np.meshgrid(np.arange(width), np.arange(height))
    cam = (Kinv @ np.stack([u[valid], v[valid], np.ones(valid.sum())])) * depth[valid]
    world = (world_from_cam[:3, :3] @ cam + world_from_cam[:3, 3:4]).T
    return world.astype(np.float32)


def to_curobo_mesh(name: str, vertices: np.ndarray, faces: np.ndarray, *, flip: bool):
    from curobo._src.geom.types import Mesh

    tris = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    if flip:
        tris = tris[:, ::-1]
    return Mesh(
        name,
        pose=[0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
        vertices=np.asarray(vertices, dtype=np.float64).tolist(),
        faces=tris.reshape(-1).tolist(),
    )


def purge_mesh_cache(planner) -> None:
    cache = getattr(
        getattr(getattr(planner, "scene_collision_checker", None), "data", None), "meshes", None
    )
    cache = getattr(cache, "wp_cache", None)
    if cache:
        cache.clear()


def build_planner():
    from curobo.motion_planner import MotionPlanner, MotionPlannerCfg

    config = MotionPlannerCfg.create(
        robot="franka.yml",
        scene_model=None,
        collision_cache={"mesh": 1},
        self_collision_check=True,
    )
    planner = MotionPlanner(config)
    planner.warmup(enable_graph=True, num_warmup_iterations=2)
    return planner


def plan_query(planner, start: np.ndarray, goal: np.ndarray, device: str) -> dict:
    import torch
    from curobo.types import JointState

    names = list(planner.joint_names)
    assert len(names) == 7, f"expected 7 joints, got {names}"
    start_state = JointState.from_position(
        torch.as_tensor(start, dtype=torch.float32, device=device).reshape(1, -1),
        joint_names=names,
    )
    goal_state = JointState.from_position(
        torch.as_tensor(goal, dtype=torch.float32, device=device).reshape(1, -1),
        joint_names=names,
    )
    t0 = time.time()
    result = planner.plan_cspace(goal_state, start_state)
    dt = time.time() - t0
    success = result is not None and result.success is not None and bool(result.success.any())
    path_len = None
    if success:
        plan = result.get_interpolated_plan()
        positions = np.asarray(plan.position.detach().cpu(), dtype=np.float64).reshape(
            -1, plan.position.shape[-1]
        )
        arm_idx = [list(plan.joint_names).index(n) for n in names]
        path_len = float(np.sum(np.linalg.norm(np.diff(positions[:, arm_idx], axis=0), axis=1)))
    return {
        "success": success,
        "seconds": round(dt, 2),
        "path_length_rad": None if path_len is None else round(path_len, 3),
    }


def main() -> None:
    args = parse_args()
    from curobo.scene import Scene

    print("[plan-esdf] fusing orbit frames ...")
    _mapper, trim, manifest = fuse_mesh(args.frames_dir, args.voxel_size, args.device)
    verts = to_numpy(trim.vertices).astype(np.float64)
    faces = to_numpy(trim.faces).astype(np.int64)
    print(f"[plan-esdf] fused mesh: {len(verts)} verts, {len(faces)} faces")

    start = HOME_JOINTS.copy()
    goal = HOME_JOINTS.copy()
    goal[0] += GOAL_PAN_OFFSET

    planner = build_planner()
    print(f"[plan-esdf] planner ready ({', '.join(planner.joint_names)})")

    outcomes = {}
    for flip in (False, True):
        obstacle = to_curobo_mesh("probe_esdf_scene", verts, faces, flip=flip)
        purge_mesh_cache(planner)
        planner.update_world(Scene(mesh=[obstacle]))
        outcomes[f"fused_flip={flip}"] = plan_query(planner, start, goal, args.device)
        print(f"[plan-esdf] fused flip={flip}: {outcomes[f'fused_flip={flip}']}")
        if outcomes[f"fused_flip={flip}"]["success"]:
            break

    try:
        from cap_harness.providers.curobo.service import _voxelized_scene_mesh

        base = args.baseline_frame
        frame_name = manifest[len(manifest) // 2] if base == "middle" else base
        points = backproject_frame(args.frames_dir, frame_name)
        print(f"[plan-esdf] baseline frame {frame_name}: {len(points)} points")
        baseline_obstacle = _voxelized_scene_mesh(points, voxel_size_m=args.voxel_size)
        purge_mesh_cache(planner)
        planner.update_world(Scene(mesh=[baseline_obstacle]))
        outcomes["single_frame"] = plan_query(planner, start, goal, args.device)
        print(f"[plan-esdf] single-frame: {outcomes['single_frame']}")
    except ImportError as exc:
        outcomes["single_frame"] = {"error": f"service import unavailable: {exc}"}
        print(f"[plan-esdf] single-frame baseline skipped: {exc}")

    print("[plan-esdf] done:", outcomes)


if __name__ == "__main__":
    main()
