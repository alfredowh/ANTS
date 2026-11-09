"""Object-level twin from a logged run's perception: bowl and plate size and position.

Input is a finished attach-mode replay (`dev/curobo/replay_attach.py`): the first planning cloud
(`clouds/cloud_000.npy`, robot base frame, before anything is grasped) and the first
`localize_object` pose per object from the run's trace (SAM 3 mask centroid). Around that pose the
cloud is cut to points above the table, voxelised at 5 mm, and the connected component nearest the
pose is the object. Its xy box gives the centre and the mean horizontal size the diameter.

The twin spec feeds the launcher's `"twin"` key (`tools/aspire_launch.py`, `_twin`): the LIBERO
mesh is the shape prior, scaled uniformly to the diameter and moved to the centre. Simulator truth
(`contacts_scene.json`) is read only to score the twin (`--score`), never to build it.

    ASPIRE/.venv-libero/bin/python tools/real2sim/twin_bodies.py \
        data/runs/curobo/replay_c0e/attach/exp10_nodemo_a2_s51 --score
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy import ndimage

OBJECTS = {"akita_black_bowl_1_main": ("bowl", 0.15), "plate_1_main": ("plate", 0.25)}
VOXEL = 0.005


def first_localization(run: Path) -> dict[str, np.ndarray]:
    """First successful localize_object position per query word, robot base frame."""
    trace = next(run.glob("run/libero-pro/*/*/*/run-*"))
    out: dict[str, np.ndarray] = {}
    for call in sorted(trace.glob("trace/calls/*-localize-object")):
        query = json.loads((call / "input.json").read_text(encoding="utf-8"))["args"][0]
        res = json.loads((call / "output.json").read_text(encoding="utf-8"))
        if not res.get("ok") or res["geometry"]["pose"]["frame"] != "robot_base":
            continue
        for word, _ in OBJECTS.values():
            if word in query and word not in out:
                out[word] = np.asarray(res["geometry"]["pose"]["position"]["$array_inline"])
    return out


def table_z(cloud: np.ndarray, near: np.ndarray) -> float:
    """Most common height within 0.3 m of the objects: the table top."""
    pts = cloud[np.linalg.norm(cloud[:, :2] - near[:2], axis=1) < 0.3]
    hist, edges = np.histogram(pts[:, 2], bins=np.arange(-0.1, 0.3, 0.002))
    return float(edges[np.argmax(hist)] + 0.001)


def segment(cloud: np.ndarray, centre: np.ndarray, radius: float, z_table: float) -> np.ndarray:
    """Connected component of above-table points nearest the localized centre."""
    near = np.linalg.norm(cloud[:, :2] - centre[:2], axis=1) < radius
    pts = cloud[near & (cloud[:, 2] > z_table + 0.006) & (cloud[:, 2] < z_table + 0.25)]
    if not len(pts):
        return pts
    ijk = np.floor((pts - pts.min(0)) / VOXEL).astype(int)
    grid = np.zeros(ijk.max(0) + 1, dtype=bool)
    grid[tuple(ijk.T)] = True
    labels, n = ndimage.label(grid, structure=np.ones((3, 3, 3)))
    lab = labels[tuple(ijk.T)]
    d = np.linalg.norm(pts[:, :2] - centre[:2], axis=1)
    keep = lab == lab[np.argmin(d)]
    return pts[keep]


def raw_cloud(path: Path) -> np.ndarray:
    """Back-project every camera of the launcher's first-frame dump (robot base frame)."""
    z = np.load(path)
    out = []
    for key in z.files:
        if not key.startswith("depth_"):
            continue
        i = key.split("_")[1]
        d, k, pose = z[key].astype(float), z[f"intrinsics_{i}"], z[f"pose_{i}"]
        v, u = np.mgrid[0 : d.shape[0], 0 : d.shape[1]]
        ok = np.isfinite(d) & (d > 0.05) & (d < 3.0)
        x = (u[ok] - k[0, 2]) * d[ok] / k[0, 0]
        y = (v[ok] - k[1, 2]) * d[ok] / k[1, 1]
        out.append((np.c_[x, y, d[ok], np.ones(ok.sum())] @ pose.T)[:, :3])
    return np.concatenate(out)


def build(run: Path) -> dict:
    cams = run / "clouds" / "cameras_000.npz"
    if not cams.is_file():  # the planning cloud has the grasp target cut out (exclude_radius_m)
        raise RuntimeError(f"{run.name}: no clouds/cameras_000.npz; rerun with --fuse")
    cloud = raw_cloud(cams)
    loc = first_localization(run)
    z_table = table_z(cloud, np.mean(list(loc.values()), axis=0))
    bodies, info = {}, {"table_z_base": round(z_table, 4)}
    for body, (word, radius) in OBJECTS.items():
        if word not in loc:
            raise RuntimeError(f"{run.name}: no successful localize_object for {word!r}")
        pts = segment(cloud, loc[word], radius, z_table)
        lo, hi = np.percentile(pts[:, :2], 1, axis=0), np.percentile(pts[:, :2], 99, axis=0)
        bodies[body] = {
            "diameter_m": round(float(np.mean(hi - lo)), 4),
            "xy_base": [round(float(v), 4) for v in (lo + hi) / 2],
        }
        info[body] = {
            "points": len(pts),
            "height_m": round(float(np.percentile(pts[:, 2], 99) - z_table), 4),
            "localized_xy": [round(float(v), 4) for v in loc[word][:2]],
        }
    return {"source": str(run), "bodies": bodies, "info": info}


def truth(run: Path) -> dict:
    """Settled simulator truth (scoring only): xy box centre and mean horizontal size per body."""
    scene = json.loads((run / "contacts_scene.json").read_text(encoding="utf-8"))
    base = np.asarray(scene["bodies"]["robot0_base"]["pos"])
    out = {}
    for body in OBJECTS:
        lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
        for g in scene["geoms"]:
            if g["body"] != body or g.get("contype", 1) + g.get("conaffinity", 1) == 0:
                continue
            rot = np.asarray(g["xmat"]).reshape(3, 3)
            size = np.asarray(g["size"])
            half = np.abs(rot) @ (size if g["type"] == 6 else np.full(3, size.max()))
            pos = np.asarray(g["pos"])
            lo, hi = np.minimum(lo, pos - half), np.maximum(hi, pos + half)
        out[body] = {
            "diameter_m": round(float(np.mean((hi - lo)[:2])), 4),
            "xy_base": [round(float(v), 4) for v in ((lo + hi) / 2 - base)[:2]],
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("runs", nargs="+", type=Path, help="finished replay run folders")
    ap.add_argument("--out", type=Path, default=None, help="spec file (default <run>/twin.json)")
    ap.add_argument("--score", action="store_true", help="add the error against simulator truth")
    args = ap.parse_args()
    for run in args.runs:
        spec = build(run)
        if args.score:
            t = truth(run)
            spec["truth"] = t
            spec["error"] = {
                b: {
                    "diameter_mm": round(
                        1000 * (spec["bodies"][b]["diameter_m"] - t[b]["diameter_m"]), 1),
                    "xy_mm": round(1000 * float(np.linalg.norm(
                        np.subtract(spec["bodies"][b]["xy_base"], t[b]["xy_base"]))), 1),
                }
                for b in OBJECTS
            }  # fmt: skip
        out = args.out or run / "twin.json"
        out.write_text(json.dumps(spec, indent=1), encoding="utf-8")
        print(run.name, json.dumps(spec.get("error", spec["bodies"])))


if __name__ == "__main__":
    main()
