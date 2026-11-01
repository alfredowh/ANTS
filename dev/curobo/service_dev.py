"""Dev launcher for ASPIRE's cuRobo service with a tunable robot-carve margin.

The stock service deletes every scene point within 5 cm of the robot's collision spheres
(`_ROBOT_SEGMENTATION_DISTANCE_M`), so an obstacle next to the gripper is invisible to the
planner. This starts the same service with ANTS_CARVE_MARGIN_M instead (default 0.02).

    ANTS_CARVE_MARGIN_M=0.02 ../ASPIRE/.venv-curobo/bin/python dev/curobo/service_dev.py --port 8118
"""

from __future__ import annotations

import os

from cap_harness.providers.curobo import service

service._ROBOT_SEGMENTATION_DISTANCE_M = float(os.environ.get("ANTS_CARVE_MARGIN_M", "0.02"))

if __name__ == "__main__":
    service.main()
