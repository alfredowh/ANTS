# Cache and memory: options, recommendation, integration steps and experiments

Status: plan, 2026-11-01. Nothing here is decided or built. It extends [memory-and-cache.md](memory-and-cache.md) (the synthesis) and uses the six reports in [research/](research/). Every number is quoted from our logs or from a report, with its tag. A number marked **guess** has no source.

Tags: [R3] [memory-audit-codebase](research/memory-audit-codebase.md), [R4] [skill libraries](research/memory-skill-libraries-llm-agents.md), [R5] [correction libraries](research/memory-correction-and-failure-libraries.md), [R6] [memory management and caching](research/memory-management-and-caching.md), [R7] [radar shortlist](research/memory-radar-shortlist.md), [code] read in `src/ants` on 2026-11-01.

---

## 0. Plain definitions

| Term | Meaning here | Test |
|---|---|---|
| **Cache** | Stores the result of a computation so that it is not repeated. Never changes a decision. | Delete it and every result is the same, only slower and more expensive |
| **Memory** | Stores knowledge that changes a future decision (what the generator is told, what the planner attacks, what the gate replays) | Delete it and behaviour changes |
| **Correction** | A constraint plus the accepted fix, the failure signature, the triggering case, the evidence and the gate verdict | A constraint without an accepted fix is only a hypothesis |
| **Skill** | A reusable program unit with a precondition, tested envelope and version | A correction can be absorbed into a skill |
| **Epoch** | One tick of the memory clock per gate decision. Decay uses epochs, not wall time, so a logged run can be replayed | |
| **Fingerprint** | A hash of everything outside the program that can change a rollout (harness commit, launcher, assets, versions) | Two results are comparable only under one fingerprint |

Everything below keeps the repo rules: nothing is trained, acceptance and held-out stay separate, every gate decision is logged, and no dependency is added without asking.

---

## 1. Where it plugs into the architecture

The loop today ([code] `orchestrator/system2.py`): `harden(incumbent, cfg, run_case, generate, log, ask_human)` takes the simulator and the generator as callables. That gives four clean seams without rewriting the loop.

```
                        ┌──────────────── orchestrator.harden ─────────────────┐
 DemoSpec ──► generate ─┤ 1 planner.propose ─► 2 run_case ─► 3 diagnose ─► 4 generate(candidate) ─► 5 run_case on ALL
 (P0)  (P1)             │                                                              │                    cases ─► 6 gate
                        └───────────────────────────────────────────────────────────────┼──────────────────────────────┘
 SEAMS                                                                                  │
  A  ChatClient.chat           llm.py          cache: exact-key replay (exists, needs hardening)
  B  run_case callable         system2.py      cache: RolloutStore wrapper (new); writes the case corpus
  C  generate callable         system2.py      memory read: retrieve k corrections -> `constraints=` slot of build_messages
  D  after regression_gate     system2.py      memory write: Correction record when `gate.accepted`
  E  diagnose / signature      diagnoser.py    memory key: signature from trace, not from the attack category
  F  planner.reset / update    planner.py      memory read (later): warm-start priors from the corpus
```

Seams A and B are caches: they change cost, not behaviour. Seams C to F are memory: they change behaviour and therefore need an ablation.

Key facts from the audit that shape the plan:
- The Muse call cache is keyed `[model, messages, temperature]` with no sample index; the demo arm's first program was served from cache in exp01, exp01b and exp02 [R3, code `llm.py:67-82`].
- There is no rollout cache, but rollouts repeat byte-identically in 63 of 65 repeat groups on this machine [R3]. The 2 mismatches straddled a launcher fix, so the launcher hash belongs in the key.
- `CapHarness.run` ignores the return code and does not catch `TimeoutExpired`, so it can return a stale `outcome.json` [code `rollout.py:76-88`].
- `regression_gate` counts a missing candidate result as a failure [code `gate.py`], so a cold cache would turn into rejections unless a miss means "rerun".
- `harden` passes **all** constraints on every cycle [code `system2.py`], and `signature()` is keyed on the perturbation category [code `diagnoser.py`].
- `Skill.help_count` and `last_used` exist but nothing reads or writes them [R3].

Where the code lives (the repo layout already says `evalkit/` holds the call cache and metrics with no system imports; `contracts/` is the only shared import):

| Piece | Home | Why |
|---|---|---|
| Record types (`FailureSignature`, `Correction`, `Evidence`, `GateVerdict`, `FailureCase`) | `contracts/` | Shared by both systems. Needs the System 2 owner's agreement before any edit [R3] |
| Cache and memory stores (SQLite plus content-addressed files) | `evalkit/` | No imports from either system |
| Retrieval and prompt assembly | `synthesizer/` | Reads records, never writes them |
| Building a `Correction` after the gate, enforcing the split on writes | `orchestrator/` | The only place that sees both systems |
| Signature from a trace, interventions, corpus, planner priors | `adversary/` | System 2 owns failure knowledge |

The alternative is a new top-level `ants/memory/` package. That is cleaner conceptually but changes the layout in `AGENTS.md`, so it is a decision for you (§8).

---

## 2. The options, and what I recommend

For each component: the choices, what each costs and gives, and a verdict. **R** = recommended, **L** = later, **N** = not recommended.

### 2.1 Cache options

| # | Option | What it saves | Risk | Verdict |
|---|---|---|---|---|
| C1 | **Harden the exact-key LLM cache** (add `sample_index`, store the request next to the response, atomic write, treat a corrupt file as a miss, log prompt hashes and response model) | Already avoided 568,247 tokens in 21 hits (17% of what would have been paid) [R6] | Hit rate falls on purpose once accidental sample sharing is removed | **R, first** |
| C2 | **Content-addressed rollout store** (`RolloutRecord` keyed by program bytes, case key, scene spec, run parameters, harness fingerprint) | About 30 s per hit; a 5-arm ablation with 3 repetitions is about 750 rollouts or 6.25 h uncached, and sharing 30 to 60% saves 1.9 to 3.75 h (**guess** for the hit rate) [R6] | A stale hit if the key misses an input; mitigated by a canary that re-runs one cached case per cycle | **R, second** |
| C3 | **Provider prefix-cache hygiene** (stable prefix, memory block after the demo block, constraints last, no timestamps in the prefix, run samples of one arm close in time) | At most about 10% of cost: 45.0% of paid prompt tokens are already cached, and 54% of paid tokens are completion, 71.5% of that reasoning [R6] | Meta's TTL, minimum length and price are undocumented; the elapsed-time pattern (38 of 49 calls within 120 s had cached tokens, 1 of 11 after) is confounded | R, cheap, no priority |
| C4 | Semantic cache (similar prompt returns an old reply) | Sounds large | Changes decisions, so it is not a cache; false hits are documented (vCache) [R6] | **N** |
| C5 | Cache the AST plan-gate verdict, DemoSpec extraction, diagnoser summary of a run dir | Small | None if keyed by content and version | R, trivial |
| C6 | Trajectory-prefix or simulator-state cache across candidates that share a program prefix | Potentially large for the gate | Needs simulator state snapshots; high risk | L (research tier) |
| C7 | Third-party cache library (for example `diskcache`) or experiment trackers (DVC, MLflow) | Concurrency and atomicity for free | New dependency; AGENTS.md prefers the standard library | N now; stdlib SQLite in WAL mode plus rename-into-place files do the same job |

### 2.2 Memory store options

| # | Option | Gives | Cost and risk | Verdict |
|---|---|---|---|---|
| M0 | No cross-run memory; constraints live only inside one `harden` run (today) | Simplest; the paper's "ANTS without memory" arm | Nothing is reused, so "skills are shared" is untested | Keep as the control arm |
| M1 | **Append-only JSONL of corrections** written at gate acceptance | Almost free; human-readable; committable for the demo | Not queryable, no atomic multi-writer updates; two ANTS processes already ran concurrently [R6] | **R for the hackathon tier** |
| M2 | **SQLite (stdlib, WAL) as the state store**, JSONL as the audit log | Atomic, queryable, FTS5 text search built in; no new dependency | Slightly more code than M1 | **R as the target**; start M1 and move once a second reader exists |
| M3 | Vector store (sqlite-vec, FAISS, Chroma, LanceDB) | Embedding retrieval on scene and symptom text | New dependency; the embedder (DINOv3 or SAM 3.1 features) is a dependency decision; exact scan is enough up to about 10^5 vectors [R6] | L; ask first |
| M4 | **Skill library with verifier admission** (ASPIRE-style entries: trigger, code, evidence, limits, runnable precondition; a fresh agent reproduces the fix from the text, at least 4 of 5 seeds) | The reusable form of absorbed corrections | L-sized; uses `params` and `attack_ranges` as the envelope [R3] | L (research tier) |
| M5 | Agent-memory frameworks: Mem0, Letta/MemGPT, Zep/Graphiti, A-MEM, LangGraph or LlamaIndex memory | Off-the-shelf lifecycle | LLM-driven ADD/UPDATE/DELETE is non-deterministic, costs tokens per decision and was not validated against ground truth; several need external services; heavy dependencies; conflict resolution by LLM reaches at most 28% on multi-hop forgetting in MemoryAgentBench [R6] | **N**. Borrow ideas only: Zep's `valid_to` instead of deleting, Generative Agents' score definition, ReasoningBank's "distil at write time" |
| M6 | Reuse ASPIRE's campaign skill library or CaP-X's regex-extracted skill library directly | Working code, Apache-2.0 and MIT | Driven by their own agents and formats; ours must record `split`, epochs, gate verdicts | Borrow the entry schema (M4); do not adopt the engine |

### 2.3 Key and signature options (the part that decides whether retrieval can work)

| # | Option | Verdict |
|---|---|---|
| K1 | Signature keyed on the perturbation category (today: `size:move_to_pose:timeout`) | **N**: it is a test-side label that does not exist at deployment, and it merges different root causes (the exp03 wine-rack stall and a plain plate stall share one signature) [R3, R5] |
| K2 | **`signature_from_trace`**: phase, primitive, status, bucketed deviation, object role, at three levels (L1 `phase|status`, L2 `+primitive`, L3 `+deviation+object_role`) | **R**. Dedup uses L3, retrieval L2 then L1, the escalation counter L2 [R5] |
| K3 | Add contact analysis (blocker part and object from `evalkit/contacts.py`) to the signature | R, already built in `evalkit` [R3] |
| K4 | Embedding of a symptom narrative | L; only inside a shortlist the typed key produced (every mature system matches on a typed key first: RCACopilot, Sentry, Getafix, DROC [R5]) |

### 2.4 Admission, exposure, ranking, forgetting

| Decision | Options | Recommendation | Evidence |
|---|---|---|---|
| **Admission** | add-all; gate-accepted; gate plus neighbour replay (V2); plus fresh verifier agent (V6) | **Gate-accepted first** (`admitted`). Add neighbour replay before a record is used across runs. Verifier agent only before sharing across tasks | Store-everything was worse than a small fixed memory on all four agents (55.48 vs 67.53 for RegAgent) [R6]; self-generated unverified skills show no gain [R4] |
| **Exposure to the generator** | all constraints (today); signature-matched k of 1 to 3; library outside the prompt | **Matched k of 1 to 3, retrieved once per generator session and frozen** so repair turns keep an identical prefix. Keep "all" as an ablation arm | ReasoningBank 39.0 none, 49.7 at k=1, 44.4 at k=4; Sentry 0.335 → 0.391 when failure lessons left the context [R4, R5] |
| **Ranking** | F1 pheromone (the paper's N13); F1b with a Wilson lower bound; F2 recency-importance-relevance; F3 ACT-R; similarity only | **F1b as the working default, F1 as the paper-faithful arm**, compared offline | No direct precedent for F1; parameters are guesses [R6] |
| **Credit** | all constraints in the accepted prompt that fixed the trigger case; leave-one-out regeneration; the model's own grade | **First rule now**, leave-one-out only for entries about to be promoted or deprecated | No paper solves credit for prompt-composed memory [R6] |
| **Forgetting** | none; rank fade only; deprecate by utility; hard delete | **Rank fade plus conservative deprecation** (never the only entry covering a case, with a grace period), tombstones for deletion requests | Harsh early retirement emptied the bank and fell below the no-skill floor [R4] |
| **Staleness** | none; time-based; re-verify on harness change | **Fingerprint-based**: a harness, allow-list or asset change is a hard invalidation; a generator change is soft; elapsed time never invalidates a deterministic artefact | Re-verifying costs about 30 s per rollout and no tokens [R6] |

### 2.5 Three bundles to choose from

| Bundle | Contents | Effort | What it lets you claim | Risk |
|---|---|---|---|---|
| **Minimal** | C1, C2, C5; K2+K3; M1 corrections JSONL; gate-accepted admission; exact-signature retrieval at k of 2; split guard | about 3 days (H1 to H7) | The loop is reproducible and cheaper; failures are reusable; a memory on/off ablation has something to retrieve | Low |
| **Standard** | Minimal plus M2 SQLite, F1b ranking, neighbour replay (V2) and the seed-literal lint (V4), a persisted case corpus with failing-first gate replay, planner warm start measured against cold start | about 2 more weeks | Memory improves repair cost and transfers across tasks, with a measured stale-hit rate | Medium: credit assignment and ranker parameters are guesses |
| **Full** | Standard plus skill library with verifier admission, run-time `MonitoredProgramRunner` with recovery, embedding retrieval, trajectory-prefix cache, autonomous-mode write-back | weeks | "Skills are shared" and run-time recovery | High: needs a safe envelope on hardware and a dependency decision |

**Recommendation: build Minimal now and run the free experiments; decide on Standard after experiment E5.**

---

## 3. Step-by-step integration

Each step is small, testable and independently revertible, so it fits the "one feature, one commit" rule. Efforts are from the audit [R3]; the dependency order is shown. "Done when" is the check I would run.

### Phase A: make the caches correct (no behaviour change)

**S1. Harden `ChatClient`** [seam A, `synthesizer/llm.py`], S, 3 to 4 h.
- Add `sample_index: int = 0` to `chat()` and the key; key a canonical `request` dict (everything sent) plus `key_schema: 2` plus the endpoint host.
- Store `{"key_schema", "request", "response", "created", "client_version"}`; on read, re-hash the request and compare it with the file name.
- Write to a temporary file and `os.replace`; treat an unreadable entry as a miss and quarantine it.
- Log in the ledger the sha of the system and user messages, the response `model` and `created`.
- Re-read the ledger tail before each uncached call, so two processes cannot both spend the last tokens.
- Test: no `Bearer` string in any cache file; a corrupted file is a miss; two samples of one prompt get two keys.
- Keep a legacy read path: for `sample_index=0`, if the new-format key misses, look up the old-format key `[model, messages, temperature]`, so existing entries still hit (the new key includes `key_schema` and the full request, so the file names differ).
- Done when: a replay of exp01 from the old cache costs zero tokens, and a new sample at index 1 is a paid call.

**S2. `CapHarness.run` fixes** [`adversary/rollout.py`], S, 1 to 2 h.
- Use a fresh `output_root` per call (or parse the run id the harness prints); check the return code; catch `TimeoutExpired`; never return a record from a previous run.
- Done when: a deliberately failing harness call returns `harness_error`, not an old result.

**S3. `RolloutStore`** [seam B, wrapper around `run_case`, home `evalkit/`], M, 6 to 8 h. Depends on S2.
- Key: sha256 of canonical JSON of the program bytes, `case_key` (suite, task, seed, `init_mode`, layout fingerprint from the reset file), the canonical scene spec (including actuation seed, scale, flags), `max_steps` and camera size, and the harness fingerprint (ASPIRE commit plus diff hash if dirty, `dependency_lock_sha256`, `launcher_sha256`, providers, SAM 3 checkpoint hash, LIBERO assets hash, MuJoCo version), plus the perturbation-spec version [R3 §4.2].
- Value: `task_success`, `program_ok`, `termination_reason`, calls, the `feedback()` dict (so the diagnoser needs no run dir), `steps_sha256`, wall time, fingerprint, split. No video.
- Rules: only deterministic policies; infrastructure failures (harness error, timeout, EGL "invalid depth") are retried once and never stored; separate namespace per split; **a miss means rerun, never "missing = fail"**; a canary re-runs one cached case per cycle and quarantines the fingerprint on a mismatch; the final accepted policy is re-run once with the cache bypassed so the headline number is a fresh rollout.
- Wiring (no change to `harden`): `run_case = cached(run_case, store)` in the experiment runner.
- Done when: the same `harden` run twice produces identical `system2.jsonl` decisions, the second run does no simulation, and a one-line change to the launcher invalidates exactly the affected keys.

**S4. Split guard** [`evalkit/`], S, 1 to 2 h.
- Stores take a `namespace` argument; writers assert `split == "acceptance"` for corrections, the corpus and every help or hurt event; the held-out reader lives only in `evalkit` and is not imported from decision code; a collision check between acceptance and held-out layout fingerprints (ASPIRE's saved mode wraps seeds at 50, and seeded mode does not guarantee distinct layouts) [R3].
- Done when: a unit test shows a held-out write raises, and the planner refuses a case whose layout fingerprint equals a held-out one.

### Phase B: structure the failures (still no behaviour change)

**S5. `signature_from_trace`** [seam E, `adversary/`], S, 2 to 3 h.
- Pure function `trace -> FailureSignature(phase, primitive, status, bucketed deviation, object_role)` with `key(level)`; phase from `evalkit/phases.py`, blocker from `evalkit/contacts.py`. Keep `Constraint.failure_signature = key(2)` so the existing escalation counter works.
- Make the constraint id global: hash of signature features plus rule, because today it is `c%03d` per run and collides across runs [R3].
- Done when: on the logged failures of experiments 01 to 04, the new key separates the wine-rack stall from the plain plate stall that the old key merged (experiment E3 below).

**S6. Persist the failure/case corpus** [`evalkit/`], S, 2 h. Depends on S3, S4, S5.
- One row per completed non-infrastructure rollout: `case_key`, `CaseSpec`, outcome kind (task_fail, timeout, unsafe, program_error; a crash is a held case, not a failure), signature, run id, split, `sampling_prob` of the adaptive draw.
- Seeds the gate set for the same policy lineage after a restart, without rerunning discovery.
- Done when: a restarted `harden` run reproduces its gate set from the corpus.

### Phase C: first memory (changes behaviour; needs an ablation)

**S7. `Correction` record, written at gate acceptance** [seam D, `orchestrator/`], S to M, 4 to 6 h. Depends on S5, and on your decision about `types.py`.
- At the `if gate.accepted:` branch of `harden`, write one record containing: the constraint (with signature features), repair kind, trigger case key, parent and repaired policy ids (program sha), the unified diff (`runlog.unified_diff` already exists), the optional rationale (`generator.repair_message(explain=True)`), the evidence ids with their split, the `GateVerdict` (accepted, fixed cases, regressions, counts), status `admitted`, and epoch fields. Proposed dataclasses are in [R3 §3.3](research/memory-audit-codebase.md); all new fields have defaults, so `from_json` stays backward compatible.
- Rejected attempts go to a separate append-only `attempts.jsonl`; they are never positive advice, but may appear as "tried and failed on this class".
- Store: JSONL first (M1), SQLite when a second reader appears (M2).
- Done when: after one hardening run, `corrections.jsonl` has one admitted record per accepted candidate, every record's trigger case flips from fail to pass when its diff is replayed, and no record has `split != acceptance`.

**S8. Retrieval into the `constraints=` slot** [seam C, `synthesizer/` and `orchestrator/`], S, 3 to 4 h. Depends on S7.
- Hard filters: status admitted or verified, scope, `split == acceptance`, harness-compatible, not deprecated. Match signature level 3, then 2, then 1, until at least one candidate. Rank by relevance times a lower bound of the help rate times a decay in epochs. Return k of 1 to 3 (cap 5).
- Rendering: the `rule` lines, plus for code-level repairs a short diff hunk as an exemplar. Placed last in the user message so the prefix stays identical; entries sorted by id, not by score, so a score change does not alter the bytes.
- Log per run: `memory_sha`, the query, the ranked list with scores, the entries injected, the ranker parameters, the epoch. Retrieval is a pure function of snapshot and query with a deterministic tie-break.
- Keep a config switch `memory = off | all | matched(k)` so the ablation arms are the same code.
- Done when: with `memory=matched(2)` the prompt of a repair call contains the expected records and nothing from the held-out namespace, and `memory=off` reproduces today's prompts byte for byte.

**S9. Credit and counters** [`orchestrator/`], S, 2 h. Depends on S7.
- After each gate decision: for every record that was in the prompt, `help` if the candidate was accepted and the record's trigger case now passes; `hurt` if the candidate failed the gate on a case the incumbent passed and the record was the only new memory item (otherwise log as unattributed). Epoch increments once per gate decision.
- Done when: counters are reproducible from `system2.jsonl` alone (a replay of the log yields the same ranking).

### Phase D: measure before going further (Phase E below), then Standard items

**S10 (Standard).** SQLite state store (M2); neighbour replay V2 (n fresh acceptance cases of the same class, require m of n) and the seed-literal lint V4 before a record is `verified`; failing-first order for gate replay (never shrink the set); planner warm start from failure pseudo-counts only (measured against cold start); `MonitoredProgramRunner` and run-time recovery are research tier.

---

## 4. Experiments

Rule for all of them: report counts and intervals, tune only on acceptance data, take the headline number from a fresh (cache-bypassed) rollout, and treat run-level differences as "hint, not result" as Experiment 01 did. Costs use measured values: a paid Muse call averages 130 s and 38,143 tokens, a rollout takes about 30 s, the observed price is about $13.5 per million tokens and is **unreconciled** with the ledger (2.75M paid tokens is about $37 at that price against a $15 cap) [R6]. Check the dashboard before any experiment that spends tokens.

### The ladder

| ID | Question | Needs | Model tokens | Time | Decision it feeds |
|---|---|---|---|---|---|
| E0 | Are rollouts deterministic enough to cache? | S2 | 0 | about 10 rollouts, about 5 min | Whether C2 is allowed at all |
| E1 | Does the hardened LLM cache replay everything and what does it save? | S1 | 0 | minutes | Whether old claims need restating |
| E2 | Does the rollout cache change any decision? | S3 | 0 to a few | one `harden` run twice | Whether the gate may rely on the cache |
| E3 | Does `signature_from_trace` separate root causes the category key merges? | S5 | 0 | minutes (offline on logs) | Whether retrieval can work |
| E4 | Which ranker retrieves the right record, offline? | S7 logs | 0 | minutes | Which ranker is the default |
| E5 | Does matched retrieval beat a placebo on a mock with known fixes? | S7, S8 | 0 | minutes | Whether the retrieval logic is bug-free |
| E6 | Does a retrieved correction cut the cost of a repair? (repair-stage micro-benchmark) | S8, budget | about 0.3 to 0.6M | hours | The headline memory claim |
| E7 | Does memory transfer across tasks? (leave-one-task-out) | E6, T0/T1/T2 | part of E6 | hours | "Skills are shared" |
| E8 | Does re-verification catch stale records? | S10 | 0 | one harness change | The staleness rule |
| E9 | Is the store robust to poisoned entries? | S8 | 0 | minutes | Security claim |

### E0. Determinism canary (free, do first)
- **Hypothesis:** a frozen program under one fingerprint reproduces `steps.jsonl` byte for byte.
- **Design:** 10 rollouts: the same program, seed and scene repeated 5 times; the same repeated 3 times while another simulation or SAM 3 job runs (GPU contention is a known source of fake "invalid depth" failures); 2 on another seed. Compare `steps_sha256`. About 30 s each.
- **Decision rule:** every identical repeat group, and a mismatch only under contention that is correctly classed as an infrastructure failure, means the rollout cache is allowed. Any mismatch on an idle machine means the cache is off until the cause is found. The earlier 63 of 65 is same-machine only [R3]; this is the cross-load check. Cross-machine determinism stays unmeasured and is stated as such.

### E1. LLM cache replay and savings (free)
- **Design:** after S1, replay experiments 01, 01b and 02 from the cache. Count hits and misses, tokens avoided, and which "independent samples" were in fact the same cached program.
- **Output:** a table of tokens avoided per experiment and a restated list of claims ("same first program, different repairs" until independent samples exist).
- **Why it matters:** it fixes the comparison basis before new arms are added.

### E2. Rollout-cache equivalence (nearly free)
- **Design:** run one real `harden` with the cache cold, then again with it warm; compare `system2.jsonl` decisions, case results and the final program; then bypass the cache for the final accepted program and compare.
- **Pass:** identical decisions, zero simulations on the second run, a fresh final rollout agrees with the cached one. **Fail:** any difference means a key is incomplete; fix the key, never accept the discrepancy.
- **Measured quantity:** hit rate and hours saved, to replace the **guess** of 30 to 60% sharing.

### E3. Signature separation (free, offline)
- **Design:** take every failure in the logged runs of experiments 01 to 04. Hand-label the root cause for a sample (for example wine-rack blocking, stale pose, slip, planner timeout from a size change). Compute purity and the number of merged distinct causes for the old key and for L1, L2 and L3 of the new one.
- **Pass:** the new L3 separates the known distinct causes the old key merged, and L2 groups failures a person would fix with the same rule. If it does not, retrieval built on it would misfire; fix the features first.
- **Caveat:** few logged failures, so report counts.

### E4. Offline retrieval benchmark (free)
- **Design:** build queries (signature features, scene features, task) from the logged cycles. Positives are records whose inclusion preceded a gate acceptance that fixed the case, plus leave-one-task-out positives across T0, T1 and T2. Compare similarity only, F1, F1b, F2 and F3 with the parameter grids from [R6 §3.2](research/memory-management-and-caching.md) on precision@k, recall@k and MRR.
- **Output:** the default ranker and k. Report counts, because the labels come from few events.

### E5. Mock-backend ablation with known fixes (free)
- **Design:** the loop already runs with callables, so use a mock simulator whose categories have one failure mechanism each and a mock generator whose fix is known. Arms: A0 memory off; A1 all constraints in context; A2 matched k of 2; plus two controls: a **placebo library** (random records) and **shuffled signatures** (right records, wrong keys).
- **Pass:** A2 beats both controls on cycles to robust; if not, the retrieval logic has a bug. This is a unit-level test of the mechanism, not evidence about Muse.

### E6. Repair-stage micro-benchmark (the first real memory evidence)
Instead of full hardening runs per arm (about 100k to 300k tokens each, so only 4 to 11 end to end runs fit under a $15 cap [R6]), isolate the stage memory acts on.
- **Design:** collect N failures with their feedback from acceptance-side rollouts of the incumbent (N of 10 to 20 across categories). For each failure, ask the generator for a repair under three prompt arms, with the same feedback and the same stable prefix:
  1. memory off;
  2. all accepted constraints (today);
  3. matched k of 2 (from a library built in a *different* hardening run, to avoid self-retrieval).
  Run each candidate on the failing case and on the full gate set (cached rollouts make the shared part free). Controls: placebo and shuffled-key libraries.
- **Metrics:** fraction of candidates the gate accepts at the first attempt, attempts to the first accepted candidate, paid tokens to the first accepted candidate, regressions caught by the gate, and the number of cases fixed minus broken. The primary comparison is arm 3 against arm 2 on tokens to the first accepted candidate with first-attempt acceptance non-inferior.
- **Sample size and power:** the unit is the failure. With paired outcomes on the same N, an exact sign test needs about 6 discordant failures all in one direction (p = 0.031 for 6:0, 0.0215 for 9:1, 0.070 for 7:1) [R6, computed]. So N of 10 detects only a large effect; N of 20 is the realistic target. Say so in advance.
- **Cost:** about 25k tokens per generator call; three arms plus two controls is five prompts per failure, so N of 10 is about 50 calls, about 1.2M tokens, N of 20 about 2.4M. That is too much at the current price. **Cheaper variant:** drop the two controls to the mock (E5), run arms 1 to 3 only (3 calls per failure), N of 10, about 0.7M tokens; the cache makes re-runs of the same arm free. Confirm the price first (to-do 19).
- **Kill criterion (fixed in advance):** if arm 3 is not better than arm 1 on tokens to the first accepted candidate and not better than the placebo, stop building Standard; keep the corrections as an audit log, which is still a result.
- **Why this design:** the literature's memory effects come from text and code benchmarks with few seeds, and show harm for strong models (REM: -2 to -9 points above 47% unaided) [R4]. Muse may be in that regime, so memory-off is the primary control, not an afterthought.

### E7. Transfer (leave-one-task-out)
- **Design:** build the library on T0 (bowl on plate, stock scene), evaluate repairs on T1 (the real-size scene, different tolerances) and, if budget allows, T2 (book under the shelf, a different mechanism). Exclude records whose evidence shares a task and seed namespace with the evaluation case; apply a temporal cut.
- **Measure:** the E6 metrics on the new task, plus the **cross-task** help and hurt counts reported separately from in-task ones. A record is promoted to `shared` only after helping on at least two distinct tasks [R6].
- **Expect:** little transfer between T0 and T2 (different strategy), which is itself informative: the signature level and `avoid_when` must keep wrong fixes out.

### E8. Staleness and re-verification
- **Design:** use a real harness change that already happened (the scaled-scene tolerance fix in the launcher). Count retrieved records whose evidence replay now fails, with and without re-verification at retrieval.
- **Output:** the stale-hit rate with its upper bound (zero events in 50 gives about 6%, rule of three) [R6], and the cost of re-verification in seconds (about 30 s per evidence case, no tokens).

### E9. Poisoning
- **Design:** inject N crafted records into a copy of the store: instruction-like text in a rule, a wrong rule with plausible evidence, a record with a held-out case id. Check that the typed record and templated rule path rejects the first, the gate and neighbour replay reject the second, and the split guard rejects the third.
- **Why:** MINJA defeats embedding sanitisation and cheap prompt detection [R6]; the defence here is provenance and a gate, which is testable.

---

## 5. What each step shows (the capabilities and the usefulness)

| Capability | Evidence that proves it | Experiment |
|---|---|---|
| Reproducible, cheaper runs | Same decisions with a warm cache, zero simulations on rerun, hours and tokens saved | E1, E2 |
| Safe caching | No mismatch under load; a fresh final rollout agrees | E0, E2 |
| Failures that can be reused | New signature separates causes the old one merged | E3 |
| A ranker worth its parameters | Offline retrieval metrics, with the similarity-only baseline | E4 |
| The mechanism works | Matched retrieval beats placebo and shuffled keys on a mock with known fixes | E5 |
| **Memory helps repair** | Fewer tokens or attempts to the first accepted candidate, no loss of first-attempt acceptance, against memory off and all-constraints | E6 |
| "Skills are shared" | Cross-task help with wrong fixes kept out | E7 |
| Safe reuse over time | Stale-hit rate and re-verification cost | E8 |
| Integrity | Poisoned and held-out records rejected | E9 |

A negative E6 is a legitimate outcome: it means corrections are an audit trail and a regression asset, not a prompt aid for this generator, and the pitch should say so.

---

## 6. Schedule against the 2026-11-04 deadline

Today is 2026-11-01, so three days. Everything in the free column needs no model tokens.

| Day | Build | Run |
|---|---|---|
| 1 | S1, S2, S4 | E0, E1 |
| 2 | S3, S5, S6 | E2, E3 |
| 3 | S7, S8, S9 | E4, E5; E6 only if the price is confirmed and a budget is approved |

Do not start in this window: embeddings, skill extraction and verifier admission, planner warm start, run-time monitors, prefix caching, SQLite migration. If only two days are available, do S1 to S5 and E0 to E3: they are the parts that change what every later number means.

For the demo, a small curated `memory/corrections.jsonl` (acceptance-side corrections with their evidence ids) can be committed so the demo starts with something to retrieve, while runtime stores stay in the git-ignored `data/`.

---

## 7. Risks and unknowns

| Risk | Mitigation |
|---|---|
| A cache key misses an input and serves a stale result | Hermetic key, request stored next to the response and re-hashed on read, canary each cycle, fresh final rollout |
| The strict per-case gate is fragile on noisy rollouts (a 123-round robot study saw nearly half of disagreeing pairs fail to reproduce) [R4] | Programs are deterministic per seed (E0); add replicates and a tolerance only for any neural-policy arm |
| Memory hurts the strong generator | Memory-off is the primary control; kill criterion in E6 |
| The ranker parameters are guesses | Choose offline (E4); report all arms |
| Credit assignment is unsolved for prompt-composed memory | Simple rule now, leave-one-out only for promotion; report unattributed events |
| Held-out contamination through a shared store | Split guard (S4), separate namespaces, frozen snapshot for the report, no held-out score feeds the next run's memory |
| The ledger contradicts the cap | Check the dashboard before E6 |
| Most 2026 evidence is from abstracts and text benchmarks with few seeds | Treat as hypotheses; our own E4 to E7 are the evidence |
| `types.py` is shared | Agree the additions with the System 2 owner first |

**Unknown and not settled by any report:** cross-machine determinism; whether `harden` works with real rollouts (it has only run on a mock); Meta's prompt-cache TTL, minimum length and price; a credit assignment method for prompt-composed memory; every decay rate, k and threshold.

---

## 8. Decisions that need you

1. Build the **Minimal** bundle now and decide on Standard after E5? (default: yes)
2. May `types.py` take `Correction`, `Evidence`, `GateVerdict` and the extra `Constraint`, `Policy`, `Skill` fields, with all new fields defaulted?
3. Home of the stores: `evalkit/` (default, no layout change) or a new `ants/memory/` package (needs a change to the layout in `AGENTS.md`)?
4. Approve the E0 canary (about 10 rollouts, no tokens)?
5. Approve a token budget for E6 once the price is confirmed (about 0.7M tokens for the cheaper variant)?
6. Rule text: deterministic `RULES` templates (default, typed and poison-resistant) or Muse Spark written rules (reads better, non-deterministic)?
7. Embedding dependency (DINOv3 or SAM 3.1 features) for the research tier?
8. Keep a committed `memory/corrections.jsonl` for the demo while runtime stores stay in `data/`?
