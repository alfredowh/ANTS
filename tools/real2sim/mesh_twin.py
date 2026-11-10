"""Mesh twin: bowl and plate shape, colour and mass estimated from a run's first camera frames.

Builds on `twin_bodies.py` (same segmentation from `clouds/cameras_000.npz` plus the SAM 3
localization). Per object it fits a radial profile r(h): the outer radius of the segmented points in
3 mm height bins around the fitted axis (bowls and plates are rotationally symmetric, so one side
seen is enough). From the profile it writes

- a visual mesh (OBJ, the profile revolved), coloured with the mean RGB of the object's pixels;
- collision boxes in the object frame (origin at the footprint centre on the table): a ring of wall
  segments following the profile plus a floor, one per LIBERO collision geom name, so the task's
  contact-based "on top of" check still finds them;
- a mass estimate: shell volume (wall thickness prior) x density prior. Mass, friction and wall
  thickness are not observable from images; they are labelled priors.

The launcher's `"twin": {"mesh": ...}` key (`tools/aspire_launch.py`, `_mesh_twin`) swaps them in.
Simulator truth (`contacts_scene.json`) is read only to score (`--score`).

    ASPIRE/.venv-libero/bin/python tools/real2sim/mesh_twin.py <run> \\
        --out <dir>/mesh_twin.json --score
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from twin_bodies import OBJECTS, first_localization, segment, table_z, truth  # noqa: E402

DENSITY_KG_M3 = 2400.0  # prior: glazed ceramic
FRICTION = [1.0, 0.005, 0.0001]  # prior: MuJoCo default sliding, torsional, rolling
WALL_M = {"bowl": 0.004, "plate": 0.004}  # prior: both are thin-walled dishes
BIN = 0.003
N_GEOMS = {"bowl": 40, "plate": 10}  # LIBERO collision geom count per body (names reused)


def coloured_cloud(path: Path) -> tuple[np.ndarray, np.ndarray]:
    z = np.load(path)
    pts, cols = [], []
    for key in z.files:
        if not key.startswith("depth_"):
            continue
        i = key.split("_")[1]
        d, k, pose = z[key].astype(float), z[f"intrinsics_{i}"], z[f"pose_{i}"]
        v, u = np.mgrid[0 : d.shape[0], 0 : d.shape[1]]
        ok = np.isfinite(d) & (d > 0.05) & (d < 3.0)
        x = (u[ok] - k[0, 2]) * d[ok] / k[0, 0]
        y = (v[ok] - k[1, 2]) * d[ok] / k[1, 1]
        pts.append((np.c_[x, y, d[ok], np.ones(ok.sum())] @ pose.T)[:, :3])
        rgb = z[f"rgb_{i}"] if f"rgb_{i}" in z.files else np.full(d.shape + (3,), 128, np.uint8)
        cols.append(rgb[ok].astype(float))
    return np.concatenate(pts), np.concatenate(cols)


def profile(pts: np.ndarray, centre: np.ndarray, z_table: float) -> np.ndarray:
    """[[h, r_outer]] from the table up, monotone smoothed, 3 mm bins."""
    h = pts[:, 2] - z_table
    r = np.linalg.norm(pts[:, :2] - centre, axis=1)
    top = float(np.percentile(h, 99))
    rows = []
    for h0 in np.arange(0.0, top, BIN):
        sel = (h >= h0) & (h < h0 + BIN)
        if sel.sum() >= 5:
            rows.append([h0 + BIN / 2, float(np.percentile(r[sel], 97))])
    prof = np.array(rows)
    prof[:, 1] = np.maximum.accumulate(prof[:, 1])  # bowls and plates widen upward
    return np.vstack([[0.0, prof[0, 1]], prof, [top, prof[-1, 1]]])


def revolve(prof: np.ndarray, wall: float | None, n: int = 48) -> tuple[np.ndarray, np.ndarray]:
    """Closed surface of revolution: outer profile, rim, inner profile (or flat top if solid)."""
    outer = [(r, h) for h, r in prof]
    if wall:
        inner = [(max(r - wall, 0.0), max(h, wall)) for h, r in prof[::-1]]
    else:
        inner = [(0.0, prof[-1, 0])]
    ring = [(0.0, 0.0)] + outer + inner + ([(0.0, wall)] if wall else [])
    th = np.linspace(0, 2 * np.pi, n, endpoint=False)
    verts = np.array([[r * math.cos(t), r * math.sin(t), h] for r, h in ring for t in th])
    faces = []
    for i in range(len(ring) - 1):
        for j in range(n):
            a, b = i * n + j, i * n + (j + 1) % n
            c, d = a + n, b + n
            faces += [[a, b, d], [a, d, c]]
    return verts, np.array(faces)


def quat_zy(yaw: float, tilt: float) -> list[float]:
    """wxyz of Rz(yaw) @ Ry(tilt)."""
    cz, sz, cy, sy = math.cos(yaw / 2), math.sin(yaw / 2), math.cos(tilt / 2), math.sin(tilt / 2)
    return [cz * cy, -sz * sy, cz * sy, sz * cy]


def collision(prof: np.ndarray, kind: str) -> list[dict]:
    n = N_GEOMS[kind]
    top, r0 = prof[-1, 0], prof[0, 1]
    wall = WALL_M[kind]
    n_floor, bands = (4, 3) if n >= 20 else (1, 1)
    floor = [
        {"type": "cylinder", "size": [r0, wall / 2], "pos": [0, 0, wall / 2], "quat": [1, 0, 0, 0]}
    ]
    floor = floor * n_floor
    az = (n - n_floor) // bands
    hs = np.linspace(0, top, bands + 1)
    rs = np.interp(hs, prof[:, 0], prof[:, 1])
    boxes = []
    for b in range(bands):
        dr, dh = rs[b + 1] - rs[b], hs[b + 1] - hs[b]
        length, tilt, rm = (
            math.hypot(dr, dh),
            math.atan2(dr, dh),
            (rs[b] + rs[b + 1]) / 2 - wall / 2,
        )
        for a in range(az):
            yaw = 2 * math.pi * a / az
            boxes.append(
                {
                    "type": "box",
                    "size": [wall / 2, math.pi * rm / az * 1.08, length / 2],
                    "pos": [rm * math.cos(yaw), rm * math.sin(yaw), (hs[b] + hs[b + 1]) / 2],
                    "quat": quat_zy(yaw, tilt),
                }
            )
    return floor + boxes


def shell_volume(prof: np.ndarray, wall: float | None) -> float:
    h, r = prof[:, 0], prof[:, 1]
    solid = float(np.sum(np.pi * ((r[1:] + r[:-1]) / 2) ** 2 * np.diff(h)))
    if not wall:
        return solid
    ri = np.maximum(r - wall, 0)
    hi = np.maximum(h, wall)
    hollow = float(np.sum(np.pi * ((ri[1:] + ri[:-1]) / 2) ** 2 * np.diff(hi)))
    return solid - hollow


def build(run: Path, out_dir: Path) -> dict:
    pts, cols = coloured_cloud(run / "clouds" / "cameras_000.npz")
    loc = first_localization(run)
    z_table = table_z(pts, np.mean(list(loc.values()), axis=0))
    bodies = {}
    for body, (word, radius) in OBJECTS.items():
        near = np.linalg.norm(pts[:, :2] - loc[word][:2], axis=1) < radius
        sel_pts, sel_cols = pts[near], cols[near]
        obj = segment(sel_pts, loc[word], radius, z_table)
        dist, idx = cKDTree(sel_pts).query(obj)  # segment() returns rows of sel_pts
        idx = idx[dist < 1e-9]
        lo, hi = np.percentile(obj[:, :2], 1, axis=0), np.percentile(obj[:, :2], 99, axis=0)
        centre = (lo + hi) / 2
        prof = profile(obj, centre, z_table)
        wall = WALL_M[word]
        verts, faces = revolve(prof, wall)
        mesh = out_dir / f"{word}.obj"
        with mesh.open("w", encoding="utf-8") as f:
            f.writelines(f"v {x:.5f} {y:.5f} {z:.5f}\n" for x, y, z in verts)
            f.writelines(f"f {a + 1} {b + 1} {c + 1}\n" for a, b, c in faces)
        rgb = np.median(sel_cols[idx], axis=0) / 255 if len(idx) else np.full(3, 0.5)
        vol = shell_volume(prof, wall)
        bodies[body] = {
            "xy_base": [round(float(v), 4) for v in centre],
            "diameter_m": round(float(2 * prof[-1, 1]), 4),
            "height_m": round(float(prof[-1, 0]), 4),
            "profile": prof.round(4).tolist(),
            "mesh": str(mesh.resolve()),
            "rgba": [round(float(c), 3) for c in rgb] + [1.0],
            "mass_kg": round(vol * DENSITY_KG_M3, 4),
            "friction": FRICTION,
            "geoms": collision(prof, word),
            "points": int(len(obj)),
        }
    return {
        "source": str(run),
        "table_z_base": round(z_table, 4),
        "priors": {"density_kg_m3": DENSITY_KG_M3, "friction": FRICTION, "wall_m": WALL_M},
        "bodies": bodies,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run", type=Path, help="finished replay run folder with clouds/cameras_000.npz")
    ap.add_argument("--out", type=Path, required=True, help="mesh_twin.json (meshes go next to it)")
    ap.add_argument("--score", action="store_true", help="add the error against simulator truth")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    spec = build(args.run, args.out.parent)
    if args.score:
        t = truth(args.run)
        scene = json.loads((args.run / "contacts_scene.json").read_text(encoding="utf-8"))
        spec["error"] = {
            b: {
                "diameter_mm": round(
                    1000 * (spec["bodies"][b]["diameter_m"] - t[b]["diameter_m"]), 1
                ),
                "xy_mm": round(
                    1000
                    * float(
                        np.linalg.norm(np.subtract(spec["bodies"][b]["xy_base"], t[b]["xy_base"]))
                    ),
                    1,
                ),
                "mass_est_kg": spec["bodies"][b]["mass_kg"],
                "mass_true_kg": scene["bodies"][b]["mass"],
            }
            for b in OBJECTS
        }
    args.out.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    print(args.run.name, json.dumps(spec.get("error", {})))


if __name__ == "__main__":
    main()
