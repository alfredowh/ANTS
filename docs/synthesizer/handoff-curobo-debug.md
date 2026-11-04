# Instructions for the next agent: remove false-negative cuRobo refusals with `curobo-sam3`

For Claude Opus (or any coding agent). Read `AGENTS.md`, `docs/runbook/agent-access.md` and this file, then work.
Do not print or commit `.env`. Muse tokens are not needed for anything below; if a step would spend them, stop and ask.

## Status 2026-11-04: read this first (it corrects sections below)

Found by reading the logged cuRobo responses and clouds. Numbers come from `data/runs/curobo/replay_framefix/` (seed 51 only).

1. **Frame bug, fixed in `tools/aspire_launch.py`.** Attach spheres were computed in the gripper-site frame (`end_effector_poses`) but mounted on
   `attached_object`, which is fixed to `panda_hand`. The site is 9.65 cm along the hand's z axis, so cuRobo modelled the held bowl 9.65 cm too high,
   inside the wrist. Spheres touching `panda_link5` (not on the ignore list) gave `start state infeasible (self_collision)` at the lift. Every other overlap was with
   ignored links, so the spheres protected nothing. **All attach runs before this fix are affected: exp09 to 11, exp12, the earlier replays.** Their benefit came only from
   removing the bowl's points from the cloud. Test: `test_attached_spheres_are_written_in_the_panda_hand_frame`.
2. **Effect (5 replays, one seed).** Exp10 no-demo attempts 1, 2 and 3 with SAM 3 masks, and attempts 1 and 2 with simulator masks, all succeed; attempts 1 and 3 have zero refusals. Attempt 1 had
   failed under every earlier setting. This is one seed: a multi-seed run was started and stopped at the owner's request before any run finished (`replay_seeds`, no usable results).
3. **Corrections to the hypotheses below.** H2 is out: the logged response says `start_state_feasible: true`, start scene collision 0, for the place refusal. H4 was wrong: the lift refusal was the frame bug, not the table.
   Point 4 under "What is established" is resolved: the blockers of the place goal were a ghost of the hand and bowl at their current position, straight above the goal (−7 to +2 cm in height from the site, within 9.5 cm radially).
   The oracle and simulator-mask tests each removed only one of the two sources, so they could not show this. My earlier statement that SAM 3 leakage is ruled out was unsound.
4. **Remaining false negatives.** Attempt 2 still has 3 refusals, all the descent onto the rim with the gripper open and the bowl not yet held. The goal labeler marks all 3 free in the simulator (`replay_smoke`, simulator masks). In the SAM 3 run no cloud point is inside the goal spheres but 34 are within 1.5 cm, so these are rim points near the fingers.
   The program does not pass `target_point_cloud`, so `exclude_radius_m` never applies to them. Untested fix: exclude the localized target from the cloud for grasp moves, in the launcher or through a generator rule. The program recovered with another grasp direction.
5. **New tools.** `planner.label_goals` in the launcher scores each plan's goal on a copy of the simulator state, with the held bowl moved with the hand. `dev/curobo/goal_confusion.py` prints the confusion matrix. `replay_attach.py --seeds` takes acceptance seeds. The labeler scores the goal only, not the path.

**Next, once the simulator is free:**
`ASPIRE/.venv-libero/bin/python dev/curobo/replay_attach.py --mode attach --out data/runs/curobo/replay_seeds --only exp10_nodemo_a1,exp10_nodemo_a2,exp10_nodemo_a3,exp10_clip233859_a3,exp10_clip233832_a2 --seeds 51,52,53`, then `--mode sparse`, then
`uv run python dev/curobo/goal_confusion.py data/runs/curobo/replay_seeds/attach data/runs/curobo/replay_seeds/sparse`. Check that the fix does not add false positives (`plan_colliding`) and re-run the rack guard. With the bowl now modelled correctly, watch for new refusals at the place move (H5).

## Goal

With `--planner curobo-sam3` (cuRobo plans on a depth cloud, the robot masked by SAM 3), cuRobo sometimes refuses a goal
that is actually free ("cuRobo refused the request", `constraint:scene_collision` above 0). That is a **false negative**:
a planner failure counted against a program that may be fine. Make these refusals rare **without** letting real collisions
through (false positives, the wine-rack bug in `dev/curobo/README.md`).

Definition used throughout: a refusal is a false negative when the refused goal joint configuration, set in MuJoCo, has no
forbidden contact (robot against anything other than the held bowl and the robot itself).

Done when, on the logged programs listed below, the share of refusals that are false negatives is near zero and the rack case
still refuses. Report the confusion matrix (cuRobo refuses or plans, against simulator free or colliding) before and after.

## What is established (all from logs in this repo)

1. **Path of the cloud.** The client builds the cloud (`ASPIRE/src/cap_harness/api.py`, `_planning_scene`, then the launcher
   overrides in `tools/aspire_launch.py`: `exclude_radius_m`, `cloud_dir`, `attach`, `oracle_exclude`). The service
   (`ASPIRE/src/cap_harness/providers/curobo/service.py`, patched by `dev/curobo/service_dev.py`) drops far points, carves the
   robot (`ANTS_CARVE_MARGIN_M`, 0.0 means 1 cm), applies a sparse-voxel filter and builds a voxelised mesh. cuRobo gets points, not a mesh.
2. **Scale of the problem.** Exp06 to 08: 142 of 182 failed `move_to_pose` calls were scene-collision refusals
   (`docs/synthesizer/experiment-06-08-curobo.md`).
3. **Replays on seed 51** of exp10 no-demo attempts 1 and 2 (`data/runs/curobo/replay_clean/`, `replay_oracle/`, `replay_simmask/`;
   script `dev/curobo/replay_attach.py`; no model tokens):

   | Setting | Attempt 1 | Attempt 2 |
   |---|---|---|
   | sparse (no attach) | fail at the place move (420 steps) | fail (701 steps) |
   | attach (held bowl as spheres) | fail right after the grasp, at the lift (150 steps) | success |
   | oracle (bowl and plate pixels removed from the cloud, simulator state) | fail at the place move | fail |
   | oracle + attach | fail at the lift | success |
   | simulator robot mask (`curobo-sim`), no attach | fail at the place move | not run |

4. **Attempt 1, place move.** The saved cloud shows points inside the goal spheres of `panda_link6`, `panda_link7` and
   `panda_hand` (heights 0.20 to 0.28 m), and 3 start-state hits (`dev/curobo/plan_data.py`). The **exact simulator robot mask did not
   remove them**, so "SAM 3 leaks robot pixels" is not supported. Excluding the bowl and plate did not remove them either. What the
   points are is **not identified**.
5. **Attempt 1, lift with the attach.** Probably the attach spheres (42 spheres, radius 1.5 cm, bottom at z 0.020) touch table points.
   Not verified.
6. **Execution errors are separate.** Exp11 attempt 0 replay: `plan_motion` succeeded, `execute_trajectory` returned `ExecutionStatus.TIMEOUT`
   (`data/runs/curobo/verify_fix3/exp11_a0/`). Do not mix these with planning refusals.
7. **`failure_code` "timeout" in run records covers both planning and execution**, so old counts cannot separate them.

## Pitfalls that already cost time (read before running anything)

- **One global attach file.** The dev service reads `data/runs/curobo/attach.json` (`ANTS_ATTACH_FILE`). A spec whose `attach.file` points
  elsewhere is never read by the service. The earlier verification replays (`verify_fix*`) wrote per-run attach files, so their cuRobo probably
  had **no** bowl spheres; do not cite their "6 of 7" as an attach result. `replay_attach.py` uses the global file and resets it before every run.
- **Never run two replays or experiments at once** while the attach is on: they overwrite each other's file and delete each other's output folders
  (this happened twice and produced bogus 0-step runs).
- Replays need the ASPIRE environment: run from `ASPIRE/` with `LIBERO_CONFIG_PATH`, `MUJOCO_GL=egl` etc. (the script sets them).
- `dev/curobo/collision_validator.py` is a **run-level** contact validator (reads a contact log). It does **not** label a single goal state.
  You have to build the goal-state labeler (below).

## Hypotheses, in the order to test them

| # | Hypothesis | How to test | Risk |
|---|---|---|---|
| H1 | The blocking points are real scene objects close to the place pose (wine rack and cabinet are within about 4 cm of the plate), so the refusal may even be correct | label each point by nearest body (simulator segmentation or the AABBs in `contacts_scene.json`) and check the true clearance of the goal in MuJoCo | none |
| H2 | The start state is already in collision (3 start hits), which makes cuRobo refuse everything | list points inside the start spheres; test `ANTS_CARVE_MARGIN_M` 0.02 and 0.03 | a bigger carve hides real obstacles (rack bug): re-run `dev/curobo/carve_check.py` on the rack case |
| H3 | Voxelisation and the 1.5 cm clearance inflate objects | change `voxel_size_m` (0.02, 0.005) and the clearance in `plan_data.py` | slower plans |
| H4 | The attach spheres touch the table at the lift | raise the attach profile 1 to 2 cm, shrink `sphere_r`, or drop table points under the bowl | gripper-bowl collisions go unseen |
| H5 | At the place move the bowl touches the plate by design | exclude plate points only near the attached spheres during the release move | the oracle test removed the whole plate and attempt 1 still failed, so this alone is not enough |
| H6 | cuRobo's trajectory optimiser fails on feasible goals (stochastic) | retry the same goal with other seeds or more attempts; check the service config | hides slow planners |
| H7 | Execution timeouts are mislabelled as planning failures | split the two in the records with the trace span names | none |

## Method

1. **Build the goal-state labeler** (new file under `dev/curobo/`, standard library plus the ASPIRE venv): for each planning call in a run
   (`trace/calls/*curobo-plan-to-joints/{input,output}.json`, clouds in `clouds/cloud_NNN.npy`), take the goal joint configuration, set it in
   MuJoCo with the held bowl in the hand, and list contacts. Label the call free or colliding, and record the blocking link and body.
2. **Confusion matrix** over every existing planning call that has a saved cloud: exp09 to 11 (`--save-clouds`), the replay folders above.
3. **One change at a time** (H1 to H7), re-label, compare matrices. Use `dev/curobo/replay_attach.py` as the template (add a mode, never a flag
   that changes defaults). Programs: `PROGRAMS` in that file.
4. Keep the rack case (`tools/mapper_probe/plan_rack.py`, `dev/curobo/carve_check.py`) as the **false-positive guard**: a change that makes it plan into the rack is rejected.
5. Write up in `docs/synthesizer/` with numbers from logged runs only; add the commands to `docs/runbook/commands.json`, then
   `uv run python -m ants.evalkit.runbook check` and `build`.

## Commands

```bash
# services (runbook ids: services.start, curobo.service); the cuRobo service must have the carve margin and the attach file:
cd ASPIRE && ANTS_CARVE_MARGIN_M=0.0 ANTS_ATTACH_FILE=$PWD/../data/runs/curobo/attach.json \
  .venv-curobo/bin/python ../dev/curobo/service_dev.py --port 8118

# replay logged programs, no tokens (modes: sparse, attach, oracle, oracle-attach):
ASPIRE/.venv-libero/bin/python dev/curobo/replay_attach.py --mode attach --out data/runs/curobo/<new_dir> --only exp10_nodemo_a1,exp10_nodemo_a2

# which cloud points sit inside the goal spheres of each plan call:
PYTHONPATH=src ASPIRE/.venv-libero/bin/python -c "import sys; sys.path.insert(0,'dev/curobo'); import plan_data; \
from pathlib import Path; plan_data.main(Path('<run dir with trace/>'), Path('<clouds dir>'), Path('<out.json>'))"

# 3D view of the planning cloud and paths for one attempt:
PYTHONPATH=src ASPIRE/.venv-libero/bin/python dev/curobo/make_viewer.py data/runs/curobo/exp10/clip_233859
```

## Rules

- Tune only on acceptance seeds 51 to 65 (debugging used seed 51). Held-out seeds 1 to 50 are never used for tuning.
- `--init-mode seeded` always. Numbers in docs come from logged runs.
- Do not edit the user's uncommitted `src/ants/studio/` files. Work on branch `synthesizer`; commit small, one feature per commit, ruff and pytest first;
  ask before opening a PR.
- Ask before any run that spends Muse tokens above 100k.

## Where the evidence lives

- Final demo vs no-demo experiment (the demo vs no demo run): `docs/synthesizer/show-once-vs-task-only/` (snapshot, notebook), settings in `docs/synthesizer/demo-vs-nodemo-config.json`.
- cuRobo replays: `data/runs/curobo/replay_clean/`, `replay_oracle/`, `replay_simmask/` (git-ignored; ask the owner for the zip).
- Earlier cuRobo docs: `docs/synthesizer/experiment-06-08-curobo.md`, `experiment-09-11-curobo-attach.md`, `dev/curobo/README.md`,
  `docs/perception/scene-reconstruction-probe.md` (the fused-mesh probe; not wired into the planner).
