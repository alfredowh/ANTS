# Experiment 01: does one demonstration help the generator? (bowl on plate)

Run 2026-10-31. Run directory: `data/runs/demo_vs_nodemo_01/` (git-ignored; programs, run directories, `record.json` per sample, `summary.md`). Model calls: `data/llm_ledger.jsonl` and `data/llm_cache/`. **n = 2 samples per arm, 1 task: a hint, not a result.**

## Setup

- **Task:** `libero_goal_swap:8` "put the bowl on the plate" (stock LIBERO objects), ASPIRE `cap-harness`, seeded mode.
- **Generator:** `muse-wonder-1.0` (Meta API). Prompt: ASPIRE program rules + API reference + one example program for another task.
- **Arms:** identical except that `demo` adds a demonstration section built from hurobo real clip `20261016_233832`:
  - the rim pinch at 1.24 bowl radii and 0.82 of the bowl's height
  - the approach from above
  - carry height
  - release at 0.67 plate radii, with an uncertain height
  - all relative to object size (`tools/hurobo_demospec.py`, `src/ants/synthesizer/generator.py`).
- **Per arm and sample:** write a program, run it on debug seed 51, repair up to 2 times from text feedback (`src/ants/adversary/rollout.py::feedback`), then evaluate the final program unchanged on seeds 51–55. Samples at temperature 0.2 and 0.7.
- **Command:** `uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ../ASPIRE --demospec data/demospecs/hurobo_233832.json --out data/runs/demo_vs_nodemo_01`

## Result

| Arm | Sample | Debug attempts | Solved debug seed | Eval success (seeds 51–55) | Tokens |
|---|---|---|---|---|---|
| no demo | 0 (T 0.2) | 3 | no | 0/5 | 63,882 |
| **demo** | 0 (T 0.2) | 2 | **yes** | **5/5** | 55,857 |
| no demo | 1 (T 0.7) | 3 | no | 0/5 | 58,854 |
| demo | 1 (T 0.7) | 3 | no | 0/5 | 105,711 |

**Total: 284,304 tokens across 12 Muse calls** (cap was 600k).

## What the programs did

- **Winning demo program** (`demo/sample0/program_attempt1.py`):
  - Uses the demo numbers directly: pinch height 0.82 × the measured bowl height, starting distance 1.24 × the measured radius.
  - Then refines the distance to the bowl wall measured from the point cloud at that height, and pinches the rim.
  - The same program, unchanged, solved all 5 acceptance seeds.
- **No-demo, sample 0:** the first attempt grasped the bowl's centre (as in the smoke test). By the last repair it had switched to a rim grasp learned from the failure feedback, but `move_to_pose` still timed out. Feedback alone moves the model in the right direction; the demo got it there faster and precisely enough.
- **Failed demo sample (T 0.7):** `move_to_pose` timeouts on all 3 attempts.

## First robustness preview (System 2 hook)

The winning program, unchanged, under three perturbations on seed 51, through `tools/aspire_launch.py`:

| Perturbation | Success |
|---|---|
| Bowl friction × 0.4 | yes |
| Bowl shifted +4 cm x, −3 cm y (the program measured exactly this shift) | yes |
| Actuation noise σ 0.01 rad + 2-step latency | yes |

These perturbations were chosen by hand, not by an adversary, and are mild. Friction and actuation could not be confirmed from the outputs of these three runs; the launcher now logs every applied change.

## Real-size scene (bowl x1.227, plate x1.855)

The winning program, unchanged, on the real-size scene of hurobo E1 (`tools/aspire_launch.py` `scale`, seeds 51-55, runs in `data/scaled_test/`): **0/5**. On seeds 51 and 52 the first `move_to_pose` times out and the bowl ends 9-14 cm from the plate centre without the task counting as done. So a program that is perfect on stock objects does not transfer to your real object sizes: a size-robustness failure of the kind System 2 should find.

Correction: the launcher's first version rebuilt the scene and then called `reset()` again, which restores the stock task, so an earlier "scaled" success was on stock objects and is discarded. The launcher now rebuilds after each reset and logs the scaled bounding radii (bowl 0.0841 -> 0.1031 m, plate 0.0974 -> 0.1806 m) as proof.

## Limits

- Two samples per arm, one task, one demo clip.
- The no-demo arm did learn a rim grasp from feedback, so a larger repair budget might close the gap. That is the next comparison to run.
- Tokens per call (about 20–25k, most of them reasoning) are higher than the smoke test suggested.
