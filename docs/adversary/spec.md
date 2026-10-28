# Adversary (System 2): agent spec

## What this package is

System 2 of ANTS. It takes a robot program written by
System 1, tries to make it fail in simulation, explains each failure, and returns the failure as a
constraint System 1 can follow. It never edits programs and never decides whether a rewrite is
accepted. Those decisions belong to `orchestrator/`.

Owner: Daniel. System 1 (`synthesizer/`) is owned by Alfredo. Only `contracts/` is shared.

## Repo context

```
├── contracts/      shared types: Demo, Policy, Perturbation, Failure, Constraint, RobotAPI
├── synthesizer/    System 1: SAM 3.1 tracking, Muse Wonder policy synthesis, experience memory
├── adversary/      System 2: this package
├── orchestrator/   closed loop, regression gate, escalation
└── evalkit/        acceptance / held-out split, metrics, logs
```

## Hard rules

1. **Model-agnostic.** No vendor SDK or model name anywhere except `models/` adapters. Planner and
   diagnoser depend only on the `ReasoningModel` interface. Muse Spark is the default, not a dependency.
2. **Simulator-agnostic.** Planner, diagnoser and history never import LIBERO. Only `rollout/` backends do.
3. **Contracts only across boundaries.** `adversary/` imports from `contracts/` and nothing else in the
   repo. Never import from `synthesizer/`, `orchestrator/` or `evalkit/`.
4. **Generated code is untrusted.** Policies run sandboxed (restricted builtins, only `RobotAPI` in
   scope, wall-clock timeout). A crash is `Outcome.ERROR`, never counted as a task failure.
5. **Severity is enforced in code, not in prompts.** Every perturbation passes through
   `PerturbationSpace.validate()` (clamp to bounds, severity ≤ ρ) whatever the model returned.
6. **The loop never crashes on the model.** Model errors, timeouts or invalid JSON fall back to
   deterministic behaviour (uniform sampling, rule-based diagnosis), and the fallback is logged.
7. **Everything is reproducible.** Every perturbation has a seed; every attack is appended to the
   history log; the same seed and config reproduce the same run with the mock model.
8. **Offline first.** A mock model and a mock simulator must always exist, so the full loop runs in
   tests without network or GPU.

## Architecture

One adversarial cycle:

```
FailureHistory ──counts per category──▶ CategorySelector ──category c──▶ PerturbationProposer
     ▲                                  (Thompson sampling, η-uniform)   (M model agents, PARALLEL)
     │                                                                          │
     │                                                    PerturbationSpace.validate (clamp, ≤ ρ)
     │                                                                          │ Perturbation p
     │                                                                          ▼
     │                           Policy π ─────────────▶ RolloutRunner (sandbox, timeout)
     │                                                    SimBackend: LIBERO | mock
     │                                                                          │ RolloutResult
     │                                          success ◀───────────────────────┤
     │                                                                          │ failure
     │                                                                          ▼
     └───────────────────────────── record ◀───────── Diagnoser (model DELIBERATE + rule fallback)
                                                                                │
                                                     AttackReport { p, result, Failure, Constraint }
                                                                                │
                                                                                ▼
                                                    orchestrator → System 1 → regression gate
```

### Components

| Component | Responsibility | Key behaviour |
|---|---|---|
| `models/` | Reasoning interface and adapters | `complete(messages, effort, json_schema, n)`; effort is FAST, DELIBERATE or PARALLEL; adapters map it to vendor modes (Spark: Instant / Thinking / Contemplating) |
| `perturbations/` | The perturbation space P = ∪ P_c | per category: parameters with (nominal, min, max); severity = max normalised distance from nominal; clamp and enforce ρ |
| `planner/selector` | Which category to attack | Beta(α_c, β_c) per category from the current policy's history (α failures, β successes), Thompson sample, η-uniform exploration; posterior quantiles for the stop rule |
| `planner/proposer` | Concrete perturbation | M agents propose parameters given the program and recent attacks; validate each; keep the most novel; uniform fallback |
| `rollout/` | Run a program under a perturbation | backend builds a perturbed episode and exposes `RobotAPI`; runner executes `run(robot)` in a sandbox; packages events, metrics, phase, video, keyframes |
| `diagnosis/` | Explain failures | model returns {mode, root_cause, confidence, constraint} against a fixed mode list; below a confidence floor, use rules from the event log |
| `history/` | Memory of attacks | JSONL append log; counts per category per policy; F_n (unique failing perturbations) for the gate |
| `adversary.py` | Public API, the only thing the orchestrator touches | `attack(π)`, `replay(π, perturbations)`, `discovered_failures()`, `status(π)` |

### Public API (stable, the orchestrator depends on it)

```python
adv = Adversary.from_config(AdversaryConfig(model="muse-spark", backend="libero"))
report: AttackReport = adv.attack(policy)              # one cycle
results: list[RolloutResult] = adv.replay(policy, ps)  # fixed cases: gate, acceptance, held-out
cases: list[Perturbation] = adv.discovered_failures()  # F_n
status: RobustnessStatus = adv.status(policy)          # .robust when max_c Q_0.95(θ_c) < τ
```

### Config (defaults)

| Field | Default | Meaning |
|---|---|---|
| `model` | `"mock"` | `"muse-spark"`, `"provider:model"` (any OpenAI-compatible endpoint), or `"mock"` |
| `backend` | `"mock"` | `"libero"` or `"mock"` |
| `categories` | pose, physics, clutter, camera | arms of the selector (also available: lighting, occlusion, actuation) |
| `rho` | 0.8 | severity bound |
| `eta` | 0.2 | uniform exploration rate (`eta=1.0` is the uniform baseline for evaluation) |
| `n_agents` | 4 | M parallel proposers |
| `tau` | 0.1 | target maximum failure rate per category |
| `stop_quantile` | 0.95 | stop when every category's upper posterior quantile is below τ |
| `rollout_timeout_s` | 30 | per-rollout wall clock |
| `record_failures` | true | video and keyframes for multimodal diagnosis |

## Layout to create

```
adversary/
├── README.md
├── __init__.py              exports Adversary, AdversaryConfig, AttackReport, RobustnessStatus
├── adversary.py             facade
├── config.py                AdversaryConfig
├── models/
│   ├── base.py              ReasoningModel protocol, Effort, Message, ModelResponse
│   ├── muse_spark.py        Meta Model API adapter
│   ├── openai_compat.py     any OpenAI-compatible endpoint, stdlib only
│   ├── mock.py              deterministic offline model
│   └── __init__.py          get_model(spec)
├── perturbations/
│   └── space.py             Param, PerturbationSpace, DEFAULT_SPACE
├── planner/
│   ├── selector.py          Thompson sampling, posterior mean and quantiles
│   ├── proposer.py          model agents + validation + novelty + fallback
│   └── planner.py           TestPlanner = selector + proposer
├── rollout/
│   ├── backend.py           SimBackend, Episode protocols
│   ├── runner.py            sandboxed execution, timeout, evidence packaging
│   ├── mock_backend.py      toy world, one failure mechanism per category
│   └── libero_backend.py    LIBERO implementation
├── diagnosis/
│   └── diagnoser.py         model diagnoser + RuleDiagnoser, failure-mode list
├── history/
│   └── store.py             FailureHistory, AttackRecord
└── prompts/
    ├── propose.md
    └── diagnose.md
```

Tests live in the repo-level `tests/`, mirroring the package (see AGENTS.md):

```
tests/adversary/
├── test_space.py            clamping, severity ≤ ρ
├── test_selector.py         posteriors, exploration, reset on new policy
├── test_runner.py           sandbox, timeout, crash → ERROR
└── test_loop.py             full loop offline: finds failures, rewrites pass a gate, failure rate drops
```

## Build order

Build in this order. Each step must pass its tests before the next one starts.

1. **Contracts.** Agree `contracts/types.py` and `contracts/primitives.py` with Alfredo first.
   Everything else depends on them.
2. **Model layer.** `base.py`, `mock.py` and `get_model`. No network yet.
3. **Perturbation space.** Parameters and bounds for the LIBERO bowl-and-plate scene.
4. **Selector, proposer, planner.** Planner, tested with the mock model.
5. **Runner and mock backend.** Sandbox and timeout, with a toy world in which each category has a
   failure mechanism that the matching robust coding pattern defeats.
6. **Diagnoser and history.** At this point the whole loop runs offline (`test_loop.py`).
7. **LIBERO backend.** The largest piece (see below).
8. **Muse Spark adapter.** Swap the mock for the real model.
9. **Prompt tuning.** Use real programs and real failures.

## What still has to be built, and how

### LIBERO backend (`rollout/libero_backend.py`)
- Load the LIBERO scene matching the recorded demo (Franka Panda, bowl and plate, OSC_POSE controller).
- Use one applier per category, run after `reset(seed)`, then step a few no-ops to settle physics:
  - **pose:** set the object's free-joint position (x, y, yaw).
  - **physics:** scale geom friction and body mass.
  - **clutter:** spawn n distractor objects at least `min_gap` from the target and from the approach path.
  - **lighting:** change light diffuse intensity and direction.
  - **camera:** offset the agent-view camera pose (yaw, pitch, distance).
  - **occlusion:** place a box between camera and target, sized to `coverage`.
  - **actuation:** wrap `env.step` with Gaussian action noise and a latency queue.
- `RobotAPI` over OSC:
  - `locate`: start with privileged simulator state; then add camera perception (SAM 3.1 mask, depth,
    centroid) so lighting, camera and occlusion attacks matter.
  - `move_to`: closed-loop motion, routing via a waypoint when `clearance > 0`.
  - `grasp`: returns held or not from finger contact.
  - `place`.
  - Every primitive logs events (`grasp_slip`, `collision`, `object_dropped`) and the last phase reached.
- `success()`: the LIBERO task predicate plus a no-collision flag.
- When recording: an mp4, plus keyframes at the start, the grasp, the failure moment and the end.

### Muse Spark adapter (`models/muse_spark.py`)
- Confirm the Meta Model API endpoint, auth header, and how the reasoning mode is selected.
- If there is no native multi-agent mode, emulate PARALLEL with n independent samples.
- Log tokens per call in `ModelResponse.usage`, so evalkit can report cost per cycle.

### Prompts
- **propose:** show the program and recent attacks in that category; ask for values that break a
  specific assumption in the code (hard-coded positions, fixed grasp force, no re-check after grasp,
  straight approach). Output is JSON params plus a one-sentence rationale.
- **diagnose:** take the event log, metrics, last phase and program, plus keyframes when available.
  Output is one mode from the fixed list, one causal sentence tied to a line in the program, a
  confidence, and one imperative constraint the generator can follow.

## Conventions

- Python 3.10+, type hints everywhere, frozen dataclasses for anything that crosses a boundary.
- No hard dependencies in the core: standard library only; LIBERO and robosuite only inside
  `libero_backend.py`.
- Log every decision with its inputs: selector draws, proposals, validated perturbation, diagnosis.
  A judge should be able to replay why each test was chosen.
- Commit or delete; no dead code. No secrets in the repo: API keys come from environment variables
  (`META_MODEL_API_KEY`, `META_MODEL_API_BASE`).

## Out of scope for this package

- Accepting or rejecting rewrites (the regression gate lives in `orchestrator/`).
- Escalation decisions (`orchestrator/` uses `status()` plus its own stall counter).
- Acceptance and held-out suites, metrics and plots (`evalkit/` uses `replay()`).
- Program generation and experience memory (`synthesizer/`).

## Definition of done

- `test_loop.py` passes offline: the adversary finds failures, rewrites pass a gate, and the posterior
  failure rate falls.
- With the LIBERO backend, one real program fails under at least two categories, gets diagnosed, and
  a constraint-guided rewrite passes all discovered cases.
- Switching between `model="mock"` and `model="muse-spark"` needs no code change.
