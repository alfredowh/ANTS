# Experiments 06 to 08: cuRobo on perception, with and without scene understanding

Status: finished 2026-11-02 (9 runs, overnight). Numbers are filled in from `data/runs/curobo` only.

## What changed in the stack first

- **Success check fixed.** LIBERO's `On(bowl, plate)` calls `plate.check_ontop(bowl)`, so `self` is the plate. `tools/aspire_launch.py` scaled the 0.03 m tolerance by the *other* object's factor (the bowl, 1.227) instead of the support's (plate, 1.855). Fixed (the default scaled check now uses the plate's factor). This changes results on every scaled scene compared with exp01 to 04.
- **New success rule (opt-in, `--ontop-area 0.5`).** "Bowl on plate" passes when the bowl touches the plate, the plate origin is not above the bowl's, and at least half of the bowl's footprint circle lies inside the plate's footprint circle (circles from the collision geoms' boxes). Unit-tested for the overlap formula; one real check: the exp03 clip 233859 attempt 4 program (a known success) still passes.
- **cuRobo with the SAM 3 robot mask is now a launcher option** (`planner` in the scene spec, `--planner curobo-sam3`): every plan uses cuRobo (default `MotionStrategy(trajectory_planner="curobo")`), the planning cloud drops pixels of the SAM 3 masks "robot arm" and "robot gripper" and points within 12 cm of the manipulated object. `--planner curobo-sim` takes the robot mask from MuJoCo's segmentation (privileged digital twin). The cuRobo service is `dev/curobo/service_dev.py` (the service ran with ANTS_CARVE_MARGIN_M=0.0, which it turns into max(voxel 0.01 m, 0.0) = 1 cm; an earlier version of this doc said 0.02 m).
- **SAM 3.1 option (added later, no results yet).** `--sam-model sam3.1` on `exp_curobo` / `demo_vs_nodemo` maps planner `curobo-sam3` to `curobo-sam31`: the same prompts go to the Meta Model API model `sam-3.1` (needs `META_API_KEY`). ASPIRE itself is untouched, and default `--sam-model sam3` keeps the old path byte-identical. Masks are box approximations of the 3.1 records until the pixel decoder lands (see `src/ants/synthesizer/sam_api.py`); probe CLIs (`a3_perception`, `perceived_scene`) accept and record the flag but their in-sandbox `segment_text` stays on SAM 3.
- **Smoke tests** (one run each, not results): the dev orbit program with `curobo-sam3` ran cuRobo plan calls and stopped with a `planning_failed` move; the known success above passes under the area rule.

## Design

Scaled scene (bowl x1.227, plate x1.855), seed 51 for debugging, `muse-wonder-1.0`, temperature 0.2, WHY repair, 4 repairs, one run per arm. Arms: demonstration summary of clip 233859, of clip 233832, and no demonstration. No acceptance or held-out evaluation seeds (debug only).

| Exp | Planner and execution | Scene text (first prompt and repairs) | Repair feedback |
|---|---|---|---|
| 06 | cuRobo, SAM 3 robot mask | none | exp03 feedback with WHY |
| 07 | cuRobo, SAM 3 robot mask | S4 built from perception (exp05) | exp03 feedback + E3: contact log, scene, stall readings |
| 08 | cuRobo, simulator robot mask | S4 from the simulator | as 07 |

Programs run through the ASPIRE API without simulator state in all three; the simulator is used for the success check, the contact log (feedback in 07 and 08, evaluation in 06) and, in 08, the robot mask. In 08 object localisation still uses the API's SAM 3 plus depth: the API has no privileged object-pose call.

A clean success is a task success with no blocking contact (contact log: non-task contact of at least 10 steps and 5 N).

## Run

`uv run python -m ants.orchestrator.exp_curobo --exp exp06,exp08,exp07` (see the run book entry `curobo.exp`). Budget: 250k new tokens per run, at most 9 runs.

## Results

All numbers come from `data/runs/curobo/<exp>/<arm>/<demo|nodemo>/sample0/record.json` and `data/runs/curobo/overnight.log`. One run per cell, debug seed 51 only, no acceptance or held-out seeds.

| Exp | Clip 233859 | Clip 233832 | No demo | Solved |
|---|---|---|---|---|
| 06 (no scene text) | not solved, 5 programs | not solved, 5 programs | solved by program 5 (attempt 4) | 1 of 3 |
| 07 (perceived S4 + E3) | not solved, 5 programs | solved by program 4 (attempt 3) | solved by program 4 (attempt 3) | 2 of 3 |
| 08 (simulator S4 + E3, simulator robot mask) | not solved, 5 programs | solved by program 5 (attempt 4) | solved by program 5 (attempt 4) | 2 of 3 |

New tokens per run: exp06 189k, 183k, 136k; exp08 204k, 252k, 181k; exp07 267k, 170k, 160k. Total 1.74M tokens, about 23.5 USD. Exp07 clip 233859 and exp08 clip 233832 ended above the 250k cap because the cap is checked before each model call.

What the logs show:

- **Blocking contacts: none.** The contact analysis found no blocking contact (at least 10 steps and 5 N) in any of the 43 rollouts. Every success is therefore also a clean success, and no failure is explained by a pressed object. The E3 evidence in 07 and 08 contained the failed calls, the expected finger-bowl contact and the joint margin, plus the S4 scene; the wine-rack contact that motivated the evidence never occurred under cuRobo planning.
- **Failures are planner failures.** Failed calls in the unsolved runs are `planning_failed` (up to 16 per program in the last 233859 attempts of 07) and `timeout` (one per program in most first attempts). Six programs ended in `program_error`.
- **Perceived against simulator scene (07 against 08):** same number solved (2 of 3); 07 solved both runs one program earlier (program 4 against 5). One run each, so this is not a difference.
- **Scene text against none (07 and 08 against 06):** 2 of 3 against 1 of 3, one run each.
- **Clip 233859** is not solved in any of the three, as in exp03 where it needed 5 programs.

## Caveats

- One run per cell and one seed: 1 against 2 of 3 is not evidence.
- The success rule changed from exp01 to 04 (plate factor fixed, footprint rule), so success rates are not comparable with those experiments.
- The programs differ a lot in how many `planning_failed` calls they absorb and still succeed (for example 41 in exp07 no-demo), so success mostly measures whether the program tolerates cuRobo failures.
- In 08, object localisation still uses the API's SAM 3 plus depth; only the robot mask and the scene text come from the simulator.
- Exp05 selection thresholds were tuned on this scene, so the perceived S4 text is in-sample.
- The scene was the L1 scene only; the hardened levels L2 and L3 were not used.
