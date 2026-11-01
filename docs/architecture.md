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
| `evalkit/` | Alfredo Wijaya | acceptance / held-out suites, metrics, run logs |
| observability | Alfredo Wijaya | read-only run report and replay viewer (System 2 tab); System 2 supplies per-step traces and the nominal run |

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

### Contracts (`src/ants/contracts/`, PR #3 with #4 merged into it)

`Policy`, `Perturbation`, `RolloutResult` + `Event`, `Failure`, `Constraint`, `AttackReport`,
`Feedback`, `Skill` + `SkillRef`, and the `RobotAPI` protocol, whose signatures mirror
`cap_harness` (`localize_object(query, *, camera_name, target_frame)`,
`generate_grasps(camera_name, mask, ...)`, `close_gripper(*, arm)` without force, results with
`ok` / `error`, quaternions in `wxyz`). Frozen dataclasses, JSON round-trippable, standard library
only.

Agreed with System 1 on 2026-11-01, arriving as follow-up contracts PRs (both approve):
- System 1: `DemoSpec`; `Policy.deterministic` and metadata (model, prompt hash, tokens); a case
  type that carries suite, task id, seed and the acceptance / held-out `split`; a free `details`
  mapping on rollout and feedback types; `Constraint.check_code` and optional `phase`;
  `Policy.params` with optional `attack_ranges` (which values the program assumed, over what range).
- Failure modes and categories become open strings with a recommended vocabulary
  (`program_error` is the one special value).
- One failure-signature helper in contracts, format `<category>:<failing primitive>:<status>`,
  e.g. `size:move_to_pose:timeout`. Stall counting, memory and escalation all key on it.
- `GateDecision` and `PolicyStage` (draft, attackable, incumbent, certified).
- Found by running the PR #5 policy offline: the robot API also needs `get_robot_state()` (base
  frame, end-effector poses, gripper positions), `get_task_context()` (language), and a
  `point_cloud` on `LocalizationResult`, which the policy reads to measure object sizes.

### System 1: synthesizer (Alfredo)

1. **Perception.** For the hackathon, DemoSpecs come from hurobo marker tracks (real phone clips)
   and from LIBERO human-demo files. SAM 3.1 hand and object tracking is a stretch goal; it is not
   in the pipeline yet.
2. **Demonstration abstraction z (DemoSpec).** Keyframes (approach, grasp, lift, transport,
   release, retreat), object tracks, object-frame end-effector paths, gripper aperture, step list,
   extraction quality scores.
3. **Program generation.** Muse Wonder writes a plain `cap_harness` script: API functions in scope,
   a top-level `result`. The backend also puts `params` (object-relative values from the DemoSpec)
   and `phase()` in scope. Context: task, z, API signatures, all active constraints, retrieved
   guidance skills.
4. **Static checks.** Pre-flight AST check: syntax, call whitelist, no imports except `math`.
5. **Nominal replay.** A develop-and-repair loop on the nominal seed, up to K attempts. Only a
   policy that passes is `attackable`; otherwise the run ends as `no_working_policy` and escalates.
6. **Entry point.** `synthesize(demo, constraints, skills, memory, *, task, incumbent=None) ->
   Policy`; a spent token budget raises `BudgetExceeded`, which the orchestrator maps to a budget
   stop. A deterministic mock `synthesize()` maps failure signatures to code patches for offline
   tests.

### System 2: adversary (Daniel)

Built on System 1's early System 2 v0 (branch `synthesizer`): its `cap_harness` rollout and
launcher become the LIBERO backend and its per-category rule diagnoser becomes the fallback.
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

- **Policy stages.** draft → attackable (passes its nominal cases) → incumbent (accepted by the
  gate) → certified (stop rule met). System 2 only attacks attackable or incumbent policies.
- **Regression gate.** One pure function in `orchestrator/gate.py`, starting from System 1's
  version. Replay candidate and current best on An = Pacc ∪ Fn. Accept only if the candidate is no
  worse on every case and better on at least one. It compares outcomes, not booleans: a crash on a
  case the incumbent passed is a regression, and an incumbent crash is not a pass. Its mode
  (`strict`, or `off` for the without-gate arm) is logged in every `GateDecision`.
- **Stop.** Two configurable modes. `posterior` (for reported numbers): every category's 0.95
  posterior quantile below τ = 0.1, which needs at least 28 clean rollouts per category (derived
  from Beta(1, n + 1)). `min_tests` (cheap, for demo runs under the token cap): every category
  tested at least k times with no failure. The mode is logged.
- **Escalation.** If the same failure signature stalls for W = 3 cycles (configurable, logged),
  ask a human for one demonstration targeted at that failure. Also when a draft never becomes
  attackable.
- **Skill admission.** After a gate pass, promote the skills the accepted policy used (or proposed)
  into the library and increment their help counts.
- **Split enforcement.** Only acceptance-set failures produce `Feedback`; held-out cases never reach
  System 1. A test asserts that a held-out case cannot produce `Feedback`.

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
model and mock world keep the loop testable offline. The Meta adapter (`adversary/models/meta.py`)
calls `https://api.meta.ai/v1/chat/completions` with `META_API_KEY`, caches every reply and logs
tokens to `data/llm_ledger.jsonl`, the same ledger System 1 uses, under a hard token budget. How the
API selects Muse Spark's Instant / Thinking / Contemplating modes is still to confirm with
`uv run python -m ants.adversary.models.probe`; until then PARALLEL is four independent calls.

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
| contracts | PR #3 with cap_harness signatures (#4) merged in; System 1 follow-up PRs agreed |
| adversary | `feature/system2`: full cycle offline (`Adversary.attack/replay/discovered_failures/status`) on System 1's launcher mapping, planner interface and rule diagnoser, with history, sandboxed runner and a mock world that runs the PR #5 v0 policy; cap_harness backend and model proposer/diagnoser next |
| synthesizer | branch `synthesizer`: Muse client with cache and token budget, prompt builder, develop-and-repair loop, DemoSpec converters, demo vs no-demo experiment with logged runs |
| orchestrator | System 1's experiment loop and gate on `synthesizer`; the shared gate moves to `orchestrator/gate.py` |
| evalkit, observability | System 1: run logging, report viewer with a System 2 tab, on `synthesizer` |
| LIBERO integration | runs on System 1's `cap_harness` checkout (RTX A5500), not in CI |

## Open decisions

1. **Primitive API: decided 2026-11-01, ASPIRE is the priority.** Programs call ASPIRE-style
   primitives (`localize_object`, `generate_grasps`, `select_grasp`, `move_to_pose`,
   `close_gripper`, `open_gripper`, plus our `phase`), as in contracts v0, and the execution
   substrate is ASPIRE `cap_harness` (LIBERO-Pro). The paper's four primitives (`locate`,
   `move_to`, `grasp`, `place`) and its v0/v4 listings need updating to match. Exact signatures are
   pinned against `cap_harness` in the contracts PR.
2. **Prototype numbers.** The paper reports offline results (adaptive 14.9 vs uniform 11.4 failures
   per 20 attacks; held-out 42% to 100%) and says the offline loop is covered by tests. No such loop
   or run log is in this repo. Per AGENTS.md, do not quote these numbers in repo docs until they are
   reproduced from a logged run here (or the source run is linked).
3. **Project name.** Paper: Adversarial Neuro-symbolic Task Synthesis. AGENTS.md: Agentic Task
   Synthesis.
4. **Gate strictness: decided 2026-11-01.** The paper's rule: no worse on every case and better on
   at least one. AGENTS.md, README and concept updated.
5. **Escalation window: decided 2026-11-01,** W = 3, configurable and logged. CaP-X stays the
   fallback harness if `cap_harness` blocks us.
6. **Hackathon scope (submission 2026-11-04): decided 2026-11-01.** The token cap (about $15,
   observed about $13.5 per million tokens) rules out the full ablation table. Log v0 without
   adversary, ANTS and no-demo first; add other arms only if budget remains. Demo runs use the
   `min_tests` stop mode.
