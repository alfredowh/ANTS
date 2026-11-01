# Experiment 02: demo vs no demo when programs are debugged in the scaled scene

Run 2026-10-31 to 2026-11-01. Run directory: `data/runs/exp02_scaled/` (git-ignored; per sample: programs, diffs, feedback, `record.json`; `summary.md`, `events.jsonl`). Model calls: `data/llm_ledger.jsonl`. **n = 3 samples per arm, 1 task: a hint, not a result.**

## Setup

Same task, generator, prompts and demo spec as [experiment 01](experiment-01-demo-vs-nodemo.md) (`libero_goal_swap:8` "put the bowl on the plate", `muse-wonder-1.0`, hurobo clip `20261016_233832`). What changed:

- **Debug scene = scaled.** Programs are debugged and repaired in a scene where the bowl is scaled x1.227 and the plate x1.855 (`--debug-scene scaled`), closer to the real-size objects in the demo. Evaluation runs the final program unchanged in both `stock` and `scaled`.
- **Up to 4 repairs** (5 attempts) per sample; temperatures 0.2, 0.7, 0.5.
- **Seeds:** debug seed 51, evaluation seeds 51-55. These are acceptance seeds used during development, not the held-out set.
- **Budget:** the first pass hit its 600,000-token budget (627,090 used) and stopped inside nodemo sample 2; the run was resumed with a 320,000-token budget (rerunning the same command with the same `--out` keeps finished samples and redoes the stopped one). Event log: `budget_stop` and the second `run_start` in `events.jsonl`.
- **Command:** `uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ../ASPIRE --demospec data/demospecs/hurobo_233832.json --out data/runs/exp02_scaled --debug-scene scaled --scenes stock,scaled`

## Result

| Arm | Sample | T | Debug attempts | Solved debug seed | Eval scaled | Eval stock | Tokens (uncached) |
|---|---|---|---|---|---|---|---|
| no demo | 0 | 0.2 | 5 | no | 1/5 | 5/5 | 162,069 |
| **demo** | 0 | 0.2 | 4 | yes | 5/5 | 0/5 | 121,073 |
| no demo | 1 | 0.7 | 5 | no | 0/5 | 0/5 | 105,598 |
| demo | 1 | 0.7 | 5 | no | 0/5 | 0/5 | 199,921 |
| **no demo** | 2 | 0.5 | 4 | yes | 5/5 | 5/5 | 87,695 |
| demo | 2 | 0.5 | 5 | no | 0/5 | 0/5 | 189,943 |

Totals: no demo 355,362 tokens, demo 510,937, together 866,299 (about $11.7 at the logged $13.5 per million).

## What it shows, and what it does not

- Each arm solved the debug seed in 1 of 3 samples. **This run does not show a benefit of the demonstration**; experiment 01's "demo solved, no demo did not" was not reproduced, and the demo arm used more tokens.
- The only program that worked in both scenes came from the **no-demo** arm (sample 2). The demo arm's one solved sample works in the scaled scene only (0/5 in stock).
- Programs that pass in the scene they were debugged in need not pass in the other (demo s0: 5/5 scaled, 0/5 stock; no-demo s0: 5/5 stock, 1/5 scaled even though its debug attempts failed). Debugging in one scene overfits to its geometry.
- With 3 samples per arm and large differences between temperatures, no claim about the demonstration is supported either way. Next steps need more samples per arm and a held-out scene or seed set.

## Limitations

- n = 3 per arm, one task, one model, one demo.
- Evaluation seeds overlap the debug seed and are acceptance seeds, not held-out.
- The first pass was cut by the budget and resumed, so the three nodemo samples were not all produced in one uninterrupted run (sample 2 was redone).
