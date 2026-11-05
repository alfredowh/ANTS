# Experiment 04: which description of the scene helps the generator

Status: finished 2026-11-01 (G and E: 23 cases; A0 replay of the 15 exp03 programs; A3 perception test). Results are in `data/runs/exp04_scene` (view with `uv run python -m ants.evalkit.report data/runs/exp04_scene`). Numbers below are filled in from that run only.

## Why

In exp03 (clip 233859, attempt 2) a program stalled four times. A replay with the simulator's contact log showed the cause: the gripper **hand body** pressed down on a thin rail of the **wine rack** (geom `wine_rack_1_g4`, top at z = 0.237 m in the robot base frame) for about 477 of 876 steps, with a mean normal force of 24 N. The program never looked at the rack, and the model's own note blamed reach. With the rack's collision switched off, all calls in that replay succeeded. (The replay is bit-identical to the original run: end-effector paths differ by 0.0 m.)

The question: **which description of the scene, given to the model, makes it write programs that keep the hand clear, and does contact evidence improve a repair?**

## Design

One clip (233859, demonstration summary in the prompt), the scaled bowl and plate (real size), debug seed 51, `muse-wonder-1.0`, temperature 0.2, one run per cell. The scene given to the model is **simulator truth** ("oracle"), not a perceived scene; whether SAM 3 plus depth can produce it is a separate experiment (A3 in the [proposal](proposal-collision-context.md)).

**G: the first program.** Only the scene section of the prompt changes.

| Id | The prompt adds |
|---|---|
| S0 | nothing (baseline) |
| S1 | object names and centre positions |
| S2 | + sizes |
| S3 | + relations: touching, and nearest distance in mm between close pairs |
| S4 | combination: radius-by-height profile for bowl and plate, the individual boxes of the wine rack, the relations, and the gripper hand (about 21 x 10 cm, underside about 3 cm above the TCP) |
| SP | placebo: S4 with the wine rack listed where it stands in a different level |

**Scene levels** (the hardened ones are built from the path of the successful attempt 4, see `data/scenes/success_trajectory.json`):

| Level | Scene |
|---|---|
| L1 | as in exp03: rack behind the plate, touching its rim |
| L2 | rack moved 38 cm forward and 40 cm left, next to the bowl's start (found by a grid search for the smallest move that blocks the hand's path, at least 1 cm clear of all other objects, exact box-to-box test) |
| L3 | L2, and the wine bottle (16 cm tall) moved 6 cm back and 2 cm right so it stands where the hand closes on the bowl rim |

The rack has no free joint, so it is moved by editing its body position in the launcher (`pose.body_offsets_m`). The hardened levels are not proven solvable.

**E: one repair.** The failed attempt 2 of exp03 is repaired once; only the evidence in the repair message changes.

| Id | The repair message adds |
|---|---|
| E0 | nothing (exp03's message; the reply is reused from exp03) |
| E1 | the simulator's contact log (gripper part, object, steps, force, contact point) |
| E2 | E1 + the S4 scene |
| E3 | E2 + the TCP height while blocked next to the contact height, and a note that nothing else was blocked and no joint was at a limit |
| EP | placebo: E3 with the rack and the contact moved to another position |

## What is logged

Per run: prompt, reply, program, diff against the repaired program (E), the rollout with video, `contacts.jsonl` (every MuJoCo contact per step), the settled scene dump with exact object gaps, and `overlay.json` (path, arm as cuRobo spheres, contact events). The viewer has an About page (summary, contents, abbreviations), a Results matrix and a Scene view.

## Caveats

- One run per cell: differences can be luck.
- The G prompts use the **current** `RULES` in `generator.py`, which contain a rule added after exp03 (programs start with `params` and `attack_ranges` dict literals). S0 is therefore a fresh baseline, not exp03's reply. E reuses exp03's conversation, so it does not contain that rule.
- Oracle scene, one clip, one task.

## Results

All numbers come from `data/runs/exp04_scene` (events.jsonl, record.json per case, `a0.json`, `a3.json`). One run per cell.

**G and E.** 23 cases, none solved the task (including the baseline), so success cannot separate the variants. Stalled calls summed over L1 to L3: S0 8, S1 2, S2 0, S3 2, S4 3, SP 3. Blocking contact (steps): S0 0, S1 77, S3 70, S4 34, SP 116; three of the four cases were the hand on the wooden cabinet, the fourth the placebo's hand on the wine rack. In E, the WHY notes of E1 to E3 name the rack and the right mechanism (hand underside about 3 cm above the TCP on the rail top at z = 0.237 m), E0 does not; E2 and E3 stalled 0 times, E1 once, E0 twice, EP once. All five still failed the task. EP is not a clean placebo (it kept the true height and the claim that the hand pressed a rack).

**A0, what blocked the stalls of the 15 exp03 programs** (replay with the contact log; 14 replayed, clip 233832 attempt 4 failed three times with a TypeError in the replay): 12 programs stalled; 7 of the 12 had a blocking contact with an object they never looked at (wine rack: 233832 a1, a2; 233859 a1, a2; 234314 a4; wooden cabinet: 234314 a2, a3, a4), 5 stalled without one (another cause).

**A3, ASPIRE perception against the simulator** (agent-view camera, SAM 3 text mask, depth, centre error in the horizontal plane): in L1 the bowl is 0.0 cm off, the plate 5.9, the bottle 4.7, the cheese 0.6, the cabinet 4.7, the stove 6.3, but the query "wine rack" returns something 86 cm away (not found). In L2 and L3 the bowl mask merges with the adjacent rack (centre 12.3 cm off, z 0.12 m instead of 0.02), the rack is 14 cm off, and "flat stove" returns the wooden cabinet (58 cm off).

See the next-steps list in the session summary; open items: repeat runs, solvability check of L2 and L3, a cleaner placebo, crossed shape x relation factors, A5 to A8.
