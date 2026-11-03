"""Fuse orbit-scan frames (scan_orbit.py) into a cuRobo Mapper TSDF/ESDF,
extract a mesh, and render a few shaded views.

Runs under ASPIRE's .venv-curobo (see docs/runbook/commands.json, command
`scene_recon.fuse`). Standalone probe: not part of synthesizer/ or
adversary/; proves the reconstruction before anyone wires it into an owned
package (System 2's `plan_motion`/`ss_cur` is the intended online consumer,
see docs/perception/scene-reconstruction-probe.md).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch

REPO_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--frames-dir", type=Path, default=REPO_ROOT / "data" / "runs" / "mapper_probe" / "frames"
    )
    parser.add_argument(
        "--out-dir", type=Path, default=REPO_ROOT / "data" / "runs" / "mapper_probe"
    )
    parser.add_argument("--voxel-size", type=float, default=0.01)
    parser.add_argument("--truncation-distance", type=float, default=0.04)
    parser.add_argument(
        "--extent", type=float, nargs=3, default=(2.0, 2.0, 1.5), metavar=("X", "Y", "Z")
    )
    parser.add_argument(
        "--grid-center", type=float, nargs=3, default=(0.0, 0.0, 0.85), metavar=("X", "Y", "Z")
    )
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--n-render-views", type=int, default=3)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    from curobo.perception import Mapper, MapperCfg
    from curobo.types import CameraObservation, Pose

    manifest = (args.frames_dir / "manifest.txt").read_text(encoding="utf-8").splitlines()
    print(f"[fuse] {len(manifest)} frames to integrate")

    sample = np.load(args.frames_dir / manifest[0])
    height, width = sample["rgb"].shape[:2]

    config = MapperCfg(
        voxel_size=args.voxel_size,
        extent_meters_xyz=tuple(args.extent),
        grid_center=torch.tensor(args.grid_center, device=args.device),
        truncation_distance=args.truncation_distance,
        depth_minimum_distance=0.05,
        depth_maximum_distance=3.5,
        minimum_tsdf_weight=0.5,
        enable_static=False,
        num_cameras=1,
        image_height=height,
        image_width=width,
        device=args.device,
    )
    mapper = Mapper(config)
    print(f"[fuse] mapper initialized: {mapper.memory_usage_mb():.1f} MB")

    for name in manifest:
        d = np.load(args.frames_dir / name)
        rgb = torch.from_numpy(d["rgb"]).to(device=args.device, dtype=torch.uint8).unsqueeze(0)
        depth = (
            torch.from_numpy(d["depth_m"]).to(device=args.device, dtype=torch.float32).unsqueeze(0)
        )
        intrinsics = (
            torch.from_numpy(d["intrinsics"])
            .to(device=args.device, dtype=torch.float32)
            .unsqueeze(0)
        )
        pose = Pose.from_matrix(
            torch.from_numpy(d["world_from_cam"]).to(device=args.device, dtype=torch.float32)
        )
        obs = CameraObservation(
            name="scan",
            rgb_image=rgb,
            depth_image=depth,
            pose=pose,
            intrinsics=intrinsics,
            depth_to_meter=1.0,
        )
        mapper.integrate(camera_observation=obs)
        print(f"[fuse] integrated {name}")

    print(f"[fuse] post-integration mapper memory: {mapper.memory_usage_mb():.1f} MB")

    mapper.compute_esdf()
    mesh = mapper.extract_mesh(refine_iterations=2, surface_only=True)
    n_vertices = mesh.vertices.shape[0] if hasattr(mesh.vertices, "shape") else len(mesh.vertices)
    print(f"[fuse] extracted mesh: {n_vertices} vertices, {len(mesh.faces)} faces")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    mesh_path = args.out_dir / "reconstructed_scene.ply"
    mesh.save_as_mesh(str(mesh_path))
    print(f"[fuse] saved mesh to {mesh_path}")

    from PIL import Image

    img_shape = (height, width)
    render_frames = manifest[:: max(1, len(manifest) // max(1, args.n_render_views))][
        : args.n_render_views
    ]
    for i, name in enumerate(render_frames):
        d = np.load(args.frames_dir / name)
        intrinsics = torch.from_numpy(d["intrinsics"]).to(device=args.device, dtype=torch.float32)
        pose = Pose.from_matrix(
            torch.from_numpy(d["world_from_cam"]).to(device=args.device, dtype=torch.float32)
        )
        shaded = mapper.render_shaded(intrinsics, pose, img_shape)
        arr = shaded.detach().cpu().numpy()
        if arr.dtype != np.uint8:
            arr = (np.clip(arr, 0.0, 1.0) * 255).astype(np.uint8)
        out_png = args.out_dir / f"reconstructed_view_{i}.png"
        Image.fromarray(arr[..., :3] if arr.ndim == 3 and arr.shape[-1] >= 3 else arr).save(out_png)
        print(f"[fuse] saved render {out_png}")

    print("[fuse] done")


if __name__ == "__main__":
    main()
