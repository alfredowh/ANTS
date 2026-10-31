# ANTS architecture

Full-system context for anyone (human or agent) working in this repo. Source: the paper draft
*Show Once, Break Often: Robust Robot Skills from a Single Demonstration* (Totolici, Wijaya;
Meta Global AI Developer Hackathon 2026, `ants_full.pdf`), reconciled with the code. Where the paper
and the repo disagree, the conflict is listed under [Open decisions](#open-decisions) instead of
being silently resolved.

## One-line claim

One human demonstration becomes a robot program; an adaptive adversary breaks it in simulation;
every failure becomes a readable fix that a regression gate keeps only if nothing got worse. No
model weights are updated anywhere.

## Owners

| Package | Owner | Role |
|---|---|---|
| `contracts/` | both | every type that crosses a boundary, and the primitive API |
| `synthesizer/` | Alfredo Wijaya | System 1: video to program, experience memory, skill proposals |
| `adversary/` | Daniel Totolici | System 2: attack, diagnose, constrain |
| `orchestrator/` | Daniel Totolici | closed loop, regression gate, escalation, skill admission |
| `evalkit/` | open | acceptance / held-out suites, metrics, logs |
| observability | open | read-only replay and explanation UI over the logs |

Package specs: [`docs/adversary/spec.md`](adversary/spec.md). Others get a `docs/<module>/spec.md`
when work starts, imported from the root `CLAUDE.md`.

## The loop

```
 human demo V ──▶ SYSTEM 1 (synthesizer)                       SYSTEM 2 (adversary)
                  SAM 3.1 perception → DemoSpec z                failure history H
                  Muse Wonder writes run(robot)  ◀── context ──  Thompson selector over categories
                  static checks + nominal replay   constraints   M Muse Spark proposers (Contemplating)
                  experience memory + skill library    + skills  severity clamp s(p) ≤ ρ
                              │ Policy π                         sandboxed rollout in LIBERO
                              ▼                                  diagnoser (Muse Spark Thinking + rules)
                  ┌─────────── ORCHESTRATOR ───────────┐                 │ AttackReport
                  │ send π to System 2 ────────────────┼────────────────▶│
                  │ on failure: Feedback → System 1    │◀────────────────┘
                  │ regression gate on Pacc ∪ Fn       │
                  │ skill admission after gate pass    │
                  │ stop: max_c Q0.95(θc) < τ          │──▶ certified skill
                  │ escalate: W cycles stalled         │──▶ request one targeted demo V′
                  └────────────────────────────────────┘
                              │ traces of every cycle (read-only)
                              ▼
                  observability: failure explainer, replay timeline, version history, robustness board
```

Per cycle (paper Algorithm 1): select category → propose and clamp perturbation → roll out the
current best program → update that category's Beta posterior → on failure diagnose, add the case to
Fn, ask System 1 for a rewrite with the new constraint → gate → if accepted, adopt it, add the
constraint for good, reset posteriors → check stop rule → check escalation.

## Components

### Contracts (`src/ants/contracts/`, PR #3)

`Policy`, `Perturbation`, `RolloutResult` + `Event`, `Failure`, `Constraint`, `AttackReport`,
`Feedback`, `Skill` + `SkillRef`, and the `RobotAPI` protocol. Frozen dataclasses, JSON
round-trippable, standard library only. A `DemoSpec` type is still to be added by System 1.

### System 1: synthesizer (Alfredo)

1. **Perception.** SAM 3.1 segments hand and objects; hand keypoints give grasp moment and aperture.
2. **Demonstration abstraction z (DemoSpec).** Phases (approach, grasp, transport, place),
   landmarks (object and target centroids), gripper aperture.
3. **Program generation.** Muse Wonder (via Muse Code) writes `run(robot, params)` over the
   primitive API only. Context: task, z, API signatures, all active constraints, top-k retrieved
   programs and skills.
4. **Static checks.** Syntax and an API whitelist; any call outside the primitives is rejected.
5. **Nominal replay.** One unperturbed LIBERO run; on failure, regenerate with the error, so the
   adversary never attacks code that fails on its own.

### System 2: adversary (Daniel)

Spec and status: [`docs/adversary/spec.md`](adversary/spec.md),
[`src/ants/adversary/README.md`](../src/ants/adversary/README.md). Failure history, Thompson
category selector (η = 0.2), M = 4 proposers with novelty filter and uniform fallback, perturbation
space with severity cap ρ = 0.8 enforced in code, sandboxed rollout runner (crash = ERROR, never a
task failure), diagnoser (model plus rule fallback). It only reports: it never edits code, accepts
rewrites or escalates.

The runner must also record **per-step state traces** (phase, primitive calls, gripper aperture)
and the matching **nominal run**, because the observability replay marks where a perturbed run
first diverged from nominal.

### Orchestrator (Daniel)

- **Regression gate.** Replay candidate and current best on An = Pacc ∪ Fn. Accept only if the
  candidate is no worse on every case and better on at least one. Robustness is therefore monotone.
- **Stop.** Robust when every category's 0.95 posterior quantile is below τ = 0.1. With no
  failures this needs at least 28 clean rollouts per category (derived from Beta(1, n + 1)).
- **Escalation.** If no rewrite was accepted for W cycles while some category's mean failure rate is
  still ≥ τ, ask a human for one demonstration targeted at the diagnosed failure.
- **Skill admission.** After a gate pass, promote the skills the accepted policy used (or proposed)
  into the library and increment their help counts.
- **Split enforcement.** Only acceptance-set failures produce `Feedback`; held-out cases never reach
  System 1.

### Skill library (System 1 retrieves and proposes, orchestrator admits)

Two kinds, one library:

- **CODE skill:** a verified function over primitives, e.g. `grasp_with_retry`. Inlined into the
  policy's code, so the policy stays one self-contained, sandboxable, replayable program.
- **GUIDANCE skill:** a rule the generator reads, e.g. "re-localise after a missed grasp". Verified
  constraints graduate into guidance skills.

Rules: admitted only through the gate; versioned (`SkillRef`); retrieved by similarity weighted by
help count with decay (the paper's "pheromone"); learned only from acceptance-set failures; a
`Constraint` can blame a skill (`target = skill`), so one fix reaches every policy using it. The
library is an ablation arm in evaluation. Agent-level skills (the model writing its own prompts) are
out of scope for now.

### Observability (read-only)

Failure explainer (Muse Spark Instant, plain language), replay timeline (video, phases, primitive
calls, aperture actual vs nominal, markers for perturbation, divergence and failure), version
history (diffs, gate verdicts, motivating constraint), robustness board (per-category posteriors and
stop criterion), skill library view, data view. It never influences decisions.

## Models

| Stage | Role | Model (mode) |
|---|---|---|
| Perception | hand and object masks | SAM 3.1 |
| Synthesis | write and rewrite programs, propose skills | Muse Wonder (via Muse Code) |
| Proposal | M parallel attack agents | Muse Spark (Contemplating) |
| Diagnosis | mode, cause, constraint | Muse Spark (Thinking) |
| Explanation | plain-language failure report | Muse Spark (Instant) |

All model access goes through adapters (`FAST`, `DELIBERATE`, `PARALLEL` effort levels); a mock
model and mock world keep the loop testable offline.

## Evaluation protocol (paper, Section IX)

- Hypotheses: H1a adaptive selection finds more failures per rollout than uniform; H1b adversarial
  feedback raises held-out robustness with weights frozen; H2 synthesis needs fewer demonstrations
  than imitation fine-tuning.
- |Pacc| = 30 acceptance cases (gate only), |Ptest| = 50 held-out cases (reporting only, different
  seeds), N = 20 cycles, M = 4, η = 0.2, ρ = 0.8, τ = 0.1, five seeds. Uniform baseline: η = 1.
- Arms: v0 without adversary; uniform testing plus repair; ANTS; ANTS without gate; ANTS without
  memory; ANTS without skill library.
- Logged per cycle: tokens, simulator time, every decision with its inputs.

## Hackathon deliverable

One closed loop on bowl-on-plate (Franka Panda, LIBERO) from our recorded demonstration, shown in
five steps: show once (v0 succeeds nominally), break it, explain and fix (timeline, diff, gate
accepts), escalate (deliberately unfixable perturbation), report (held-out v0 vs final, adaptive vs
uniform, cost per cycle).

## Status (repo, not paper)

| Piece | State |
|---|---|
| contracts | draft in PR #3, skills included; awaiting System 1 review |
| adversary | model layer, perturbation space, category selector done; proposer, runner, mock world, diagnoser, history, facade not started |
| synthesizer | discussion doc on branch `synthesizer`; no code |
| orchestrator, evalkit, observability | not started |
| LIBERO integration | demo replay on a simulated Franka exists on System 1's side (paper Fig. 5), not in this repo |

## Open decisions

1. **Primitive API.** The paper defines four primitives: `locate(name) → pose`,
   `move_to(pose, clearance)`, `grasp(width, force) → bool`, `place(pose)`. Contracts v0 follows
   ASPIRE names from `docs/synthesizer/discussion.md` (`localize_object`, `generate_grasps`,
   `select_grasp`, `move_to_pose`, `close_gripper`, `open_gripper`). Pick one before the runner and
   backend are built.
2. **Prototype numbers.** The paper reports offline results (adaptive 14.9 vs uniform 11.4 failures
   per 20 attacks; held-out 42% to 100%) and says the offline loop is covered by tests. No such loop
   or run log is in this repo. Per AGENTS.md, do not quote these numbers in repo docs until they are
   reproduced from a logged run here (or the source run is linked).
3. **Project name.** Paper: Adversarial Neuro-symbolic Task Synthesis. AGENTS.md: Agentic Task
   Synthesis.
4. **Gate strictness.** Paper: no worse on every case *and better on at least one*. AGENTS.md: at
   least as good on every case. The strict version can reject a rewrite that only adds a skill.
5. **Escalation window W** and the harness (ASPIRE `cap_harness` vs CaP-X) are not fixed yet.
