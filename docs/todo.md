# To do (for the user)

Open items that need you: a measurement, a decision, access or a review. The interactive version is the [ANTS To-do](https://claude.ai/artifact/C3NqC3ij7jDMMtEqfzdaFp) artifact (source: `todo.html`). Started 2026-10-31.

| # | Item | Why | Status |
|---|---|---|---|
| 1 | ~~Measure the printed ArUco marker edge length~~ (hurobo E1 setup) | Measured 5.75 cm (user, 2026-10-31). Matches hurobo's `RecordingSpec.marker_length_m` default (0.0575), not the 6.0 cm used in the ANTS smoke runs. The 3.9 cm fit for `test_03` is refuted as a marker-size effect; its cause is still open | done |
| 2 | **Merge ASPIRE with SAM 3.1** | ASPIRE's SAM provider loads only SAM 3 (`sam3.pt`). Using 3.1 inside the harness needs a provider patch, and loading the 3.1 checkpoint into the image model is unverified ([aspire-assessment.md](synthesizer/aspire-assessment.md) §5) | open |
| 3 | **Review the skills definition** | Proposal in [synthesizer/skills.md](synthesizer/skills.md): what a skill is, its six parts, store operations, autonomous mode | open |
| 4 | **Set effort levels and budgets for autonomous mode** | Needed before any test-time CaP-Agent0-style search (skills.md §3) | open |
| 5 | **Confirm the hackathon rules allow reusing ASPIRE and hurobo code** | The official rules mention pre-existing work | open |
| 6 | **Agree the narrowed novelty claim with your teammate** (paper) | README and concept.md now claim the loop, not demo-to-program (RAPID) | open |
| 7 | Decide on Gemini Robotics-ER 2 (needs a Google key) | Keyframe and progress signal; not needed for the MVP | open |
| 8 | **Tell me Muse's price per token** (Meta API dashboard), or the current spend | Needed to enforce the $15 cap; the first smoke test used ~53k tokens ([smoke-2026-10-31.md](synthesizer/smoke-2026-10-31.md)) | open |
| 9 | Check `table_marker_fraction` > 1 in hurobo's extraction summary | Reads 1.07–1.08 on every E1 clip; possibly a counting bug | open |
| 10 | Re-record or review the 22 flagged E1 clips | Only 4/26 pass extraction at 6.0 cm (5 "no grasp detected", several position flags) | open |
| 11 | **Decide whether ANTS accepts in-cell teleop / VR / kinesthetic demos**, not only human video | Machenta teaches in the cell; our plan is human video plus a simulated teleop demo ([instant-learning.md](dev/instant-learning.md) §3) | open |
| 12 | Check the SynthICL repo (licence, weights) and read the Instant-Fold paper | Likeliest public basis of Machenta's model; repo not opened yet | open |
| 13 | **Licence: Instant Policy is PolyForm Noncommercial** and the full paper has a commercial layer | Offline baseline only; see [instant-learning.md](dev/instant-learning.md) §5 X3 | open |
| 14 | Re-check the paper's Machenta comparison (§II) against the 27 Oct 2026 blog | New facts: VDA, four teaching modes, six robots, $40M seed | open |
| 15 | Read the USV blog and Business Insider article that TNW quotes | "11 employees", "no near-term plans to sell", "30 minutes of extra data" are second-hand | open |
| 16 | **Include the hurobo modules inside ANTS** | Today hurobo is called as a separate read-only tool; decide which modules move into `src/ants` (Wilson stats, transforms, DemoExtractor/markers/camera, LayoutSampler; skip training and splat). See [dev/reuse-from-hurobo.md](dev/reuse-from-hurobo.md) | open |
| 17 | **Hackathon memory content**: seed corrections from a T0 run and retrieve them on a second seed set, or mark the memory ablation "future" | Paper C11; see [memory-and-cache.md](synthesizer/memory-and-cache.md) §8 | open |
| 18 | **May `types.py` take `Correction`, `Evidence`, `GateVerdict`** and extra fields | Shared contract; needs the System 2 owner; diff in the audit report §3.3 | open |
| 19 | **Check the Muse dashboard**: ledger shows 2.75M paid tokens (about $37 at $13.5/M) against a $15 cap | Decides how many runs the memory ablation can afford; with item 8 | open |
| 20 | Allow about 10 rollouts as a determinism canary before the gate relies on a rollout cache | 63 of 65 repeats identical, same machine only | open |
| 21 | Where memory lives: `data/` plus a small committed `memory/corrections.jsonl` for the demo? | `data/` is git-ignored | open |
| 22 | Rule text: deterministic `RULES` templates or Muse Spark? Credit assignment default OK? | Changes dedup, cost and the cache key | open |
| 23 | Read Teach and Grow, RPG, RoboSkill, RACaP, SEAR and GRASP before the pitch and restate the delta | A 2026 cluster makes the weights-free, few-demonstration skill claim too; [memory-radar-shortlist.md](synthesizer/research/memory-radar-shortlist.md) | open |
| 24 | Fix the radar: 4 wrong or changed arXiv ids; add 53 queued works | LeRobot id is SmolVLA's; N2M2 id is unrelated; nothing was changed | open |
| 25 | **Try Muse Image goal-scene generation** as an extra VLM input (initial prompt and repair) | `synthesizer/image_gen.py` and `image_message` are built and unit-tested offline; the live API call is untested (key, $0.01/image, cap 15 per run). Needs a CLI flag, one live call, and a with/without ablation | open |

<!-- runbook:start -->

## Run book (generated, redundant on purpose)

If a session limit hits, copy a command from here and keep going. Full flag tables: [runbook/commands-full.md](runbook/commands-full.md). UI: [ANTS Run Book](https://claude.ai/artifact/AimCCqfBF2ooHEqZwiFVMS) or `docs/runbook.html`. Agent access notes: [runbook/agent-access.md](runbook/agent-access.md). Catalog updated 2026-11-01.

**Setup and health checks** (reference)

```bash
uv sync
```

```bash
uv run ruff check . && uv run pytest
```

```bash
cd ASPIRE && CUDA_VISIBLE_DEVICES=0 TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 scripts/supervise_services.sh \
    --profile a5500 \
    --providers sam3,pyroki
```

**Make a DemoSpec from a demonstration** (reference)

```bash
cd hurobo && .venv/bin/python scripts/02_extract_demos.py data/raw/e1/clips/*.mp4 \
    --setup data/raw/setup_01/measurements.yaml \
    --intrinsics data/camera_intrinsics_s10e.npz \
    --cuts data/raw/e1/cuts.json \
    --marker-size-m 0.0575 \
    --out ../data/hurobo_e1/demos_marker_0.0575
```

```bash
hurobo/.venv/bin/python -I tools/hurobo_demospec.py data/hurobo_e1/demos_marker_0.06/20261016_233832.npz \
    --setup hurobo/data/raw/setup_01/measurements.yaml \
    --out data/demospecs/hurobo_233832.json
```

**Exp 01: does one demo help? (bowl on plate)** (done)

```bash
uv run python -m ants.orchestrator.demo_vs_nodemo \
    --aspire ASPIRE \
    --demospec data/demospecs/hurobo_233832.json \
    --out data/runs/demo_vs_nodemo_01 \
    --temperatures 0.2,0.7 \
    --repairs 2 \
    --scenes stock
```

```bash
uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ASPIRE --demospec data/demospecs/hurobo_233832.json --out data/runs/exp01b \
    --token-budget 600000
```

**Exp 02: debug in the scaled scene** (done)

```bash
uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ASPIRE --demospec data/demospecs/hurobo_233832.json --out data/runs/exp02_scaled --debug-scene scaled --scenes stock,scaled \
    --temperatures 0.2,0.7,0.5 \
    --token-budget 600000
```

```bash
uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ASPIRE --demospec data/demospecs/hurobo_233832.json --out data/runs/exp02_scaled --debug-scene scaled --scenes stock,scaled \
    --temperatures 0.2,0.7,0.5 \
    --token-budget 320000
```

**Exp 03: explain-then-repair, one run per clip** (done (no write-up))

```bash
uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ASPIRE --arms demo --temperatures 0.2 --explain --debug-scene scaled --scenes stock,scaled --eval-seeds "" \
    --demospec data/demospecs/hurobo_233859.json \
    --out data/runs/exp03_explain/clip_233859 \
    --token-budget 250000
```

```bash
uv run python -m ants.evalkit.report data/runs/exp04_scene \
    --open
```

**Exp 04: which scene description helps?** (done (see experiment-04-scene-context.md))

```bash
uv run python -m ants.orchestrator.scene_context_exp --aspire ASPIRE --prep \
    --out data/runs/exp04_scene
```

```bash
uv run python -m ants.orchestrator.scene_context_exp --aspire ASPIRE --dry-run \
    --out data/runs/exp04_scene
```

**Perturbation preview (System 2 hook)** (done)

```bash
cd ASPIRE && LIBERO_CONFIG_PATH=$PWD/.libero TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 MUJOCO_GL=egl PYOPENGL_PLATFORM=egl EGL_PLATFORM=device CUDA_VISIBLE_DEVICES=0 .venv-libero/bin/python ../tools/aspire_launch.py ../data/runs/perturb_preview/friction04.json -- run \
    --benchmark libero-pro \
    --suite libero_goal_swap \
    --task-id 8 \
    --seed 51 \
    --init-mode seeded \
    --program PATH/program.py \
    --output-root ../data/runs/perturb_preview/out \
    --max-steps 2000 \
    --camera-width 800 \
    --camera-height 512
```

```bash
cd ASPIRE && LIBERO_CONFIG_PATH=$PWD/.libero TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 MUJOCO_GL=egl PYOPENGL_PLATFORM=egl EGL_PLATFORM=device CUDA_VISIBLE_DEVICES=0 .venv-libero/bin/python ../tools/aspire_launch.py ../data/scaled_test/scale.json -- run \
    --suite libero_goal_swap \
    --task-id 8 \
    --seed 51 \
    --init-mode seeded \
    --program PATH/program.py \
    --output-root ../data/scaled_test/out
```

**System 2 v0: harden with the never-regress gate** (built, no live run)

```bash
uv run python tools/system2_mock.py data/runs/system2_mock_synthetic
```

```bash
uv run python -m ants.evalkit.report data/runs --open
```

**dev/curobo: why does the planner go through the rack?** (done (dev notes))

```bash
cd ASPIRE && ANTS_CARVE_MARGIN_M=0.0 ANTS_ATTACH_FILE=$PWD/../data/runs/curobo/attach.json .venv-curobo/bin/python ../dev/curobo/service_dev.py \
    --port 8118
```

```bash
cd ASPIRE && ANTS_CONTACT_LOG=../data/evidence/out.jsonl LIBERO_CONFIG_PATH=$PWD/.libero TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 MUJOCO_GL=egl PYOPENGL_PLATFORM=egl EGL_PLATFORM=device CUDA_VISIBLE_DEVICES=0 .venv-libero/bin/python ../dev/curobo/contact_launch.py scene.json -- run --benchmark libero-pro --suite libero_goal_swap --task-id 8 --seed 51 --init-mode seeded --program ../dev/curobo/programs/exp3_a2_orbit.py
```

**Research radar maintenance** (tooling)

```bash
uv run python .claude/skills/robot-research-radar/scripts/radar.py build \
    --in scratch/orgs.json scratch/works.json \
    --out scratch/radar_docs.json
```

```bash
uv run python .claude/skills/robot-research-radar/scripts/radar.py pending \
    --dump scratch/pending.json
```

**Agent skills (slash commands)** (reference)

```bash
/idea-judge  # then your raw idea text
```

```bash
/storyline-judge  # then the storyline text or a storyline_id
```

**Exp 05: perceived scene vs oracle** (done (see experiment-05-perceived-scene.md))

```bash
uv run python -m ants.orchestrator.perceived_scene --probe \
    --out data/runs/exp05_perceived_scene \
    --aspire ASPIRE
```

```bash
uv run python -m ants.orchestrator.perceived_scene --analyse \
    --out data/runs/exp05_perceived_scene
```

**Exp 06 to 08: cuRobo on perception, scene understanding off, perceived, privileged** (done (see experiment-06-08-curobo.md))

```bash
uv run python -m ants.orchestrator.exp_curobo \
    --exp exp06,exp08,exp07 \
    --token-budget 250000
```

```bash
uv run python -m ants.evalkit.report data/runs/exp04_scene \
    --open
```

**Exp 09 to 11: exp06 to 08 again, with the held bowl attached to the hand** (code ready, not run)

```bash
cd ASPIRE && ANTS_CARVE_MARGIN_M=0.0 ANTS_ATTACH_FILE=$PWD/../data/runs/curobo/attach.json .venv-curobo/bin/python ../dev/curobo/service_dev.py \
    --port 8118
```

```bash
uv run python -m ants.orchestrator.exp_curobo \
    --exp exp06,exp08,exp07 \
    --token-budget 250000
```

**Scene reconstruction probe: cuRobo Mapper TSDF/ESDF on the LIBERO scene** (probe working, logged once)

```bash
LIBERO_CONFIG_PATH=$PWD/.libero TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 MUJOCO_GL=egl PYOPENGL_PLATFORM=egl EGL_PLATFORM=device CUDA_VISIBLE_DEVICES=0 .venv-libero/bin/python ../tools/mapper_probe/scan_orbit.py
```

```bash
LIBERO_CONFIG_PATH=$PWD/.libero TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 MUJOCO_GL=egl PYOPENGL_PLATFORM=egl EGL_PLATFORM=device CUDA_VISIBLE_DEVICES=0 .venv-libero/bin/python ../tools/mapper_probe/scan_arm.py
```

**Exp 12: demo vs no demo on cuRobo (simulator robot mask, attached bowl)** (final (submission experiment, tag submission-experiment))

```bash
uv run python -m ants.orchestrator.demo_vs_nodemo \
    --aspire ASPIRE \
    --out data/runs/demo_e3_s4_sim \
    --demospec data/demospecs/hurobo_233859.json \
    --arms demo \
    --temperatures 0.2,0.7 \
    --explain \
    --repairs 4 \
    --planner curobo-sim \
    --attach-known \
    --save-clouds \
    --debug-scene scaled \
    --scenes scaled \
    --eval-seeds 1,2,3,4,5 \
    --token-budget 300000 \
    --evidence e3 \
    --contacts \
    --scene-text-file data/scene_text/S4_L1.txt
```

```bash
uv run python -m ants.orchestrator.demo_vs_nodemo \
    --aspire ASPIRE \
    --out data/runs/nodemo_task_only_sim \
    --demospec data/demospecs/hurobo_233859.json \
    --arms nodemo \
    --temperatures 0.2,0.7 \
    --explain \
    --repairs 4 \
    --planner curobo-sim \
    --attach-known \
    --save-clouds \
    --debug-scene scaled \
    --scenes scaled \
    --eval-seeds 1,2,3,4,5 \
    --token-budget 300000
```

<!-- runbook:end -->
| 25 | Choose the memory bundle (Minimal / Standard / Full) and the store location (`evalkit/` or a new `ants/memory/`) | [memory-integration-plan.md](synthesizer/memory-integration-plan.md) §2.5 and §8 | open |
| 26 | Approve the E0 determinism canary (about 10 rollouts) and a token budget for E6 (about 0.7M tokens) | Confirm the Muse price first (item 19) | open |
