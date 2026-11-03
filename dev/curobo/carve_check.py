"""Does cuRobo's own robot-point carve erase the obstacle the gripper is about to hit?

The cuRobo service removes every scene point within (sphere radius + 5 cm) of the robot's
collision spheres at the *start* state, because depth cameras see the robot itself. An obstacle
within 5 cm of the gripper is then deleted from the planning world. This script replays that
step offline on a dumped planning cloud and reports what survives near a contact point.

Run with ASPIRE's cuRobo venv (needs the GPU):
    ASPIRE/.venv-curobo/bin/python dev/curobo/carve_check.py \
        CLOUD.npy TRACE_CALLS_DIR CALL_ID X Y Z
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from cap_harness.providers.curobo import service


def joints(path: Path, key: str) -> list[float]:
    d = json.loads(path.read_text(encoding="utf-8"))
    state = (
        d["args"][0]["expected_start"] if key == "start" else d["final_observation"]["robot_state"]
    )
    return state["joint_positions"]["primary"]["$array_inline"]


def main() -> None:
    cloud = np.load(sys.argv[1]).astype(np.float32)
    calls, call = Path(sys.argv[2]), int(sys.argv[3])
    contact = np.array([float(v) for v in sys.argv[4:7]])
    exec_dir = calls / f"call-{call:06d}-execute-trajectory"
    for label, path, key in (
        ("start of stuck move", exec_dir / "input.json", "start"),
        ("where it stalled", exec_dir / "output.json", "final"),
    ):
        q = joints(path, key)
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
        kept = service._carve_robot_points(req, planner, cloud)
        near = lambda p: int((np.linalg.norm(p - contact, axis=1) < 0.05).sum())  # noqa: E731
        clearance = (
            np.linalg.norm(kept[:, None, :] - spheres[None, :, :3], axis=-1) - spheres[:, 3]
        ).min()
        print(
            f"{label}: cloud {len(cloud)} -> {len(kept)} after carve; "
            f"points within 5 cm of contact {near(cloud)} -> {near(kept)}; "
            f"min sphere-to-kept-point clearance {clearance * 100:.1f} cm"
        )


if __name__ == "__main__":
    main()
