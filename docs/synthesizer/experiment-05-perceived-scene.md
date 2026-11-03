# Exp 05: perceived scene against the simulator oracle

Run dir: `data/runs/exp05_perceived_scene` (git-ignored). Report: `report.html` there. No model call, no tokens.

## Why

Exp04 gave the generator a scene description built from simulator state ("oracle"). A deployed system has only cameras. This study asks: with the modules that exist today (ASPIRE `segment_text`, `mask_to_point_cloud`, `estimate_geometry`, the wrist camera, robot state), how close does a perceived collision world come to the oracle, and what is missing?

## Design

- Scene: L1 of libero_goal_swap task 8, seed 51 (rack behind the plate, touching its rim; bowl x1.227, plate x1.855). Truth: `data/scenes/L1/contacts_scene.json`.
- Perception (`data/scenes/perception_probe2.py`, `perception_probe3.py`): 13 SAM 3 text prompts (7 objects, rack synonyms `wine bottle rack`, `wooden wine rack`, `shelf`, `table`, `robot arm`, `robot gripper`) in both cameras (agentview, robot0_eye_in_hand); every mask becomes a depth point cloud in the robot base frame (down-sampled to about 1000 points). Two states: arm at home, and arm moved over the rack (the move reported `ok = False`, TCP 0.485, -0.172, 0.258).
- Analysis (`ants.orchestrator.perceived_scene`, pure Python): variants V0 to V5, cumulative (table below), then the perceived `CollisionWorld`, the same `describe(world, "combo")` text as exp04's S4, and relations from `relations()`.
- Found = centre within 3 cm in xy of the oracle object. Selection rules use no truth (size/position plausibility, claim removal, cluster consensus), but they were written after looking at this scene.
- Report: `uv run python -m ants.evalkit.perceived_report`. Commands: `uv run python -m ants.evalkit.runbook cmd exp05.probe` (and `.analyse`, `.report`).
- The committed perception files come from the same two probes run by hand before the `--probe` stage existed (`probe_L1` run 20261102T005635, `probe_L1_arm/run2`); `--probe` repeats them into `probe_L1_start` and `probe_L1_arm`.

## Results (all from `analysis.json`)

Start state (arm at home) / arm over the rack, 7 objects:

| id | change | within 3 cm | mean xy err cm | mean abs height err cm | mean 3D IoU |
|---|---|---|---|---|---|
| V0 | a3 baseline (estimate_geometry) | 2/7 / 1/7 | 15.5 / 19.2 | 11.2 / 6.5 | 0.323 / 0.285 |
| V1 | box from mask depth points | 6/7 / 5/7 | 1.6 / 5.4 | 2.6 / 3.1 | 0.581 / 0.478 |
| V2 | + plausible masks, rack synonyms with consensus, claim removal | 7/7 / 7/7 | 1.1 / 1.0 | 2.4 / 2.5 | 0.629 / 0.623 |
| V3 | + wrist camera masks, gated | 7/7 / 7/7 | 1.0 / 1.0 | 2.5 / 2.5 | 0.631 / 0.626 |
| V4 | + table plane, robot-mask subtraction | 7/7 / 7/7 | 1.1 / 1.0 | 0.5 / 0.7 | 0.706 / 0.693 |
| V5 | + circle (bowl, plate) and oriented rectangle | 7/7 / 7/7 | 1.2 / 1.2 | 0.5 / 0.7 | 0.697 / 0.685 |

What helped: using the mask's depth points instead of `estimate_geometry` (V0 to V1: the rack box was 2.25 m wide because of flying depth pixels; the plate centre was 5.9 cm off); consensus and plausibility (V2: stove 5.5 to 1.4 cm, and in the arm state cream cheese, whose correct mask has SAM score 0.01 and was not rank 0); the table plane for heights (V3 to V4). Not helping measurably: the wrist camera (V2 to V3, 0.1 cm), robot-mask subtraction (65 points removed in the arm state, IoU unchanged), the shape fit (V4 to V5, IoU slightly lower; the circle gives the round objects a radius but no taper). The box percentile (0.5 to 99.5) was picked from a sweep on this scene (`extent_sweep` in `analysis.json`).

Relations (V5, start): near-or-touching pairs 12 of 15 recalled, precision 1.0, mean gap error 11.9 mm. The two real contacts (plate-rack, cream cheese-plate) are seen at 11 mm and 4 mm, so the 3 mm rule calls them `near`. Rack structure: z levels of the perceived points lie in the two upper boards; the floor boards (z 0.006 to 0.033) and the far side (y range seen -0.313 to -0.133, truth -0.382 to -0.128) are missing; rack box size error in y is -9.2 cm. Robot: the `robot arm` mask has 87% (home) and 97% (hover) of points on the cuRobo spheres and reaches 38 and 39 of 61 spheres; `robot gripper` best score 0.01 (unusable).

The per-capability table (covered / partly / not covered, missing module, how to complete, effort) is in the report.

## Caveats

- One scene, one seed, one hover pose that does not hide the rack; selection thresholds and the box percentile were set on this scene, so figures are in-sample. No held-out check yet (acceptance seeds 51 to 65 and levels L2/L3 are the next step).
- Points per mask were down-sampled by the probe, so voxel claims and fine shapes are coarse.
- Held-object attach was not tested.
- Nothing here says a generator does better with the perceived text; that needs an exp04-style run with this text (paid, not done).
