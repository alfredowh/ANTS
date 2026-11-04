# Experiments 09 to 11: the held bowl attached to the hand

Status: ran 2026-11-02 (see `data/runs/curobo/exp09|exp10|exp11`); results not written up yet. Numbers will be filled in from `data/runs/curobo` only.

## Why

Experiments 06 to 08 ([doc](experiment-06-08-curobo.md)) solved 1, 2 and 2 of 3 arms. Of 182 failed `move_to_pose` calls, 142 were "cuRobo goal state infeasible (scene_collision)". In a replay of one failed and one successful program the cloud points inside the goal spheres sit 10 to 18 cm under the hand flange (median 14 cm): the held bowl is not attached to the robot and none of the 43 programs passes it as `target_point_cloud`, so its depth points stay in the cloud as an obstacle. A replay with my own sphere-against-cloud check (not the real cuRobo) suggested the refusals go away when the bowl is attached.

## What changed in the stack

- **Attached bowl.** While the gripper is closed on the bowl, `tools/aspire_launch.py` (`planner.attach`) removes the bowl's points from the planning cloud and writes spheres that cover a bowl of the **known** outer-radius profile (from `data/scenes/L1/contacts_scene.json`; rings at heights 0, 1.2, 3.7 and 6.2 cm, radii 2.8, 5.6, 6.7 and 6.6 cm; sphere radius 1.5 cm; about 40 spheres) to `data/runs/curobo/attach.json`, in the hand frame. `dev/curobo/service_dev.py` reads that file before every plan and puts the spheres on cuRobo's `attached_object` link (fixed to `panda_hand`; `dev/curobo/franka_attach.yml` has 64 slots instead of 4), so they move with the hand in every collision check. ASPIRE is not modified.
- **Where the bowl points come from.** SAM 3 text mask "bowl" (exp09, exp10, `curobo-sam3`), or the simulator's segmentation render (exp11, `curobo-sim`). The bowl axis is fitted to the visible rim with the known radius (SAM 3) or taken from the simulator box (sim); the height comes from the profile.
- **No SAM 3D.** In exp10 the sphere size also comes from the known bowl size, not from SAM 3D (not installed).
- **Planning clouds are saved** per attempt (`--save-clouds`) so the plan viewer can replay them.
- **Carve margin, correction.** Exp06 to 08 ran with `ANTS_CARVE_MARGIN_M=0.0`, which the service turns into max(voxel 0.01 m, 0.0) = 1 cm. The earlier doc and viewer text said 2 cm. The replay constant is now 1 cm.
- **Sticky latch (fix after exp09-11).** The first version re-decided "held or not" every frame and dropped the bowl back into the cloud on any missed mask; exp11/nodemo attempt 2 then refused the descent goal (hand inside the bowl's own points: 245 ring points in the descent cloud, 0 at carry). Now the latch stays shut while the gripper is closed, and removal also cuts cloud points around the *predicted* sphere positions (hand-frame spheres from the attach frame moved by the current hand pose), so a flickering mask cannot replant the obstacle. Verified on the failing data (ring points 245 → 0, goal hits → 0 in the replay model). Per-frame diagnostics go to `<attach-file-stem>.frames.jsonl` next to `attach.json`, since the `[ants-attach]` stderr lines were lost for exp09-11.
- **Sandbox builtins (fix after exp09-11).** exp11/nodemo attempt 3 died with `NameError: name 'getattr' is not defined` (cap-harness AST sandbox); attempt 4 without `getattr`/`isinstance` probing succeeded, so the generator `RULES` now forbid them and tell the model to probe fields with direct access in `try/except AttributeError`.
- **Two sim-mode attach bugs (found verifying the latch on the GPU host, 2026-11-03).** (1) `binary_dilation(mask, iterations=0)` dilates until stable, i.e. the whole frame: every simulator bowl mask was full-frame, so the bowl was never "near" and the latch never engaged in exp11. Prefixed (object) masks are now returned exact. (2) The sim branch built spheres from `body_aabb` in sim-world frame but subtracted the hand pose in `robot_base` frame (offset verified translation-only to <1 mm on the exp11 bowl via the settled scene dump vs the localization); the box is now moved by the `robot0_base` world pose. Verified live: the exact failing program (exp11/nodemo attempt 2, descent refused) now runs to `task_succeeded`, latch `keep` on all held frames, 42 spheres, 500-700 points removed per frame (`data/runs/curobo/verify_fix/sim/`). Re-ran an exp09 (SAM3) program too: identical refusal signature as its original run (grasp self-collisions retried through, place goal-infeasible), so no regression there — the release-goal refusal is the known fat-sphere caveat below.

- **Frame bug (found 2026-11-04, fixed after these runs).** The spheres were written in the gripper-site frame but mounted on `panda_hand`, 9.65 cm too high. In exp09 to 11 only the bowl's cloud removal worked as described. See handoff-curobo-debug.md.

## Design

Same as exp06 to 08 (scaled scene, seed 51, `muse-wonder-1.0`, temperature 0.2, WHY repair, 4 repairs, one run per arm: clip 233859, clip 233832, no demo; footprint success rule; 250k tokens per run).

| Exp | Planner and masks | Scene text | Repair feedback | Held bowl |
|---|---|---|---|---|
| 09 | cuRobo, SAM 3 masks | none | WHY only | attached, known size |
| 10 | cuRobo, SAM 3 masks | S4 from perception (exp05) | E3 | attached, known size |
| 11 | cuRobo, simulator masks | S4 from the simulator | E3 | attached, known size |

## Caveats to check when the results come in

- The attach used to fail silently (exp09-11 stderr was lost). Now each planning scene appends one JSON line to `<attach-file-stem>.frames.jsonl` (`action` wait/keep/release, `n_bowl`, `n_spheres`, `n_removed`, `failed`); a `release`/`wait` where the bowl should be held, or a `failed` entry, means the run behaves like exp06 to 08.
- The attached bowl touches the plate by design at the release, so release goals may still be refused.
- The service removes cloud points within 1 cm of every robot sphere, now including the attached bowl, so a real object that close to the bowl at the start pose is hidden from the planner. The contact log (blocking contact) is the check.
- One run per cell; the success rule and carve differ from exp01 to 04.

## Results

Not run yet.
