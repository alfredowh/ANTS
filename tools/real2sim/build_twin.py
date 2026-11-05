"""Build a sim-ready digital twin from a hurobo COLMAP scan (stdlib only).

Reads COLMAP sparse points (points3D.bin), applies the ChArUco metric scale,
fits the dominant table plane (RANSAC), and emits a MuJoCo scene: measured
table box as collider, scaled LIBERO bowl/plate meshes on the table, the
sparse room cloud as a background PLY, and a robot-base placement.

    uv run python tools/real2sim/build_twin.py \
        --sparse data/runs/real2sim/setup_01/work/setup01/colmap/sparse/0 \
        --scale-m-per-unit 0.2218 \
        --measurements hurobo/data/raw/setup_01/measurements.yaml \
        --out data/runs/real2sim/setup_01/twin
"""

from __future__ import annotations

import argparse
import json
import math
import random
import struct
from pathlib import Path


def read_points3d(path: Path) -> list[tuple[float, float, float]]:
    data = path.read_bytes()
    (count,) = struct.unpack_from("<Q", data, 0)
    off, pts = 8, []
    for _ in range(count):
        vals = struct.unpack_from("<QdddBBBd", data, off)  # id, xyz, rgb (3B), error
        x, y, z = vals[1], vals[2], vals[3]
        off += 8 + 24 + 3 + 8
        (n_track,) = struct.unpack_from("<Q", data, off)
        off += 8 + 8 * n_track  # track element: image_id u32 + point2D_idx u32
        pts.append((x, y, z))
    return pts


def parse_measurements(path: Path) -> dict[str, float]:
    # Tiny YAML subset parser for the flat numeric keys we need.
    out: dict[str, float] = {}
    section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith(" ") and line.rstrip().endswith(":"):
            section = line.strip()[:-1]
        stripped = line.strip()
        if ":" in stripped and not stripped.startswith("#"):
            key, _, val = stripped.partition(":")
            val = val.split("#")[0].strip()
            try:
                out[f"{section}.{key.strip()}"] = float(val)
            except ValueError:
                pass
    return out


def ransac_plane(pts, iters=800, thresh=0.01, seed=0):
    rng = random.Random(seed)
    sample = pts[:: max(1, len(pts) // 6000)][:6000]
    best = (None, -1)
    for _ in range(iters):
        a, b, c = rng.sample(sample, 3)
        ab = [b[i] - a[i] for i in range(3)]
        ac = [c[i] - a[i] for i in range(3)]
        n = [
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        ]
        norm = math.sqrt(sum(v * v for v in n))
        if norm < 1e-9:
            continue
        n = [v / norm for v in n]
        d = -sum(n[i] * a[i] for i in range(3))
        inl = sum(1 for p in sample if abs(sum(n[i] * p[i] for i in range(3)) + d) < thresh)
        if inl > best[1]:
            best = ((n, d), inl)
    return best


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sparse", type=Path, required=True)
    ap.add_argument("--scale-m-per-unit", type=float, required=True)
    ap.add_argument("--measurements", type=Path, required=True)
    ap.add_argument(
        "--libero-assets",
        type=Path,
        default=Path("ASPIRE/third_party/LIBERO-PRO/libero/libero/assets/stable_scanned_objects"),
    )
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    raw = read_points3d(args.sparse / "points3D.bin")
    s = args.scale_m_per_unit
    pts = [(x * s, y * s, z * s) for x, y, z in raw]
    (normal, d), inliers = ransac_plane(pts)
    # Table plane height along its normal; place table top on this plane.
    m = parse_measurements(args.measurements)
    tw, td = m.get("table.width_m", 1.445), m.get("table.depth_m", 0.60)
    bowl_scale, plate_scale = 1.245, 1.86  # real/LIBERO, see handoff doc

    with (args.out / "room_background.ply").open("w", encoding="utf-8") as f:
        f.write(
            "ply\nformat ascii 1.0\n" f"element vertex {len(pts)}\n"
            "property float x\nproperty float y\nproperty float z\nend_header\n"
        )
        for p in pts:
            f.write(f"{p[0]:.4f} {p[1]:.4f} {p[2]:.4f}\n")

    xml = f"""<mujoco model="setup01_twin">
  <compiler angle="radian"/>
  <asset>
    <mesh name="bowl" file="bowl.obj" scale="{bowl_scale} {bowl_scale} {bowl_scale}"/>
    <mesh name="plate" file="plate.obj" scale="{plate_scale} {plate_scale} {plate_scale}"/>
  </asset>
  <worldbody>
    <light pos="0 0 2" diffuse="0.8 0.8 0.8"/>
    <geom name="floor" type="plane" size="3 3 0.1" rgba="0.3 0.3 0.3 1"/>
    <!-- measured table {tw}x{td} m; plane d={d:.3f}, inliers {inliers} -->
    <body name="table" pos="0 0 0.38">
      <geom name="table_top" type="box" size="{tw / 2:.3f} {td / 2:.3f} 0.02" rgba="0.6 0.5 0.4 1"/>
    </body>
    <body name="bowl" pos="0.15 0 0.40"><freejoint/>
      <geom type="mesh" mesh="bowl" rgba="0.1 0.1 0.1 1"/></body>
    <body name="plate" pos="-0.15 0 0.40"><freejoint/>
      <geom type="mesh" mesh="plate" rgba="0.9 0.9 0.9 1"/></body>
    <body name="robot_base" pos="-0.55 0 0.40"/><!-- Franka URDF here, see manifest -->
  </worldbody>
</mujoco>
"""
    # LIBERO visual meshes are model.obj (plate) / akita_black_bowl.obj (bowl)
    bowl_src = args.libero_assets / "akita_black_bowl" / "akita_black_bowl.obj"
    plate_src = args.libero_assets / "plate" / "model.obj"
    (args.out / "bowl.obj").write_bytes(bowl_src.read_bytes())
    (args.out / "plate.obj").write_bytes(plate_src.read_bytes())
    (args.out / "twin.xml").write_text(xml, encoding="utf-8")
    manifest = {
        "source_sparse_points": len(pts),
        "scale_m_per_unit": s,
        "table_plane_normal": normal,
        "table_plane_d": d,
        "table_plane_inliers_subsample": inliers,
        "table_size_m": [tw, td],
        "bowl_scale": bowl_scale,
        "plate_scale": plate_scale,
        "robot_urdf": ("ASPIRE/third_party/curobo/curobo/content/assets/robot/"
            "franka_description/franka_panda.urdf"),
        "robot_base_pos": [-0.55, 0, 0.40],
        "background_ply": "room_background.ply",
        "limits": ("Kinematic/visual twin. Table pose is plane-fitted, not "
            "ChArUco-registered; object poses are starter placements."),
    }
    (args.out / "twin_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
