# System 2: the adversary

System 2 takes a robot program written by System 1 and tries to make it fail in simulation. It explains each failure and hands it back as a constraint System 1 can follow. It only reports. It never edits code, never accepts or rejects rewrites, and never decides to escalate.

> Status: the full System 2 cycle runs offline. Implemented and tested: model layer, perturbation space wired to the ASPIRE launcher, selector and test planner, rule diagnoser, failure history, sandboxed runner, a mock world that runs System 1's v0 policy (`examples/bowl_on_plate/policy.py`) unchanged, and the `Adversary` entry point. With `model="muse-spark"`, four Muse Spark agents propose each attack from the program's code, Muse Spark diagnoses each failure and writes a plain-language explanation, all with rule fallbacks; tested against a fake API, not yet run live. Next: the cap_harness backend. Mock-world numbers are test fixtures, not results; nothing is measured on the simulator yet. Full-system context: [`docs/architecture.md`](../../../docs/architecture.md). Hard rules, layout and build order are in [`docs/adversary/spec.md`](../../../docs/adversary/spec.md).

## One adversarial cycle

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

The first half (steps 1 to 4) chooses the attack. The second half (steps 5 to 8) runs it and turns any failure into something System 1 can act on.

## Choosing the attack

### 1. Failure history (`history/`)

System 2's memory. Every attack is appended to a log: which program version, which perturbation, success or failure, and the diagnosed failure mode. Two things are read from it:

- **Counts per category** (failures and successes) for the current program version. These feed the selector.
- **Every perturbation that ever caused a failure.** The orchestrator's regression gate re-runs these, so a fixed program has to keep passing them.

When System 1 writes a new version, the counts start fresh, because the old program's weaknesses say nothing certain about the new one. The log itself is kept, so the whole run can be replayed and audited.

### 2. Category selector (`planner/selector`)

Decides *where* to attack: pose, physics, clutter, camera and so on. Each category keeps an estimate of how often it breaks the current program, a Beta distribution built from its failures and successes. Each cycle it draws a sample from every category's estimate and attacks the highest (Thompson sampling).

- A category that keeps causing failures gets attacked more often.
- A category that has barely been tried still gets chances, because its estimate is wide.
- On top of that, 20% of picks (η) are uniformly random, so no category is ever ignored.

The same estimates drive the **stop rule**: when every category is confidently below the target failure rate τ (its 95th-percentile estimate is under τ), System 2 reports the program as robust.

### 3. Perturbation proposer (`planner/proposer`)

Decides *what* exactly to change inside the chosen category. It is the only creative part of the planner. Four model agents run in parallel, and each one sees:

- the program's code,
- the allowed range for each setting,
- recent attacks in that category and what happened.

Each agent proposes concrete values aimed at an assumption in the code, for example "the bowl position is hard-coded, so shift it 9 cm left" or "grasp force is fixed at 20 N, so triple the mass". The proposer keeps the suggestion least like anything already tried, so the adversary explores instead of repeating itself. If the model errors or returns junk, it falls back to random values within the allowed range and the loop keeps running.

### 4. Perturbation space (`perturbations/`)

The rules of the game: pure data plus validation. Every category declares its settings with a nominal value, a minimum and a maximum (for example friction ×0.2 to ×2.0). **Severity** is how far a perturbation strays from nominal, from 0 (unchanged scene) to 1 (edge of the range).

Every proposal passes through here: unknown settings are dropped, missing ones are filled with the nominal value, values are clamped, and severity is capped at ρ (0.8). The bound lives in code, not in the prompt, so the model can never produce an absurd scene (a 50 kg bowl) that would make "failure" meaningless.

**Output: one perturbation p**, with the category, the exact values, the severity, a seed for reproducibility, and the model's one-line reason for choosing it.

## Running the attack

### 5. Rollout runner and simulator backend (`rollout/`)

Where the program meets the perturbed world. Two layers:

- **Backend (ASPIRE `cap_harness` on LIBERO-Pro, or the mock world)** builds one episode. It resets the scene with the seed and applies the perturbation: moves the bowl, scales friction, spawns distractors, shifts the camera, dims the lights. It then hands over a robot object with the shared ASPIRE-style primitives (`localize_object`, `generate_grasps`, `select_grasp`, `move_to_pose`, `close_gripper`, `open_gripper`, `phase`). Each primitive logs events as it runs (`grasp_slip`, `collision`, `object_dropped`) and records the last step that completed.
- **Runner** executes System 1's code against that robot in a sandbox: only a whitelist of basic builtins, the robot as the only thing in scope, and a wall-clock timeout.
  - A crash in the generated code is an **error**, not a failure, so broken code never inflates the failure statistics.
  - A timeout is a **failure**.
  - Everything is packed into a rollout result: outcome, metrics (for example distance to target), event log, last phase, and video plus keyframes when recording.

### 6. Success branch

The outcome is added to the history. That raises the category's success count, so the selector becomes less interested in it next time.

### 7. Diagnoser (`diagnosis/`)

Turns a failure into understanding. The model reasons step by step (DELIBERATE effort) over the event log and metrics, where the program stopped, the program's code, and keyframes if any.

It returns structured JSON:

- one failure mode from a fixed list: missed object, grasp slip, collision, object dropped, timeout, wrong placement, program error;
- a one-sentence causal explanation tied to the code;
- a confidence;
- one instruction for the generator, such as "re-localise the bowl after a failed grasp".

A rule-based diagnoser reads the event log in parallel. If the model is unavailable or below the confidence floor, the rule answer is used, so every failure still gets a label.

### 8. Attack report

The only thing that leaves System 2 after a cycle. It holds the perturbation, the rollout result, the selector's draws (so a judge can see *why* this test was chosen) and, on failure, the diagnosis plus the constraint. The orchestrator forwards the constraint to System 1, which writes a new version, and the regression gate decides whether to keep it.

## Around the eight pieces

- **Model layer (`models/`).** One interface: "complete these messages with this effort level and this output format". The proposer uses PARALLEL effort and the diagnoser DELIBERATE. Adapters translate that for each vendor (Muse Spark's Thinking and Contemplating modes, any OpenAI-compatible endpoint, or the offline mock), which is why nothing in the planner or diagnoser names a model.
- **Shared contracts (`ants.contracts`).** The data shapes (program, perturbation, failure, constraint) and the robot primitives, owned jointly by both systems so System 1's generator and System 2 can't drift apart.
- **`Adversary` class (`adversary.py`).** The one entry point the orchestrator calls:

```python
adv = Adversary.from_config(AdversaryConfig(model="muse-spark", backend="libero"))
report = adv.attack(policy)  # one cycle -> AttackReport
results = adv.replay(policy, cases)  # re-run fixed cases: gate, acceptance, held-out
cases = adv.discovered_failures()  # the gate's growing test set
status = adv.status(policy)  # stop rule: .robust when every category is below τ
```

## Defaults

| Setting | Default | Meaning |
|---|---|---|
| `model` | `"mock"` | `"muse-spark"`, `"provider:model"` (OpenAI-compatible) or `"mock"` |
| `backend` | `"mock"` | `"libero"` or `"mock"` |
| `categories` | pose, physics, clutter, camera | selector arms (also: lighting, occlusion, actuation) |
| `rho` | 0.8 | severity bound ρ |
| `eta` | 0.2 | uniform exploration rate η (`1.0` = uniform baseline) |
| `n_agents` | 4 | parallel proposer agents |
| `tau` | 0.1 | target maximum failure rate per category τ |
| `stop_quantile` | 0.95 | posterior quantile used by the stop rule |
| `rollout_timeout_s` | 30 | per-rollout wall clock |
| `record_failures` | true | video and keyframes for multimodal diagnosis |

## What System 2 deliberately doesn't do

It never edits code, never accepts or rejects rewrites, and never decides to escalate. It only reports. That separation is what makes the regression gate trustworthy: the part that finds weaknesses has no say in whether a fix is accepted.
