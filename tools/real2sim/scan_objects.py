"""Real bowl and plate from phone video: posed views, SAM 3 masks, per-object visual hull.

Camera poses come from the ChArUco board (metric). Each sampled view is segmented by the SAM 3
service with one text prompt per object, and a voxel grid over the tabletop is carved per object: a
voxel survives if it projects inside the object's mask in at least `--keep` of the views that have a
mask and see it. The largest component is the object.

Outputs in `--out`: `scan.json` (metric size, position, colour per object, error against the tape
measurements), `<name>_hull.npz` (carved voxels, tabletop frame, z = 0 on the table) and the masks
under `masks/` (reused on rerun; SAM 3 is only called for missing ones).

A visual hull cannot see the inside of a bowl; `scene_from_scan.py` makes it a shell. Run with the
hurobo venv and the SAM 3 service up:

    hurobo/.venv/bin/python tools/real2sim/scan_objects.py \\
        hurobo/data/raw/setup_01/table_scene_zoom_0{2,3}.mp4 \\
        --setup hurobo/data/raw/setup_01/measurements.yaml --out data/runs/real2sim_scan/setup_01
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import requests
import yaml
from scipy import ndimage
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parent))
from real_scan import board_from, detect  # noqa: E402

PROMPTS = {"bowl": "white bowl", "plate": "white plate"}
SAM3 = "http://127.0.0.1:8114"


def sam_mask(rgb: np.ndarray, prompt: str, path: str, max_frac: float) -> np.ndarray | None:
    ok, buf = cv2.imencode(".png", rgb[..., ::-1])
    if not ok:
        return None
    body = {"image_base64": base64.b64encode(buf.tobytes()).decode(), "text_prompt": prompt}
    res = requests.post(SAM3 + path, json=body, timeout=300).json().get("results") or []
    for item in sorted(res, key=lambda r: -float(r.get("score", 0))):
        h, w = item["shape"]
        mask = np.frombuffer(base64.b64decode(item["mask_base64"]), np.uint8).reshape(h, w) > 0
        if 200 < mask.sum() < max_frac * mask.size:
            return mask
    return None


def posed_views(videos: list[Path], board, k, dist, every: int, out: Path, min_corners: int):
    (out / "views").mkdir(parents=True, exist_ok=True)
    views = []
    for video in videos:
        cap = cv2.VideoCapture(str(video))
        cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 0)  # the intrinsics are for the stored frames
        i = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if i % every == 0:
                pose = detect(board, frame, k, dist, min_corners)
                if pose and pose[2] < 2.0:
                    name = f"{video.stem}_{i:05d}"
                    # OpenCV board frame -> table frame (y toward the top of the image, z up).
                    rot = pose[0] @ np.diag([1.0, -1.0, -1.0])
                    und = cv2.undistort(frame, k, dist)
                    jpg = out / "views" / f"{name}.jpg"
                    if not jpg.exists():
                        cv2.imwrite(str(jpg), und, [cv2.IMWRITE_JPEG_QUALITY, 90])
                    views.append({"name": name, "rot": rot, "t": pose[1], "err": pose[2]})
            i += 1
    return views


def carve(views, masks, k, lo, hi, voxel, keep, min_seen):
    n = np.ceil((hi - lo) / voxel).astype(int)
    axes = [lo[a] + (np.arange(n[a]) + 0.5) * voxel for a in range(3)]
    g = np.stack(np.meshgrid(*axes, indexing="ij"), -1).reshape(-1, 3)
    inside, seen = np.zeros(len(g), np.int32), np.zeros(len(g), np.int32)
    h, w = next(iter(masks.values())).shape
    for v in views:
        if v["name"] not in masks:
            continue
        mask = masks[v["name"]]
        pc = g @ v["rot"].T + v["t"]
        front = pc[:, 2] > 0.05
        z = np.where(front, pc[:, 2], 1.0)
        u = (pc[:, 0] / z * k[0, 0] + k[0, 2]).astype(int)
        px = (pc[:, 1] / z * k[1, 1] + k[1, 2]).astype(int)
        vis = front & (u >= 0) & (u < w) & (px >= 0) & (px < h)
        seen += vis
        inside[vis] += mask[px[vis], u[vis]]
    occ = (seen >= min_seen) & (inside >= keep * np.maximum(seen, 1))
    labels, nlab = ndimage.label(occ.reshape(n), structure=np.ones((3, 3, 3)))
    if nlab == 0:
        return np.zeros((0, 3))
    sizes = ndimage.sum(occ.reshape(n), labels, range(1, nlab + 1))
    return g[labels.ravel() == int(np.argmax(sizes)) + 1]


def outline(kind: str, x: np.ndarray, n: int = 48) -> np.ndarray:
    """Surface points (tabletop frame) of a parametric object; silhouette = their convex hull."""
    th = np.linspace(0, 2 * np.pi, n, endpoint=False)
    if kind == "bowl":
        cx, cy, r0, r1, height, p = x
        r0 = abs(r0)
        rows = []
        for s in np.linspace(0, 1, 7):
            r = r0 + (r1 - r0) * s ** max(p, 0.2)
            rows.append(np.c_[cx + r * np.cos(th), cy + r * np.sin(th), np.full(n, s * height)])
        return np.concatenate(rows)
    cx, cy, a, b, yaw, e, height, foot = x
    c, s = np.cos(th), np.sin(th)
    u = a * np.sign(c) * np.abs(c) ** (2 / max(e, 1.2))
    v = b * np.sign(s) * np.abs(s) ** (2 / max(e, 1.2))
    px, py = u * np.cos(yaw) - v * np.sin(yaw), u * np.sin(yaw) + v * np.cos(yaw)
    return np.concatenate(
        [
            np.c_[cx + px, cy + py, np.full(n, height)],
            np.c_[cx + foot * px, cy + foot * py, np.zeros(n)],
        ]
    )


def silhouette_iou(pts, views, masks, k, lift, scale=4) -> float:
    """Mean IoU between the projected object and the SAM 3 masks, over views that have a mask."""
    board = pts - [0, 0, lift]
    ious = []
    for v in views:
        mask = masks.get(v["name"])
        if mask is None:
            continue
        pc = board @ v["rot"].T + v["t"]
        if np.any(pc[:, 2] < 0.05):
            continue
        uv = pc[:, :2] / pc[:, 2:] * [k[0, 0], k[1, 1]] + [k[0, 2], k[1, 2]]
        draw = np.zeros(mask.shape, np.uint8)
        cv2.fillConvexPoly(draw, cv2.convexHull((uv / scale).astype(np.int32)), 1)
        a, b = draw > 0, mask
        if b[[0, -1], :].any() or b[:, [0, -1]].any():  # object cut by the image edge: no outline
            continue
        ious.append((a & b).sum() / max((a | b).sum(), 1))
    return float(np.mean(ious)) if ious else 0.0


def fit_shape(kind, views, masks, k, lift, centre) -> tuple[np.ndarray, float]:
    small = {
        n: cv2.resize(m.astype(np.uint8), None, fx=0.25, fy=0.25, interpolation=cv2.INTER_NEAREST)
        > 0
        for n, m in masks.items()
    }

    def loss(x):
        return 1.0 - silhouette_iou(outline(kind, x), views, small, k, lift)

    if kind == "bowl":
        starts = [[*centre, 0.04, 0.07, h, 0.7] for h in (0.05, 0.07, 0.09)]
    else:
        starts = [[*centre, 0.13, 0.13, y, 3.0, h, 0.7] for h in (0.02, 0.04) for y in (0.0, 0.6)]
    best = None
    for x0 in starts:
        res = minimize(
            loss, x0, method="Powell", options={"maxiter": 12, "xtol": 5e-4, "ftol": 1e-4}
        )
        if best is None or res.fun < best.fun:
            best = res
    return best.x, 1.0 - float(best.fun)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("videos", nargs="+", type=Path)
    ap.add_argument("--setup", type=Path, required=True)
    ap.add_argument("--intrinsics", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--every", type=int, default=6, help="use every Nth frame")
    ap.add_argument("--min-corners", type=int, default=6)
    ap.add_argument("--voxel", type=float, default=0.003, help="carving voxel, metres")
    ap.add_argument("--keep", type=float, default=0.9, help="fraction of masked views that agree")
    ap.add_argument("--min-seen", type=int, default=20, help="masked views a voxel must appear in")
    ap.add_argument(
        "--square-m",
        type=float,
        default=None,
        help="board square size for this recording, if it differs from measurements.yaml",
    )
    ap.add_argument("--segment-path", default="/segment", help="SAM 3 service route")
    args = ap.parse_args()

    setup = yaml.safe_load(args.setup.read_text(encoding="utf-8"))
    if args.square_m:
        c = setup["charuco"]
        c["marker_length_m"] *= args.square_m / c["square_length_m"]
        c["square_length_m"] = args.square_m
    z = np.load(args.intrinsics or args.setup.parents[2] / "camera_intrinsics_s24.npz")
    k, dist = z["camera_matrix"], z["dist_coeffs"]
    views = posed_views(
        args.videos, board_from(setup), k, dist, args.every, args.out, args.min_corners
    )
    print(len(views), "posed views", flush=True)
    t, lift = setup["table"], float(setup["charuco"].get("tablet_thickness_m", 0.0))
    lo = np.array([t["left_edge_x_m"], t["near_edge_y_m"], -lift + 0.002])
    hi = np.array([t["right_edge_x_m"], t["top_edge_y_m"], -lift + 0.12])
    report = {"views": len(views), "voxel_m": args.voxel, "keep": args.keep, "objects": {}}
    colours_by = {}
    for name, prompt in PROMPTS.items():
        (args.out / "masks" / name).mkdir(parents=True, exist_ok=True)
        masks = {}
        for v in views:
            path = args.out / "masks" / name / f"{v['name']}.png"
            if path.exists():
                masks[v["name"]] = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) > 0
                continue
            bgr = cv2.imread(str(args.out / "views" / f"{v['name']}.jpg"))
            mask = sam_mask(bgr[..., ::-1], prompt, args.segment_path, 0.5)
            if mask is not None:
                masks[v["name"]] = mask
                cv2.imwrite(str(path), mask.astype(np.uint8) * 255)
        print(name, "masks", len(masks), flush=True)
        pts = carve(views, masks, k, lo, hi, args.voxel, args.keep, args.min_seen)
        if not len(pts):
            print(name, "empty hull", flush=True)
            continue
        cols = []
        for v in views[:: max(1, len(views) // 25)]:
            if v["name"] not in masks:
                continue
            bgr = cv2.imread(str(args.out / "views" / f"{v['name']}.jpg"))
            cols.append(np.median(bgr[masks[v["name"]]], axis=0)[::-1])
        colours_by[name] = cols
        p = pts + [0, 0, lift]  # tabletop frame
        np.savez_compressed(args.out / f"{name}_hull.npz", points=p, voxel=args.voxel)
        ext = np.percentile(p, 99, axis=0) - np.percentile(p, 1, axis=0)
        obj = {
            "voxels": int(len(p)),
            "masks": len(masks),
            "centre_xy": ((np.percentile(p, 1, axis=0) + np.percentile(p, 99, axis=0)) / 2)[:2]
            .round(4)
            .tolist(),
            "extent_m": ext.round(4).tolist(),
            "height_m": round(float(np.percentile(p[:, 2], 99.5)), 4),
            "diameter_m": round(float(ext[:2].mean()), 4),
            "rgb": [round(float(c)) for c in np.median(cols, axis=0)],
        }
        tape = setup.get(name) or {}
        if "diameter_m" in tape:
            obj["error_vs_tape_mm"] = {
                "diameter": round(1000 * (obj["diameter_m"] - tape["diameter_m"]), 1),
                "height": round(1000 * (obj["height_m"] - tape.get("height_m", 0)), 1),
            }
        foot_xy = p[p[:, 2] < 0.015][:, :2]
        centre = (np.percentile(foot_xy, 2, axis=0) + np.percentile(foot_xy, 98, axis=0)) / 2
        x, iou = fit_shape(name, views, masks, k, lift, centre)
        obj["hull_note"] = "visual hull height is unconstrained from these views; use fit"
        obj["fit"] = {"params": [round(float(v), 5) for v in x], "iou": round(iou, 4)}
        if name == "bowl":
            cx, cy, r0, r1, height, power = x
            obj["fit"]["params"][2] = round(abs(float(r0)), 5)
            obj["fit"].update(diameter_m=round(2 * float(r1), 4), height_m=round(float(height), 4))
        else:
            cx, cy, a, b, yaw, e, height, foot = x
            obj["fit"].update(diameter_m=round(float(a + b), 4), height_m=round(float(height), 4))
        obj["centre_xy"] = [round(float(cx), 4), round(float(cy), 4)]
        if "diameter_m" in tape:
            obj["fit"]["error_vs_tape_mm"] = {
                "diameter": round(1000 * (obj["fit"]["diameter_m"] - tape["diameter_m"]), 1),
                "height": round(1000 * (obj["fit"]["height_m"] - tape["height_m"]), 1),
            }
        report["objects"][name] = obj
    (args.out / "scan.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report["objects"], indent=1))


if __name__ == "__main__":
    main()
