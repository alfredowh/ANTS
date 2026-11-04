# Results (2026-11-04)

All numbers come from logged runs on one RTX 5090 (Vast.ai), ASPIRE `cap_harness` on LIBERO-Pro
`libero_goal_swap` task 8, "put the bowl on the plate", Franka arm. Run folders live in `data/runs/`
(git-ignored); each has its logs, policies, rollout videos and a `studio.html`. Attacks use
acceptance seeds 51–65; held-out cases use seeds 1–50 and never reach System 1.

## Runs

| Run folder | What | Severity | Result |
|---|---|---|---|
| `libero_loop` | closed loop, 10 cycles, all categories, then 50 held-out cases | 0.3–0.8 | 1 failure (size), rewrite rejected; held-out v0 **47/50** |
| `libero_loop_size` | loop restricted to size, 8 cycles | 0.3–0.8 | 2 failures, both rewrites rejected |
| `libero_loop_size_v2` | the same after the diagnosis fix (#21), then 50 held-out size cases | 0.3–0.8 | **v1 accepted**; held-out v0 **49/50**, v1 **47/50** |
| `libero_spark_08` | 8 attacks proposed by Muse Spark | ≤ 0.8 | 1 size failure |
| `libero_h1a_08` | adaptive (η = 0.2) vs uniform (η = 1.0), 5 seeds × 40 attacks | 0.3–0.8 | 2/200 vs 1/200 failures |
| `libero_studio`, `libero_spark`, `libero_h1a` | first runs, severity cap 0.6 | ≤ 0.6 | 0 failures in 131 attacks |

759 real rollouts in total.

## Findings

1. **v0 is robust when perception is right.** Over the first 625 rollouts: 0 failures in 599 with
   a correct plate measurement, 11 failures in 26 when SAM 3 mis-read the plate (measured 11–19 cm
   tall instead of about 2 cm), so v0 released the bowl too high.
2. **A larger plate triggers the mis-read.** Share of size attacks with a mis-read plate, by plate
   scale: ×1.0–1.3 0/7, ×1.3–1.5 6/52, ×1.5–1.6 5/21, ×1.6–1.7 8/18, ×1.7–2.0 4/8. About 1% in
   the other categories. Some scene seeds (19, 27, 36, 40) mis-read the plate under other
   attacks or mild plate scales too.
3. **The first diagnoses blamed the wrong call.** Every rollout, successes included, has a harmless
   `move_to_pose` timeout at `approach_high`. Before #21 the signature took the first failed call,
   and the model never saw the program's printed measurements; Muse Spark's budget also ran out
   after 3 attacks.
4. **After #21 the loop repaired the failure it found.** Muse Spark (confidence 0.84) traced it to
   `plate_top_z = max(...)`, comparing plate height 0.112 m with 0.019 m in the nominal run. Muse
   Wonder computed the support height from interior plate points and added a final check; the gate
   accepted v1 (fixed the attack case, no regression on nominal seeds 51–53).
5. **The fix did not generalise.** On 50 held-out size cases v1 fixed 1 case and broke 3 (seeds
   19, 27, 40: plate mask still mis-read; v1 released at the right height, the bowl ended about
   6 cm off centre). Not significant with 4 differing cases, but no gain. The gate saw 4 cases;
   the paper's protocol uses 30 acceptance cases, which would cover more scene seeds.
6. **H1a is not answered.** v0 fails about 1% of the time, too rarely for adaptive selection to
   learn from in 40 attacks.

## Cost

| Item | Tokens | Cost |
|---|---|---|
| Muse Spark (System 2: proposals, diagnoses, explanations) | 805k | $10.87 |
| Muse Wonder (4 rewrites) | 104k | $1.40 |

Per loop cycle: $0.17 (`libero_loop`), $0.27 (`libero_loop_size`), $0.55 (`libero_loop_size_v2`,
with Muse Spark on every cycle). Prices at the observed $13.5 per million tokens.

## Reproduce

Needs the ASPIRE checkout (`git submodule update --init ASPIRE`), its LIBERO and provider
bootstraps, services SAM 3 (:8114) and PyRoki (:8116), and `META_API_KEY` in `.env`.

```bash
uv run python -m ants.orchestrator.preflight --aspire /abs/path/ASPIRE --muse-spark --smoke

# closed loop restricted to size, then held-out evaluation
uv run python -m ants.orchestrator.run --backend cap_harness --aspire /abs/path/ASPIRE \
  --model muse-spark --adversary-token-budget 500000 \
  --synthesizer muse-api --synth-token-budget 400000 \
  --categories size --cycles 10 --eval-held-out 50 --out data/runs/libero_loop_size_v2

# adaptive vs uniform
uv run python -m ants.adversary.experiments.adaptive_vs_uniform --backend cap_harness \
  --aspire /abs/path/ASPIRE --attacks 40 --seeds 0 1 2 3 4 --out data/runs/libero_h1a_08

# look at any run
uv run python -m ants.studio.console --adversary-run data/runs/libero_loop_size_v2
```
