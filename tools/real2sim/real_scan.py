"""Real tabletop scan -> metric object meshes, from a phone video with the ChArUco board in view.

Camera poses come from the board (OpenCV ChArUco, metric, board frame: x along the 7-square side,
z up out of the board). The white objects are separated from the wooden table by colour (low
saturation), and a voxel grid above the table is carved: a voxel survives if it falls inside the
object mask in at least `--keep` of the views that see it (visual hull). Connected components of
the hull are the objects. Per object it writes a mesh (convex hull, OBJ), the metric size, a mass
estimate (hull volume x fill x density prior) and the mean colour.

A visual hull cannot see concavities (the inside of the bowl), and mass and friction are not
observable from video: they are labelled priors in the output, not measurements.

Run with the hurobo venv (OpenCV with aruco, scipy, trimesh):

    hurobo/.venv/bin/python tools/real2sim/real_scan.py \
        hurobo/data/raw/setup_01/table_scene_zoom_02.mp4 \
        --setup hurobo/data/raw/setup_01/measurements.yaml --out data/runs/real2sim_real/setup_01
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import trimesh
import yaml
from scipy import ndimage

# Priors (not measured): glazed ceramic tableware.
DENSITY_KG_M3 = 2400.0
FRICTION_PRIOR = {"sliding": 0.6, "note": "ceramic on rubber pads, literature range 0.5-0.8"}


def board_from(setup: dict) -> cv2.aruco.CharucoBoard:
    c = setup["charuco"]
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    return cv2.aruco.CharucoBoard(
        (c["squares_x"], c["squares_y"]), c["square_length_m"], c["marker_length_m"], d
    )


def detect(board, frame, k, dist, min_corners: int):
    """Board pose (R, t: board -> camera) or None; tries the plain and inverted image."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    best = None
    for img in (gray, 255 - gray):
        for legacy in (False, True):
            board.setLegacyPattern(legacy)
            cc, ci, _, _ = cv2.aruco.CharucoDetector(board).detectBoard(img)
            if (
                ci is not None
                and len(ci) >= min_corners
                and (best is None or len(ci) > len(best[1]))
            ):
                best = (cc, ci, legacy)
    if best is None:
        return None
    board.setLegacyPattern(best[2])
    obj, img = board.matchImagePoints(best[0], best[1])
    ok, rvec, tvec = cv2.solvePnP(obj, img, k, dist, flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        return None
    err = cv2.projectPoints(obj, rvec, tvec, k, dist)[0].reshape(-1, 2) - img.reshape(-1, 2)
    return (
        cv2.Rodrigues(rvec)[0],
        tvec.ravel(),
        float(np.sqrt((err**2).sum(1).mean())),
        len(best[1]),
    )


def object_mask(frame, sat_max: int, val_min: int) -> np.ndarray:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m = ((hsv[..., 1] < sat_max) & (hsv[..., 2] > val_min)).astype(np.uint8)
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8)).astype(bool)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("videos", nargs="+", type=Path)
    ap.add_argument("--setup", type=Path, required=True, help="measurements.yaml (board, table)")
    ap.add_argument(
        "--intrinsics", type=Path, default=None, help="npz (default: s24 next to data/)"
    )
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--every", type=int, default=3, help="use every Nth frame")
    ap.add_argument("--min-corners", type=int, default=12)
    ap.add_argument("--voxel", type=float, default=0.002, help="carving voxel, metres")
    ap.add_argument("--keep", type=float, default=0.85, help="fraction of views that must agree")
    ap.add_argument("--sat-max", type=int, default=95)
    ap.add_argument("--val-min", type=int, default=80)
    args = ap.parse_args()

    setup = yaml.safe_load(args.setup.read_text(encoding="utf-8"))
    intr = args.intrinsics or args.setup.parents[2] / "camera_intrinsics_s24.npz"
    z = np.load(intr)
    k, dist = z["camera_matrix"], z["dist_coeffs"]
    board = board_from(setup)
    t = setup["table"]
    lift = float(setup["charuco"].get("tablet_thickness_m", 0.0))  # board surface above tabletop

    views = []
    for video in args.videos:
        cap = cv2.VideoCapture(str(video))
        cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 0)  # intrinsics are for the stored landscape frames
        i = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if i % args.every == 0:
                pose = detect(board, frame, k, dist, args.min_corners)
                if pose and pose[2] < 2.0:
                    # OpenCV's board frame has y down the board image and z into the table; the
                    # table frame (measurements.yaml) has y toward the top of the image and z up.
                    pose = (pose[0] @ np.diag([1.0, -1.0, -1.0]), *pose[1:])
                    und = cv2.undistort(frame, k, dist)
                    views.append(
                        (
                            pose[0],
                            pose[1],
                            object_mask(und, args.sat_max, args.val_min),
                            und,
                            pose[2],
                        )
                    )
            i += 1
    if len(views) < 10:
        raise SystemExit(f"only {len(views)} views with the board found")
    print(
        f"{len(views)} posed views, median reprojection {np.median([v[4] for v in views]):.2f} px"
    )

    # Grid over the tabletop, board frame; z from the tabletop up to 12 cm.
    lo = np.array([t["left_edge_x_m"], t["near_edge_y_m"], -lift + 0.003])
    hi = np.array([t["right_edge_x_m"], t["top_edge_y_m"], -lift + 0.10])
    n = np.ceil((hi - lo) / args.voxel).astype(int)
    g = np.stack(
        np.meshgrid(
            *[lo[a] + (np.arange(n[a]) + 0.5) * args.voxel for a in range(3)], indexing="ij"
        ),
        -1,
    ).reshape(-1, 3)
    inside = np.zeros(len(g), np.int32)
    seen = np.zeros(len(g), np.int32)
    colour = np.zeros((len(g), 3))
    h, w = views[0][2].shape
    box = np.array(
        [[x, y, zz] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for zz in (lo[2], hi[2])]
    )
    for rot, tr, mask, img, _ in views:
        # White wall and curtain behind the table look like objects; outside the image of the
        # table volume everything is background.
        bc = box @ rot.T + tr
        if np.all(bc[:, 2] > 0.05):
            poly = (bc[:, :2] / bc[:, 2:] * [k[0, 0], k[1, 1]] + [k[0, 2], k[1, 2]]).astype(
                np.int32
            )
            roi = np.zeros(mask.shape, np.uint8)
            cv2.fillConvexPoly(roi, cv2.convexHull(poly), 1)
            mask = mask & roi.astype(bool)
        pc = g @ rot.T + tr
        front = pc[:, 2] > 0.05
        uv = pc[:, :2] / np.where(front, pc[:, 2], 1)[:, None] * [k[0, 0], k[1, 1]] + [
            k[0, 2],
            k[1, 2],
        ]
        u, v = uv[:, 0].astype(int), uv[:, 1].astype(int)
        vis = front & (u >= 0) & (u < w) & (v >= 0) & (v < h)
        hit = np.zeros(len(g), bool)
        hit[vis] = mask[v[vis], u[vis]]
        seen += vis
        inside += hit
        colour[hit] += img[v[hit], u[hit], ::-1]
    keep = (seen >= 0.3 * len(views)) & (inside >= args.keep * np.maximum(seen, 1))
    occ = keep.reshape(n)
    labels, nlab = ndimage.label(occ, structure=np.ones((3, 3, 3)))
    sizes = ndimage.sum(occ, labels, range(1, nlab + 1))
    args.out.mkdir(parents=True, exist_ok=True)
    objects = []
    for lab in np.argsort(sizes)[::-1][:4] + 1:
        sel = (labels.ravel() == lab) & keep
        pts = g[sel]
        if len(pts) < 200:
            continue
        pts_t = pts + [0, 0, lift]  # tabletop frame: z = 0 on the table
        hull = trimesh.convex.convex_hull(pts_t)
        ext = pts_t.max(0) - pts_t.min(0)
        rgb = colour[sel].sum(0) / np.maximum(inside[sel].sum(), 1)
        objects.append(
            {
                "voxels": int(len(pts)),
                "centre_xy": pts_t[:, :2].mean(0).round(4).tolist(),
                "extent_m": ext.round(4).tolist(),
                "height_m": round(float(pts_t[:, 2].max()), 4),
                "diameter_m": round(float(ext[:2].mean()), 4),
                "hull_volume_m3": round(float(hull.volume), 6),
                "rgb": [round(float(c)) for c in rgb],
                "hull": hull,
            }
        )
    # Name by shape: the flattest large component is the plate, the tallest the bowl.
    named = {}
    if objects:
        named["plate"] = min(objects, key=lambda o: o["height_m"] / o["diameter_m"])
        rest = [o for o in objects if o is not named["plate"]]
        if rest:
            named["bowl"] = max(rest, key=lambda o: o["height_m"])
    fill = {"bowl": 0.25, "plate": 0.6}  # prior: solid fraction of the hull (bowl is hollow)
    report = {
        "views": len(views),
        "voxel_m": args.voxel,
        "keep": args.keep,
        "objects": {},
        "priors": {
            "density_kg_m3": DENSITY_KG_M3,
            "fill_fraction": fill,
            "friction": FRICTION_PRIOR,
        },
    }
    for name, o in named.items():
        o["hull"].export(args.out / f"{name}_hull.obj")
        o.pop("hull")
        o["mass_kg_prior"] = round(o["hull_volume_m3"] * fill[name] * DENSITY_KG_M3, 3)
        m = setup.get(name) or {}
        if "diameter_m" in m:
            o["error_vs_tape_mm"] = {
                "diameter": round(1000 * (o["diameter_m"] - m["diameter_m"]), 1),
                "height": round(1000 * (o["height_m"] - m.get("height_m", 0)), 1),
            }
        report["objects"][name] = o
    np.savez_compressed(
        args.out / "hull_voxels.npz", points=g[keep] + [0, 0, lift], labels=labels.ravel()[keep]
    )
    (args.out / "scan.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report["objects"], indent=1))


if __name__ == "__main__":
    main()
