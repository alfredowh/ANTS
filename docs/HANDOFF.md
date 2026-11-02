# ANTS handoff: state on 2026-10-31 and next steps

Give this file to a new session as context. It is the single place that says where the project stands, how to run what exists, what was found, and what to do next. Read `AGENTS.md` (repo rules) and `docs/concept.md` (idea) next. Branch `synthesizer`.

## 1. One-paragraph state

- **What ANTS is.** One video demonstration → a frozen code model (Meta Muse) writes a robot program → an adversary perturbs the scene → failures become constraints → a gate accepts only rewrites that never regress. The claim was narrowed against RAPID, ASPIRE and CaP-X: the novelty is the loop (adversary-chosen tests, never-regress gate, targeted-demo escalation), not demo-to-program.
- **What runs.** The execution layer is NVIDIA ASPIRE's `cap-harness`, installed at `../ASPIRE` and working on the RTX A5500 laptop.
- **First result.** On LIBERO "put the bowl on the plate", Muse **with** a demonstration from a real hurobo phone clip wrote a program that solved 5/5 acceptance seeds (1 of 2 samples). **Without** the demo it solved 0/10 (0 of 2 samples). That program also survived three hand-picked perturbations.
- **Not built yet.** System 2 (adversary planner, diagnoser, constraint loop, regression gate, escalation) and memory.

## 2. Decisions already taken (do not re-ask)

| Topic | Decision |
|---|---|
| Harness | ASPIRE `cap-harness` at `../ASPIRE`, driven by ANTS's own client via subprocess. ASPIRE's Claude-Code agent layer is not used |
| Policy format | A program over primitives, written once per cycle (no model in the control loop). Per-step agent only as a later comparison arm |
| No-demo baseline | System 1 minus the DemoSpec. CaP-Agent0-lite (1 sample, ≤2 turns, text feedback) later if budget remains; full CaP-X later |
| Generator | Muse via the Meta API (`muse-wonder-1.0`), **$15 cap**. Other models via OpenRouter, **$5 cap**. No reference model yet |
| SAM | SAM 3 inside the harness (ASPIRE loads only `sam3.pt`). SAM 3.1 for demo-video tracking later (also served by the Meta API as `sam-3.1`) |
| Tasks | **T1** hurobo real-size bowl → plate (real phone clips; hurobo reused read-only) and **T2** LIBERO `libero_90:89` "pick up the book on the right and place it under the cabinet shelf". T0 = stock bowl-on-plate smoke task |
| hurobo | Read-only. Outputs go to `ANTS/data/`, never into hurobo |
| Marker size | 5.75 cm, measured by the user (2026-10-31). Smoke runs used 6.0 cm, so re-extract with `--marker-size-m 0.0575` |
| Long runs | Ask the user before anything over ~15 min, unless they said "do it" for that step |
| Git | Commit and push at milestones on `synthesizer`. The global git proxy is stale: use `git -c http.proxy= push` |

## 3. Where things are

| What | Where |
|---|---|
| Research assessment (ASPIRE, RAPID, CaP-X, SAM 3/3.1, hardware, checklist, build plan) | `docs/synthesizer/aspire-assessment.md`, appendices in `docs/synthesizer/research/` |
| Skills definition and autonomous mode (user's idea) | `docs/synthesizer/skills.md` |
| Smoke tests (install, first Muse attempt, hurobo extraction) | `docs/synthesizer/smoke-2026-10-31.md` |
| **Experiment 01** (demo vs no-demo) | `docs/synthesizer/experiment-01-demo-vs-nodemo.md` |
| User's open items | `docs/todo.md`; interactive [ANTS To-do](https://claude.ai/artifact/C3NqC3ij7jDMMtEqfzdaFp) (Status, Next steps, To-do; db collections `steps`, `next`, `todos`) |
| Research radar (labs and works with ANTS reviews) | [Robot Research Radar](https://claude.ai/artifact/3epiiPPS6AcpPoVyWfRfS5); skill `.claude/skills/robot-research-radar/` |
| Contracts | `src/ants/contracts/types.py` (DemoSpec, Policy, Constraint, Perturbation, CaseSpec, CallRecord, EpisodeTrace, Skill) |
| Muse client (cache, ledger, hard token budget) | `src/ants/synthesizer/llm.py` |
| Prompt builder (arms differ only in the demo section) | `src/ants/synthesizer/generator.py` |
| Harness runner + text feedback | `src/ants/adversary/rollout.py` |
| Experiment runner | `src/ants/orchestrator/demo_vs_nodemo.py` |
| hurobo clip → DemoSpec (run with hurobo's Python) | `tools/hurobo_demospec.py` |
| LIBERO human demos → DemoSpec (run with ASPIRE's Python) | `tools/libero_demospec.py` |
| Perturbation launcher (no ASPIRE edits) | `tools/aspire_launch.py` |
| Local data (git-ignored) | `data/`: `hurobo_e1/` extractions, `demospecs/`, `libero_demos/book_under_shelf_demo.hdf5` (596 MB, 50 demos), `runs/`, `llm_cache/`, `llm_ledger.jsonl`, `viz/` |
| ASPIRE local changes | `../ASPIRE/configs/profiles/a5500.json` and an `sm_86` entry in `configs/dependency-lock.json` |

## 4. How to run what exists

Every command, flag and example is in the run book: `uv run python -m ants.evalkit.runbook list` (also `docs/runbook.html`, `docs/synthesizer/experiment-commands.md`, `docs/runbook/commands-full.md`). The snippets below are the short version.

```bash
# ASPIRE services (SAM 3 + PyRoki, ~4.5 GB GPU). The experiments need them.
cd ../ASPIRE && CUDA_VISIBLE_DEVICES=0 TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 \
  scripts/supervise_services.sh --profile a5500 --providers sam3,pyroki

# Experiment 01 again (cached calls cost nothing; new ones count against --token-budget)
cd ANTS && uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ../ASPIRE \
  --demospec data/demospecs/hurobo_233832.json --out data/runs/<name>

# One program under a perturbation
cd ../ASPIRE && LIBERO_CONFIG_PATH=$PWD/.libero TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 MUJOCO_GL=egl \
  PYOPENGL_PLATFORM=egl EGL_PLATFORM=device CUDA_VISIBLE_DEVICES=0 \
  .venv-libero/bin/python ../ANTS/tools/aspire_launch.py <perturbation.json> -- run \
  --benchmark libero-pro --suite libero_goal_swap --task-id 8 --seed 51 --init-mode seeded \
  --program <program.py> --output-root <dir> --max-steps 2000 --camera-width 800 --camera-height 512

# Checks
uv run ruff check . && uv run pytest
```

- Keys: `ANTS/.env` holds `META_API_KEY` (endpoint `https://api.meta.ai/v1`). The OpenRouter key is in `../agentic-robot/sim/.env`. Never print or commit them.
- Muse models on the key: `muse-wonder-1.0`, `muse-spark-1.3`, `muse-spark-1.2`, `muse-spark-1.1`, `sam-3.1`, `muse-image-1.0`, `muse-voice-transcribe-1.0`.

### Recording and viewer (added after the first handoff)

- A run (`uv run python -m ants.orchestrator.demo_vs_nodemo ... --out data/runs/<name>`) writes every prompt, model reply, program (initial policy and each repair), program diff, feedback and event (`events.jsonl`) into its run directory.
- `--token-budget` now caps the **new** tokens of that run (default 600k, about $8 at the observed $13.5 per M tokens), not the ledger total. `--repairs` defaults to 4, `--scenes stock,scaled` evaluates each final program in both scenes (debug and repair use stock).
- View a run: `uv run python -m ants.evalkit.report data/runs/<name> --open` (one `report.html` in the run dir; `--serve` for http). It also renders `demo_vs_nodemo_01`.
- Observed Muse cost: dashboard went $150 -> $145.44 for about 337k tokens.

## 5. Results so far (all from logged runs, small n)

| What | Result | Doc |
|---|---|---|
| ASPIRE example on this laptop | success, 36 s, 4.5 GB GPU | smoke §1 |
| Muse, no demo, smoke (seed 51) | 0/3 attempts; grasped the bowl's centre and stalled | smoke §2 (raw files lost) |
| hurobo E1 clip extraction | 4/26 usable at 6.0 cm marker, 0/26 at 3.9 cm | smoke §3 |
| hurobo usable clips agree | rim pinch at 1.05–1.26 bowl radii, 5.5 cm high | experiment-01 |
| **Experiment 01** | demo 1/2 samples solved, 5/5 eval; no demo 0/2, 0/10. 284k tokens | experiment-01 |
| Winning program under 3 perturbations | 3/3 (friction × 0.4, bowl shift 5 cm, actuation noise + latency) | experiment-01 |
| LIBERO book demos (T2), 50 demos | grasp at the book's edge (~9.8 cm from centre along its z axis), book tilted **~63°** (56–74°) while carried and at release | `data/demospecs/libero_book_under_shelf.json` |

**Spend.** Muse total ≈ 53k (smoke) + 284k (exp. 01) ≈ 337k tokens. The dollar price is unknown (to-do item 8).

## 6. Traps learned

- **The session scratch folder gets wiped.** Keep all evidence under `ANTS/data/`.
- **Seeds.** Always use `--init-mode seeded`. The default `saved` mode, and CaP-X, map seeds as `(seed-1) % 50`, so seed 51 equals seed 1.
- **Actions.** ASPIRE drives LIBERO with **absolute joint-position targets**. Never send zero actions (it means "move to joint angle 0").
- **Reasoning tokens.** Muse uses most of its output on reasoning (≈75–80%), so calls cost about 20–25k tokens each. Budget for it.
- **Success reset.** LIBERO resets to stock objects after a success, so stop at the first success (hurobo D-010).
- **GPU contention.** Don't run two sims plus SAM 3 at once; contended EGL gives fake "invalid depth" failures.
- **Tokens and keys.** The old `gh` lacks `auth token`; use `gh api graphql`. Semantic Scholar unauthenticated: use the batch endpoint (`metrics.py` does).

## 7. Next steps (recommended order)

1. **Make experiment 01 meaningful** (cheap, high value):
   - 3–5 more samples per arm (the cache keeps old calls free)
   - the no-demo arm with 4 repairs instead of 2 (it was learning a rim grasp)
   - the demo arm with each of the 4 good clips, to test that the result is not one clip's luck
   - Wilson intervals on the eval success.
   - Est. 0.6–1.0M tokens: check the budget with the user first.
2. **T2 book task, nominal:** feed `libero_book_under_shelf.json` (edge grasp, ~63° tilt) to the generator. Compare demo vs no-demo on `libero_90:89`. This is the task where ASPIRE says no model found the human strategy.
3. **System 2 v0 (the actual ANTS claim):**
   - perturbation categories with a severity bound in code (`Perturbation.severity`)
   - a feasibility check (oracle or nominal program must pass)
   - a uniform sampler first, then Thompson sampling over categories
   - a rule-based diagnoser reading `rollout.feedback()`, then Muse Spark as the diagnoser
   - a `Constraint` per failure → generator context
   - the **per-case regression gate** (new candidate must pass every case the incumbent passes)
   - acceptance seeds 51–65, held-out seeds 1–50.
4. **T1 real-size scene (optional, after 1 and 3; it is a different test, not a harder one):**
   - Use `aspire_launch.py`'s `scale` option (bowl ×1.227, plate ×1.855) with the five other objects parked, as in hurobo E1.
   - Re-check placement, since the experimental scaling does not check overlap.
   - Then run the demo arm there.
5. **Escalation:** after K stalled cycles on one failure signature, ask for one targeted demo. The 4 hurobo clips and 50 LIBERO demos let us simulate the "answer".
6. **Logging and report:** an evidence export from `data/runs` into a results doc, plus a README results section once there are held-out numbers.

## 8. Optional steps

- CaP-Agent0-lite reference arm (1 sample, ≤2 turns, text feedback, 10 cases); later CaP-X itself for the exact baseline.
- Muse Spark vs Muse Wonder as the generator (cost and success).
- A text visual-difference description of the failure keyframe in the feedback (CaP-X M3), via `muse-spark` with an image or Gemini on the $5 OpenRouter budget.
- SAM 3.1 for demo tracking (Meta API `sam-3.1`), and the to-do "merge ASPIRE with SAM 3.1".
- A checkpoint monitor (C3) and a skill library with versioning and re-verification (`docs/synthesizer/skills.md`), autonomous mode.
- The robosuite nut-assembly task (T3, manufacturing-like, CaP-X oracle program exists) and a LIBERO-10 long-horizon task (T4).
- Re-record or review the 22 flagged hurobo clips; check hurobo's `table_marker_fraction` > 1.

## 9. Open items that need the user (see the to-do page)

Muse price or spend. Review the skills definition. Autonomous-mode budgets. Hackathon rules on reused code. Novelty wording with the teammate. Gemini key (optional). The hurobo clip issues. **Hackathon submission: 2026-11-04.**
