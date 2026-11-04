<p align="center"><img src="docs/images/banner.svg" alt="ants" width="100%"></p>

# ANTS: Agentic Task Synthesis

**Show a robot a task once. An adversary breaks it in simulation. Every failure becomes a readable fix, kept only if nothing got worse.** No model weights are trained.

Our entry for the [Meta Global AI Developer Hackathon 2026](https://dev.meta.ai/events/global-hackathon).

## Problem

Robots learn one task at a time from lots of data, and nobody can say when they will fail. Small changes (a camera angle, a bigger plate) can break a skill that worked in the lab. A factory with a new part every week cannot use a skill it cannot trust.

## Solution

![ANTS: System 1 writes a program from one human demo, System 2 attacks it in simulation](docs/images/architecture.png)

*Figure from the paper. In this build the demo is marker-tracked (SAM 3 is the robot's perception in simulation), the experience memory is future work, and every rewrite passes a regression gate.*

| Part | What it does |
|---|---|
| **System 1** (synthesizer) | Tracks one demonstration video, summarises it relative to object size, and has Muse Wonder write the robot program (v0), checked in simulation |
| **System 2** (adversary) | Picks the weakest category (Thompson sampling), four Muse Spark agents propose attacks on the program's assumptions, severity is capped in code, LIBERO runs it, and the failure is diagnosed into a rule |
| **Gate** (orchestrator) | Replays every case seen so far; a rewrite is accepted only if it is no worse on all of them and better on one |
| **ANTS Studio** | One window to watch it: the Synthesizer chat and live cameras, and the Adversary's attacks, replays and versions |

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
| **Muse Spark** (Contemplating) | four agents read the program and each propose an attack on one assumption |
| **Muse Spark** (Thinking) | diagnoses each failure into a cause and a rule |
| **Muse Spark** (Instant) | explains each failure in plain language in the studio |
| **SAM 3** | the robot's perception: segments the bowl and the plate in every rollout |

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

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).

```
uv sync
uv run python -m ants.orchestrator.run --cycles 30 --out data/runs/mock_loop   # offline test world
uv run python -m ants.studio.console --adversary-run data/runs/mock_loop      # open http://localhost:8765
```

The simulator runs need a GPU, the ASPIRE checkout and `META_API_KEY`: see [docs/results.md](docs/results.md).

## Docs

[Results](docs/results.md) · [Concept](docs/concept.md) · [Architecture](docs/architecture.md) · [Context and decisions](docs/context.md) · [For coding agents](AGENTS.md)

## License

[Apache-2.0](LICENSE). Third-party models (SAM 3, Muse) and datasets keep their own licenses.
