# ANTS run book: every command and every flag

Generated from `docs/runbook/commands.json` on 2026-11-01 by `uv run python -m ants.evalkit.runbook build`. Do not edit by hand; edit the JSON.

Run from the ANTS repo root unless the command starts with `cd`. Services must be up (`setup` section) before any simulation. Commands marked **paid** spend Muse tokens: check `--token-budget` first. GitHub and VS Code show a copy button on every code block.

Interactive version: `docs/runbook.html`. Essential commands only: [experiment-commands.md](../synthesizer/experiment-commands.md).

## Setup and health checks

*reference.* Is the environment ready to run anything?

- Docs: `docs/synthesizer/smoke-2026-10-31.md`
- Inputs: uv; ASPIRE with venvs; GPU; META_API_KEY in .env
- Outputs: services up on 8114/8116 (+8118); tests green
- Result so far: ASPIRE example passes in 36 s on the RTX A5500 laptop (smoke §1).

### `setup.sync`: Install / sync the ANTS env

Installs exactly what uv.lock says. Run after every git pull.

```bash
uv sync
```

Frozen (CI-style, forbids lockfile changes):

```bash
uv sync --frozen
```

### `setup.check`: Lint and tests

Run before every commit. Report the real result.

```bash
uv run ruff check . && uv run pytest
```

Format:

```bash
uv run ruff format .
```

One test file:

```bash
uv run pytest tests/orchestrator/test_system2.py -q
```

### `services.start`: Start SAM 3 + PyRoki (+ cuRobo) services

Every experiment needs these up (about 4.5 GB GPU with SAM 3 + PyRoki). Keep it running in its own terminal. Do not run two simulators plus SAM 3 at once: contended EGL gives fake 'invalid depth' failures.

```bash
cd ASPIRE && CUDA_VISIBLE_DEVICES=0 TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 scripts/supervise_services.sh \
    --profile a5500 \
    --providers sam3,pyroki
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--profile` | `a5500` | yes | Hardware profile (default rtx5090; this laptop uses the local a5500). |
| `--providers` | `sam3,pyroki` | yes | Which services to start. Add curobo for dev/curobo and cuRobo-planned programs (first plan takes about 50 s). Choices: sam3,pyroki, sam3,pyroki,curobo, sam3, curobo. |
| `--log-dir` | `PATH` | no | Service log directory. |
| `--ready-timeout` | `300` | no | Max seconds to wait for readiness. |

Background, logging to ANTS/data/services.log:

```bash
cd ASPIRE && CUDA_VISIBLE_DEVICES=0 TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 nohup scripts/supervise_services.sh --profile a5500 --providers sam3,pyroki > ../data/services.log 2>&1 &
```

### `services.doctor`: ASPIRE doctor (install check)

Verifies the LIBERO/robosuite install and (optionally) the services. Writes environment.json in ASPIRE.

```bash
cd ASPIRE && .venv-libero/bin/python -m cap_harness.cli doctor \
    --providers sam3,pyroki \
    --unit
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--providers` | `sam3,pyroki` | yes | Providers to check. |
| `--unit` |  | yes | Unit mode: services reported unreachable are allowed (use without it when services are up). |
| `--check-curobo` |  | no | Also check cuRobo. |
| `--skip-services` |  | no | Do not probe services. |
| `--quiet` |  | no | Less output. |

### `services.stop-check`: Check what is on the GPU / ports

Quick check before starting a run, so two runs do not fight for the GPU.

```bash
nvidia-smi --query-gpu=memory.used,memory.total --format=csv && (ss -ltnp 2>/dev/null | grep -E ':(8114|8116|8118)' || echo 'no ASPIRE services listening')
```

## Make a DemoSpec from a demonstration

*reference.* Turn a human demo into the object-relative summary the generator reads.

- Docs: `docs/synthesizer/experiment-01-demo-vs-nodemo.md` · run dir: `data/demospecs/`
- Inputs: hurobo clips + setup yaml, or LIBERO demo hdf5
- Outputs: data/demospecs/*.json
- Result so far: 4 of 26 hurobo clips usable at 6.0 cm marker (smoke §3); the measured marker is 5.75 cm, so re-extract with --marker-size-m 0.0575.

### `demo.hurobo-extract`: hurobo: extract demos from clips

hurobo is read-only for ANTS: outputs go to ANTS/data/. The exact invocation of the first extraction is reconstructed from smoke-2026-10-31.md §3; check hurobo's own README if a path differs.

```bash
cd hurobo && .venv/bin/python scripts/02_extract_demos.py data/raw/e1/clips/*.mp4 \
    --setup data/raw/setup_01/measurements.yaml \
    --intrinsics data/camera_intrinsics_s10e.npz \
    --cuts data/raw/e1/cuts.json \
    --marker-size-m 0.0575 \
    --out ../data/hurobo_e1/demos_marker_0.0575
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--setup` | `data/raw/setup_01/measurements.yaml` | yes | Board mode: table frame from the ChArUco board described here. |
| `--intrinsics` | `data/camera_intrinsics_s10e.npz` | yes | Camera intrinsics. |
| `--cuts` | `data/raw/e1/cuts.json` | yes | Skip rejected clips; extract inside each cut. |
| `--marker-size-m` | `0.0575` | yes | Measured printed marker edge. 5.75 cm is the measured value; smoke runs used 6.0 (4/26 usable) and 3.9 (0/26). Choices: 0.0575, 0.06, 0.039. |
| `--out` | `../data/hurobo_e1/demos_marker_0.0575` | yes | Output folder (never write into hurobo). |
| `--pad-offset-m` | `0.115` | no | Board mode: bowl centre offset along the pad marker x axis. |
| `--close-threshold-m` | `0.03` | no | Gripper closed below this aperture. |
| `--open-threshold-m` | `0.05` | no | Gripper open above this aperture. |

### `demo.hurobo`: hurobo demo (.npz) to DemoSpec JSON

Uses hurobo's Python (numpy); ANTS does not depend on numpy. Distances are given in metres and as fractions of object radius.

```bash
hurobo/.venv/bin/python -I tools/hurobo_demospec.py data/hurobo_e1/demos_marker_0.06/20261016_233832.npz \
    --setup hurobo/data/raw/setup_01/measurements.yaml \
    --out data/demospecs/hurobo_233832.json
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--setup` | `hurobo/data/raw/setup_01/measurements.yaml` | yes | measurements.yaml of the recording setup. |
| `--out` | `data/demospecs/hurobo_233832.json` | yes | DemoSpec JSON to write; also prints the summary block the prompt uses. |

Clip 233859:

```bash
hurobo/.venv/bin/python -I tools/hurobo_demospec.py data/hurobo_e1/demos_marker_0.06/20261016_233859.npz --setup hurobo/data/raw/setup_01/measurements.yaml --out data/demospecs/hurobo_233859.json
```

Clip 234314:

```bash
hurobo/.venv/bin/python -I tools/hurobo_demospec.py data/hurobo_e1/demos_marker_0.06/20261016_234314.npz --setup hurobo/data/raw/setup_01/measurements.yaml --out data/demospecs/hurobo_234314.json
```

Clip 234603:

```bash
hurobo/.venv/bin/python -I tools/hurobo_demospec.py data/hurobo_e1/demos_marker_0.06/20261016_234603.npz --setup hurobo/data/raw/setup_01/measurements.yaml --out data/demospecs/hurobo_234603.json
```

### `demo.libero`: LIBERO human demos to DemoSpec JSON

Replays stored simulator states (no rendering, no policy). Result: grasp at the book's edge, book tilted about 63 degrees.

```bash
cd ASPIRE && LIBERO_CONFIG_PATH=$PWD/.libero TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 MUJOCO_GL=egl PYOPENGL_PLATFORM=egl EGL_PLATFORM=device CUDA_VISIBLE_DEVICES=0 .venv-libero/bin/python ../tools/libero_demospec.py ../data/libero_demos/book_under_shelf_demo.hdf5 \
    --object yellow_book_1 \
    --target wooden_two_layer_shelf_1 \
    --max-demos 50 \
    --out ../data/demospecs/libero_book_under_shelf.json
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--object` | `yellow_book_1` | yes | Manipulated object body name. |
| `--target` | `wooden_two_layer_shelf_1` | yes | Target fixture body name. |
| `--max-demos` | `50` | yes | How many demos to replay (median and 10-90th percentile over them). |
| `--out` | `../data/demospecs/libero_book_under_shelf.json` | yes | DemoSpec JSON to write. |

## Exp 01: does one demo help? (bowl on plate)

*done.* Arms differ only in the demo section. Does the demo arm write a working program?

- Docs: `docs/synthesizer/experiment-01-demo-vs-nodemo.md` · run dir: `data/runs/demo_vs_nodemo_01`
- Inputs: data/demospecs/hurobo_233832.json; services up; Muse tokens
- Outputs: data/runs/demo_vs_nodemo_01/ (programs, diffs, feedback, record.json, summary.md); report.html
- Cost: 284,304 tokens in the original run (cap 600k)
- Result so far: demo 1/2 samples solved (5/5 eval); no demo 0/2 (0/10). n=2: a hint, not a result.

### `exp01.run`: Exp 01: demo vs no demo (as originally run) (paid)

The core System 1 loop: write a program, run it on the debug seed, repair from text feedback up to N times, then evaluate the final program unchanged on the acceptance seeds. Needs services up and META_API_KEY. SPENDS MUSE TOKENS: set --token-budget and ask before big runs.

```bash
uv run python -m ants.orchestrator.demo_vs_nodemo \
    --aspire ASPIRE \
    --demospec data/demospecs/hurobo_233832.json \
    --out data/runs/demo_vs_nodemo_01 \
    --temperatures 0.2,0.7 \
    --repairs 2 \
    --scenes stock
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--aspire` | `ASPIRE` | yes | ASPIRE checkout. |
| `--demospec` | `data/demospecs/hurobo_233832.json` | yes | Which hurobo clip's DemoSpec the demo arm sees. Choices: data/demospecs/hurobo_233832.json, data/demospecs/hurobo_233859.json, data/demospecs/hurobo_234314.json, data/demospecs/hurobo_234603.json. |
| `--out` | `data/runs/demo_vs_nodemo_01` | yes | Run directory. Re-running with the same --out keeps finished samples and redoes only the stopped one. |
| `--arms` | `nodemo,demo` | no | Arms to run. They differ only in the demo section of the prompt. Choices: nodemo,demo, demo, nodemo. |
| `--temperatures` | `0.2,0.7` | yes | One sample per temperature. Default 0.2,0.7,0.5,1.0; exp01 used 0.2,0.7. |
| `--repairs` | `2` | yes | Max repairs from text feedback. Default 4; exp01 used 2. |
| `--scenes` | `stock` | yes | Scenes each final program is evaluated in. Default stock,scaled. Choices: stock, stock,scaled, scaled. |
| `--debug-scene` | `stock` | no | Scene where programs are debugged and repaired (must be one of --scenes). Choices: stock, scaled. |
| `--eval-seeds` | `51,52,53,54,55` | no | Acceptance seeds for the final evaluation. Empty string skips evaluation. Never use held-out seeds here. |
| `--debug-seed` | `51` | no | Seed where programs are debugged. |
| `--explain` |  | no | Repair replies start with a WHY: rationale (the API returns no reasoning text). |
| `--model` | `muse-wonder-1.0` | no | Generator model on the Meta API. Choices: muse-wonder-1.0, muse-spark-1.3, muse-spark-1.2, muse-spark-1.1. |
| `--token-budget` | `600000` | no | HARD cap on NEW (uncached) tokens in this run. About $8 at $13.5 per M tokens. Cached calls are free. |
| `--usd-per-mtok` | `13.5` | no | Only for the cost estimate. |
| `--suite` | `libero_goal_swap` | no | LIBERO suite. |
| `--task-id` | `8` | no | Task id in the suite (8 = put the bowl on the plate). |
| `--task` | `put the bowl on the plate` | no | Task text given to the model. |
| `--scale-json` | `{"akita_black_bowl_1_main": 1.227, "plate_1_main": 1.855}` | no | Body name to scale factor for the scaled scene. |
| `--eval-only` |  | no | No generation: re-score the final programs of an existing --out in --scenes. |

Exact exp01 (n=2 per arm):

```bash
uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ASPIRE --demospec data/demospecs/hurobo_233832.json --out data/runs/demo_vs_nodemo_01 --temperatures 0.2,0.7 --repairs 2 --scenes stock
```

Cheap smoke: one sample, one repair, one eval seed:

```bash
uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ASPIRE --demospec data/demospecs/hurobo_233832.json --out data/runs/smoke --arms demo --temperatures 0.2 --repairs 1 --eval-seeds 51 --scenes stock --token-budget 80000
```

Next step from HANDOFF: more samples, 4 repairs, both scenes:

```bash
uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ASPIRE --demospec data/demospecs/hurobo_233832.json --out data/runs/exp01c --temperatures 0.2,0.7,0.5,1.0 --repairs 4 --scenes stock,scaled --token-budget 600000
```

### `exp01b.run`: Exp 01b: defaults (4 temperatures, 4 repairs, stock + scaled) (paid)

What exp01b ran: all defaults of the runner. Evaluated in both scenes; debug scene stock.

```bash
uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ASPIRE --demospec data/demospecs/hurobo_233832.json --out data/runs/exp01b \
    --token-budget 600000
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--token-budget` | `600000` | yes | Hard cap on new tokens. |
| `--temperatures` | `0.2,0.7,0.5,1.0` | no | One sample per temperature. |

### `exp01b.rescore`: Re-score finished programs (no model calls)

Used after the on-top tolerance rule for scaled scenes changed (3 cm x the target's scale factor). Costs no tokens; needs services and the simulator.

```bash
uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ASPIRE --demospec data/demospecs/hurobo_233832.json --eval-only \
    --out data/runs/exp01b \
    --scenes stock,scaled
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--out` | `data/runs/exp01b` | yes | Existing run to re-score. |
| `--scenes` | `stock,scaled` | yes | Scenes to score in. |
| `--eval-seeds` | `51,52,53,54,55` | no | Acceptance seeds. |

### `report.run`: View a run (HTML trace UI)

Writes one self-contained report.html in the run dir: success rates with intervals, seed-by-sample heatmap, rollout explorer with video, compare, policies, System 2 and Scene tabs. Keep report.html in the folder (videos are linked by relative path). Works on any run dir and on data/runs itself.

```bash
uv run python -m ants.evalkit.report data/runs/exp04_scene \
    --open
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--open` |  | yes | Open report.html in the browser. |
| `--serve` |  | no | Serve the run directory over http so videos play (127.0.0.1). |
| `--port` | `8765` | no | Port for --serve. |

All runs, pick in the UI:

```bash
uv run python -m ants.evalkit.report data/runs --open
```

Exp 02 over http:

```bash
uv run python -m ants.evalkit.report data/runs/exp02_scaled --serve --open
```

### `perturb.run`: Run a program under a perturbation

The launcher applies the perturbation after every reset and on every step, then hands over to ASPIRE's normal CLI. Everything after `--` goes to `cap-harness run`. The program cannot see the perturbation. Edit the first argument to pick a spec.

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

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--benchmark` | `libero-pro` | yes | cap-harness benchmark. |
| `--suite` | `libero_goal_swap` | yes | LIBERO suite. |
| `--task-id` | `8` | yes | 8 = put the bowl on the plate. |
| `--seed` | `51` | yes | Acceptance seeds 51-65, held-out 1-50. |
| `--init-mode` | `seeded` | yes | ALWAYS seeded: 'saved' maps seed to (seed-1) % 50, so seed 51 equals seed 1. Choices: seeded, saved. |
| `--program` | `PATH/program.py` | yes | The program under test, e.g. a program_attemptK.py from a run dir. |
| `--output-root` | `../data/runs/perturb_preview/out` | yes | Where the run dir goes. |
| `--max-steps` | `2000` | yes | Episode length in control ticks. |
| `--camera-width` | `800` | yes | Camera width. |
| `--camera-height` | `512` | yes | Camera height. |
| `--no-videos` |  | no | Skip mp4 capture (faster). |
| `--flat-run-dir` |  | no | Write <output-root>/<seed>/<run-id> instead of nesting. |

Friction x0.4 on the bowl (spec):

```bash
{"physics": {"friction_scale": 0.4, "bodies": ["bowl"]}}
```

Bowl shifted +4 cm x, -3 cm y (spec):

```bash
{"pose": {"offsets_m": {"akita_black_bowl_1_joint0": [0.04, -0.03]}}}
```

Actuation noise + 2-step latency (spec):

```bash
{"actuation": {"noise_std": 0.01, "latency_steps": 2, "seed": 0}}
```

Camera + lighting (spec):

```bash
{"camera": {"name": "agentview", "pos_offset_m": [0.0, 0.02, 0.0], "fovy_delta_deg": 2.0}, "lighting": {"diffuse_scale": 0.6}}
```

## Exp 02: debug in the scaled scene

*done.* Same arms, but programs are debugged and repaired in the real-size scene (bowl x1.227, plate x1.855).

- Docs: `docs/synthesizer/experiment-02-scaled-scene.md` · run dir: `data/runs/exp02_scaled`
- Inputs: data/demospecs/hurobo_233832.json
- Outputs: data/runs/exp02_scaled/
- Cost: 866,299 tokens (about $11.7), first pass 600k then resumed with 320k
- Result so far: Each arm solved the debug seed in 1 of 3 samples. exp01's demo benefit was not reproduced.

### `exp02.run`: Exp 02: debug in the scaled scene (paid)

Same task and prompts as exp01, but programs are debugged and repaired in the real-size scene.

```bash
uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ASPIRE --demospec data/demospecs/hurobo_233832.json --out data/runs/exp02_scaled --debug-scene scaled --scenes stock,scaled \
    --temperatures 0.2,0.7,0.5 \
    --token-budget 600000
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--temperatures` | `0.2,0.7,0.5` | yes | Exp 02 used three temperatures. |
| `--token-budget` | `600000` | yes | First pass was 600k and hit the cap. |
| `--repairs` | `4` | no | Default 4. |

### `exp02.resume`: Resume a budget-stopped run (paid)

Re-running with the same --out keeps finished samples and redoes the stopped one. This is how a session limit or a budget stop is survived.

```bash
uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ASPIRE --demospec data/demospecs/hurobo_233832.json --out data/runs/exp02_scaled --debug-scene scaled --scenes stock,scaled \
    --temperatures 0.2,0.7,0.5 \
    --token-budget 320000
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--temperatures` | `0.2,0.7,0.5` | yes | Keep identical to the first pass. |
| `--token-budget` | `320000` | yes | A NEW budget for the resumed pass (the ledger total is not counted). |

### `exp01b.rescore`: Re-score finished programs (no model calls)

Used after the on-top tolerance rule for scaled scenes changed (3 cm x the target's scale factor). Costs no tokens; needs services and the simulator.

```bash
uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ASPIRE --demospec data/demospecs/hurobo_233832.json --eval-only \
    --out data/runs/exp01b \
    --scenes stock,scaled
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--out` | `data/runs/exp01b` | yes | Existing run to re-score. |
| `--scenes` | `stock,scaled` | yes | Scenes to score in. |
| `--eval-seeds` | `51,52,53,54,55` | no | Acceptance seeds. |

### `report.run`: View a run (HTML trace UI)

Writes one self-contained report.html in the run dir: success rates with intervals, seed-by-sample heatmap, rollout explorer with video, compare, policies, System 2 and Scene tabs. Keep report.html in the folder (videos are linked by relative path). Works on any run dir and on data/runs itself.

```bash
uv run python -m ants.evalkit.report data/runs/exp04_scene \
    --open
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--open` |  | yes | Open report.html in the browser. |
| `--serve` |  | no | Serve the run directory over http so videos play (127.0.0.1). |
| `--port` | `8765` | no | Port for --serve. |

All runs, pick in the UI:

```bash
uv run python -m ants.evalkit.report data/runs --open
```

Exp 02 over http:

```bash
uv run python -m ants.evalkit.report data/runs/exp02_scaled --serve --open
```

## Exp 03: explain-then-repair, one run per clip

*done (no write-up).* With a WHY: rationale in each repair, how do the 3 good hurobo clips fare? Clip 233859 attempt 2 stalls on the wine rack and motivates exp04 and dev/curobo.

- Docs: `docs/synthesizer/proposal-collision-context.md` · run dir: `data/runs/exp03_explain/clip_<id>`
- Inputs: data/demospecs/hurobo_233832|233859|234314.json
- Outputs: data/runs/exp03_explain/clip_*/
- Result so far: Config only (see run dirs and data/exp03.log); no results doc yet. Reconstructed command, taken from config.json.

### `exp03.run`: Exp 03: explain-then-repair for one clip (paid)

Reconstructed from the run's config.json (arms demo, temperature 0.2, --explain, debug scene scaled, no evaluation seeds). Clip 233859 attempt 2 is the case that stalls on the wine rack.

```bash
uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ASPIRE --arms demo --temperatures 0.2 --explain --debug-scene scaled --scenes stock,scaled --eval-seeds "" \
    --demospec data/demospecs/hurobo_233859.json \
    --out data/runs/exp03_explain/clip_233859 \
    --token-budget 250000
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--demospec` | `data/demospecs/hurobo_233859.json` | yes | Clip to use. Exp 03 ran 233832, 233859 and 234314. Choices: data/demospecs/hurobo_233832.json, data/demospecs/hurobo_233859.json, data/demospecs/hurobo_234314.json. |
| `--out` | `data/runs/exp03_explain/clip_233859` | yes | One run dir per clip. |
| `--token-budget` | `250000` | yes | Per-clip cap used in exp03. |
| `--repairs` | `4` | no | Default 4. |

All three clips:

```bash
for c in 233832 233859 234314; do uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ASPIRE --demospec data/demospecs/hurobo_$c.json --out data/runs/exp03_explain/clip_$c --arms demo --temperatures 0.2 --explain --debug-scene scaled --scenes stock,scaled --eval-seeds "" --token-budget 250000; done
```

### `report.run`: View a run (HTML trace UI)

Writes one self-contained report.html in the run dir: success rates with intervals, seed-by-sample heatmap, rollout explorer with video, compare, policies, System 2 and Scene tabs. Keep report.html in the folder (videos are linked by relative path). Works on any run dir and on data/runs itself.

```bash
uv run python -m ants.evalkit.report data/runs/exp04_scene \
    --open
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--open` |  | yes | Open report.html in the browser. |
| `--serve` |  | no | Serve the run directory over http so videos play (127.0.0.1). |
| `--port` | `8765` | no | Port for --serve. |

All runs, pick in the UI:

```bash
uv run python -m ants.evalkit.report data/runs --open
```

Exp 02 over http:

```bash
uv run python -m ants.evalkit.report data/runs/exp02_scaled --serve --open
```

## Exp 04: which scene description helps?

*done (see experiment-04-scene-context.md).* G: which scene section (S0-S4, SP placebo) in the first prompt helps, in levels L1-L3. E: which contact evidence (E0-E3, EP placebo) helps one repair.

- Docs: `docs/synthesizer/experiment-04-scene-context.md` · run dir: `data/runs/exp04_scene`
- Inputs: data/demospecs/hurobo_233859.json; data/scenes/levels.json; exp03 program_attempt2.py (for E)
- Outputs: data/runs/exp04_scene/{G,E}-<variant>/; contacts.jsonl; overlay.json; scenes/
- Cost: default cap 900,000 new tokens
- Result so far: Results coming (docs/synthesizer/experiment-04-scene-context.md).

### `exp04.prep`: Exp 04 step 1: settle and dump every scene level

Simulation only, no model call. Dumps the settled scene (poses, geoms, exact gaps) of each level, then stops.

```bash
uv run python -m ants.orchestrator.scene_context_exp --aspire ASPIRE --prep \
    --out data/runs/exp04_scene
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--out` | `data/runs/exp04_scene` | yes | Run dir. |
| `--levels-file` | `data/scenes/levels.json` | no | Scene level definitions (L1-L3). |
| `--levels` | `L1,L2,L3` | no | Levels to prepare. |

### `exp04.dry`: Exp 04 step 2: write the prompts only

No model call and no simulation: prints the size of each changing prompt part. Do this to inspect what the model will read before spending tokens.

```bash
uv run python -m ants.orchestrator.scene_context_exp --aspire ASPIRE --dry-run \
    --out data/runs/exp04_scene
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--out` | `data/runs/exp04_scene` | yes | Run dir; prompts go to <out>/prompts/. |
| `--groups` | `G,E` | no | G = first-program variants, E = repair-evidence variants. Choices: G,E, G, E. |
| `--g-variants` | `S0,S1,S2,S3,S4,SP` | no | Scene-description variants (SP is the placebo). |
| `--e-variants` | `E0,E1,E2,E3,EP` | no | Repair-evidence variants (EP is the placebo). |
| `--levels` | `L1,L2,L3` | no | Scene levels. |

### `exp04.run`: Exp 04 step 3: run the scene-context experiment (paid)

One run per cell, so differences can be luck. The scene given to the model is simulator truth (oracle). SPENDS MUSE TOKENS. The original run was done in chunks (see examples) so a limit never loses work.

```bash
uv run python -m ants.orchestrator.scene_context_exp --aspire ASPIRE \
    --out data/runs/exp04_scene \
    --token-budget 900000
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--out` | `data/runs/exp04_scene` | yes | Run dir. Finished cells are kept on re-run (sample-level resume); every call is cached. |
| `--groups` | `G,E` | no | G (first program) and/or E (one repair). Choices: G,E, G, E. |
| `--levels` | `L1,L2,L3` | no | Scene levels for group G. Choices: L1,L2,L3, L1, L2, L3, L1,L2. |
| `--g-variants` | `S0,S1,S2,S3,S4,SP` | no | Scene description in the first prompt: S0 none, S1 positions, S2 +extents, S3 +relations, S4 combined, SP placebo. |
| `--e-variants` | `E0,E1,E2,E3,EP` | no | Repair evidence: E0 none, E1 +contact log, E2 +scene, E3 +stall readings, EP placebo. |
| `--demospec` | `data/demospecs/hurobo_233859.json` | no | Clip used for the demo summary. |
| `--levels-file` | `data/scenes/levels.json` | no | Level definitions. |
| `--temperature` | `0.2` | no | Sampling temperature. |
| `--model` | `muse-wonder-1.0` | no | Generator. Choices: muse-wonder-1.0, muse-spark-1.3. |
| `--token-budget` | `900000` | yes | HARD cap on NEW tokens (about $12 at $13.5/M). |
| `--debug-seed` | `51` | no | Seed for the rollouts. |

First program, level 1 only:

```bash
uv run python -m ants.orchestrator.scene_context_exp --aspire ASPIRE --out data/runs/exp04_scene --groups G --levels L1
```

Repair-evidence group only:

```bash
uv run python -m ants.orchestrator.scene_context_exp --aspire ASPIRE --out data/runs/exp04_scene --groups E
```

Level 2 and 3 first-program variants:

```bash
uv run python -m ants.orchestrator.scene_context_exp --aspire ASPIRE --out data/runs/exp04_scene --groups G --levels L2,L3
```

Cheapest useful cell: placebo vs full scene, level 2:

```bash
uv run python -m ants.orchestrator.scene_context_exp --aspire ASPIRE --out data/runs/exp04_scene --groups G --levels L2 --g-variants S0,S4,SP --token-budget 200000
```

### `report.run`: View a run (HTML trace UI)

Writes one self-contained report.html in the run dir: success rates with intervals, seed-by-sample heatmap, rollout explorer with video, compare, policies, System 2 and Scene tabs. Keep report.html in the folder (videos are linked by relative path). Works on any run dir and on data/runs itself.

```bash
uv run python -m ants.evalkit.report data/runs/exp04_scene \
    --open
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--open` |  | yes | Open report.html in the browser. |
| `--serve` |  | no | Serve the run directory over http so videos play (127.0.0.1). |
| `--port` | `8765` | no | Port for --serve. |

All runs, pick in the UI:

```bash
uv run python -m ants.evalkit.report data/runs --open
```

Exp 02 over http:

```bash
uv run python -m ants.evalkit.report data/runs/exp02_scaled --serve --open
```

## Perturbation preview (System 2 hook)

*done.* Does a working program survive hand-picked perturbations? (friction x0.4, bowl shift, actuation noise + latency)

- Docs: `docs/synthesizer/experiment-01-demo-vs-nodemo.md` · run dir: `data/runs/perturb_preview/`
- Inputs: a program.py; perturbation.json
- Outputs: run dir under --output-root
- Result so far: Winning exp01 program: 3/3 survived.

### `perturb.run`: Run a program under a perturbation

The launcher applies the perturbation after every reset and on every step, then hands over to ASPIRE's normal CLI. Everything after `--` goes to `cap-harness run`. The program cannot see the perturbation. Edit the first argument to pick a spec.

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

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--benchmark` | `libero-pro` | yes | cap-harness benchmark. |
| `--suite` | `libero_goal_swap` | yes | LIBERO suite. |
| `--task-id` | `8` | yes | 8 = put the bowl on the plate. |
| `--seed` | `51` | yes | Acceptance seeds 51-65, held-out 1-50. |
| `--init-mode` | `seeded` | yes | ALWAYS seeded: 'saved' maps seed to (seed-1) % 50, so seed 51 equals seed 1. Choices: seeded, saved. |
| `--program` | `PATH/program.py` | yes | The program under test, e.g. a program_attemptK.py from a run dir. |
| `--output-root` | `../data/runs/perturb_preview/out` | yes | Where the run dir goes. |
| `--max-steps` | `2000` | yes | Episode length in control ticks. |
| `--camera-width` | `800` | yes | Camera width. |
| `--camera-height` | `512` | yes | Camera height. |
| `--no-videos` |  | no | Skip mp4 capture (faster). |
| `--flat-run-dir` |  | no | Write <output-root>/<seed>/<run-id> instead of nesting. |

Friction x0.4 on the bowl (spec):

```bash
{"physics": {"friction_scale": 0.4, "bodies": ["bowl"]}}
```

Bowl shifted +4 cm x, -3 cm y (spec):

```bash
{"pose": {"offsets_m": {"akita_black_bowl_1_joint0": [0.04, -0.03]}}}
```

Actuation noise + 2-step latency (spec):

```bash
{"actuation": {"noise_std": 0.01, "latency_steps": 2, "seed": 0}}
```

Camera + lighting (spec):

```bash
{"camera": {"name": "agentview", "pos_offset_m": [0.0, 0.02, 0.0], "fovy_delta_deg": 2.0}, "lighting": {"diffuse_scale": 0.6}}
```

### `perturb.scale`: Real-size scene (bowl x1.227, plate x1.855)

scale.json = {"scale": {"bodies": {"akita_black_bowl_1_main": 1.227, "plate_1_main": 1.855}}}. The scene is rebuilt after every reset and LIBERO's 0.03 m on-top tolerance grows with the target's factor. Placement overlap is NOT re-checked (experimental).

```bash
cd ASPIRE && LIBERO_CONFIG_PATH=$PWD/.libero TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 MUJOCO_GL=egl PYOPENGL_PLATFORM=egl EGL_PLATFORM=device CUDA_VISIBLE_DEVICES=0 .venv-libero/bin/python ../tools/aspire_launch.py ../data/scaled_test/scale.json -- run \
    --suite libero_goal_swap \
    --task-id 8 \
    --seed 51 \
    --init-mode seeded \
    --program PATH/program.py \
    --output-root ../data/scaled_test/out
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--suite` | `libero_goal_swap` | yes | Suite. |
| `--task-id` | `8` | yes | Task. |
| `--seed` | `51` | yes | Seed 51-55 used. |
| `--init-mode` | `seeded` | yes | Always seeded. |
| `--program` | `PATH/program.py` | yes | Program. |
| `--output-root` | `../data/scaled_test/out` | yes | Output. |

Remove an object's collisions (diagnosis only):

```bash
{"ablate": {"bodies": ["wine_rack"]}}
```

### `perturb.contacts`: Log every MuJoCo contact of a run

Spec: {"scale": {...}, "contacts": {"path": "run/contacts.jsonl"}}. Read-only evidence: one JSON line per env step, plus <stem>_scene.json (every body pose, geom, exact gaps) after dump_at_step (default 6) and _scene_reset.json. Feeds ants.evalkit.contacts and the Scene tab.

```bash
cd ASPIRE && LIBERO_CONFIG_PATH=$PWD/.libero TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 MUJOCO_GL=egl PYOPENGL_PLATFORM=egl EGL_PLATFORM=device CUDA_VISIBLE_DEVICES=0 .venv-libero/bin/python ../tools/aspire_launch.py ../data/evidence/contacts_spec.json -- run \
    --suite libero_goal_swap \
    --task-id 8 \
    --seed 51 \
    --init-mode seeded \
    --program PATH/program.py
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--suite` | `libero_goal_swap` | yes | Suite. |
| `--task-id` | `8` | yes | Task. |
| `--seed` | `51` | yes | Seed. |
| `--init-mode` | `seeded` | yes | Always seeded. |
| `--program` | `PATH/program.py` | yes | Program. |

Spec:

```bash
{"scale": {"bodies": {"akita_black_bowl_1_main": 1.227, "plate_1_main": 1.855}}, "contacts": {"path": "../data/evidence/run/contacts.jsonl"}}
```

## System 2 v0: harden with the never-regress gate

*built, no live run.* Does the adversary + diagnoser + gate loop improve a working program without regressions?

- Docs: `src/ants/orchestrator/system2.py` · run dir: `data/runs/system2_mock_synthetic`
- Inputs: incumbent program; HardenConfig
- Outputs: system2.jsonl; Human gate request/answer JSON
- Result so far: Only a synthetic mock world so far (clearly marked); harden() has no CLI. A live run needs a thin driver script (not written).

### `system2.mock`: Write a synthetic System 2 run (no sim, no model)

Fake world: program v0 breaks on size and physics, v1 fixes size but breaks pose (the gate must reject it), v2 fixes both. Clearly marked synthetic in config.json. Use it to try the System 2 tab; it is not a result.

```bash
uv run python tools/system2_mock.py data/runs/system2_mock_synthetic
```

Then view:

```bash
uv run python -m ants.evalkit.report data/runs --open
```

### `report.all`: View all runs (incl. synthetic System 2 mock)

Opens the run selector.

```bash
uv run python -m ants.evalkit.report data/runs --open
```

### `test.system2`: Tests for the System 2 loop, gate, planner

harden() has no CLI; its behaviour is exercised here with fake run_case and generate callables.

```bash
uv run pytest tests/orchestrator tests/adversary -q
```

## dev/curobo: why does the planner go through the rack?

*done (dev notes).* Tune cuRobo's robot carve, add a robot mask, validate no forbidden collisions.

- Docs: `dev/curobo/README.md` · run dir: `data/evidence/exp03_233859_a2*`
- Inputs: dumped planning clouds; trace calls dir; a program.py
- Outputs: contact logs; validator JSON
- Result so far: 6 configurations compared; only the scene-aware ones (5, 6) had 0 forbidden-contact steps. One scene, one seed.

### `curobo.service`: cuRobo service (dev): carve margin and attached held object

Stock service deletes every scene point within 5 cm of the robot spheres, so an obstacle next to the gripper is invisible. ANTS_CARVE_MARGIN_M replaces that (default here 0.02). Stop the supervised cuRobo first. Since 2026-11-02 it also uses dev/curobo/franka_attach.yml (64 sphere slots on the attached_object link) and reads the spheres to attach from $ANTS_ATTACH_FILE before every plan (written by tools/aspire_launch.py, planner.attach). Exp06 to 08 ran with ANTS_CARVE_MARGIN_M=0.0, which the service turns into max(voxel 0.01 m, 0.0) = 1 cm, not the 2 cm the doc first stated.

```bash
cd ASPIRE && ANTS_CARVE_MARGIN_M=0.0 ANTS_ATTACH_FILE=$PWD/../data/runs/curobo/attach.json .venv-curobo/bin/python ../dev/curobo/service_dev.py \
    --port 8118
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--port` | `8118` | yes | Service port (stock cuRobo port). |

Stock margin for comparison:

```bash
ANTS_CARVE_MARGIN_M=0.05 ASPIRE/.venv-curobo/bin/python dev/curobo/service_dev.py --port 8118
```

### `curobo.contact`: Run with per-step contact log + robot mask

tools/aspire_launch.py plus a per-step contact log. The env switches are prefixed to the command (set the ones you need). scene.json is a launcher spec such as scale.json. Programs under dev/curobo/programs/: exp3_a2_curobo_all.py (cuRobo on every move), exp3_a2_orbit.py (scene-aware transit + orbit skill). cuRobo service must be up for these.

```bash
cd ASPIRE && ANTS_CONTACT_LOG=../data/evidence/out.jsonl LIBERO_CONFIG_PATH=$PWD/.libero TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 MUJOCO_GL=egl PYOPENGL_PLATFORM=egl EGL_PLATFORM=device CUDA_VISIBLE_DEVICES=0 .venv-libero/bin/python ../dev/curobo/contact_launch.py scene.json -- run --benchmark libero-pro --suite libero_goal_swap --task-id 8 --seed 51 --init-mode seeded --program ../dev/curobo/programs/exp3_a2_orbit.py
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `ANTS_ROBOT_MASK=` | `sam3` | no | Env: build the planning cloud from non-robot pixels. 1 = simulator segmentation (privileged); sam3 = SAM3 prompts 'robot arm' and 'robot gripper'. Choices: 1, sam3. |
| `ANTS_EXCLUDE_RADIUS_M=` | `0.12` | no | Env: drop scene points within r of the manipulated object. |
| `ANTS_CLOUD_DIR=` | `../data/evidence/clouds` | no | Env: dump every planning cloud (input to carve_check, carve_curve, probe_goal). |
| `ANTS_PROBE_XYZ=` | `0.477,-0.175,0.237` | no | Env: print per scene body how close its points get to this goal. |
| `ANTS_ONTOP_TEST=` | `../data/evidence/ontop.json` | no | Env: drop the bowl on the plate and record what the on-top check sees. |

### `curobo.validate`: No-forbidden-collision validator

Second success validator: reads the contact log of each RUN_DIR and flags every step with a forbidden contact (robot with anything but the bowl; bowl with anything but plate, table or robot). Clean success = task check passed and nothing flagged. Pass several run dirs to compare.

```bash
python3 dev/curobo/collision_validator.py data/evidence/exp03_233859_a2
```

Several runs:

```bash
python3 dev/curobo/collision_validator.py RUN_A RUN_B RUN_C
```

### `curobo.carve-check`: Does the carve erase the obstacle?

Replays the robot carve on a dumped planning cloud (needs the GPU) and reports what survives near a contact point X Y Z (robot base frame).

```bash
cd ASPIRE && .venv-curobo/bin/python ../dev/curobo/carve_check.py CLOUD.npy TRACE_CALLS_DIR CALL_ID 0.477 -0.175 0.237
```

### `curobo.carve-curve`: Sweep the carve margin

Same replay as carve_check, over a range of margins (stock is 5 cm); prints JSON.

```bash
cd ASPIRE && .venv-curobo/bin/python ../dev/curobo/carve_curve.py CLOUD.npy TRACE_CALLS_DIR CALL_ID 0.477 -0.175 0.237
```

### `curobo.probe`: Which scene points make a goal infeasible?

Re-plans the last curobo_plan_to_joints call with parts of the cloud removed. Needs requests and numpy and the cuRobo service on 8118. Use ASPIRE's cuRobo python if numpy is missing.

```bash
python3 dev/curobo/probe_goal.py CLOUD.npy TRACE_CALLS_DIR 0.477 -0.175 0.237
```

### `curobo.ontop`: What does LIBERO's on-top check see?

ontop_test.py has no CLI of its own; set ANTS_ONTOP_TEST in curobo.contact.

```bash
echo 'run curobo.contact with ANTS_ONTOP_TEST=out.json (ontop_test.py is called by contact_launch.py)'
```

## Agent skills (slash commands)

*reference.* Prompts that write into the ANTS To-do artifact.

- Docs: `docs/runbook/agent-access.md`
- Inputs: free text
- Outputs: artifact db documents
- Result so far: Claude Code slash commands. Another agent can follow the SKILL.md files as plain instructions.

## Exp 05: perceived scene vs oracle

*done (see experiment-05-perceived-scene.md).* Can SAM 3 and depth build the exp04 collision world and S4 text without simulator state, and what is missing?

- Docs: `docs/synthesizer/experiment-05-perceived-scene.md` · run dir: `data/runs/exp05_perceived_scene`
- Inputs: data/scenes/L1/contacts_scene.json; data/scenes/perception_probe2.py; data/scenes/perception_probe3.py
- Outputs: perception_start.json; perception_arm.json; analysis.json; s4_perceived.txt; s4_oracle.txt; report.html
- Cost: free (no model call)
- Result so far: See docs/synthesizer/experiment-05-perceived-scene.md and data/runs/exp05_perceived_scene/report.html.

### `exp05.probe`: Exp 05 step 1: perceive the L1 start state (SAM 3, two arm poses)

Simulation and SAM 3 only, no model call. Writes perception_start.json and perception_arm.json (all masks of 13 prompts in both cameras). The committed results come from the same probes run by hand earlier (probe_L1 and probe_L1_arm/run2).

```bash
uv run python -m ants.orchestrator.perceived_scene --probe \
    --out data/runs/exp05_perceived_scene \
    --aspire ASPIRE
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--out` | `data/runs/exp05_perceived_scene` | yes | Run dir. |
| `--aspire` | `ASPIRE` | yes | ASPIRE checkout (services sam3 and pyroki must run). |

Run it:

```bash
uv run python -m ants.orchestrator.perceived_scene --aspire ASPIRE --out data/runs/exp05_perceived_scene --probe
```

### `exp05.analyse`: Exp 05 step 2: build the perceived world and compare with the oracle

Offline, pure Python. Variants V0 to V5, relations, S4 text, robot check. Writes analysis.json, s4_perceived.txt, s4_oracle.txt.

```bash
uv run python -m ants.orchestrator.perceived_scene --analyse \
    --out data/runs/exp05_perceived_scene
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--out` | `data/runs/exp05_perceived_scene` | yes | Run dir. |

Run it:

```bash
uv run python -m ants.orchestrator.perceived_scene --analyse --out data/runs/exp05_perceived_scene
```

### `exp05.report`: Exp 05 step 3: write the HTML report

Writes report.html (self-contained, light and dark) next to analysis.json.

```bash
uv run python -m ants.evalkit.perceived_report \
    --out data/runs/exp05_perceived_scene
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--out` | `data/runs/exp05_perceived_scene` | yes | Run dir. |

Run it:

```bash
uv run python -m ants.evalkit.perceived_report --out data/runs/exp05_perceived_scene
```

## Exp 06 to 08: cuRobo on perception, scene understanding off, perceived, privileged

*done (see experiment-06-08-curobo.md).* With cuRobo planning on the depth cloud (SAM 3 robot mask), does a scene description in the first prompt and contact evidence in repairs help, and how much does perception cost against a digital twin?

- Docs: `docs/synthesizer/experiment-06-08-curobo.md` · run dir: `data/runs/curobo/<exp>/<arm>`
- Inputs: data/demospecs/hurobo_233859.json; data/demospecs/hurobo_233832.json; data/runs/exp05_perceived_scene/s4_perceived.txt
- Outputs: data/runs/curobo/
- Result so far: 9 runs: solved 1 of 3 (06), 2 of 3 (07), 2 of 3 (08); no blocking contact in any rollout. See the doc.

### `curobo.exp`: Exp 06 to 08: cuRobo on perception, with and without scene understanding (paid)

Needs the ASPIRE services (SAM 3, PyRoki) and the dev cuRobo service (dev/curobo/service_dev.py, port 8118). Runs write to data/runs/curobo/<exp>/<arm>/. Success is the footprint rule (half of the bowl inside the plate); a clean success also has no blocking contact. Repeat the command to resume.

```bash
uv run python -m ants.orchestrator.exp_curobo \
    --exp exp06,exp08,exp07 \
    --token-budget 250000
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--exp` | `exp06,exp08,exp07` | yes | exp06: no scene text, WHY only. exp07: S4 from perception + E3 evidence. exp08: S4 from the simulator + E3, simulator robot mask. exp09 to exp11 repeat exp06 to 08 with the held bowl attached to the hand (known bowl size) and save the planning clouds. Choices: exp06, exp07, exp08, exp09, exp10, exp11, exp09,exp10,exp11. |
| `--token-budget` | `250000` | yes | Per run (3 arms per experiment: clip 233859, clip 233832, no demo). Up to 9 runs, about 30 USD at the high end. |
| `--arms` | `clip_233859,clip_233832,nodemo` | no | Subset of arms. |
| `--total-token-budget` | `` | no | Stop starting new runs once this many NEW tokens were spent in this command (counted from data/llm_ledger.jsonl). Default: no total cap. |
| `--arm-major` |  | no | Loop arms outside and experiments inside, so a stop leaves comparable arms. |
| `--print` |  | no | Print the demo_vs_nodemo commands and stop. |

Overnight, all three:

```bash
uv run python -m ants.orchestrator.exp_curobo --exp exp06,exp08,exp07 --token-budget 250000
```

Show the commands only:

```bash
uv run python -m ants.orchestrator.exp_curobo --exp exp07 --print
```

Exp 09 to 11, attach the held bowl:

```bash
uv run python -m ants.orchestrator.exp_curobo --exp exp09,exp10,exp11 --token-budget 250000
```

### `report.run`: View a run (HTML trace UI)

Writes one self-contained report.html in the run dir: success rates with intervals, seed-by-sample heatmap, rollout explorer with video, compare, policies, System 2 and Scene tabs. Keep report.html in the folder (videos are linked by relative path). Works on any run dir and on data/runs itself.

```bash
uv run python -m ants.evalkit.report data/runs/exp04_scene \
    --open
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--open` |  | yes | Open report.html in the browser. |
| `--serve` |  | no | Serve the run directory over http so videos play (127.0.0.1). |
| `--port` | `8765` | no | Port for --serve. |

All runs, pick in the UI:

```bash
uv run python -m ants.evalkit.report data/runs --open
```

Exp 02 over http:

```bash
uv run python -m ants.evalkit.report data/runs/exp02_scaled --serve --open
```

## Exp 09 to 11: exp06 to 08 again, with the held bowl attached to the hand

*code ready, not run.* Do the cuRobo refusals disappear when the held bowl is an attached object of the known size instead of an obstacle in the cloud, and does that change the solved count?

- Docs: `docs/synthesizer/experiment-09-11-curobo-attach.md` · run dir: `data/runs/curobo/<exp>/<arm>`
- Inputs: data/demospecs/hurobo_233859.json; data/demospecs/hurobo_233832.json; data/runs/exp05_perceived_scene/s4_perceived.txt; data/scenes/L1/contacts_scene.json
- Outputs: data/runs/curobo/exp09|exp10|exp11/
- Result so far: Not run yet.

### `curobo.service`: cuRobo service (dev): carve margin and attached held object

Stock service deletes every scene point within 5 cm of the robot spheres, so an obstacle next to the gripper is invisible. ANTS_CARVE_MARGIN_M replaces that (default here 0.02). Stop the supervised cuRobo first. Since 2026-11-02 it also uses dev/curobo/franka_attach.yml (64 sphere slots on the attached_object link) and reads the spheres to attach from $ANTS_ATTACH_FILE before every plan (written by tools/aspire_launch.py, planner.attach). Exp06 to 08 ran with ANTS_CARVE_MARGIN_M=0.0, which the service turns into max(voxel 0.01 m, 0.0) = 1 cm, not the 2 cm the doc first stated.

```bash
cd ASPIRE && ANTS_CARVE_MARGIN_M=0.0 ANTS_ATTACH_FILE=$PWD/../data/runs/curobo/attach.json .venv-curobo/bin/python ../dev/curobo/service_dev.py \
    --port 8118
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--port` | `8118` | yes | Service port (stock cuRobo port). |

Stock margin for comparison:

```bash
ANTS_CARVE_MARGIN_M=0.05 ASPIRE/.venv-curobo/bin/python dev/curobo/service_dev.py --port 8118
```

### `curobo.exp`: Exp 06 to 08: cuRobo on perception, with and without scene understanding (paid)

Needs the ASPIRE services (SAM 3, PyRoki) and the dev cuRobo service (dev/curobo/service_dev.py, port 8118). Runs write to data/runs/curobo/<exp>/<arm>/. Success is the footprint rule (half of the bowl inside the plate); a clean success also has no blocking contact. Repeat the command to resume.

```bash
uv run python -m ants.orchestrator.exp_curobo \
    --exp exp06,exp08,exp07 \
    --token-budget 250000
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--exp` | `exp06,exp08,exp07` | yes | exp06: no scene text, WHY only. exp07: S4 from perception + E3 evidence. exp08: S4 from the simulator + E3, simulator robot mask. exp09 to exp11 repeat exp06 to 08 with the held bowl attached to the hand (known bowl size) and save the planning clouds. Choices: exp06, exp07, exp08, exp09, exp10, exp11, exp09,exp10,exp11. |
| `--token-budget` | `250000` | yes | Per run (3 arms per experiment: clip 233859, clip 233832, no demo). Up to 9 runs, about 30 USD at the high end. |
| `--arms` | `clip_233859,clip_233832,nodemo` | no | Subset of arms. |
| `--total-token-budget` | `` | no | Stop starting new runs once this many NEW tokens were spent in this command (counted from data/llm_ledger.jsonl). Default: no total cap. |
| `--arm-major` |  | no | Loop arms outside and experiments inside, so a stop leaves comparable arms. |
| `--print` |  | no | Print the demo_vs_nodemo commands and stop. |

Overnight, all three:

```bash
uv run python -m ants.orchestrator.exp_curobo --exp exp06,exp08,exp07 --token-budget 250000
```

Show the commands only:

```bash
uv run python -m ants.orchestrator.exp_curobo --exp exp07 --print
```

Exp 09 to 11, attach the held bowl:

```bash
uv run python -m ants.orchestrator.exp_curobo --exp exp09,exp10,exp11 --token-budget 250000
```

### `curobo.viewer`: Build the cuRobo plan viewer for one run attempt

Replays every cuRobo plan call of one attempt (cloud, robot spheres, straight vs planned path, before/after attaching the bowl by my own collision check) and writes <run>/plan_viewer/index.html and plans2d.html. View it in the run viewer's Doc tab: uv run python -m ants.evalkit.report data/runs/curobo --serve --open

```bash
cd to the ANTS repo root && PYTHONPATH=src ASPIRE/.venv-libero/bin/python dev/curobo/make_viewer.py \
    data/runs/curobo/exp09/clip_233859 ''
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `data/runs/curobo/exp09/clip_233859` | `` | yes | Run folder (needs --save-clouds, on by default in exp09 to exp11). Passed as the first argument. |
| `--attempt` | `4` | no | Attempt to replay; default the last. |

All three arms of exp09, last attempt:

```bash
for a in clip_233859 clip_233832 nodemo; do PYTHONPATH=src ASPIRE/.venv-libero/bin/python dev/curobo/make_viewer.py data/runs/curobo/exp09/$a; done
```

### `report.run`: View a run (HTML trace UI)

Writes one self-contained report.html in the run dir: success rates with intervals, seed-by-sample heatmap, rollout explorer with video, compare, policies, System 2 and Scene tabs. Keep report.html in the folder (videos are linked by relative path). Works on any run dir and on data/runs itself.

```bash
uv run python -m ants.evalkit.report data/runs/exp04_scene \
    --open
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--open` |  | yes | Open report.html in the browser. |
| `--serve` |  | no | Serve the run directory over http so videos play (127.0.0.1). |
| `--port` | `8765` | no | Port for --serve. |

All runs, pick in the UI:

```bash
uv run python -m ants.evalkit.report data/runs --open
```

Exp 02 over http:

```bash
uv run python -m ants.evalkit.report data/runs/exp02_scaled --serve --open
```

## Demo vs no demo on cuRobo (simulator robot mask, attached bowl)

*final (submission experiment, tag submission-experiment).* With cuRobo planning and the held bowl attached, does one human demonstration (plus S4 scene text and E3 repair evidence) beat task text only?

- Docs: `docs/synthesizer/show-once-vs-task-only/demo_vs_no_demo_analysis.ipynb` · run dir: `data/runs/demo_e3_s4_sim | data/runs/nodemo_task_only_sim`
- Inputs: data/demospecs/hurobo_233859.json; data/scene_text/S4_L1.txt
- Outputs: data/runs/demo_e3_s4_sim/; data/runs/nodemo_task_only_sim/
- Result so far: Held-out seeds 1 to 5, two samples (T 0.2, 0.7) per arm. Demo: debug seed solved in 2 and 2 attempts; scaled 5/5 and 2/5, stock 4/5 and 3/5. No-demo: solved in 5 (no) and 3 attempts; scaled 4/5 and 4/5, stock 0/5 and 0/5. The arms also differ in scene text and evidence. Source: events.jsonl of each run. Ran before the attach frame fix: spheres 9.65 cm too high.

### `exp12.demo`: Demo vs no demo, demo arm: demo + S4 + E3 on cuRobo (paid)

Needs the SAM 3 and PyRoki services and the dev cuRobo service on port 8118 (runbook entries services.start and curobo.service). Settings saved in docs/synthesizer/demo-vs-nodemo-config.json. Run the demo and no-demo commands one after the other, not in parallel.

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

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--aspire` | `ASPIRE` | yes | ASPIRE checkout. |
| `--out` | `data/runs/demo_e3_s4_sim` | yes | Run folder. Repeat the same --out to resume. |
| `--demospec` | `data/demospecs/hurobo_233859.json` | yes | DemoSpec of clip 233859 (the no-demo arm ignores its content but the flag is required). |
| `--arms` | `demo` | yes | demo or nodemo. |
| `--temperatures` | `0.2,0.7` | yes | One sample per temperature. |
| `--explain` |  | yes | Repair replies start with WHY. |
| `--repairs` | `4` | yes | Max repairs per sample (5 attempts). |
| `--planner` | `curobo-sim` | yes | cuRobo with the robot mask from the simulator (privileged). |
| `--attach-known` |  | yes | Attach the held bowl with its known size (privileged). Needs the dev cuRobo service with ANTS_ATTACH_FILE=data/runs/curobo/attach.json; do not run two such commands at once (one shared attach file). |
| `--save-clouds` |  | yes | Keep every planning cloud for dev/curobo/make_viewer.py. |
| `--debug-scene` | `scaled` | yes | Debug and repair in the scaled scene. |
| `--scenes` | `scaled` | yes | As run on 2026-11-04. The run also logged stock-scene evaluation. |
| `--eval-seeds` | `1,2,3,4,5` | yes | Held-out seeds, reporting only. |
| `--token-budget` | `300000` | yes | Hard cap on new tokens per command. Observed: demo 204,933, no-demo 247,243 (about 2.8 and 3.3 USD). |
| `--evidence` | `e3` | yes | Repair adds the contact log, the scene text and stall readings. |
| `--contacts` |  | yes | Log simulator contacts per attempt. |
| `--scene-text-file` | `data/scene_text/S4_L1.txt` | yes | S4 scene text (regenerate with g_scene_text('S4','L1') in ants.orchestrator.scene_context_exp). |

Demo vs no demo, demo arm: demo + S4 + E3 on cuRobo:

```bash
uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ASPIRE --temperatures 0.2,0.7 --explain --repairs 4 --planner curobo-sim --attach-known --save-clouds --debug-scene scaled --scenes scaled --eval-seeds 1,2,3,4,5 --token-budget 300000 --demospec data/demospecs/hurobo_233859.json --out data/runs/demo_e3_s4_sim --arms demo --evidence e3 --contacts --scene-text-file data/scene_text/S4_L1.txt
```

### `exp12.nodemo`: Demo vs no demo, no-demo arm: task text only on cuRobo (paid)

Needs the SAM 3 and PyRoki services and the dev cuRobo service on port 8118 (runbook entries services.start and curobo.service). Settings saved in docs/synthesizer/demo-vs-nodemo-config.json. Run the demo and no-demo commands one after the other, not in parallel.

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

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--aspire` | `ASPIRE` | yes | ASPIRE checkout. |
| `--out` | `data/runs/nodemo_task_only_sim` | yes | Run folder. Repeat the same --out to resume. |
| `--demospec` | `data/demospecs/hurobo_233859.json` | yes | DemoSpec of clip 233859 (the no-demo arm ignores its content but the flag is required). |
| `--arms` | `nodemo` | yes | demo or nodemo. |
| `--temperatures` | `0.2,0.7` | yes | One sample per temperature. |
| `--explain` |  | yes | Repair replies start with WHY. |
| `--repairs` | `4` | yes | Max repairs per sample (5 attempts). |
| `--planner` | `curobo-sim` | yes | cuRobo with the robot mask from the simulator (privileged). |
| `--attach-known` |  | yes | Attach the held bowl with its known size (privileged). Needs the dev cuRobo service with ANTS_ATTACH_FILE=data/runs/curobo/attach.json; do not run two such commands at once (one shared attach file). |
| `--save-clouds` |  | yes | Keep every planning cloud for dev/curobo/make_viewer.py. |
| `--debug-scene` | `scaled` | yes | Debug and repair in the scaled scene. |
| `--scenes` | `scaled` | yes | As run on 2026-11-04. The run also logged stock-scene evaluation. |
| `--eval-seeds` | `1,2,3,4,5` | yes | Held-out seeds, reporting only. |
| `--token-budget` | `300000` | yes | Hard cap on new tokens per command. Observed: demo 204,933, no-demo 247,243 (about 2.8 and 3.3 USD). |

Demo vs no demo, no-demo arm: task text only on cuRobo:

```bash
uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ASPIRE --temperatures 0.2,0.7 --explain --repairs 4 --planner curobo-sim --attach-known --save-clouds --debug-scene scaled --scenes scaled --eval-seeds 1,2,3,4,5 --token-budget 300000 --demospec data/demospecs/hurobo_233859.json --out data/runs/nodemo_task_only_sim --arms nodemo
```

### `report.run`: View a run (HTML trace UI)

Writes one self-contained report.html in the run dir: success rates with intervals, seed-by-sample heatmap, rollout explorer with video, compare, policies, System 2 and Scene tabs. Keep report.html in the folder (videos are linked by relative path). Works on any run dir and on data/runs itself.

```bash
uv run python -m ants.evalkit.report data/runs/exp04_scene \
    --open
```

| Flag | Default | On | Meaning |
|---|---|---|---|
| `--open` |  | yes | Open report.html in the browser. |
| `--serve` |  | no | Serve the run directory over http so videos play (127.0.0.1). |
| `--port` | `8765` | no | Port for --serve. |

All runs, pick in the UI:

```bash
uv run python -m ants.evalkit.report data/runs --open
```

Exp 02 over http:

```bash
uv run python -m ants.evalkit.report data/runs/exp02_scaled --serve --open
```
