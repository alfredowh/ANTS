"""Box twin of each real E1 recording: the real bowl and plate layout, placed in the LIBERO scene.

E1 clips (`hurobo/data/raw/e1/clips`) are filmed from a fixed phone with the ChArUco board (table
frame), the bowl pad marker (id 21) and the plate marker (id 22) in view. hurobo's
`BoardMarkerPoseEstimator` gives T_table_bowl and T_table_plate per frame; the median over the
first `--seconds` (before the hand moves anything) is the clip's layout. Sizes are the tape
measurements in `measurements.yaml`, not estimated.

Mapping to the robot base frame (an assumption, logged in the output): the robot stands where the
phone stood. The E1 phone faces the board from its far side, so table -x (right in the image) is
base -y and table -y (away from the phone) is base +x. The midpoint of bowl and plate is anchored
at the midpoint of the LIBERO nominal layout (`--anchor`), so the real relative layout (distance,
direction) is kept exactly; the absolute offset on the table is not.

Output per clip: `<out>/<clip>/twin.json` in the launcher's `"twin": {"bodies": ...}` format
(`tools/aspire_launch.py`, `_twin`), readable by `dev/curobo/replay_attach.py --twin-dir`.

    hurobo/.venv/bin/python ../ANTS-real2sim/tools/real2sim/e1_twin.py \\
        hurobo/data/raw/e1/clips --out data/runs/real2sim_e1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

BODIES = {"bowl": "akita_black_bowl_1_main", "plate": "plate_1_main"}
# Table frame -> robot base frame rotation (robot where the phone was). The E1 phone faces the
# board from its far side: image right is table -x and "away from the phone" is table -y.
R_BASE_TABLE = np.array([[0.0, -1.0], [1.0, 0.0]])


def layout(video: Path, estimator, seconds: float) -> dict | None:
    cap = cv2.VideoCapture(str(video))
    cap.set(cv2.CAP_PROP_ORIENTATION_AUTO, 0)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    xy: dict[str, list] = {"bowl": [], "plate": []}
    frames = 0
    for _ in range(int(seconds * fps)):
        ok, frame = cap.read()
        if not ok:
            break
        frames += 1
        poses = estimator.estimate(frame)
        if not poses:
            continue
        for role in xy:
            if role in poses:
                xy[role].append(poses[role][:3, 3])
    if not xy["bowl"] or not xy["plate"]:
        return None
    out = {"frames": frames}
    for role, pts in xy.items():
        p = np.asarray(pts)
        med = np.median(p, axis=0)
        out[role] = {
            "xyz_table": med.round(4).tolist(),
            "detections": len(p),
            "spread_mm": round(1000 * float(np.median(np.linalg.norm(p - med, axis=1))), 1),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("clips", type=Path, help="folder of E1 clips (.mp4)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--hurobo", type=Path, default=Path("hurobo"), help="hurobo checkout")
    ap.add_argument("--seconds", type=float, default=1.0, help="layout window from the clip start")
    ap.add_argument(
        "--anchor",
        type=float,
        nargs=2,
        default=[0.5397, 0.0466],
        help="base-frame xy of the bowl-plate midpoint (default: LIBERO nominal, seed 51)",
    )
    args = ap.parse_args()
    sys.path.insert(0, str((args.hurobo / "src").resolve()))
    from hurobo.camera import CameraIntrinsics
    from hurobo.real_setup import RealSetup
    from hurobo.recording import RecordingSpec

    setup_path = args.hurobo / "data/raw/setup_01/measurements.yaml"
    setup = RealSetup.load(setup_path)
    intr = CameraIntrinsics.load(args.hurobo / "data/camera_intrinsics_s24.npz")
    spec = RecordingSpec()
    sizes = {"bowl": setup.bowl.diameter_m, "plate": setup.plate.diameter_m}
    anchor = np.asarray(args.anchor)
    rows = []
    for video in sorted(args.clips.glob("*.mp4")):
        lay = layout(video, spec.estimator(intr, setup), args.seconds)
        if lay is None:
            print(f"{video.name}: board or a marker not seen, skipped")
            rows.append({"clip": video.name, "skipped": True})
            continue
        xy_t = {r: np.asarray(lay[r]["xyz_table"][:2]) for r in BODIES}
        mid = (xy_t["bowl"] + xy_t["plate"]) / 2
        bodies = {
            BODIES[r]: {
                "diameter_m": round(float(sizes[r]), 4),
                "xy_base": [round(float(v), 4) for v in anchor + R_BASE_TABLE @ (xy_t[r] - mid)],
            }
            for r in BODIES
        }
        sep = float(np.linalg.norm(xy_t["bowl"] - xy_t["plate"]))
        twin = {
            "source": str(video),
            "bodies": bodies,
            "info": {
                "layout_table": lay,
                "bowl_plate_distance_m": round(sep, 4),
                "sizes": "tape measurements, measurements.yaml",
                "mapping": "robot at the phone: table -x -> base -y, -y -> base +x; "
                f"bowl-plate midpoint anchored at {anchor.tolist()}",
            },
        }
        d = args.out / video.stem
        d.mkdir(parents=True, exist_ok=True)
        (d / "twin.json").write_text(json.dumps(twin, indent=1), encoding="utf-8")
        rows.append({"clip": video.name, "distance_m": round(sep, 4), **bodies})
        print(video.name, f"sep {sep:.3f} m", json.dumps(bodies))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
