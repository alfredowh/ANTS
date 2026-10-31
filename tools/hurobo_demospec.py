"""Convert one hurobo HumanDemo (.npz) into an ANTS DemoSpec (JSON), object-relative.

Run it with hurobo's Python, since it needs numpy and ANTS does not depend on it:

    ../hurobo/.venv/bin/python -I tools/hurobo_demospec.py \
        data/hurobo_e1/demos_marker_0.06/20261016_233832.npz \
        --setup ../hurobo/data/raw/setup_01/measurements.yaml \
        --out data/demospecs/hurobo_233832.json

Distances are given both in metres and as a fraction of the object's radius, so they carry
over to a simulator object of a different size. Heights are above the table (z = 0).
The output matches ants.contracts.DemoSpec plus a "summary" block for the generator prompt.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np


def read_round_objects(setup: Path) -> dict[str, dict[str, float]]:
    """Read bowl and plate diameter/height from measurements.yaml without a YAML dependency."""
    out: dict[str, dict[str, float]] = {}
    current = None
    for line in setup.read_text(encoding="utf-8").splitlines():
        head = re.match(r"^(\w+):\s*$", line)
        if head:
            current = head.group(1)
            continue
        field = re.match(r"^\s+(diameter_m|height_m):\s*([0-9.]+)", line)
        if field and current in ("bowl", "plate"):
            out.setdefault(current, {})[field.group(1)] = float(field.group(2))
    return out


def convert(npz: Path, setup: Path) -> dict:
    d = np.load(npz, allow_pickle=True)
    t = d["timestamps_s"]
    tcp = d["tcp_pos_table"]
    aperture = d["pinch_aperture_m"]
    g, r = int(d["grasp_frame_idx"]), int(d["release_frame_idx"])
    bowl_c, plate_c = d["t_table_bowl"][:3, 3], d["t_table_plate"][:3, 3]
    sizes = read_round_objects(setup)
    bowl_r, plate_r = sizes["bowl"]["diameter_m"] / 2, sizes["plate"]["diameter_m"] / 2

    grasp_xy = tcp[g, :2] - bowl_c[:2]
    release_xy = tcp[r, :2] - plate_c[:2]
    carry = tcp[g : r + 1]
    lift_idx = next((i for i in range(g, r) if tcp[i, 2] > tcp[g, 2] + 0.03), g)
    approach = tcp[: g + 1]
    descent_xy = float(np.linalg.norm(approach[-1, :2] - approach[max(0, g - 10), :2]))
    descent_z = float(approach[max(0, g - 10), 2] - approach[-1, 2])

    summary = {
        "grasp": {
            "radial_offset_m": round(float(np.linalg.norm(grasp_xy)), 3),
            "radial_offset_over_radius": round(float(np.linalg.norm(grasp_xy)) / bowl_r, 2),
            "height_above_table_m": round(float(tcp[g, 2]), 3),
            "height_over_object_height": round(float(tcp[g, 2]) / sizes["bowl"]["height_m"], 2),
            "aperture_before_m": round(float(aperture[max(0, g - 10)]), 3),
            "aperture_at_grasp_m": round(float(aperture[g]), 3),
            "approach_last_0.5s": {
                "horizontal_m": round(descent_xy, 3),
                "drop_m": round(descent_z, 3),
            },
        },
        "carry": {
            "lift_before_moving_m": 0.03,
            "lift_time_after_grasp_s": round(float(t[lift_idx] - t[g]), 2),
            "max_height_above_table_m": round(float(carry[:, 2].max()), 3),
            "duration_s": round(float(t[r] - t[g]), 2),
        },
        "release": {
            "radial_offset_from_plate_centre_m": round(float(np.linalg.norm(release_xy)), 3),
            "radial_offset_over_plate_radius": round(
                float(np.linalg.norm(release_xy)) / plate_r, 2
            ),
            "height_above_table_m": round(float(tcp[r, 2]), 3),
        },
        "objects_real": {"bowl": sizes["bowl"], "plate": sizes["plate"]},
    }
    keyframes = [
        {"t_s": round(float(t[0]), 2), "kind": "approach", "anchor": "bowl"},
        {"t_s": round(float(t[g]), 2), "kind": "grasp", "anchor": "bowl"},
        {"t_s": round(float(t[lift_idx]), 2), "kind": "lift", "anchor": "bowl"},
        {"t_s": round(float(t[r]), 2), "kind": "release", "anchor": "plate"},
        {"t_s": round(float(t[-1]), 2), "kind": "retreat", "anchor": "plate"},
    ]
    step = max(1, len(t) // 40)
    return {
        "source": f"phone:{Path(str(d['source_video'])).name}",
        "task_text": "put the bowl on the plate",
        "objects": [{"name": "bowl", "poses_world": {}}, {"name": "plate", "poses_world": {}}],
        "keyframes": keyframes,
        "ee_path_obj": {
            "approach_in_bowl_frame": [
                [round(float(v), 3) for v in p - bowl_c] for p in tcp[: g + 1 : step]
            ],
            "carry_in_plate_frame": [
                [round(float(v), 3) for v in p - plate_c] for p in tcp[g : r + 1 : step]
            ],
        },
        "aperture": [
            [round(float(a), 2), round(float(b), 3)]
            for a, b in zip(t[::step], aperture[::step], strict=False)
        ],
        "steps": [
            "approach the bowl from above",
            "pinch the bowl's rim",
            "lift",
            "carry over the plate",
            "lower and release",
            "retreat",
        ],
        "quality": {},
        "summary": summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("npz", type=Path)
    parser.add_argument("--setup", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    spec = convert(args.npz, args.setup)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    print(json.dumps(spec["summary"], indent=1))


if __name__ == "__main__":
    main()
