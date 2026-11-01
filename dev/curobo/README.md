# cuRobo scene understanding (dev)

Experiments on making ASPIRE's cuRobo planner see the scene correctly. Nothing here is part of the
`ants` package, and ASPIRE itself is not modified: every change is a monkeypatch in a launcher.

Case under study: Exp 3, clip 233859, attempt 2 (`libero_goal_swap` task 8, seed 51, bowl x1.227 and
plate x1.855). The logged program gets stuck at the placement: the gripper presses into the wine rack.

## What we found

| Finding | Evidence |
|---|---|
| The gripper really touches the wine rack, for 410 to 479 steps. | `contact_launch.py` contact log: `gripper0_right_gripper | wine_rack_1_main` from step 564, at (0.477, -0.175, 0.237) in the robot base frame. |
| The planner does see the rack in its cloud. | `scene_points` near that contact: 62 points within 5 cm. |
| cuRobo's own "robot carve" erases it. The service deletes every scene point within 5 cm of its robot spheres (`_ROBOT_SEGMENTATION_DISTANCE_M`) at the start state, to remove the robot's own depth pixels. | `carve_check.py`: points within 5 cm of the contact drop from 92 to 4 (start of the stuck move) and 0 (where it stalled). The smallest sphere-to-point clearance in the planning world is exactly 5.0 cm. |
| With the carve tightened, the held bowl and the robot's unmodelled geometry turn into obstacles. | Grasp and release goals become `goal_scene_collision`. |
| With the robot removed by pixel (segmentation render) and the held bowl excluded by radius, cuRobo correctly reports the original release pose as infeasible (rack) and a pose orbited 90 degrees around the bowl as free. | `programs/exp3_a2_orbit.py`: probe at 0 degrees fails, at 90 degrees succeeds; 0 gripper-rack contact steps. |

## Comparison (same scene, seed 51, one run each)

Rack contact = simulator steps in which the gripper touches the wine rack (from the contact log, used for
evaluation only). Bowl-plate = horizontal distance of the body centres at the end; LIBERO's on-top check
(scaled plate) needs it below 0.056 m and the bowl body z at or below the plate body z.

| # | Configuration | task_success | Sim steps | Rack contact | Bowl-plate xy (m) | Bowl z - plate z (m) |
|---|---|---|---|---|---|---|
| 1 | Default planner, logged program | False | 886 | 477 | 0.060 | +0.020 |
| 2 | cuRobo stock service, every move | False | 1086 | 410 | 0.061 | +0.020 |
| 3 | cuRobo stock service + orbit skill | False | 959 | 478 | 0.055 | +0.019 |
| 4 | Tight carve, no robot mask | False | 192 (stopped) | 0 | 0.182 | +0.075 |
| 5 | Scene-aware, simulator robot mask (privileged) | False | 696 | 0 | 0.040 | +0.012 |
| 6 | Scene-aware, SAM3 robot mask (no simulator state) | False | 696 | 0 | 0.040 | +0.012 |

Config 4 stops at the first grasp: without a robot mask, the robot's own depth pixels stay in the world
and the grasp goal is rejected. Configs 5 and 6 pick the same orbit angle (90 degrees), so their runs match.
All six fail `task_success`; in 5 and 6 only the z rule fails.

## Tools

- `contact_launch.py`: `tools/aspire_launch.py` plus a per-step contact log (JSONL) and these switches:
  - `ANTS_CLOUD_DIR`: dump every planning cloud.
  - `ANTS_ROBOT_MASK=1`: build the planning cloud from non-robot pixels (MuJoCo segmentation render, privileged).
  - `ANTS_ROBOT_MASK=sam3`: same, but the robot mask comes from SAM3 prompts "robot arm" and "robot gripper".
  - `ANTS_EXCLUDE_RADIUS_M`: drop scene points within r of the manipulated object (replaces the 1-99% quantile box).
  - `ANTS_PROBE_XYZ=x,y,z`: print, per scene body, how close its points get to a goal.
- `service_dev.py`: the cuRobo service with `ANTS_CARVE_MARGIN_M` instead of the fixed 5 cm.
- `carve_check.py`, `probe_goal.py`: offline replays of the carve and of goal feasibility on a dumped cloud.
- `programs/`: the test programs (`exp3_a2_curobo_all.py`: logged program with cuRobo on every move;
  `exp3_a2_orbit.py`: scene-aware transit, default planner for contact, and the orbit skill).

## Limits

- The SAM3 mask (config 6) removes simulator state from the planning path, but the scene is still simulated RGB-D. The contact log and body labels are evaluation tools.
- The held bowl is excluded from the world, not attached to the robot, so the planner cannot see the bowl hit anything.
- One scene, one seed, one run per configuration.
