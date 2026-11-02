"""Dev launcher for ASPIRE's cuRobo service: tunable robot carve, and an attached held object.

The stock service deletes every scene point within 5 cm of the robot's collision spheres
(`_ROBOT_SEGMENTATION_DISTANCE_M`), so an obstacle next to the gripper is invisible to the
planner. This starts the same service with ANTS_CARVE_MARGIN_M instead (default 0.02).

Attached object: cuRobo's Panda has an `attached_object` link, fixed to `panda_hand`, with a few
sphere slots. `franka_attach.yml` (a copy of the stock config with 64 slots) is used, and before
every request the spheres listed in the JSON file $ANTS_ATTACH_FILE are written into that link, so
they move with the hand in every collision check. The file is `{"spheres": [[x, y, z, r], ...]}` in
the hand frame (metres); an empty list or a missing file detaches. The launcher
(`tools/aspire_launch.py`, planner.attach) writes the file; nothing else in ASPIRE changes.

    ANTS_CARVE_MARGIN_M=0.02 ANTS_ATTACH_FILE=/tmp/attach.json \
      ../ASPIRE/.venv-curobo/bin/python dev/curobo/service_dev.py --port 8118
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import torch
from cap_harness.providers.curobo import service

service._ROBOT_SEGMENTATION_DISTANCE_M = float(os.environ.get("ANTS_CARVE_MARGIN_M", "0.02"))
os.environ.setdefault(
    "CAP_HARNESS_CUROBO_PANDA_CONFIG", str(Path(__file__).with_name("franka_attach.yml"))
)
LINK = "attached_object"
_attached = False


def _spheres() -> list[list[float]]:
    path = os.environ.get("ANTS_ATTACH_FILE")
    if not path or not Path(path).is_file():
        return []
    return json.loads(Path(path).read_text(encoding="utf-8")).get("spheres", [])


def _apply(planner, request) -> None:
    global _attached
    spheres = _spheres()
    manager = planner.trajopt_solver.core.attachment_manager  # the planner's own property is broken
    if spheres:
        buf = manager.kinematics_params.link_spheres
        tensor = torch.tensor(spheres, device=buf.device, dtype=buf.dtype)
        manager.update(tensor, service._state(request, planner), LINK)
        _attached = True
    elif _attached:
        manager.detach(LINK)
        _attached = False


_planner = service._planner


def _planner_with_attach(request):
    planner = _planner(request)
    _apply(planner, request)
    return planner


service._planner = _planner_with_attach

if __name__ == "__main__":
    service.main()
