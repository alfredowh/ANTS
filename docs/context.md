# ANTS project context

Why ANTS exists, where it sits, what we have decided, and how we work. It complements
[`architecture.md`](architecture.md) (how the system works) and [`concept.md`](concept.md) (short
pitch). Source for sections 1 to 6: the paper draft *Show Once, Break Often: Robust Robot Skills
from a Single Demonstration* (Daniel Totolici, System 2 lead; Alfredo Wijaya, System 1 lead; Meta
Global AI Developer Hackathon 2026; `ants_full.pdf` on Google Drive). Numbers attributed to other
work are as cited in the paper, not checked by us.

## 1. Problem

Industrial robots are deployed one task at a time; a new part means new demonstrations and
retraining, days to weeks per task. Vision-language-action models (RT-2, OpenVLA) moved the
bottleneck rather than removing it: new tasks still need task data and fine-tuning, and policies are
brittle. Cited evidence: LIBERO-Plus reports success falling from about 95% to below 30% under mild
camera or initial-state changes; RoboGate reports a model at 97.65% on LIBERO and 0% on 68
industrial scenarios. A factory cannot certify a skill whose failure modes are unknown.

## 2. Idea

Separate two questions that current systems merge. *Can the robot do the task?* System 1 writes the
skill as a short program from one demonstration. *When does it fail, and why?* System 2 searches for
failures in simulation and turns each into a precise instruction for System 1. The program is the
unit of change: a failure becomes a line of code a person can read, not a gradient step.

Recipe and knife skills: the program decides *what*, in which order, and what if something goes
wrong; each primitive decides *how*, running perception and closed-loop control at 20 to 500 Hz
inside the call. Primitives are scripted controllers today and can become small learned policies
behind the same signature later.

## 3. Positioning and research gap

| Family | Skill is | Improves by | Auditable |
|---|---|---|---|
| VLA (RT-2, OpenVLA) | network weights | more data, fine-tuning | no |
| World-action models | learned dynamics + policy | more data | no |
| In-context imitation (Instant Policy, Machenta) | weights + demo as prompt | sim meta-training | no |
| Code as policy (Code as Policies, FAEA, RHO, ARCHITECT, ASPIRE) | program | fixed tests or human critic | yes |
| **ANTS** | program | **adversary + regression gate** | yes |

- **Code-generating robot agents** (RHO, ARCHITECT, FAEA, ASPIRE) refine code from feedback, but on
  fixed benchmarks or human corrections; none selects tests adversarially.
- **Failure discovery** (FATE-VLA, RoboGate) finds failures but never repairs the policy.
- **Failure explanation** (REFLECT, AHA) does not tie the explanation to a line of code or a fix.
- **Machenta** (closest commercial work): same story ("show it once, no retraining, simulation as
  the engine of scale"), opposite method: robustness from training-data diversity, black-box
  policy, real robots. We do not compete on instant learning; we compete on trust.

**The gap ANTS fills:** a closed loop in which an adaptive adversary's findings directly drive
auditable repairs under a no-regression guarantee.

## 4. Contributions (as the paper states them)

1. Two-system architecture for one-shot skill acquisition with adversarial validation,
   model-agnostic, mapped onto Meta's stack (SAM 3.1, Muse Wonder, Muse Spark).
2. Adaptive adversary: Thompson sampling over categories, model proposers, hard severity bound, and
   a regression gate that guarantees non-decreasing robustness without weight updates.
3. Read-only observability layer: plain-language failure explanations, replay linked to code and fix.
4. Research-gap analysis and commercial positioning as a test-and-repair layer for physical AI.
5. Worked end-to-end example and hackathon deliverable with an evaluation protocol.

## 5. Worked example (bowl on plate, Franka Panda, LIBERO)

v0 hard-codes what the demo showed: fixed bowl and plate poses, fixed grasp force, straight
approach, one look at the scene. It passes the nominal replay. The adversary then exposes one
assumption per accepted rewrite:

| Attack | Failure | Constraint | Version |
|---|---|---|---|
| physics: low friction, heavy bowl | grasp slip | scale grasp force with mass and friction | v1 |
| pose: bowl shifted | missed object | read poses from perception at run time | v2 |
| clutter: distractors on the path | collision | approach with obstacle clearance | v3 |
| camera: viewpoint shift | missed object | re-localise and retry after a failed grasp | v4 |

Every line added since v0 traces to one diagnosed failure, and every version passes all failures
found before it. That is the auditable property. (The paper's listings use its four-primitive API;
the code uses ASPIRE primitives, see decision D1.)

The paper also reports offline prototype numbers (adaptive vs uniform failures found; held-out
success before and after rewrites). **They are not reproduced in this repo yet; do not quote them in
repo docs or results until a logged run here produces them** (decision D4).

## 6. Product and limits

- **Customer:** manufacturers and integrators on high-mix, low-volume lines, whose blocking question
  is whether a skill keeps working when light, part batch or fixture changes, and whether they can
  prove it.
- **Product (Antagon):** record a demo; get a program, an adversarial test report, the failures found
  and fixed, and a replayable audit trail. System 2 alone can test black-box VLA policies (report
  only, no repair).
- **Moat:** failure-data flywheel (every attack, diagnosis and fix is a labelled record),
  auditability, model independence, memory and skills shared across tasks.
- **Main limits:** expressiveness capped by the primitives; depends on a frontier code model; gate
  cost grows with discovered failures; only the perturbation space we define is searched;
  diagnoser errors waste rewrites; sim-to-real gap; certification needs about 28 clean rollouts per
  category at τ = 0.1; one task and one robot do not show generality.
- **Future work:** learned primitives attacked individually; promoting recurring patterns into new
  primitives (our code skills are the first step); open-ended perturbation categories; cheaper
  gating by clustering failures; a diagnoser trained on our labelled failures; sim-to-real
  validation; multi-task memory; testing black-box policies.

## 7. Decisions log

| Id | Date | Decision |
|---|---|---|
| D1 | 2026-11-01 | ASPIRE is the priority: ASPIRE-style primitives in `contracts/`, `cap_harness` (LIBERO-Pro) as substrate, CaP-X as fallback. The paper's four-primitive API is to be revised. |
| D2 | 2026-11-01 | Skill library holds CODE and GUIDANCE skills only (no model-written prompts). System 1 retrieves and proposes; the orchestrator admits after a gate pass. |
| D3 | 2026-10-31 | Daniel owns System 2 and the orchestrator; Alfredo owns System 1. |
| D4 | 2026-11-01 | Paper prototype numbers are not quoted in the repo until reproduced from a logged run. |
| D5 | 2026-11-01 | Policies are plain `cap_harness` scripts (API functions in scope, top-level `result`); the backend provides `params` and `phase()`. Deterministic per seed. Replaces the earlier `run(robot, params)` shape. |
| D6 | 2026-10-29 | Module context lives in `docs/<module>/spec.md`, imported from the root `CLAUDE.md`. |
| D7 | 2026-11-01 | Contracts mirror the real `cap_harness` signatures (PR #4): `wxyz` quaternions, `ExecutionResult`, no grasp force. |
| D8 | 2026-11-01 | Failure modes and categories are open strings with a recommended vocabulary; one shared failure signature `<category>:<primitive>:<status>`. |
| D9 | 2026-11-01 | Gate: no worse on every case and better on at least one; compares outcomes; one function in `orchestrator/gate.py`; mode logged. |
| D10 | 2026-11-01 | Policy stages draft, attackable, incumbent, certified; System 2 only attacks attackable policies. |
| D11 | 2026-11-01 | Alfredo owns `evalkit/` and the replay viewer; System 2 supplies per-step traces and the nominal run. |
| D12 | 2026-11-01 | System 2 is built on System 1's v0 (rollout, launcher, rule diagnoser); no competing implementation. |
| D13 | 2026-11-01 | Escalation window W = 3. Hackathon scope: v0, ANTS and no-demo arms first; `min_tests` stop mode for demo runs. |
| D14 | 2026-11-01 | DemoSpecs come from hurobo markers and LIBERO demo files; SAM 3.1 tracking is a stretch goal. |
| D15 | 2026-11-01 | Deliverable: a 3 to 5 minute visual demo video showing explainability and Meta's models. Combined Meta credits: $270, enough for the paper's Muse Spark roles in System 2 (4 proposer agents, diagnoser, explainer), all sharing one token ledger with System 1. |
| D16 | 2026-11-01 | Follow the paper's plan with these deviations: ASPIRE primitives (paper text to be updated), SAM 3.1 as stretch, evaluation scaled to the simulator time available and stated as such. |
| D17 | 2026-11-03 | Daniel owns `orchestrator/` (confirms D3): the closed loop, gate and human gate ported from System 1's `harden()` live in `orchestrator/loop.py`, `gate.py`, `human_gate.py`. System 1 plugs in behind `Synthesizer.rewrite()`. |
| D18 | 2026-11-03 | Hackathon scope: no memory. Experience memory, the recovery-skill module and the deployment (fast) phase are concept slides, not code. |
| D19 | 2026-11-03 | Storyline: problem, show once, break it adaptively, explain and fix (including a fix the gate rejects), escalate, report (logged numbers only), vision (deployment phase, recovery skills, sim2real assumption stated). Built on Alfredo's two-phase framework (slow development loop, fast deployment loop). |

Still open (see `architecture.md`): project name (Alfredo proposes Agentic Task Synthesis
everywhere, paper to align), and the source of the paper's prototype numbers.

## 8. How we work

- Branches: `main` (milestones, PR from `integration` only) ← `integration` (both systems) ←
  `feature/system2` (Daniel), `synthesizer` (Alfredo), short branches such as `contracts/v0` for
  shared changes. Details in AGENTS.md, Git workflow.
- Contract changes go in their own PR and need both owners.
- Results in any write-up come from logged runs in this repo; acceptance and held-out sets stay
  separate in code and data paths.

When a decision is made or reversed, add a row to the decisions log and update the matching doc.
