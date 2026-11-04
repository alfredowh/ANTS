# Skills: definition, storage and autonomous mode

Status: proposal, 2026-10-31, for review (see ../todo.md, item "Skills definition"). Nothing is built yet. Sources for the parts borrowed: ASPIRE skill entries (Trigger / Code / Evidence / Limits, runnable precondition, verifier admission), Voyager and CaP-X skill libraries (functions extracted from successful code), RAPID (per-phase success predicates), Skill-V (admission without regression), SkillForge (re-verification before reuse). See [aspire-assessment.md](aspire-assessment.md).

## 1. What a skill is

**A skill is a reusable, verified unit of robot behaviour, stored as code plus the facts needed to decide when it applies and how far it can be trusted.**

The levels, from small to large:

| Level | What it is | Who makes it | Example |
|---|---|---|---|
| **Primitive** | One atomic action or perception call, given by the harness | the harness (ASPIRE API) | `localize_object`, `move_to_pose`, `close_gripper` |
| **Skill** | A composition of primitives (or of other skills) with its own checks and recovery; reusable across tasks | the generator, admitted only after verification | `grasp_bowl_by_rim(bowl)`, `place_centered_on(obj, target)` |
| **Policy (program)** | The task-level program for one task, composed of skills and primitives | the generator, accepted by the regression gate | `put_bowl_on_plate(api, spec)` |
| **Constraint** | A rule learned from one failure; it is either absorbed into a skill or stays as a rule in the generator's context | System 2 (diagnoser) | "re-localise the bowl after the approach" |

A stored skill has six parts:

1. **Interface:** name, inputs (object roles and parameters), typed result with a status, and the effect it promises as a **success predicate** that can be checked (RAPID).
2. **Applicability:** when to use it, preferably as a **runnable precondition** over observations (ASPIRE: "a precondition is code or it is nothing"), plus a text description for retrieval.
3. **Body:** the code, using only allow-listed primitives and skills, with its internal checks and retries.
4. **Validated envelope:** the range of conditions it was tested under. Examples: object diameter 10–15 cm, friction ×0.5–1.5, pose ±5 cm, light levels. It comes from the adversary's cases, so it says where the skill is known to work and where it has never been tested.
5. **Evidence and provenance:** source demo, the cases it passed and failed (run ids), the constraints it embodies, generator model and version, date, cost to create.
6. **Lifecycle:** version and parent, status (`candidate`, `verified`, `deprecated`), help count, last use, decay.

## 2. Operations on the skill store

| Operation | When | Rule |
|---|---|---|
| **Retrieve** | before writing a program | rank by similarity (task text, scene and object features) × help count; keep only skills whose precondition holds now |
| **Reuse** | the situation is inside the validated envelope | call it as is |
| **Modify (new version)** | it almost fits, or a new failure is inside its scope | the new version must pass **every case the old version passed** (the regression gate applied to skills, as in Skill-V), plus the new case |
| **Extend (new skill)** | the situation is outside its scope: the precondition fails or the envelope is exceeded | create a new skill; record its relation to the old one ("specialises", "replaces for heavy objects") |
| **Re-verify** | on retrieval after a long time, or after the harness or model changes | replay its evidence cases first (SkillForge); a failure lowers its status |
| **Deprecate** | unused for a long time, or failing re-verification | keep it for audit, exclude it from retrieval |

## 3. Autonomous mode (deployment side)

The user's idea, written down. When a deployed skill meets an edge case it cannot handle, and no stored skill covers it, the system may switch to **autonomous mode**:

1. **Ask first.** The operator approves autonomous mode for this case, with an **effort level** and a **budget** (model calls, tokens, €, wall time, number of physical or simulated attempts).
2. **Search for a strategy.** A CaP-Agent0-style loop at test time: the model writes code, sees the result as text (stdout, typed statuses, a text description of visual change), regenerates or finishes. The effort level sets the number of samples, turns and the model.
3. **Optionally harden.** Before saving, the adversary perturbs the scenario within its severity bound to check that the new strategy is not a lucky one-off.
4. **Save informatively.** On success, save the whole scenario (the scene and conditions that triggered it), the program, the run trace, the hardening results, and the cost. Then either **modify** the closest skill (new version, no regression) or **add** a new skill if the case is outside the old skill's scope (section 2).
5. **Reuse.** If the same case happens again, the skill is retrieved directly. If something *similar* happens, retrieval surfaces it as a starting point for the generator.

**Open points:**
- Safety: on a real robot, autonomous attempts need a safe envelope (speed limits, workspace bounds, human stop).
- A strategy found from one scenario can overfit, which is why step 3 and the validated envelope exist.
- Budget defaults per effort level are not set yet.
- Verifier admission: should a fresh agent reproduce the fix from the stored text alone, as in ASPIRE, before the skill counts as `verified`?
