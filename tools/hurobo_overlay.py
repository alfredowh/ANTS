"""Render one extracted hurobo demo over its source clip, for the Studio: hand skeleton, marker
detections, TCP trajectory, object centres and gripper gauge, played at the recorded speed.

Run it with hurobo's Python and from hurobo's folder, since it needs hurobo and OpenCV:

    (cd hurobo) .venv/bin/python ../tools/hurobo_overlay.py demo.npz --video clip.mp4 \
        --setup data/raw/setup_01/measurements.yaml --intrinsics data/camera_intrinsics_s10e.npz \
        --marker-size-m 0.0575 --out overlay_raw.mp4

The drawing is hurobo's own `DemoOverlay`. The output uses OpenCV's codec; the Studio transcodes it
to H.264 so a browser can play it.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    from hurobo.camera import CameraIntrinsics
    from hurobo.demo import HumanDemo
    from hurobo.demo_overlay import DemoOverlay
    from hurobo.real_setup import RealSetup
    from hurobo.recording import RecordingSpec, diagnose_capture

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("demo", type=Path)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--setup", type=Path, required=True)
    parser.add_argument("--intrinsics", type=Path, required=True)
    parser.add_argument("--marker-size-m", type=float, required=True)
    parser.add_argument("--width", type=int, default=960)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    demo = HumanDemo.load(args.demo)
    intrinsics = CameraIntrinsics.load(args.intrinsics)
    spec = RecordingSpec(marker_length_m=args.marker_size_m)
    diagnosis = diagnose_capture(args.video, intrinsics, RealSetup.load(args.setup), spec)
    DemoOverlay(demo, diagnosis, intrinsics).write_video(
        args.out, width_px=args.width, slowdown=1.0
    )
    print(f"overlay -> {args.out}")


if __name__ == "__main__":
    main()
