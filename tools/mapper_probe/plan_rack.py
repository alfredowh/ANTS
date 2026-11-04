"""Wine-rack planning test: persistent fused mesh vs ASPIRE's single-frame carved cloud.

Reproduces the dev/curobo incident geometry (libero_goal_swap task 8, seed 51): the gripper
presses into the wine rack. Same cuRobo planner, same start and goals, four worlds:
none (blind control), fused mesh (robot carved out once, at scan time), single frame carved
at the start state (ASPIRE service filters), single frame uncarved. Planning only.

Runs under ASPIRE's .venv-curobo. Needs gate_truth.py output for the rack (gate_rack/).
Standalone probe: not part of synthesizer/ or adversary/.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ASPIRE" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
RUN_DIR = REPO_ROOT / "data" / "runs" / "mapper_probe"

LOGGED_CONTACT_BASE = np.array([0.477, -0.175, 0.237])  # dev/curobo/README.md, robot base frame
GRIPPER_DOWN_WXYZ = np.array([0.0, 1.0, 0.0, 0.0])
HOVER_ABOVE_M = 0.15
NEAR_ABOVE_M = 0.03
FREE_GOAL_BASE = np.array([0.35, 0.10, 0.45])
CARVE_PAD_M = 0.05


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mesh", type=Path, default=RUN_DIR / "fused_orbit_hires" / "reconstructed_scene.ply"
    )
    parser.add_argument(
        "--baseline-frames",
        type=Path,
        nargs="+",
        default=[RUN_DIR / "frames", RUN_DIR / "frames_orbit_r1", RUN_DIR / "frames_orbit_r2"],
    )
    parser.add_argument("--rack-truth", type=Path, default=RUN_DIR / "gate_rack" / "truth.json")
    parser.add_argument("--start", choices=["far_hover", "near_contact"], default="far_hover")
    parser.add_argument("--near-above-m", type=float, default=NEAR_ABOVE_M)
    parser.add_argument("--out", type=Path, default=None, help="default: plan_rack_<start>.json")
    parser.add_argument("--baseline-voxel-m", type=float, default=0.01)
    parser.add_argument("--device", default="cuda:0")
    return parser.parse_args()


def pose_from(pos: np.ndarray, quat_wxyz: np.ndarray, device: str):
    import torch
    from curobo.types import Pose

    return Pose(
        position=torch.as_tensor(pos, dtype=torch.float32, device=device).reshape(1, 3),
        quaternion=torch.as_tensor(quat_wxyz, dtype=torch.float32, device=device).reshape(1, 4),
    )


def joint_state(planner, q: np.ndarray, device: str):
    import torch
    from curobo.types import JointState

    return JointState.from_position(
        torch.as_tensor(q, dtype=torch.float32, device=device).reshape(1, -1),
        joint_names=list(planner.joint_names),
    )


def spheres_at(planner, q: np.ndarray, device: str) -> np.ndarray:
    out = planner.compute_kinematics(joint_state(planner, q, device))
    return np.asarray(out.robot_spheres.detach().cpu(), dtype=np.float64).reshape(-1, 4)


def solve_ik(pos: np.ndarray, arm_names: list[str], device: str) -> np.ndarray | None:
    from curobo.inverse_kinematics import InverseKinematics, InverseKinematicsCfg
    from curobo.types import GoalToolPose

    solver = InverseKinematics(
        InverseKinematicsCfg.create(
            robot="franka.yml",
            scene_model=None,
            collision_cache={"mesh": 1},
            num_seeds=32,
            self_collision_check=True,
        )
    )
    seed = joint_state(solver, np.array(json_home()), device)
    frame = list(solver.tool_frames)
    goal = GoalToolPose.from_poses(
        {frame[0]: pose_from(pos, GRIPPER_DOWN_WXYZ, device)},
        ordered_tool_frames=frame,
        num_goalset=1,
    )
    res = solver.solve_pose(goal, current_state=seed)
    if res.success is None or not bool(res.success.any()):
        return None
    sol = np.asarray(res.js_solution.position.detach().cpu()).reshape(-1)
    names = list(res.js_solution.joint_names)
    return np.array([sol[names.index(n)] for n in arm_names])


def json_home() -> list[float]:
    from plan_esdf import HOME_JOINTS

    return HOME_JOINTS.tolist()


def plan_to(planner, start_q: np.ndarray, goal_pos: np.ndarray, device: str) -> dict:
    from curobo.types import GoalToolPose

    frame = list(planner.tool_frames)
    goal = GoalToolPose.from_poses(
        {frame[0]: pose_from(goal_pos, GRIPPER_DOWN_WXYZ, device)},
        ordered_tool_frames=frame,
        num_goalset=1,
    )
    res = planner.plan_pose(goal, joint_state(planner, start_q, device))
    ok = res is not None and res.success is not None and bool(res.success.any())
    out: dict = {"success": ok}
    if ok:
        plan = res.get_interpolated_plan()
        last = plan.position.detach().cpu().numpy().reshape(-1, plan.position.shape[-1])[-1]
        names = list(plan.joint_names)
        q = np.array([last[names.index(n)] for n in planner.joint_names])
        tcp = planner.compute_kinematics(joint_state(planner, q, device)).tool_poses.to_dict()
        pos = np.asarray(tcp[frame[0]].position.detach().cpu()).reshape(-1)
        out["final_tcp_base"] = pos.round(4).tolist()
    return out


def inside(p: np.ndarray, lo: np.ndarray, hi: np.ndarray, margin: float = 0.0) -> bool:
    return bool(np.all(p > lo - margin) and np.all(p < hi + margin))


def main() -> None:
    args = parse_args()
    if args.out is None:
        args.out = RUN_DIR / f"plan_rack_{args.start}_{args.near_above_m:.2f}.json"
    import trimesh
    from curobo.scene import Scene
    from plan_esdf import backproject_frame, build_planner, purge_mesh_cache, to_curobo_mesh

    truth = json.loads(args.rack_truth.read_text(encoding="utf-8"))
    base = np.array(truth["robot_base_pos"])
    assert np.allclose(np.array(truth["robot_base_mat"]), np.eye(3)), (
        "base is rotated; add the transform"
    )
    rack_lo, rack_hi = np.array(truth["aabb_min"]) - base, np.array(truth["aabb_max"]) - base
    home = np.array(truth["robot_joints"])
    print(f"[rack] rack in base frame: {rack_lo.round(3)} .. {rack_hi.round(3)}")
    contact_in_rack = inside(LOGGED_CONTACT_BASE, rack_lo, rack_hi)
    print(f"[rack] logged contact inside rack box: {contact_in_rack}")

    planner = build_planner()
    starts: dict[str, np.ndarray] = {}
    for label, above in (("far_hover", HOVER_ABOVE_M), ("near_contact", args.near_above_m)):
        if label != args.start:
            continue
        q = solve_ik(
            LOGGED_CONTACT_BASE + np.array([0.0, 0.0, above]),
            list(planner.joint_names),
            args.device,
        )
        if q is None:
            raise SystemExit(f"IK found no {label} start state")
        starts[label] = q
    home_spheres = spheres_at(planner, home, args.device)

    mesh = trimesh.load(args.mesh, process=False)
    verts = np.asarray(mesh.vertices) - base
    faces = np.asarray(mesh.faces)
    d = np.linalg.norm(verts[:, None, :] - home_spheres[None, :, :3], axis=-1)
    keep_v = np.all(d > home_spheres[None, :, 3] + CARVE_PAD_M, axis=1)
    keep_f = keep_v[faces].all(axis=1)
    print(
        f"[rack] fused mesh: {len(verts)} verts, robot carve at scan pose removed "
        f"{int((~keep_v).sum())} verts"
    )
    fused_v, fused_f = verts, faces[keep_f]

    from cap_harness.providers.curobo.service import (
        _drop_sparse_voxels,
        _filter_robot_points,
        _voxelized_scene_mesh,
    )

    best, best_n = None, -1
    for fdir in args.baseline_frames:
        for name in (fdir / "manifest.txt").read_text(encoding="utf-8").splitlines():
            pts = backproject_frame(fdir, name) - base.astype(np.float32)
            n = int(np.all((pts > rack_lo - 0.02) & (pts < rack_hi + 0.02), axis=1).sum())
            if n > best_n:
                best, best_n = (fdir.name, name, pts), n
    print(f"[rack] baseline frame {best[0]}/{best[1]}: {best_n} raw points on the rack box")
    pts = best[2]
    voxel = args.baseline_voxel_m

    def single_frame_mesh(points: np.ndarray):
        points = _drop_sparse_voxels(points, voxel_size_m=voxel, min_points=3)
        return _voxelized_scene_mesh(points, voxel_size_m=voxel), points

    def rack_pts(p: np.ndarray) -> int:
        return int(np.all((p > rack_lo - 0.02) & (p < rack_hi + 0.02), axis=1).sum())

    plain_mesh, plain_pts = single_frame_mesh(pts)
    results: dict = {}
    kept: dict = {"uncarved": rack_pts(plain_pts)}
    for label, start_q in starts.items():
        spheres = spheres_at(planner, start_q, args.device)
        carved_mesh, carved_pts = single_frame_mesh(
            _filter_robot_points(pts, spheres, padding_m=CARVE_PAD_M)
        )
        kept[f"carved_at_{label}"] = rack_pts(carved_pts)
        worlds = {
            "none_blind": None,
            "fused_persistent": to_curobo_mesh("fused", fused_v, fused_f, flip=False),
            "single_frame_carved": carved_mesh,
            "single_frame_uncarved": plain_mesh,
        }
        for name, obstacle in worlds.items():
            purge_mesh_cache(planner)
            if obstacle is not None:
                planner.update_world(Scene(mesh=[obstacle]))
            row = {
                "goal_logged_contact": plan_to(planner, start_q, LOGGED_CONTACT_BASE, args.device),
                "goal_free_space": plan_to(planner, start_q, FREE_GOAL_BASE, args.device),
            }
            tcp = row["goal_logged_contact"].get("final_tcp_base")
            row["contact_plan_ends_inside_rack"] = (
                None if tcp is None else inside(np.array(tcp), rack_lo, rack_hi)
            )
            results[f"{label}/{name}"] = row
            print(f"[rack] {label}/{name}: {row}")
    print(f"[rack] rack points kept by the baseline: {kept}")

    report = {
        "scene": truth["scene"],
        "rack_box_base": [rack_lo.tolist(), rack_hi.tolist()],
        "logged_contact_inside_rack_box": contact_in_rack,
        "start_offsets_above_contact_m": {
            "far_hover": HOVER_ABOVE_M,
            "near_contact": args.near_above_m,
        },
        "baseline_frame": f"{best[0]}/{best[1]}",
        "rack_points_kept": kept,
        "results": results,
        "notes": "Goals use a gripper-down orientation, not the logged one. Baseline frame is the "
        "orbit frame with the most rack points (favours the baseline). One scene, one seed.",
    }
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[rack] wrote {args.out}")


if __name__ == "__main__":
    main()
