"""Sim-ready gate, stage 2: crop one object out of the fused mesh and check its geometry.

Runs under ASPIRE's .venv-curobo (trimesh, scipy). Needs gate_truth.py output.
Writes gate_<tag>_report.json (geometry checks), recon_hull.stl and truth_hull.stl
(object-local, z-up) for gate_settle.py. Thresholds are fixed up front via flags,
not tuned to pass. Standalone probe.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import trimesh
from scipy.spatial import cKDTree

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = REPO_ROOT / "data" / "runs" / "mapper_probe"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mesh", type=Path, default=RUN_DIR / "fused_hires" / "reconstructed_scene.ply"
    )
    parser.add_argument("--gate-dir", type=Path, default=RUN_DIR / "gate")
    parser.add_argument("--tag", default="fused_hires")
    parser.add_argument("--margin-m", type=float, default=0.015, help="crop margin beyond true box")
    parser.add_argument("--floor-clearance-m", type=float, default=0.004)
    parser.add_argument("--scale", type=float, default=1.0, help="negative control: scale the crop")
    parser.add_argument("--max-chamfer-mean-mm", type=float, default=5.0)
    parser.add_argument("--max-chamfer-p95-mm", type=float, default=10.0)
    parser.add_argument("--max-bbox-err-mm", type=float, default=10.0)
    parser.add_argument("--max-hull-volume-err", type=float, default=0.15)
    return parser.parse_args()


def chamfer_mm(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    d_ab = cKDTree(b).query(a)[0] * 1000.0
    d_ba = cKDTree(a).query(b)[0] * 1000.0
    both = np.concatenate([d_ab, d_ba])
    return {
        "mean": float(both.mean()),
        "p95": float(np.percentile(both, 95)),
        "recon_to_truth_mean": float(d_ab.mean()),
        "truth_to_recon_mean": float(d_ba.mean()),
    }


def local_hull(points: np.ndarray, center_xy: np.ndarray, floor_z: float) -> trimesh.Trimesh:
    local = points - np.array([center_xy[0], center_xy[1], floor_z])
    return trimesh.convex.convex_hull(local)


def main() -> None:
    args = parse_args()
    truth = json.loads((args.gate_dir / "truth.json").read_text(encoding="utf-8"))
    truth_v = np.load(args.gate_dir / "truth_vertices.npy").astype(np.float64)
    lo, hi = np.array(truth["aabb_min"]), np.array(truth["aabb_max"])
    center_xy = 0.5 * (lo[:2] + hi[:2])
    floor_z = float(lo[2])

    scene = trimesh.load(args.mesh, process=False)
    verts = np.asarray(scene.vertices)
    inside = (
        (verts[:, 0] > lo[0] - args.margin_m)
        & (verts[:, 0] < hi[0] + args.margin_m)
        & (verts[:, 1] > lo[1] - args.margin_m)
        & (verts[:, 1] < hi[1] + args.margin_m)
        & (verts[:, 2] > floor_z + args.floor_clearance_m)
        & (verts[:, 2] < hi[2] + args.margin_m)
    )
    keep_faces = inside[scene.faces].all(axis=1)
    crop = trimesh.Trimesh(vertices=verts, faces=scene.faces[keep_faces], process=False)
    crop.remove_unreferenced_vertices()
    parts = crop.split(only_watertight=False)
    if not parts:
        raise SystemExit("crop is empty: the fused mesh has no surface at the object")
    crop = max(parts, key=lambda m: len(m.faces))
    if args.scale != 1.0:
        centre = crop.vertices.mean(axis=0)
        crop.vertices = centre + (crop.vertices - centre) * args.scale

    watertight_raw = bool(crop.is_watertight)
    repaired = crop.copy()
    trimesh.repair.fill_holes(repaired)
    trimesh.repair.fix_normals(repaired)
    watertight_repaired = bool(repaired.is_watertight)

    pts = np.asarray(crop.vertices)
    cd = chamfer_mm(pts, truth_v)
    bbox_err = np.abs((pts.max(axis=0) - pts.min(axis=0)) - (hi - lo)).max() * 1000.0
    recon_hull = local_hull(pts, center_xy, floor_z)
    truth_hull = local_hull(truth_v, center_xy, floor_z)
    vol_err = abs(recon_hull.volume - truth_hull.volume) / truth_hull.volume

    checks = {
        "chamfer_mean": bool(cd["mean"] <= args.max_chamfer_mean_mm),
        "chamfer_p95": bool(cd["p95"] <= args.max_chamfer_p95_mm),
        "bbox_error": bool(bbox_err <= args.max_bbox_err_mm),
        "hull_volume": bool(vol_err <= args.max_hull_volume_err),
        "convex_hull_watertight": bool(recon_hull.is_watertight),
    }
    report = {
        "tag": args.tag,
        "mesh": str(args.mesh),
        "object": truth["body"],
        "crop": {"vertices": len(crop.vertices), "faces": len(crop.faces)},
        "raw_watertight": watertight_raw,
        "repaired_watertight": watertight_repaired,
        "chamfer_mm": cd,
        "bbox_err_mm": float(bbox_err),
        "hull_volume_m3": {"recon": float(recon_hull.volume), "truth": float(truth_hull.volume)},
        "hull_volume_rel_err": float(vol_err),
        "thresholds": {
            "chamfer_mean_mm": args.max_chamfer_mean_mm,
            "chamfer_p95_mm": args.max_chamfer_p95_mm,
            "bbox_err_mm": args.max_bbox_err_mm,
            "hull_volume_rel_err": args.max_hull_volume_err,
        },
        "checks": checks,
        "geometry_pass": all(checks.values()),
        "note": "raw_watertight is informational: the underside is never observed, so the "
        "collision body is the convex hull (loses the bowl's concavity).",
    }
    (args.gate_dir / f"gate_{args.tag}_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    recon_hull.export(args.gate_dir / f"recon_hull_{args.tag}.stl")
    truth_hull.export(args.gate_dir / "truth_hull.stl")
    crop.export(args.gate_dir / f"crop_{args.tag}.ply")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
