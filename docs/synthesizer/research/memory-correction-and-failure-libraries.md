# Correction library and failure corpus: how others store, match, validate and reuse failures, and a design for ANTS

Status: research note, 2026-11-01. Nothing here is built or decided; it feeds the open Q9 (memory), C10/C11 in [../../dev/paper-vs-docs.md](../../dev/paper-vs-docs.md) and [../skills.md](../skills.md). Ground rules from [AGENTS.md](../../../AGENTS.md) still hold: nothing is trained, acceptance and held-out stay separate, numbers come from logged runs. Numbers below are quoted from the sources, not from ANTS runs.

**Tags.** `[read]` I read the relevant sections of the full text (PDF or HTML) today. `[abstract]` only the abstract or the arXiv listing. `[summary]` a search-result summary or secondary page, not the paper. `[repo]` taken from an ANTS doc in this repo that already read the source. `[memory]` from my own background knowledge, not checked today. `[proposal]` my design, not in the literature.

**Method.** Anchors were read first (REFLECT, DROC, Code-as-Monitor, AHA, Voyager, RAPID, ASPIRE via repo). The 2025-2026 "cited by" lists of REFLECT, DROC and Code-as-Monitor were pulled from the Semantic Scholar API (AHA was rate-limited, so its list was not pulled), then snowballed by web search into the 2026 failure-recovery and failure-lesson memory papers (Sentry, BASM, RESETTLE, LIBERO-Recover, FRAMES, Library Drift). Neighbouring fields were searched by data structure and lifecycle, not by keyword alone. arXiv IDs of the form 26xx are 2026 papers; none has been peer-reviewed as far as I could tell.

---

## 0. Short version

1. **Nobody in robotics has measured a correction library for LLM-written robot programs under adversarial perturbation.** The closest robotics systems either explain one failure and re-plan with no memory (REFLECT), keep a small hand-fed correction store (DROC, LYRA, ARCHITECT), or report only the monitoring half (FRAMES). The measured evidence for failure-lesson libraries comes from non-robot LLM-agent work (Sentry, BASM, ReasoningBank, SWE-Exp). Treat transfer to ANTS as a hypothesis.
2. **The strongest, most directly relevant result is that failure knowledge must be conditionally exposed.** Sentry [read] found failure lessons in the agent's context misfire when their failure is absent (removing them from an ACE playbook raised held-out reward from 0.335 to 0.391; adding the full playbook to persistent context lowered WebShop reward from 0.364 to 0.296), and BASM [abstract+read] found success-only skills raise the wrong-tool margin by 47%. ANTS currently puts every accepted constraint into the generator's context. That is the design the evidence argues against.
3. **Match on observable symptom first, mechanism second, embedding last.** Every mature system uses a typed key before similarity: RCACopilot (alert type, then nearest incidents), Sentry (failure type plus label overlap, k=5), Getafix (pattern applies by AST match, then frequency ranking), DROC (task semantics plus object visual features). In Sentry's ablation, restricting to broad type lost about 11.3%, no filter about 18.8%, random about 28.9% (relative).
4. **A stored fix must be validated on the evidence case first, then on neighbours, then by the per-case gate.** Getafix validates with the same analyser that raised the warning; ASPIRE admits a skill only if a fresh verifier reproduces the fix (2 attempts, at least 4/5 seeds) [repo]; Skill-V requires non-regression on historical replay [abstract]. Nobody I found checks that a fix is not a single-seed fix except ASPIRE's "no seed-specific branches" rule.
5. **The current ANTS diagnoser keys its explanation on the perturbation category, which is a test-side label** [read: `diagnoser.py`]. That works inside the loop and is useless at deployment, where no category label exists. The signature has to be computable from the trace alone. This is the single most important schema change.
6. **Run-time recovery fits the existing `Constraint.check_code` and `PolicyKind = "monitored_program"`** [read: `types.py`]. Evidence: Code-as-Monitor (monitor code returns a flag plus a reason), AgentSpec (trigger, predicate, enforcement; LLM-written rules reached 95.56% precision but only 70.96% recall), LIBERO-Recover (a four-level recovery ladder). FailBench says VLM judges are near chance on contact-heavy tasks, so monitors should read structured state, not images.
7. **The failure corpus is a regression asset and a planner prior, but it is a biased sample.** Order the gate's replay failing-first to fail fast (RETECS-style), never shrink the gate's set. Warm-start Thompson sampling from past failures only (discounted failure pseudo-counts), never from past passes, and log the sampling probability of every adaptive draw so a rate can be estimated later with importance weights [proposal, supported by Raj and Kalyani, RETECS, Feng et al.].
8. **Leakage control is a solved-looking problem in SWE-Exp** [read]: exclude experiences from the same repository and any generated after the target. ANTS analogue: the library write-path accepts acceptance-side evidence only; held-out failures are logged but never diagnosed into records; memory-benefit experiments use leave-one-task-out and a temporal cut.

---

## 1. What ANTS has now, and the gap [read: repo]

| Item | Current state | Gap for a correction library |
|---|---|---|
| `Constraint` ([types.py](../../../src/ants/contracts/types.py)) | `constraint_id, failure_signature, when_to_apply, rule, check_code, evidence[]` | no mechanism, no fix diff, no scope or API version, no negative applicability, no validation state, no usage counters |
| Signature ([diagnoser.py](../../../src/ants/adversary/diagnoser.py)) | `"{perturbation.category}:{failed_tool}:{status}"`, e.g. `size:move_to_pose:timeout` | first field is the attack label, not an observable; no phase, no deviation bucket, no object role |
| Diagnosis | `RULES[perturbation.category]`: one fixed rule text per category | the explanation is read from the attack, so it cannot discriminate two mechanisms inside one category, and does not exist at run time |
| Planner ([planner.py](../../../src/ants/adversary/planner.py)) | Beta(1+f, 1+p) per category, `reset()` when the incumbent changes | all history is discarded on every new incumbent; no use of the failure corpus; no cross-run prior |
| Escalation | K=3 cycles with the same signature (Q11) | signature granularity silently sets the escalation behaviour |
| Memory (Q9, C11, N13) | embedding top-k x usage score ("pheromone") with decay; stores successful programs; "failure written to M" in Fig. 2 | nothing says what a failure record contains, how a wrong fix is avoided, or how a stored fix is re-validated |
| `Skill` ([types.py](../../../src/ants/contracts/types.py), [skills.md](../skills.md)) | interface, precondition, code, envelope, evidence, status, `help_count` | no `harm_count`; `constraints` list exists but nothing says when a constraint is absorbed |
| Adversary spec | `history/` JSONL, F_n for the gate, `replay(π, ps)` | no per-case determinism, minimal failing severity, or feasibility field on a stored case |

Already compatible: `Policy.constraints_used`, `Skill.evidence`, the gate over "every case seen so far", `PolicyKind = "monitored_program"`, C16 (feasibility), N11 (a crash is an error, not a failure).

---

## 2. Source survey

### 2.1 Robotics: failure explanation, detection and recovery

| Source | Unit of storage | Key / signature | Retrieval and reuse | Validation before reuse | Numbers (as quoted) | Limits and failure modes | Tag |
|---|---|---|---|---|---|---|---|
| [REFLECT](https://arxiv.org/abs/2306.15724) (Columbia, Stanford; CoRL 2023) | None persistent. A per-episode hierarchical summary (sensory, event, subgoal) built from RGB-D, sound, state | none | Not reused across failures: one explanation feeds one correction plan | Corrected plan is executed and scored | RoboFail: 100 sim failures (10 tasks x 10) and 30 real UR5e failures; taxonomy 55% planning / 45% execution. Sim, execution failures: Exp 88.4, Loc 96.0, Co-plan 79.1 vs 41.9 without explanation; planning failures: 84.2 / 80.7 / 80.7 vs 56.1 without explanation | Scene-graph heuristics may fail in complex scenes; assumes a static environment; "less effective for handling low-level control failures" | [read] |
| [Inner Monologue](https://arxiv.org/abs/2207.05608) | Text feedback in the prompt (success detection, scene description, human) | none | in-context only | none | not read | not read | [abstract] |
| [DROC](https://arxiv.org/abs/2311.10678) (Stanford; ICRA 2024) | Dictionary keyed by task name: task-related knowledge, variables to save, modified code or plan, updated object states | task semantics (LLM picks similar tasks) plus visual feature of the task object; some knowledge (robot constraints, user preferences) is always retrieved | LLM decides which past experiences are relevant; visual retrieval uses DINO-family features (visual-visual) and CLIP (visual-semantic) | none beyond the next human correction; the human is the validator | Needs "less than half" the first-round corrections vs Code as Policies. Plan level, corrections needed (DROC vs naive retrieval of saved plans): user preferences 0.5 vs 1, feasibility 0.67 vs 1.33, common sense 0 vs 1.5, scene information 0.5 vs 1.5. 5 skill tasks x 3 iterations, 6 rounds, 3 authors as oracle users | Text similarity alone retrieves the wrong grasp (handle vs knob), hence the visual key. No limitations section in the arXiv text. Tiny scale | [read] |
| [Code-as-Monitor](https://arxiv.org/abs/2412.04455) (CVPR 2025) | Per-task "constraint elements" (points, lines, surfaces) tracked in 3D; generated monitor code | constraint-to-element mapping | Monitor code takes element positions and returns a boolean flag plus a cause string; a tolerance is a number in the code (e.g. 15 degrees) | none stored | "28.7% higher success rate and 31.8% less execution time under severe disturbances" (3 simulators plus real). vs DoReMi in OmniGibson: 34.8% less time, 52.2% fewer tokens | Misses force-direction failures with no visible displacement; VLM hallucination in code generation; authors name RAG as a possible fix | [read] |
| [AHA](https://arxiv.org/abs/2410.00371) (NVIDIA, UW; ICLR 2025) | Procedurally generated failure QA pairs (FailGen on RLBench keyframes) | 7 failure modes: incomplete grasp, inadequate grip retention, misaligned keyframe, incorrect rotation, missing rotation, wrong action sequence, wrong target object | A fine-tuned VLM; used as reward-reflection, task-plan and sub-task verification signal | none | "49K+" image-query pairs over 79 sim tasks; beats GPT-4o by more than 20.0% on average across datasets; sub-task verification improves task success by an average of 21.4% | Fine-tuned (outside ANTS scope); fixed 7-mode taxonomy from keyframe edits | [read] |
| [Guardian / GuardianFail-36k](https://arxiv.org/abs/2512.01946) | Perturbed successful trajectories plus VLM reasoning traces | failure type | trained verifier | evaluated on three unseen real benchmarks | 36k failure-reasoning set (RLBench, BridgeDataV2) | trained model | [abstract] |
| [RoboFAC](https://arxiv.org/abs/2505.12224) | 9,440 erroneous trajectories, 78,623 QA pairs, 53 scenes | systematically categorised failure types | lightweight multimodal model as external supervisor | real VLA pipeline | +34.1% failure-analysis accuracy vs GPT-4o; +29.1% relative on four real tasks | trained model | [abstract] |
| [FailSafe](https://arxiv.org/abs/2510.01642) | Simulator-generated failure cases **paired with executable recovery actions** | failure case | fine-tuned VLM (FailSafe-VLM) | ManiSkill evaluation | up to 22.6% average gain over three VLAs | needs a simulator with motion planning; trained model | [abstract] |
| [FailBench](https://arxiv.org/abs/2609.03611) | 2,197 manipulation attempts, 14 sources | n/a (benchmark) | n/a | n/a | 13 VLM detectors; best 0.77 mean balanced accuracy; below 0.60 on contact-intensive tasks; bias toward "success" under ambiguous evidence; fine-tuned detectors underperform general VLMs | judges are unreliable exactly where ANTS grasp and place failures live | [abstract] |
| [LIBERO-Recover](https://arxiv.org/abs/2609.05178) | Real failures from SOTA models, annotated with recovery level, failure category and a one-line imperative recovery action (JSON) | 4 recovery levels (L1 action retry, L2 action adaptation, L3 object-state recovery, L4 environmental recovery) x 6 categories (grasp, placement, displacement, collision, obstruction, other) | benchmark | evaluates recovery success per level | PDF text: 2178 scenarios from 130 subtasks; "all models suffer over 50% performance drops" on natural failures; models do well on L1/L2 and poorly on L3/L4 | arXiv listing and PDF disagree on scenario count ("1,000+" vs "2,000+"/2178): version drift | [read] |
| [FRAMES](https://arxiv.org/abs/2609.22538) (2026) | Memory module of prior skill experience; Recovery Agent conditioned on the failed subtask and failure evidence | per skill | retrieved records for the selected skill | monitor tested alone | monitor detects 48/50 failures, accepts 46/50 successes, 94.0% accuracy; full recovery loop "ongoing" | no end-to-end result yet | [abstract] |
| [RESETTLE](https://arxiv.org/abs/2610.12185) (2026) | Same-task demonstration reference | trigger: two independently sampled action proposals persistently disagree | V-JEPA retrieval of a demo reference, one corrective action, then control returns | benchmark runs | up to +8.70 / +6.28 / +6.83 points on LIBERO-Plus / Meta-World / RoboCasa; 74.04-93.57% lower latency than VoLoAgent; code released | retrieves demonstrations, not failure records | [abstract] |
| [FLARE](https://arxiv.org/abs/2608.26645) (2026) | "Small library of object-centric Reset skills" chosen from offline MLLM failure analysis | OOD state identified from video | online MLLM monitor arbitrates execution vs Reset | contact-rich tasks | not quoted | trains policies | [abstract] |
| [FIPER](https://arxiv.org/abs/2510.09459), [AEGIS](https://arxiv.org/abs/2606.06660) | Calibrated OOD and entropy scores / activation probe | n/a | alarm triggers a handoff | conformal calibration on successes / pre-registered | AEGIS: early-window AUROC 0.764, recovers 10.1% of lost trajectories vs 4.6% for blind escalation | policy-internal signals, need access to the policy | [abstract] |

### 2.2 Robotics and agent memories of corrections, skills and lessons

| Source | Unit of storage | Key / signature | Retrieval | Validation before reuse | Numbers (as quoted) | Limits and failure modes | Tag |
|---|---|---|---|---|---|---|---|
| ASPIRE ([2607.00272](https://arxiv.org/abs/2607.00272), Apache-2.0) | Markdown skill: Trigger, Code (5-20 lines), Why and Evidence, Limits, optional runnable precondition ("code or it is nothing"); paper describes failure signature, when-to-apply, repair, sketch | failure signature plus trigger | skills injected as context | fresh verifier agent, 2 attempts on seeds 51-55, needs at least 4/5; no seed-specific branches in fixes | LIBERO-Pro 0.72 (CaP-Agent0 0.18); zero-shot LIBERO-Pro Long 0.047 with 0 learned tasks to 0.305 with 90 | Verifier checks that a skill "transmits" on its source task, not that it transfers; skills verified once can go stale; compute heavy | [repo] |
| RAPID ([2609.30249](https://arxiv.org/abs/2609.30249)) | Primitive library (success predicate per primitive), strategy | coding agent decides whether a segment is covered by an existing primitive | retrieve if covered | agent-written feasibility filters on random scene variants; verified on every (environment, effect) pair | ablation removing scene variants drops performance and raises variance; adding variants to CaP-Agent0 does not help without the object-centric representation | one demo, non-prehensile focus | [read] |
| [Voyager](https://arxiv.org/abs/2305.16291) | Verified program; key = embedding of an LLM-written description | description embedding | top-5 skills | self-verification critic; "most important among all the feedback types"; stuck after 4 rounds moves on | not re-quoted | critic can miss a success signal (spider string example) | [read] |
| [LYRA](https://arxiv.org/abs/2509.18597) | Modular skills plus execution examples in external memory | RAG; user hints when retrieval is insufficient | RAG | human feedback | 0.93 success, up to 27% above baselines, 42% better correction efficiency | designed around a human in the loop | [abstract] |
| [ARCHITECT](https://arxiv.org/abs/2607.23784) (2026) | Human corrections grounded in code by execution traces, distilled into a persistent skill library | trace-to-code grounding | skill library as long-term in-context learning | human supervisor | transfers to novel tasks "with decreasing human intervention" | search snippet says it is limited by how many corrections it receives | [abstract] |
| [Harness VLA](https://arxiv.org/abs/2607.08448) | "operating range" of fixed primitives learned from traces, global success rules and failure models | per primitive | planner | benchmark | +38.6 / +25.4 points on LIBERO-Pro / RoboCasa365 | needs a fine-tuned VLA | [abstract] |
| [Sentry](https://arxiv.org/abs/2610.02994) (2026) | Verified recovery: failure type, retrieval labels, trigger pattern, repair principle. Playbook is kept outside the agent context | failure type, then at least one shared retrieval label, ranked by label overlap; fallback = most recent of same type | retrieved only when a failure is diagnosed mid-trajectory, k=5 | recovery judged resolved without reward access; only verified recoveries stored | beats the strongest runtime baseline by 37% on average (up to 77% on WebShop) and ACE by 39%; resolves 81.7% of 939 detected failures; local recovery 33.5% to 60.5%; ablations (average): no self-evolution -31%, no failure-specific retrieval -26%, no recovery verification -20%; retrieval: type only about -11.3%, unfiltered about -18.8%, random about -28.9%; k=3 -4.5%, k=10 -6.2%; human agreement 86.0% (intervention) and 81.8% (recovery) | two small and mid models; text agents; detector and verifier are LLM-based | [read] |
| [BASM](https://arxiv.org/abs/2608.22339) (2026) | Skill = goal, procedure, tools, **applicability conditions, risk cues, avoidance rules, recovery notes** | skill retrieval plus boundary-aware rerank | budgeted retrieval and formatting | boundary check at decision time | success-distilled skills raise the wrong-tool margin by 47%; up to +23.8% on AppWorld | text tool-use only; boundaries are free text | [read] |
| [Skill-V](https://arxiv.org/abs/2610.11781) (2026) | Versioned, falsifiable skill contract linking intent to observable criteria | contract | applicability-aware filter | revisions must pass non-regression on historical replay | ALFWorld 95.3%, WebShop 85.9%, more compact library | not robotics | [abstract] |
| [SkillForge](https://arxiv.org/abs/2608.24747), [Library Drift](https://arxiv.org/abs/2605.19576) | evidence-verified skills / append-only evidence log with per-skill contribution | n/a | n/a | re-verification; outcome-driven retirement plus an active cap | Library Drift: held-out pass@1 from 0.258 to a late-window mean of 0.584; premature retirement was "active harm" (-0.019) | MBPP+ code tasks | [abstract] |
| [RESKILL](https://arxiv.org/abs/2609.15684), [EmbodiSkill](https://arxiv.org/abs/2605.10332) | repair state linking failure hypotheses to patches / skill-aware reflection | hypothesis-patch links | n/a | retest, carry unsuccessful retests forward / separate "skill wrong" from "executor did not follow it" | RESKILL +3.7 points over direct repair; EmbodiSkill 93.28% on ALFWorld | text environments | [abstract] |
| [AutoManual](https://arxiv.org/abs/2405.16247) | Rules of 6 types (Special Phenomenon, Special Mechanism, Useful Helper Method, Success Process, Corrected Error, Unsolved Error) with rule, example, validation_record | rule type and relation to existing rules | manual compiled for the planner | Builder classifies the error as "imperfect rules" or "imperfect agent" first | case-conditioned prompting raises success from 93.8% to 97.4% (ALFWorld) | Planner "may sometimes ignore these rules": needs enforcement or validation | [read] |
| [ReasoningBank](https://arxiv.org/abs/2509.25140), [Dynamic Cheatsheet](https://arxiv.org/abs/2504.07952), [ACE](https://arxiv.org/abs/2510.04618), [ExpeL](https://arxiv.org/abs/2308.10144), [CLIN](https://arxiv.org/abs/2310.10134), [AWM](https://arxiv.org/abs/2409.07429), [Reflexion](https://arxiv.org/abs/2303.11366) | distilled strategies from successes **and** failures / snippets / delta-updated playbook / insights / causal abstractions / workflows / verbal reflections | task similarity | embedding top-k | mostly none | ACE names "brevity bias" and "context collapse"; CLIN +23 over Reflexion on ScienceWorld; Reflexion memory is a sliding window and the authors call for vector-DB style memory | generic; the failure mode ACE names (rewriting erodes detail) applies to any rewritten rule list | [abstract], Reflexion limits [read] |
| [Xiong et al.](https://arxiv.org/abs/2505.16067) (ACL 2026) | memory add/delete study | n/a | n/a | strict evaluator before adding; history-based deletion | "add-all" performs worse than a fixed-memory baseline; selective addition with a strict evaluator narrows the gap to an error-free baseline | "experience-following": a retrieved record with similar input makes the agent copy its output, errors included, and re-adding the new run propagates them | [abstract] |
| [Memento](https://arxiv.org/abs/2508.16153) | case bank of (state, action, reward) | encoder similarity, or a learned case-selection policy | top-K | reward | case memory adds 4.7 to 9.6 points on out-of-distribution tasks; retrieval K plateaus at 4 and more adds noise | deep-research tasks | [abstract], K plateau [read] |

### 2.3 Neighbouring fields

| Field | Source | Unit of storage | Key / signature | Retrieval | Validation before reuse | Numbers (as quoted) | Limits and failure modes | Tag |
|---|---|---|---|---|---|---|---|---|
| Automated program repair | [Getafix](https://arxiv.org/abs/1902.06111) (Facebook; OOPSLA 2019) | Fix pattern = AST edit with holes, learned by hierarchical clustering and anti-unification from (bug, fix) pairs | the bug category (static-analyser warning) and the AST context | all patterns that match are applied; ranked by pattern frequency and location prior; patterns covering less than 1% of the training set are dropped | the same static analyser that raised the warning must stop raising it (no test suite) | top suggestion equals the human fix for 12% to 91% depending on category; top-5 contains the fix for 526 of 1,268 bugs; developers accept about 42% of suggestions | needs a cheap, trusted detector; only recurring patterns are learned | [read] |
| | [FixMiner](https://arxiv.org/abs/1810.01791) | Fix pattern from iterative clustering of atomic changes (Rich Edit Script) | tree shape per clustering round | pattern library fed to APR | downstream APR validation | not quoted | pattern must be "tractable and reusable" | [abstract] |
| | [SWE-Exp](https://arxiv.org/abs/2507.23361) (2025, v2 2026) | Experience = {perspective: generalised understanding, modification: transferable strategy}, from successes and failures; two facets (comprehension, modification) | issue type plus a generalised description, embedded | top N=10 by cosine on issue type, an LLM reranker keeps k=1 | none beyond downstream tests; **leakage control: drop experiences from the same repository and any generated after the target** | 73.0% Pass@1 (Claude 4 Sonnet, v2); ablation on DeepSeek-V3: full 42.0%, no extraction (raw patch as demonstration) 36.0%, no LLM rerank 38.2% | distilled experience beats raw golden-patch demos by 6.0 points | [read] |
| | [Agentless](https://arxiv.org/abs/2407.01489), [ChatRepair](https://arxiv.org/abs/2304.00385) | localise-repair-validate with reproduction tests; failed patches fed back into the dialogue | failing test output | n/a | patch validation by tests | ChatRepair title: "162 out of 337 bugs for $0.42 each" | failed attempts help only within the same bug | [abstract] |
| Software testing | [RETECS](https://arxiv.org/abs/1811.04122) (ISSTA 2017) | per-test history: duration, last run, verdict history | test id | a policy ranks tests by history; rewards favour failing tests early | CI cycle result | three industrial datasets; compared against Random, recent-verdict Sorting and Weighting baselines (I did not verify the margins) | history length matters; reward design matters | [read] partial |
| | Flaky tests (Google testing blog, 2016) | flaky = both pass and fail on the same code | test id | quarantine, rerun | rerun | about 1.5% of all test runs flaky; almost 16% of tests have some flakiness | cost figures in vendor blogs are not traceable to primary sources | [summary] |
| Autonomous driving | [Feng et al., Nature 2023](https://www.nature.com/articles/s41586-023-05732-2) (dense RL) | adversarial background agents trained on naturalistic data, non-critical states removed | safety-critical states | learned sampling | on-track tests | "3 to 5 orders of magnitude" faster evaluation | rare events need biased sampling and a correction for it | [abstract-level via search] |
| | VerifAI / Scenic (Seshia group) | scenario programs and counterexamples | scenario parameters | falsification samplers; counterexample rate and scenario diversity metrics | rule-book metrics | a library of 25 Scenic programs in one paper | counterexample-guided retraining in some demos | [summary] |
| | Waymo Carcraft, vendor scenario-library practice | real encounters plus derived variants; field disengagements added back as regression tests | scenario | variants reproduce a problem and probe similar ones | deterministic re-run after each software change | Applied Intuition blog: stale scenarios return to the regression set | vendor sources, not papers | [summary] |
| Incident management | [RCACopilot](https://arxiv.org/abs/2305.15778) (Microsoft) | incident handler (per alert type), diagnostic information, past incident with root-cause category | alert type selects the handler; then similarity = 1/(1+distance) x exp(-alpha x time gap) over FastText vectors trained on own incidents | alpha=0.3, K=5, top K drawn from different categories as demonstrations | LLM predicts a category and writes an explanation; engineers use it | accuracy "up to 0.766"; collection component in use for over four years | heterogeneous incidents; prompt length; time decay needed | [read] |
| | [Ahmed et al.](https://arxiv.org/abs/2301.03797) | past incident text | semantic and lexical similarity | fine-tuned vs zero-shot LLM | human evaluation by incident owners | more than 40,000 incidents | text only | [abstract] |
| Case-based reasoning | Aamodt and Plaza 1994 (retrieve, reuse, revise, retain) | case = problem, solution, outcome | indexing | similarity | revise step tests the adapted solution | n/a | known issues: swamping (utility problem, Minton 1990), maintenance | [memory] |
| | Smyth and Keane, IJCAI 1995 ([paper](https://ijcai.org/proceedings/1995/50)) | case competence classes: pivotal, auxiliary, spanning, support | coverage and reachability | footprint deletion removes auxiliary cases first, pivotal last | n/a | deleting critical cases can make some problems "permanently unsolvable" | Zhu and Yang 1999 argue deletion cannot guarantee a coverage lower bound and propose addition policies | [summary] |
| Continual learning | [GEM](https://arxiv.org/abs/1706.08840), [Tiny episodic memories](https://arxiv.org/abs/1902.10486), [MIR](https://arxiv.org/abs/1908.04742), [PER](https://arxiv.org/abs/1511.05952) | small replay memory; prioritised transitions | sample id | GEM: constrain the loss on memory not to increase; MIR: retrieve samples most interfered by the update; PER: replay by priority | the constraint itself | tiny memories: gains of 7% to 17% with a single example per class; PER beats uniform replay on 41 of 49 Atari games | selection of what to replay matters more than size | [abstract] |
| Guardrails | [AgentSpec](https://arxiv.org/abs/2503.18666) | rule = trigger, predicate, enforcement (DSL) | trigger event | rules evaluated at runtime | LLM-written rules checked on embodied scenarios | rules by o1 few-shot: 95.56% precision, 70.96% recall; over 90% of unsafe code executions prevented; millisecond overhead | generated rules miss violations (recall) | [read] partial |
| | [GuardAgent](https://arxiv.org/abs/2406.09187), [AGrail](https://arxiv.org/abs/2502.11448) | guardrail code generated per request; demonstrations retrieved from a memory of earlier tasks / lifelong, adaptive safety checks | request | memory retrieval | executed code is deterministic | GuardAgent: over 98% and 83% guardrail accuracy on two benchmarks | text/web agents | [abstract] |

Licences: ASPIRE Apache-2.0 and CaP-X MIT [repo]. RoboFAC, Guardian, RESETTLE, ReasoningBank, ToolMaze, GuardAgent, AGrail, SWE-Exp and AutoManual release code or data, but I did not check their licences.

---

## 3. What the sources agree on, and where they disagree

| Topic | Convergent finding | Disagreement or gap |
|---|---|---|
| Unit of storage | The record is **conditional**: when it applies, what it says, how it was verified, where it stops. ASPIRE (Trigger/Limits), BASM (applicability, risk, avoidance, recovery), Skill-V (falsifiable contract), Sentry (trigger pattern, repair principle) | No source stores the code diff of the fix. Getafix stores it as an AST pattern, but for human-written fixes |
| Key | A typed failure label first, similarity second | Every work invents its own label set: REFLECT (planning vs execution, 55/45), AHA (7 modes), LIBERO-Recover (4 levels x 6 categories), Sentry (3 types plus fine-grained labels). There is no shared normalisation |
| Exposure | Retrieve at the moment of need, a few records (k=4 to 5) | Persistent-context playbooks (ACE, ExpeL, AWM) are the dominant robotics-adjacent practice and Sentry shows they cost performance |
| Validation | Replay beats judgement. Getafix: same detector. Skill-V: replay. ASPIRE: fresh verifier | A VLM or LLM as the validator is unreliable on contact tasks (FailBench) and optimistic (Xiong et al.: quality labels from later outcomes are "free") |
| Quality control of what enters | Strict admission beats add-all (Xiong et al.; Sentry: no recovery verification costs about 20%; Library Drift) | Rejected attempts: Sentry stores only verified recoveries; RESKILL carries failed retests forward. These are compatible if rejected attempts live in a separate log |
| Forgetting | Retire by outcome with a cap (Library Drift), keep pivotal cases (Smyth and Keane) | Premature retirement hurts (Library Drift: -0.019); no robotics evidence |
| Scale | Hundreds to tens of thousands of records (RCACopilot: a year of incidents; Getafix: thousands of changes; Memento: K plateaus at 4) | Robotics memories in the survey are tiny (DROC: 5 + 7 tasks). A flat-retrieval degradation beyond about 64-128 skills is quoted in [module-radar.md](module-radar.md) [repo, second-hand] |

---

## 4. Design for ANTS

Everything in this section is `[proposal]` unless it cites a source.

### 4.1 Records

Three levels, mirroring the repair literature's symptom -> pattern -> fix hierarchy (Getafix, FixMiner) and robotics recovery levels (LIBERO-Recover):

```
symptom (observable)  ->  mechanism (validated cause)  ->  fix (what to do)
(lift, close_gripper,     stale_pose | slip |             re-localize before approach |
 closed_on_empty)         width_mismatch                  lift-and-check | measure radius
```

The mapping is many-to-many: one symptom has several mechanisms, and one mechanism shows up as several symptoms. Retrieve by symptom (the only thing visible at run time), store fixes by mechanism, and make the symptom-to-mechanism link an explicit, tested edge.

**A. Normalised failure signature** (computed from the trace and observations only; never from the attack label):

```python
@dataclass(frozen=True)
class FailureSignature:
    phase: str                 # KeyframeKind at the failure: approach|grasp|lift|transport|release|retreat|setup
    primitive: str             # allow-listed call that failed, or "program" for a crash
    status: str                # CallRecord.failure_code or EpisodeTrace.termination_reason (closed enum)
    deviation: tuple[tuple[str, int], ...]  # observables bucketed on a log scale, e.g. (("pose_err_cm", 3), ("aperture_at_close", 0))
    object_role: str | None    # "bowl", "plate": roles, not instance names
    def key(self, level: int) -> str:
        # L1 phase|status   L2 + primitive   L3 + deviation + object_role
        ...
```

Why levels: the same string drives three behaviours that want different granularity: dedup in the corpus (L3), retrieval (L2 then L1 as fallback, as Sentry falls back to type), and the K=3 escalation counter (L2). Make the level of each use a logged config value.

**B. `FailureCase` (corpus entry).**

| Field | Content | Reason |
|---|---|---|
| `case` | existing `CaseSpec` (task, seed, perturbations, `split`) plus simulator and harness version | exact replay |
| `found_by`, `trace_ref` | policy id, run dir | audit |
| `outcome_kind` | `task_fail` / `timeout` / `unsafe` / `program_error` | N11: a crash is a held case, not a failure |
| `signature` | `FailureSignature` | matching |
| `boundary` | smallest failing severity and largest passing severity found by a shrink along the perturbation | the case at the edge is the most informative regression case; also bounds the severity calibration of C16 |
| `feasibility` | oracle result and method (scripted oracle or IK check) | C16: an unwinnable case makes the gate unsatisfiable |
| `determinism` | replays n, agreeing k | flaky cases (Google: about 1.5% of runs flaky [summary]) are quarantined from the gate and counted, not silently dropped |
| `mechanisms` | list of (mechanism, confidence, how validated: `intervention` / `rule` / `vlm`) | see 4.2 |
| `status` | `open` -> `fixed(by policy)` -> `guarded` -> `retired`; or `flaky`, `infeasible` | lifecycle |
| `sampling_prob` | probability the adaptive planner had of drawing this case | importance-weighted rate estimates (4.5) |
| `origin` | `acceptance_adversary` / `field` / `human_demo` | never `held_out` (4.6) |

**C. `CorrectionRecord`** (built by the orchestrator after a gate decision, because only the orchestrator sees both systems):

| Field | Content |
|---|---|
| `signature_keys` | L1, L2, L3 keys of the class it answers |
| `mechanism` | closed list, starting from the discussion's §4.4 hypothesis: stale_geometry, unverified_action, hard_coded_constant, frame_mismatch, planner_infeasible, grasp_slip, perception_invalid, settle_timing, sequencing |
| `scope` | task family, skill, phase, embodiment, API version range |
| `precondition_code` | runnable check on current observations (ASPIRE: "code or it is nothing") |
| `avoid_when` | negative applicability and risk cues (BASM) |
| `fix.kind` | `constraint` / `idiom` / `patch` / `recovery` / `monitor` / `new_skill` / `human_demo` |
| `fix.rule_text`, `fix.code_sketch`, `fix.diff` | the generator-facing rule, an idiom, and the actual diff between rejected parent and accepted child program |
| `check_code` | the same field as `Constraint.check_code`, with a typed signature (4.4) |
| `recovery` | `level` (L1 retry, L2 adapt, L3 restore object state, L4 clear environment), routine, post-condition, max attempts, safe envelope |
| `evidence` | evidence case ids, neighbour case ids and pass rate, gate decision id, parent and child policy ids |
| `admission` | `candidate` -> `replayed` -> `neighbour_verified` -> `verifier_verified` |
| `stats` | `retrieved`, `applied`, `helped`, `harmed`, `gate_rejected`, `last_used` |
| `lifecycle` | `supersedes`, `conflicts_with`, `absorbed_into` (a `Skill` id), status `active` / `shadowed` / `absorbed` / `deprecated` |
| `provenance` | generator model and prompt hash, source (`adversary` / `human_demo` / `autonomous_mode`), cost |

Links to existing types: `Constraint` stays the one message from System 2 to System 1 and its fields are unchanged; `Constraint.failure_signature` becomes `FailureSignature.key(2)`. A `CorrectionRecord` references one or more constraint ids. `Skill.constraints`, `Skill.evidence` and `Skill.precondition` are filled from the record when `fix.kind == "new_skill"` or the record is `absorbed`. Add `harm_count` next to `help_count` on `Skill`.

**D. Rejected attempts** go to a separate append-only `attempts` log (C10 says to log every constraint). They are not retrievable as positive advice. They may be shown as "tried and failed on this class" when the same L2 class recurs, which is the RESKILL pattern (carry failed retests forward) without the Sentry risk (a lesson from a failed repair misfires).

### 4.2 Diagnosis by intervention, not by label

The simulator can test a cause, which none of the robotics works above exploit (they rely on VLM or LLM judgement). For each failed case, run cheap counterfactuals:

| Intervention | Question | Reading |
|---|---|---|
| remove the perturbation | does the incumbent pass the nominal case? | necessary condition for "caused by the perturbation" |
| restore one perturbed parameter at a time | which parameter flips the outcome? | attribution; the shrink in `boundary` is the same loop |
| privileged state in place of a perceived pose | does ground truth fix it? | perception or geometry mechanism |
| scripted oracle on the perturbed case | is the case winnable? | feasibility (C16) |
| apply the candidate fix only | does the failure vanish? | that is the validation in 4.3 |

A mechanism label is `validated` only if an intervention supports it. Otherwise it stays `rule` or `vlm` with its confidence, and paper-vs-docs C10's advice applies: do not use the model's own confidence as the trigger, use disagreement or a failed check. EmbodiSkill's distinction (a failure can mean "the guidance was wrong" or "the executor did not follow valid guidance") maps to one more check: if a constraint was in context and the program still failed, run its `check_code` on the program. If the check fails, the generator ignored the rule (AutoManual reports the same behaviour); if it passes, the rule was insufficient.

### 4.3 Matching, retrieval and avoiding the wrong fix

| Mode | Use | Strength | Risk of wrong fix | Evidence |
|---|---|---|---|---|
| Exact / hierarchical signature | primary, L3 then L2 then L1 | deterministic, auditable, cheap | too coarse at L1 (many mechanisms) | Sentry: type-only about -11.3% relative to type plus label |
| Rule-based filters | hard gates: embodiment, API version, `status == active`, `precondition_code` holds, not shadowed | removes inapplicable records outright | none if the precondition is correct | ASPIRE precondition; BASM applicability |
| Embedding | rank inside the candidates; scene features (DINOv3 key from Q9) and a text embedding of the symptom narrative | handles unseen wording and scene differences | text similarity retrieves a lookalike (DROC: handle vs knob) | DROC visual retrieval; RCACopilot trained its own embeddings |
| Usage and time weights | multiply the rank by a lower bound on help rate (Beta posterior with `helped`, `harmed`, `gate_rejected`) and a time decay | stops popular-but-wrong records dominating | raw `help_count` rewards early records | RCACopilot time decay (alpha 0.3); N13 pheromone; Xiong et al. |
| LLM rerank | pick k=1 to 3 from the shortlist | SWE-Exp: removing it costs 3.8 points | an LLM judge can be optimistic | SWE-Exp; FailBench for the judging risk |

Recommended cascade: hard filters, then signature level 3, 2, 1 until at least one candidate, then rank by (label overlap) x (lower bound of help rate) x (time decay), with diversity (top-K from different mechanisms, as RCACopilot takes top-K from different categories), then an optional LLM rerank, cap k at 3 to 5 (Sentry k=5 best, k=3 and k=10 worse; Memento plateau at 4).

Ways a wrong fix gets in, and the guard:

1. **Lookalike symptom, different mechanism.** Guard: `avoid_when`, mechanism check by intervention (4.2), and a "misfire log": a record whose application was followed by a gate rejection gets `gate_rejected += 1` and is down-ranked for that L3 key only.
2. **Experience-following** (Xiong et al.): the generator copies the record's fix. Guard: the fix must pass 4.4 before it counts; never add an applied-and-unverified program back to the library.
3. **Stale record** after a model, API or harness change. Guard: `api_version` range, and re-verify on retrieval after a change (SkillForge idea, SkillForge/Library Drift are [abstract]).
4. **Bloat and context collapse** (ACE names both brevity bias and collapse). Guard: only retrieved records enter the prompt (Sentry); the rest of the library stays outside; incremental, never whole-list rewrites; a cap on active records (Library Drift) with retirement by outcome and a grace period.

Below about 50 records, flat signature retrieval is enough; add embeddings when the library passes that or the signature misses near-duplicates (a [proposal] threshold, to be measured).

### 4.4 Validation on reuse, and run-time recovery

**Admission and reuse pipeline** (each stage is logged, each can reject):

| Stage | Check | Source of the idea |
|---|---|---|
| V0 | `precondition_code` holds on the current scene; API version in range | ASPIRE |
| V1 | replay the **evidence case(s)** on the candidate program: does this exact failure disappear? | Getafix (same detector), SWE-style fail-to-pass reproduction tests |
| V2 | **neighbourhood replay**: n fresh cases from the same class (same category, severity within a band of the failing one, new seeds, params re-sampled); require at least m of n | ASPIRE verifier (4/5), "no seed-specific branches" |
| V3 | the per-case regression gate over all seen cases | ANTS gate, Skill-V |
| V4 | static lint in the plan gate: no `case_id` or seed literals, no numeric literal equal to an evidence parameter, no branch on a constant that only the evidence case has | [proposal] overfit detector |
| V5 | re-verification when the harness, API, simulator or generator model changes | SkillForge |
| V6 | fresh verifier agent reproduces the fix from the record text alone, no proposer code | ASPIRE; expensive, use only before sharing a record across tasks |

V2 is what rejects a correction that only fixes one seed. The neighbours are new acceptance-side cases and join the corpus; they are never held-out cases. ASPIRE states its verifier checks that a skill transmits on its source task, not that it transfers [repo]; V2 plus leave-one-task-out transfer tests (4.8) are the cheapest way to start measuring transfer.

**Run-time recovery.** Keep the generated program frozen at test time (the stance of RHO and the TAMP coding-agent paper in [module-radar.md](module-radar.md) [repo]). The library supplies the recovery routine at write time; the run time only dispatches it.

```
program step -> monitor(check_code) -> flag + signature -> dispatch table (signature -> recovery routine)
              -> post-condition check -> resume | next recovery level (L1 -> L2 -> L3 -> L4) | hold + escalate
```

- `PolicyKind = "monitored_program"` already names this shape. The dispatch table is a plain dict compiled into the program from retrieved records, so there is no LLM call at run time by default. An LLM "autonomous mode" stays the approved, budgeted option of [skills.md](../skills.md) §3.
- `Constraint.check_code` gets two roles with one typed signature: `check(window: list[CallRecord], obs: Observation) -> Verdict(flag: bool, reason: str, signature: FailureSignature | None)`. At write time it verifies that the program honours the constraint (ASPIRE precondition; AutoManual's gap that the Planner ignores rules). At run time it is the monitor (Code-as-Monitor returns a flag plus a reason from tracked element positions, with a tolerance in code).
- **Monitors are tested like code, on the corpus.** Positives are corpus failures, negatives are passing cases. Report precision and recall per `check_code` before it is allowed into a runtime. AgentSpec's LLM-written rules reached 95.56% precision and 70.96% recall: expect generated monitors to be precise and to miss cases, so the miss rate must be measured, and a missed failure still falls to the final success predicate. A `check_code` that raises is an error, not a verdict (N11), and runs in the same sandbox as policies (generated code is untrusted).
- **Use structured state, not a VLM, as the monitor input.** FailBench puts VLM detectors near chance on contact-intensive tasks and shows a success bias. Code-as-Monitor itself says it is weak where force direction matters and nothing visibly moves. In simulation ANTS has privileged state; on a real robot use aperture, depth, joint effort and tracked points.
- Recovery levels follow LIBERO-Recover: L1 retry, L2 change the action (grasp point, approach, timing), L3 restore object state, L4 clear the environment. Each routine declares max attempts and a safe envelope. Anything above the allowed level, or an exhausted budget, returns a typed `held` result, never a silent retry loop.
- **Field failures** enter the corpus with `origin = "field"` and are acceptance-side data only if the field deployment is not part of the held-out report. Vendor AV practice does the same with disengagements [summary].

### 4.5 The corpus as a regression asset and a prior for the test planner

**Regression asset.**
- Keep the gate rule exactly as written: no worse on every case seen so far. Spend effort on **order, not membership**: replay the cases most likely to regress first (recently failed, same L2 class as the change, smallest `boundary` margin) and stop at the first regression, as history-based test prioritisation does (RETECS ranks tests by failure history; recent-verdict sorting is one of its baselines). A rejected candidate is then cheap, and an accepted one still pays the full set once.
- Exclude `flaky` and `infeasible` cases from the gate, log them, and report their count. A set that contains them makes "at least as good on every case" unsatisfiable or noisy.
- Keep the corpus as a **deduplicated** set by L3 key, retaining the case with the smallest margin per key plus all cases that are the only members of a class (a simple analogue of Smyth and Keane's pivotal cases). Gate cost then grows with the number of distinct failure classes, not with the number of attacks. Do this only after measuring that gate cost is a problem.
- Every corpus entry is reproducible from its `CaseSpec` and versions, which is what AV vendors rely on when they re-run deterministic scenarios after each software change [summary].

**Prior for the adaptive planner** (Thompson sampling over categories, Beta(1+f, 1+p)):

| Idea | Rule | Support |
|---|---|---|
| Warm start across incumbents | at `reset()`, set alpha_c = 1 + gamma x f_c(previous incumbent), beta_c = 1, with gamma in (0,1]; **failure pseudo-counts only** | Raj and Kalyani: discount the prior parameters to reduce the effect of past observations (non-stationary TS) [abstract] |
| Stop rule uses fresh data only | the "every category confidently robust" certificate (Q0.95 below tau) is computed from post-reset tests only | a warm-started failure prior cannot lower the stop threshold, and no pass pseudo-count can raise it; this keeps C9's caution about the stop claim intact |
| Cross-task prior | alpha_0, beta_0 per (task family, category) from earlier runs, capped at a few pseudo-observations | empirical-Bayes style; cap keeps the planner adaptive [proposal] |
| Do not mix gate replays into the posterior | corpus replays were chosen because they failed once; they are not iid draws from the category | prevents an optimistic failure-rate estimate for the new incumbent |
| Corpus-guided proposals | the proposer's recent-attack context is the open `FailureClass` boundaries: mutate the smallest failing perturbations, keep the eta-uniform share (default 0.2 in the adversary spec) | coverage-guided fuzzers keep and mutate interesting inputs [memory, not checked today] |
| Log the sampling probability of every adaptive draw | `sampling_prob` on each case | adaptive sampling is biased by design; with the draw probabilities a Horvitz-Thompson style estimate is possible later (importance sampling is the standard fix for rare-event validation in AV: Feng et al.; PER corrects its sampling bias with importance weights) |

An adversarially chosen corpus is **not** a robustness estimate. The headline number stays the held-out set drawn from a separate, non-adaptive seed namespace.

### 4.6 Risks: contamination, memorised seeds, one-seed fixes

| Risk | How it happens | Control |
|---|---|---|
| Held-out contamination | a failure on the held-out set is diagnosed into a record or case; or a shared library carries it into a later acceptance run | write-path accepts `origin in {acceptance_adversary, field, human_demo}` only; held-out failures are logged for the report and never reach the diagnoser; assert this in code; tests use disjoint seed namespaces (ASPIRE runs held-out seeds once after the fix is final [repo]) |
| Leakage in the memory ablation | records built from the evaluation task are retrieved at evaluation | SWE-Exp rule [read]: exclude records from the same repository and records created after the target. ANTS: leave-one-task-out and a temporal cut; exclude records whose evidence shares a `(task, seed_namespace)` with the evaluation case |
| Memorised seeds in the program | `if seed == 7: ...` or a constant copied from the evidence parameters | V4 lint; V2 neighbourhood replay with fresh seeds |
| Memorised seeds in the library | a record whose only evidence is one `(seed, params)` and whose retrieval key is that scene embedding: it "works" on replay for the wrong reason | require `neighbour_verified` before `active` for cross-run use; record the neighbour pass rate; show it in the record |
| Corrections that fix one seed | the gate passes because the rest of the set did not exercise the mechanism | V2; also report each record's neighbour pass rate in the run summary |
| Wrong fix retrieved, negative transfer | see 4.3 | `avoid_when`, usage counters including harm, misfire log, record only verified recoveries |
| Context bloat | all accepted constraints in the prompt | retrieve k at most 5; a hard cap on active records; incremental edits only |
| Obsolete or conflicting rules | two constraints push opposite ways; a rule has been absorbed into the program | conflict is tested, not guessed: if a program satisfying A fails B's evidence, mark both `conflicts_with` and let the gate decide a conditional merge (AutoManual's Builder merges and consolidates rules past a size threshold). A rule whose evidence passes under later programs without it is `absorbed` (and moved into a `Skill`); `deprecated` after a grace period, never immediately (Library Drift: premature retirement hurt) |
| Diagnoser mislabels | a VLM judge is biased toward success (FailBench) | success always from the benchmark predicate; mechanism labels carry how they were validated (4.2) |
| Unwinnable cases | perturbation outside what the task tolerates | C16 feasibility check stored on every case |
| Human demo as correction | an escalation demo fixes the case | store as `source = human_demo`, verify with V1-V3 like any other fix; it is expensive, so its record deserves the same neighbour check |

### 4.7 What goes where in the repo layout (AGENTS.md)

- `contracts/`: `FailureSignature`, `FailureCase`, `CorrectionRecord` (shared types, no logic beyond serialisation).
- `adversary/`: signature normaliser, shrink, determinism replay, feasibility, interventions, corpus store, planner priors.
- `orchestrator/`: builds `CorrectionRecord` after a gate decision, runs V0-V4, enforces the held-out write-path rule.
- `synthesizer/`: retrieval and prompt assembly (reads records, never writes them).
- `evalkit/`: split guard, leakage check, metrics.

### 4.8 Minimal ablation design

The arms differ in one thing each, share the frozen generator, simulator, budget and acceptance/held-out split, and are run with at least 3 independent generator runs per arm, since the generated program is deterministic per seed but the generator is not (a program kind needs one rollout per case; the generator variance is across runs). Choose a task where the no-demo arm does not already saturate (Q1, [discussion.md](../discussion.md)), start on the mock backend to test retrieval and conflict logic with known ground-truth fixes, then move to LIBERO-Pro.

| Arm | Memory | Tests |
|---|---|---|
| A0 | none | baseline loop, constraints kept only inside one run |
| A1 | current design: all accepted constraints in context, flat | what the repo does now |
| A2 | A1 but signature-filtered, k at most 5, library outside the context | Sentry's finding (conditional exposure) |
| A3 | A2 plus structured `CorrectionRecord` with fix diff and `avoid_when` | does a richer record help over rule text |
| A4 | A3 plus V2 neighbour verification and V4 lint | do fewer one-seed fixes reach the library |
| A5 | A4 plus run-time monitors and recovery routines | held-out success with monitors on vs off |
| A6 | A4 with warm-started planner priors vs cold start vs uniform | failures found per rollout, tokens to robust |

Controls that make a null result interpretable: a **placebo library** (random records, Sentry's random-retrieval control) and **shuffled signatures** (same records, wrong keys).

Metrics, all from logged runs: held-out success with Wilson intervals over at least 50 cases (as AGENTS.md and disc. §10.5 already require); tokens and sim time to robust; regressions caught by the gate; library hit precision (retrieved record's fix applied and passed); wrong-retrieval rate (applied then gate-rejected or harmful); neighbour pass rate of each admitted fix; monitor precision and recall per `check_code`; recovery success per level; failures found per rollout; prompt tokens contributed by memory. Transfer: leave-one-task-out with the library built from run times earlier than the evaluation. Pre-register the primary comparison (A2 against A1 on tokens to robust, with held-out success non-inferior) and a kill criterion, in the style AEGIS used for its probe study [abstract]. A first cheap result is possible without LIBERO: A1 vs A2 on the mock backend.

---

## 5. Unsupported or unsolved in the literature

1. No measured with/without comparison of a correction library for LLM-written robot programs under adversarial perturbation. DROC's gain is in the number of human corrections on 5 + 7 tasks with the authors as users [read]; FRAMES' recovery loop is "ongoing" [abstract]; the strongest numbers (Sentry, BASM, SWE-Exp) are text or code-repair agents.
2. No shared failure-signature normalisation across robotics works; each taxonomy (REFLECT, AHA, LIBERO-Recover, Sentry) is incompatible with the others.
3. Retrieval wrong-fix rates are not reported in robotics. Only the "misaligned experience replay" and "skill imitation trap" analyses (Xiong et al., BASM) measure the harm, in non-robot agents.
4. Nobody measures **generalisation of a correction** (the share of fresh neighbours it fixes). ASPIRE's verifier is the nearest and it measures transmission on the source task [repo].
5. Conflict and obsolescence handling for robot rule libraries is absent; AutoManual's consolidation and Library Drift's retirement are the closest and are not robotic.
6. Warm-starting an adversarial test planner from a failure corpus is, as far as I found, not published for robot manipulation. The pieces exist elsewhere: history-based test prioritisation (RETECS), discounted Thompson sampling, importance sampling for rare events (Feng et al.). The search was limited; absence is not proof.
7. Interventional diagnosis in a simulator (removing or restoring a cause to validate a mechanism) is not used by any of the failure-explanation systems read; they rely on VLM or LLM judgement.
8. Sim-to-real portability of a stored recovery record is unaddressed. Records should carry the observation set their `check_code` needs so a real-robot port can say what is missing.

---

## 6. Unverified items and caveats

- Semantic Scholar "cited by" was pulled for REFLECT, DROC and Code-as-Monitor only; AHA was rate-limited. The 2026 papers were found by web search and Semantic Scholar titles, not by exhaustive citation traversal.
- [abstract] sources were not read in full: Inner Monologue, Guardian, RoboFAC, FailSafe, FailBench, FRAMES, RESETTLE, FLARE, FIPER, AEGIS, LYRA, ARCHITECT (summary also from search snippets), Harness VLA, Skill-V, SkillForge, Library Drift, RESKILL, EmbodiSkill, ReasoningBank, ACE, Dynamic Cheatsheet, ExpeL, CLIN, AWM, Xiong et al., Memento (K plateau only), Agentless, ChatRepair, FixMiner, GuardAgent, AGrail, GEM, tiny episodic memories, MIR, PER, Ahmed et al.
- [read] sources were read only in the parts quoted: REFLECT, DROC, Code-as-Monitor, AHA, Sentry, BASM, SWE-Exp, Getafix, RCACopilot, LIBERO-Recover, AutoManual, Voyager, RAPID, AgentSpec, RETECS.
- `[memory]` items not checked today: Aamodt and Plaza's four-step cycle, Minton's utility problem, coverage-guided fuzzing corpora.
- `[summary]` items: Google's 1.5% flaky-run figure comes from a search summary of a 2016 blog; Smyth and Keane and Zhu and Yang from search summaries; Waymo Carcraft, Applied Intuition, VerifAI/Scenic details, Feng et al.'s speed-up from search summaries. Vendor blogs are not primary evidence.
- LIBERO-Recover's scenario count differs between the arXiv listing and the PDF text (version drift). The "flat retrieval degrades beyond about 64-128 skills" figure is quoted second-hand from [module-radar.md](module-radar.md).
- Licences were not checked except for ASPIRE and CaP-X.
- Nothing here was run on ANTS data. Every threshold in section 4 (neighbour count and pass fraction, gamma, retrieval k, record-count threshold for embeddings, grace period) is a starting value to tune on the acceptance set only.

## 7. Suggested first steps (smallest vertical slice)

1. A pure function `signature_from_trace(trace) -> FailureSignature` with tests, replacing the category-keyed signature; keep `Constraint.failure_signature = key(2)`.
2. Extend the history JSONL into `FailureCase` with replay determinism, feasibility and `sampling_prob`; no shrink yet.
3. `CorrectionRecord` stub built after the existing gate decision; log rejected attempts separately.
4. On the mock backend: A1 vs A2 retrieval, with a placebo library, before any LIBERO run.
