# Memory and cache for ANTS: synthesis

Status: synthesis of six research reports, 2026-11-01. Nothing here is decided and nothing is built. Every number is quoted from a paper or from our own logs, with the report it came from. Where a recommendation has no support in the literature it says "guess".

**Next:** options, integration steps and experiments are in [memory-integration-plan.md](memory-integration-plan.md).

**Reports this note combines** (all in [research/](research/)):

| Tag | Report | Question |
|---|---|---|
| [R1] | [../dev/instant-learning.md](../dev/instant-learning.md) | Machenta and the Imperial line vs ANTS |
| [R2] | [research/imperial-stack-fit.md](research/imperial-stack-fit.md) | Can those works improve our stack? |
| [R3] | [research/memory-audit-codebase.md](research/memory-audit-codebase.md) | Where memory and cache fit in our code |
| [R4] | [research/memory-skill-libraries-llm-agents.md](research/memory-skill-libraries-llm-agents.md) | What the skill-library literature shows |
| [R5] | [research/memory-correction-and-failure-libraries.md](research/memory-correction-and-failure-libraries.md) | Correction and failure libraries |
| [R6] | [research/memory-management-and-caching.md](research/memory-management-and-caching.md) | Lifecycle, rankers, cache engineering |
| [R7] | [research/memory-radar-shortlist.md](research/memory-radar-shortlist.md) | Radar mined for memory works: family map, 25-paper deep-read list, 53 paste-ready radar additions, 12 data issues |

---

## 1. The answer in ten lines

1. **The Imperial works do not improve System 1 or System 2 directly.** None of the code is runnable in our stack as an arm: SynthICL is training-only (Apache-2.0), Instant-Fold is a cloth-folding model with a 60.9% real result, Instant Policy is noncommercial with a compiled model, MT3 needs Docker and CUDA 11.8 [R2]. Their value is design: MT3's retrieval, SynthICL's keyframe rule, Skild's "execution-strategy shift" perturbation.
2. **The best memory module to build first is the correction library**, because a correction is data `harden` already holds at `system2.py:126-159` [R3]. It needs a record written at gate acceptance and a read path into the `constraints=` slot.
3. **Admit only what the gate accepts.** Execution-grounded admission is the only rule with consistent gains in the literature; self-generated, unverified skills show none [R4, R6].
4. **Retrieve 1 to 3 records, not all of them.** ReasoningBank: no memory 39.0, k=1 49.7, k=4 44.4 [R4, R6]. Sentry: removing failure lessons from context raised held-out reward from 0.335 to 0.391 [R5]. Our `harden` currently passes every constraint every cycle [R3].
5. **Key failures by what the trace shows, not by the attack label.** `diagnoser.py` keys the signature on the perturbation category, which does not exist at deployment [R5].
6. **Cache the cheap deterministic things first.** Rollouts are byte-identical in 63 of 65 repeat groups, so a content-addressed rollout cache is safe on one machine and saves about 30 s per hit [R3, R6].
7. **Held-out separation must be enforced in the store, not by convention.** Seeds alone are not enough, because ASPIRE's saved mode wraps seeds at 50 [R3].
8. **Memory can hurt a strong generator.** REM: -2 to -9 points above 47% unaided [R4]. We must report memory-off for Muse.
9. **Three of our own design claims have no precedent**: reinforce-on-contribution credit, re-verify at retrieval, strict per-case non-regression. That makes the ablation a contribution, and also means the defaults are guesses [R4, R6].
10. **Money first:** the ledger holds 2.75M paid tokens, about $37 at $13.5 per M, against a $15 cap [R6]. Please check the dashboard before more runs.

---

## 2. Can the Imperial works improve our stack?

Per work, per ANTS module. "Covered" means ANTS already does it by another route.

| Work | Perception / DemoSpec | Synthesis | Memory / retrieval | Gate / System 2 | Verdict |
|---|---|---|---|---|---|
| **MT3** (MIT) | covered (hurobo) | conflicts (replay, no code) | **improves**: language schema first, then 512-d geometry cosine, single best demo | n/a | **Use the design**; reimplement retarget-replay over ASPIRE primitives (about 100-200 lines); do not install |
| **SynthICL** (Apache-2.0, training only) | **improves**: keyframe rule (first frame, gripper-state changes, low-velocity frames, at most 6) | conflicts (needs training) | demo-conditioning is a context cache, nothing to borrow in code | use demo keyframes as visual checkpoints for the diagnoser | **Ideas only**; not a runnable arm |
| **Instant Policy** (PolyForm NC) | needs segmented point clouds | conflicts | n/a | stochastic: gate needs replicates | **Later, large**; offline baseline only; conda under a uv-only rule |
| **Instant-Fold** (MIT) | n/a | n/a | n/a | n/a | **Never**: cloth only; real 39/64 = 60.9% (Wilson 48.7-71.9) |
| **IGA** (MIT) | n/a | possible `place_relative` primitive | n/a | n/a | **Never now**: 15 s inference, rigid grasp, three depth cameras |
| Rhoda, Generalist, Skild | n/a | n/a | n/a | Skild's execution-strategy shift is a new perturbation category | **Cite only** |

Source: [R2] with [R1]. Two leads that may be closer to ANTS than the Imperial line, read as abstracts only: **JEDI** (LIBERO, demo bank) and **SAIL** (archive of successful trajectories).

**What ANTS covers that they do not:** adversary-chosen tests, a never-regress gate, readable constraints, escalation chosen from a failure signature [R1]. **What they cover that ANTS does not:** closed-loop reactive control, learning from a demo given in the cell. **What conflicts:** the licence (Instant Policy vs the paper's commercial layer), the uv-only rule (conda and Docker repos), and the stochastic-policy gate [R2].

---

## 3. Where memory and cache fit in our pipeline

Phases from [R3]; the right-hand columns combine [R3], [R5], [R6].

| Phase | Today | Memory / cache candidate | Key | Worth |
|---|---|---|---|---|
| P0 demo ingestion | DemoSpec json in `data/demospecs/` | **demo store** | `demo_sha` = clip bytes + marker size + extractor version | S |
| P1 synthesis | Muse call cache (`llm.py:67-82`), key = model + messages + temperature | harden the call cache; **correction retrieval** into `constraints=`; skill retrieval (research tier) | add `sample_index`; stable prefix, memory last | S / M |
| P2 plan gate, nominal replay | none | cache AST verdicts | program hash | S |
| P3 test planning | Thompson posteriors reset per acceptance | **failure / case corpus** as warm start | `case_key` | S-M |
| P4 rollout | no cache; stale-`outcome.json` bug in `CapHarness.run` | **rollout store** | policy sha + case + scene + run params + harness fingerprint | M |
| P5 diagnosis | category-keyed signature | trace-keyed `FailureSignature`, three levels | phase + primitive + status (+ bucketed deviation, object role) | S |
| P6 constraint formation | `c%03d` ids collide across runs | global ids | hash(signature features + rule) | S |
| P7 regression gate | missing result counts as a failure | rerun on cache miss; replay failing cases first, never shrink | one harness fingerprint per comparison | S |
| P8 stop / escalate | K stalled cycles on one signature | escalation memory, human-demo store | signature level 2 | M |
| P9 deployment | not built | situational corrections as `check_code` + recovery, `MonitoredProgramRunner` | signature features + precondition | L |
| P10 reporting | `report.py` | `memory_sha`, retrieved entries, fingerprint in events | n/a | S |

**Must not be cached or remembered** [R3]: held-out outcomes or seeds; success predicates; non-deterministic rollouts; anything with a key or token; a deployment self-report as evidence.

---

## 4. The correction behavior library

### 4.1 What it is

A correction is a gate-verified repair for one failure signature. A constraint without an accepted repair is only a hypothesis [R3]. It joins: the `Constraint`, the repair diff, the failure signature, the triggering case, evidence run ids, the gate verdict and an absorption status.

Three levels, from the repair literature [R5]:

```
symptom (observable)  ->  mechanism (validated cause)  ->  fix
(lift, close_gripper,     stale_pose | slip |              re-localize before approach |
 closed_on_empty)         width_mismatch                   lift-and-check | measure radius
```

Retrieve by symptom (the only thing visible at run time), store fixes by mechanism, keep the symptom-to-mechanism link an explicit, tested edge.

### 4.2 Records (proposal)

- **`FailureSignature`** (frozen): `phase`, `primitive`, `status`, bucketed `deviation`, `object_role`, with `key(level)` for L1 `phase|status`, L2 `+primitive`, L3 `+deviation+object_role`. Dedup uses L3, retrieval uses L2 then L1, the K=3 escalation counter uses L2 [R5].
- **`FailureCase`** (corpus entry): `CaseSpec`, harness version, outcome kind (task_fail, timeout, unsafe, program_error), signature, `boundary` (smallest failing and largest passing severity), feasibility result, determinism replay count, sampling probability of the adaptive draw, `origin` (never held-out) [R5].
- **`Correction`**: constraint, repair kind, trigger case key, parent and repaired policy ids, diff, optional rationale, optional recovery code, tested envelope, typed `Evidence` list (each with `split`; writers reject held-out), `GateVerdict`, status, `help_count`, `hurt_count`, logical-clock epochs [R3]. The full dataclass diff is in R3 §3.3; it is a proposal and `types.py` needs agreement with the System 2 owner before any edit.
- **Rejected attempts** go to a separate append-only log. They are never positive advice, but may be shown as "tried and failed on this class" [R5].

Lifecycle: `proposed -> admitted (gate accepted a candidate that had it in the prompt and fixed the trigger case) -> verified (replay on evidence cases plus fresh neighbours) -> absorbed into a Skill -> deprecated` [R3, R5].

### 4.3 Retrieval

1. Hard filters: status, scope, `precondition` true now, harness-compatible, `split == acceptance`, not deprecated [R3].
2. Signature level 3, then 2, then 1, until at least one candidate; diversity across mechanisms [R5].
3. Rank by relevance times a lower bound of the help rate times a time decay. Three rankers to compare [R6]:
   - **F1 pheromone** (the paper's N13): `sim x (eps + tau)^a`, with `tau` a sum of decayed help events minus `beta` times decayed hurt events. No direct precedent.
   - **F2** recency, importance, relevance (Generative Agents), with importance defined deterministically as the number of failing cases a candidate flipped.
   - **F3** ACT-R activation `ln sum (e - e_j + 1)^-d + w_s sim`.
4. Cap at k = 1 to 3 (Sentry's best was 5; Memento plateaus at 4) and put memory last in the user message so the 5-6k-token stable prefix stays identical [R3, R5, R6].
5. Record `memory_sha`, the query, the ranked list and the entries injected, on the `Policy` [R3, R6].

Below about 50 records, flat signature matching is enough; add embeddings later. The claim that flat retrieval degrades at 64-128 skills is unverified [R4].

### 4.4 Validation on reuse and run-time recovery

Order (each stage logged, each can reject) [R5]: precondition, evidence-case replay, fresh-neighbour replay (rejects one-seed fixes), per-case gate, seed-literal lint. The simulator also allows **diagnosis by intervention**: remove the perturbation, restore one parameter at a time, use privileged state in place of a perceived pose, run a scripted oracle. No surveyed system does this [R5].

Run time: programs have no model in the loop, so recovery must be deterministic code. Absorbed corrections are already inside the saved program. Situational ones stay as `check_code` plus allow-listed `recovery_code` in a `MonitoredProgramRunner`, capped at K attempts, then stop safely or escalate. A field recovery creates a `proposed` correction only; it becomes `admitted` after a simulator replay and the gate. A deployment self-report must never raise `help_count` [R3]. Use structured state for checks, not VLM judges (FailBench: near chance on contact tasks) [R5].

---

## 5. How the memory is managed

From [R6], with the audit's clock rule [R3].

**Logical clock.** All decay and ageing use an epoch counter (one tick per gate decision, persisted in the store), never wall time, so retrieval is a pure function of snapshot and query and logged runs reproduce.

**Six stores:**

| # | Store | Write rule | Forget rule |
|---|---|---|---|
| R1 | Demo store | at extraction, immutable | never auto-deleted |
| R2 | Policy / skill store | only when the gate accepts a candidate on the acceptance set; `verified` after a fresh replay | deprecate on failed re-verification or low utility, never the only entry covering a case |
| R3 | Correction store | gate acceptance after a candidate had the constraint in its prompt | same, plus soft-stale on generator change |
| R4 | Failure / case corpus | every completed non-infrastructure rollout, acceptance split only | not forgotten in a lineage (the gate needs a monotone set); `needs_rerun` on fingerprint change |
| R5 | Posteriors and per-entry statistics | each gate decision | snapshots per epoch |
| R6 | Caches (LLM call, rollout, extraction, AST, diagnoser) | on completion of a non-error result | size quota (LRU) only, never by relevance |

**Forgetting.** Retrieval priority fades through `tau`. Removal from the retrievable set is more conservative: deprecate if not pivotal and (many retrievals with low utility, or fade below a threshold after a grace period, or failed re-verification). `pivotal` means removing it shrinks the set of cases covered by verified entries of the same scope. Evidence: outcome-driven retirement with a cap of 50 gained +0.33 pass@1, but harsh early retirement emptied the bank and fell below the no-skill floor [R4, R6].

**Staleness.** Stored programs depend on the harness and assets, not on the generator model. A harness or allow-list change is a hard invalidation (plan gate, then evidence replay); a model change is soft; elapsed time never invalidates a deterministic artefact. Re-verification costs about 30 s per rollout and no tokens: five evidence cases take about 2.5 minutes [R6].

**Conflicts and merges.** Do not use an LLM to resolve them (at most 28% on multi-hop forgetting in MemoryAgentBench). Use deterministic scope, version and evidence rules; mark overlapping contradictory rules as a conflict set; a merge is admitted only if the merged entry passes the union of both evidence sets [R6].

**Audit and integrity.** One append-only `memory_events.jsonl` plus SQLite as queryable state; `memory_sha` per run; typed records and templated rules (MINJA defeats embedding sanitisation and cheap prompt detection); signing only when memory is shared [R6].

**Cache engineering.** Hermetic content-addressed keys, not a semantic cache. Rollout key: policy bytes, `CaseSpec`, scene spec, `max_steps`, camera size, `init_mode`, ASPIRE git and dirty-diff hash, launcher hash, dependency-lock hash. Provider prompt caching is worth at most about 10% of cost: 54% of paid tokens are completion and about 71.5% of that is reasoning. The exact call cache already avoided 568k tokens [R3, R6].

---

## 6. Conflicts between the reports and our docs

| # | Conflict | Decide |
|---|---|---|
| K1 | `harden` passes **all** constraints every cycle; Sentry and ReasoningBank argue for k <= 5 matched records | Keep all-in-context as one ablation arm; make retrieved k the default once there are more than about 5 constraints |
| K2 | Signature keyed by perturbation category (test side) vs trace observables | Replace with `signature_from_trace`, keep `Constraint.failure_signature = key(2)` |
| K3 | Strict per-case gate vs noisy rollouts (nearly half of disagreeing pairs failed to reproduce in a 123-round robot study) | Programs are deterministic per seed (63/65), so keep strict; add replicates only for any neural arm; measure cross-machine determinism |
| K4 | "Nothing is trained" vs a pheromone ranker with tuned parameters | Parameters are guesses; the offline retrieval benchmark on cached logs finds them without new rollouts |
| K5 | `Skill.last_used` is a wall-clock string | Use the epoch counter |
| K6 | `data/` is git-ignored, so memory cannot be shared by commit | Runtime stores in `data/`; a small curated `memory/corrections.jsonl` committed for the demo |
| K7 | Docs claim SkillForge replay-verifies and Skill-V gates per case | Both are wrong: SkillForge is RL-trained and does not replay-verify; Skill-V is RL-based with a rubric-outcome gate [R4]. Fix `skills.md` |
| K8 | Budget: ledger about $37 vs $15 cap | Check the dashboard |
| K9 | exp01 / exp02 "not reproduced" claims share the cached first program | Restate as "same first program, different repairs" until independent samples exist [R3] |

---

## 7. Build order

Hackathon tier (deadline 2026-11-04), from [R3] and [R5]. Do not start embeddings, skill extraction, planner warm start, run-time monitors or prefix caching in this tier.

| Order | Item | Effort |
|---|---|---|
| H1 | Harden `ChatClient`: `sample_index`, atomic write, miss on corrupt, prompt hashes and response model in the ledger | S, 3-4 h |
| H2 | `RolloutStore` plus fixed `CapHarness.run` (return code, timeout, fresh `output_root`), `run_case` wrapped in the real `harden` | M, 6-8 h |
| H3 | `Correction` JSONL v0 written at gate acceptance; render into `constraints=`; retrieval = exact task text + signature features | S-M, 4-6 h |
| H4 | `signature_from_trace` with phase and blocker features | S, 2-3 h |
| H5 | Persist the failure / case corpus (acceptance only) | S, 2 h |
| H6 | DemoSpec hash and extraction parameters | S, 1-2 h |
| H7 | Log fields: `config_sha`, fingerprint, `memory_sha` | S, 1-2 h |

Research tier: skill library with verifier admission, embedding retrieval, leave-one-out credit assignment, planner warm start from the corpus (measured against cold start first), `MonitoredProgramRunner`, autonomous-mode write-back, in-cell teleop demo store, trajectory-prefix caching, cross-machine determinism study, conformal staleness check.

**Smallest ablation that is powered at our budget:** only about 4 to 11 end-to-end runs are affordable at $15 [R6]. Run the case-level paired comparison (memory off, all constraints, retrieved k) on cached logs, report Wilson intervals over cases, and compare rankers offline [R6]. A mock-backend A1 vs A2 retrieval test with a placebo library comes before any LIBERO run [R5].

---

## 8. Decisions that need you

1. **Hackathon memory content (paper C11).** Seed corrections from a first hardening run on T0 and retrieve them on a second seed set or task, or mark the memory ablation "future". Default: seed and retrieve.
2. **Contracts.** May `types.py` take `Correction`, `Evidence`, `GateVerdict` and the extra `Constraint`, `Policy`, `Skill` fields (all defaulted, shared with the System 2 owner)?
3. **Determinism.** May I spend about 10 rollouts on a canary study before the gate relies on the rollout cache?
4. **Store location.** Runtime in `data/`, a small committed `memory/corrections.jsonl` for the demo?
5. **Credit assignment.** Accept "all constraints in the accepted prompt that fixed the trigger case get credit" for now, leave-one-out later?
6. **Rule source.** Keep the deterministic `RULES` templates as rule text, or let Muse Spark write rules? It changes dedup, cost and the key.
7. **Embedding dependency.** Approve DINOv3 or SAM 3.1 features for the research tier?
8. **Licence.** Instant Policy as an offline baseline only, never in a product path?
9. **Muse price or spend** (to-do #8), since it decides whether prompt ordering matters.

## 9. Unsettled

Cross-machine determinism; whether `harden` works with real rollouts (it was only run on a mock); Meta's prompt-cache TTL, minimum length and price; credit assignment for prompt-composed memory (no paper solves it); all decay rates, k and thresholds (tagged guesses). Most 2026 papers cited by the reports were read as abstracts or summaries and are the authors' claims, on text or code benchmarks with few seeds, not on robots.

---

## 10. Radar findings that change the pitch or the plan [R7]

Abstract-level evidence only; no paper was read in full.

1. **A 2026 cluster makes ANTS's first half.** Robot skill memory that is weights-free and built from few demonstrations: **Teach and Grow** (2608.17209, "training-free few demos to skills"), **RPG** (2610.02204, weights-free skill refinement with simulator practice), **RoboSkill** (2609.37810), **RACaP** (2609.29394, frozen typed APIs plus experience memory), **SEAR** (2610.18792, a "learning or trying more?" benchmark) and **ENPIRE**. They have almost no citations yet, so they are not in anyone's related-work list, but they are the closest peers for a memory claim. Read them before the pitch (T1 in the deep-read list), as with RAPID, and restate the delta against them.
2. **The ANTS gate has a published relative: GRASP (2605.29668).** It admits a skill edit only if it nets an improvement on a balanced held-out probe under a hard regression budget, in a bounded library. It is in neither the radar nor our docs. With Skill-V, SkillCommit and Library Drift it forms a 2026 governance cluster, all with 0 to 19 citations.
3. **The established lineage for similarity x help x decay is not robotics:** Generative Agents (6293 citations), MemoryBank (854), ExpeL (1239), Prioritized Experience Replay (4769). Cite these for the pheromone ranker.
4. **Caching has no robot-specific literature.** Rollout caching is an engineering result for us (63 of 65 identical repeats), not a literature item. Agent-level caches: Agentic Plan Caching (2506.14852), AgentRR, "Don't Break the Cache".
5. **The radar is thin where memory needs it:** of 287 works only Reflexion is a text-agent experience-memory paper, with 0 caching and 0 test-selection papers. 53 additions are ready to paste (`status: queued`, for the radar skill's sync mode to verify).
6. **Radar data issues** (nothing was fixed): LeRobot's id 2506.01844 is actually SmolVLA (the LeRobot paper is 2602.22818); N2M2's id resolves to an unrelated statistics paper; FIPER has no arXiv id (it is 2510.09459); ASPIRE and BPP were retitled on arXiv; `memory-skills` is mis-tagged on ANYmal Parkour, DINOv3, V-JEPA 2, LeRobot and Open X-Embodiment.
7. **Deep-read first (P1, before 2026-11-04):** GRASP, Skill-V, ACE, ReasoningBank, Memp, ExpeL, Rainbow Teaming (an archive design for the failure history), SEAR, Teach and Grow, RPG, Agentic Plan Caching. The sibling note also asks to verify the Skill-V numbers (71.9 / 89.1 / 95.3) before they appear in any write-up.
