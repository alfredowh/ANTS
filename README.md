<p align="center"><img src="docs/images/banner.svg" alt="ants" width="100%"></p>

# ANTS: Agentic Task Synthesis

**Show a robot a task once. An adversary breaks it in simulation. Every failure becomes a readable fix, kept only if no case seen so far got worse.** No model weights are trained.

Our entry for the [Meta Global AI Developer Hackathon 2026](https://dev.meta.ai/events/global-hackathon).

## Problem

Robots learn one task at a time from lots of data, and nobody can say when they will fail. Small changes (a camera angle, a bigger plate) can break a skill that worked in the lab. A factory with a new part every week cannot use a skill it cannot trust.

## Solution

![ANTS: the Synthesizer writes a program from one human demo, the Adversary attacks it in simulation, and a regression gate keeps only rewrites that do no worse](docs/images/architecture.svg)

*Solid boxes are built and running. Dashed boxes are future work.*

| Part | What it does |
|---|---|
| **Synthesizer** (System 1) | Tracks one demonstration video, summarises it relative to object size, and has Muse Wonder write the robot program (v0), checked in simulation |
| **Adversary** (System 2) | Picks the weakest category (Thompson sampling), four Muse Spark agents propose attacks on the program's assumptions, severity is capped in code, LIBERO runs it, and the failure is diagnosed into a rule |
| **Gate** (orchestrator) | Replays every case seen so far; a rewrite is accepted only if it is no worse on all of them and better on one |
| **ANTS Studio** | One window to watch it: the Synthesizer chat and live cameras, and the Adversary's attacks, replays and versions |

## Show once: from one human video to the robot

| One human demonstration (phone, 15 s) | The program Muse Wonder wrote from it (v0, LIBERO-Pro) |
|---|---|
| ![a person puts a bowl on a plate](docs/images/demo_human.gif) | ![the Franka arm puts the bowl on the plate in simulation](docs/images/demo_robot.gif) |

- **Tracking:** markers on the bowl, the plate and a ChArUco board give the hand and object paths in metres.
- **Summary (DemoSpec):** grasp the rim, approach from above, carry height, release over the plate, all as fractions of the object sizes, so they carry over to the simulated objects.
- **Program:** Muse Wonder writes a plain Python script over the robot API (`localize_object`, `move_to_pose`, `close_gripper`, …), checked on a nominal seed; one text repair made v0 pass.

## The task in LIBERO-Pro

![LIBERO-Pro scene: start and end of the v0 rollout](docs/images/libero_scene.png)

LIBERO-Pro `libero_goal_swap`, task 8, "put the bowl on the plate": a Franka arm, the bowl, the plate, and other objects that are not part of the task. The robot sees through SAM 3 (RGB-D masks to point clouds) and plans with PyRoki, inside NVIDIA's ASPIRE `cap_harness`.

## How System 2 attacks

![The same starting scene under each attack category](docs/images/attacks.png)

Each attack changes the scene before the program runs, within a severity cap of ρ = 0.8 enforced in code:

| Category | What changes | At the 0.8 cap |
|---|---|---|
| **pose** | where the bowl starts | moved up to about 6 cm |
| **size** | bowl and plate scale | bowl ×1.2, plate ×1.7 |
| **physics** | friction and bowl mass (invisible in a still) | friction ×0.44, mass ×2.6 |
| **actuation** | noise and delay on every arm command (invisible in a still) | 1.6 cm noise, 2 steps late |
| **camera** | the robot's camera pose and field of view | moved 4 cm, +3.2° |
| **lighting** | scene brightness | ×0.44 |

**One attack, step by step:** Thompson sampling picks the category most likely to fail → four Muse Spark agents read the program and each propose values that break one assumption (e.g. "the plate stays its demo size") → the values are clamped to the cap → LIBERO runs the program → on a failure, Muse Spark compares the program's printed measurements with the nominal run and writes one rule for Muse Wonder.

## What broke it

![Nominal vs plate x1.7, same seed: carry, release, end](docs/images/size_failure.png)

With a ×1.7 plate, SAM 3 measured the plate 11 cm tall instead of 2 cm (the mask likely merges with the cabinet behind it), so v0 let go about 9 cm too high and the bowl landed on the rim. Muse Spark traced it to `plate_top_z = max(...)`, Muse Wonder rewrote the support height from the plate's interior points, and the gate accepted v1.

## What we tested

Bowl-on-plate with a Franka arm in LIBERO, on an RTX 5090: **759 real simulator rollouts**, attack severity 0.3 to 0.8, held-out cases on scene seeds the system never trained or tuned on.

## Results

| Question | Result |
|---|---|
| Does one demonstration give a working program? | **Yes.** v0 passes **94% (47/50)** of held-out perturbed episodes |
| Does the adversary find real weak spots? | **Yes.** All failures come from one blind spot: SAM 3 mis-reads a larger plate. **0 failures in 599** rollouts with correct perception, **11 in 26** with a mis-read plate |
| Does the gate block bad fixes? | **Yes.** 3 of 3 rewrites that did not fix the failure were rejected |
| Can the loop repair itself? | **Yes, once.** Muse Spark diagnosed the cause from the measurements, Muse Wonder wrote a fix, and the gate accepted v1 |
| Does the fix generalise? | **Not yet.** Held-out size cases: v0 **98% (49/50)**, v1 **94% (47/50)**. The gate saw only 4 cases, so it missed regressions on unseen scenes |
| Does adaptive testing beat uniform testing? | **Not answered.** 2/200 vs 1/200 failures: v0 fails too rarely to compare |

Details, run folders and commands: [docs/results.md](docs/results.md).

## Meta models

| Model | Role |
|---|---|
| **Muse Wonder** | writes the program from the demonstration, and rewrites it after each failure |
| **Muse Spark** | four agents read the program and each propose an attack on one assumption |
| **Muse Spark** | diagnoses each failure into a cause and a rule |
| **Muse Spark** | explains each failure in plain language in the studio |
| **SAM 3** | the robot's perception: segments the bowl and the plate in every rollout |

The code maps effort levels to Muse Spark's Contemplating, Thinking and Instant modes; how the API selects those modes is unconfirmed, and "four agents" means four separate calls.

## Cost

| Item | Cost |
|---|---|
| Muse Spark (attacks, diagnoses, explanations) | $10.87 (805k tokens) |
| Muse Wonder (4 rewrites) | $1.40 (104k tokens) |
| One loop cycle | $0.17 to $0.55 |
| GPU | one RTX 5090 at $0.85/h |

Token prices at the observed $13.5 per million tokens.

## Vision

A test-and-repair layer for robot skills: from one demonstration, an integrator gets a program, an adversarial test report and an audit trail. Next: larger acceptance sets in the gate, perception checks the loop can learn, skills shared across tasks, and the same adversary testing any black-box robot policy.

## Quick start

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/). Everything runs through `uv run`.

**1. Offline, no GPU or key** (a toy world that exercises the whole loop):

```bash
uv sync
uv run python -m ants.orchestrator.run --cycles 30 --out data/runs/mock_loop   # attack, rewrite, gate, escalate
uv run python -m ants.studio.console --adversary-run data/runs/mock_loop      # open http://localhost:8765
```

**2. On a GPU** (Ubuntu 22.04, CUDA 12.8; we used one RTX 5090). You need approved access to [`facebook/sam3`](https://huggingface.co/facebook/sam3) and a Meta API key.

```bash
git submodule update --init ASPIRE && uv sync                                   # code and the ANTS env
(cd ASPIRE && scripts/bootstrap_libero.sh \
  && scripts/bootstrap_providers.sh --providers sam3,pyroki --profile rtx5090)  # simulator and models
export HF_TOKEN=hf_...; echo 'META_API_KEY=...' > .env                           # keys
(cd ASPIRE && TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 scripts/supervise_services.sh \
  --profile rtx5090 --providers sam3,pyroki)                                    # SAM 3 + PyRoki; keep running
uv run python -m ants.orchestrator.preflight --aspire $PWD/ASPIRE --muse-spark --smoke   # must print READY
```

**3. Run the attacks** (pass the ASPIRE path as an absolute path; one simulator job at a time):

```bash
A="--backend cap_harness --aspire $PWD/ASPIRE"

# Muse Spark attacks on v0, no rewrites: why each attack, the replay, the diagnosis
uv run python -m ants.studio.run --attacks 8 $A --model muse-spark --token-budget 300000 --out data/runs/attacks

# the closed loop: attack, diagnose, rewrite, gate; then 50 held-out cases
uv run python -m ants.orchestrator.run $A --model muse-spark --synthesizer muse-api \
  --synth-token-budget 400000 --categories size --cycles 10 --eval-held-out 50 --out data/runs/loop

# adaptive vs uniform test selection
uv run python -m ants.adversary.experiments.adaptive_vs_uniform $A --attacks 40 --seeds 0 1 2 3 4 --out data/runs/h1a
```

**4. Watch a run:** `uv run python -m ants.studio.console --adversary-run data/runs/loop`. Replay plays each attack's video next to the nominal run, and the call timeline is the scrubber.

Rollouts take about 13 s each on the 5090; a Muse Spark attack takes 1–2 min for its four agents. The README images come from these runs: `tools/make_readme_media.py`.

**5. From your own video, in ANTS Studio:** start the console as in step 4, click `/policy-dev`, click `+` and pick a clip, type the task, press Enter, then choose the settings. The run goes through extraction, DemoSpec, Muse Wonder and a nominal check, then holds for you with the rollout looping before the Adversary starts. Clips need the marker setup; `20261016_233859` is known to pass. This path plans with PyRoki and interpolation, without cuRobo, and writes every setting to `execution.json`.

## Docs

[Results](docs/results.md) · [Concept](docs/concept.md) · [Architecture](docs/architecture.md) · [Context and decisions](docs/context.md) · [For coding agents](AGENTS.md)

## License

[Apache-2.0](LICENSE). Third-party models (SAM 3, Muse) and datasets keep their own licenses.
