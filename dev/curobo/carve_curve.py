"""How many obstacle points near the gripper survive cuRobo's robot carve, for each carve margin?

Same replay as carve_check.py, but sweeps the margin (the stock service uses 5 cm) and prints JSON.

    ASPIRE/.venv-curobo/bin/python dev/curobo/carve_curve.py \
        CLOUD.npy TRACE_CALLS_DIR CALL_ID X Y Z
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from cap_harness.providers.curobo import service
from carve_check import joints

MARGINS_M = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08]


def main() -> None:
    cloud = np.load(sys.argv[1]).astype(np.float32)
    calls, call = Path(sys.argv[2]), int(sys.argv[3])
    contact = np.array([float(v) for v in sys.argv[4:7]])
    q = joints(calls / f"call-{call:06d}-execute-trajectory" / "input.json", "start")
    req = service.PlanRequest(
        base_frame="robot_base",
        model="panda",
        arm="primary",
        joint_positions={"primary": q},
        joint_names={"primary": [f"panda_joint{i}" for i in range(1, 8)]},
        base_transforms={"primary": np.eye(4).tolist()},
        end_effector_links={"primary": "panda_hand"},
        target=service.Target(
            type="pose",
            position=[0.46, -0.1, 0.2],
            quaternion_wxyz=[0, 1, 0, 0],
            frame="robot_base",
        ),
    )
    planner = service._planner(req)
    spheres = np.asarray(
        planner.compute_kinematics(service._state(req, planner)).robot_spheres.detach().cpu(),
        dtype=np.float64,
    ).reshape(-1, 4)
    near = lambda p: int((np.linalg.norm(p - contact, axis=1) < 0.05).sum())  # noqa: E731
    rows = []
    for m in MARGINS_M:
        kept = service._filter_robot_points(cloud, spheres, padding_m=m)
        rows.append({"margin_m": m, "cloud_kept": len(kept), "near_contact_kept": near(kept)})
    print(json.dumps({"cloud": len(cloud), "near_contact": near(cloud), "rows": rows}, indent=1))


if __name__ == "__main__":
    main()
