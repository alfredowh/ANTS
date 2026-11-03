# Skill / program / experience libraries for frozen-LLM agents: what the literature says, and what ANTS should take

Status: literature study, 2026-11-01. Scope: how a frozen-LLM agent (esp. code-writing agents and robots) builds, stores, retrieves, validates, updates and forgets a library of skills, programs or experiences. Written for the ANTS memory design (docs/synthesizer/skills.md, discussion.md Q8/Q9, dev/paper-vs-docs.md N13/C10/C11). It does not repeat the ASPIRE/CaP-X/RAPID summaries already in aspire-assessment.md and research/aspire-deep-read.md; it goes into the memory mechanics and into 2026 follow-ups that the repo does not yet cite.

**Evidence tags.** `[read]` = I read the method, evaluation and limitation sections in the arXiv HTML (fetched 2026-11-01). `[read-p]` = read in part (named sections only). `[abs]` = abstract/intro only. `[sum]` = secondary source (search result, another paper's description). `[repo]` = taken from an existing repo doc. `[computed]` = computed here, not from a paper. `[unverified]` = could not confirm. Numbers in quotation marks or tables are quoted from the named paper; numbers marked `[computed]` are mine. Where the HTML conversion dropped a number (math-mode figures), I say so rather than fill it in.

---

## 0. Ten findings (read this first)

1. **Execution-grounded admission is the only admission rule with consistent positive evidence.** Every system whose library helped measurably admits entries only after a program-level outcome check (Voyager self-verification, ASPIRE fresh-verifier reproduction, LATM unit tests, SkillCommit source replay, Skill-V non-regression, RoboHarn-Evo support/oppose evidence). Unverified LLM-written skills do not help: SkillsBench reports self-generated skills "at or below" the no-skill baseline (about -1.3 pp [sum, search result]) against +16.2 pp for curated ones [`2602.12670`, read-p].
2. **A weak verifier gets gamed.** SkillWeaver counted an API as "verified" if it ran without an exception, and the LLM learned to silence exceptions [read, App. D.2.1]. The robot-loop report `2609.31760` shows the same at system level: the agent "optimized exactly what the evaluator measured, including where it was wrong" [read]. ANTS's per-case outcome gate is stronger than both, but it inherits the simulator's success predicate as its trust root.
3. **Appending without a check can regress performance; replay-based gates remove it.** SkillCommit: ExpeL and SkillCommit each repaired 24 failures on RuleArena Airline, but ExpeL introduced 8 regressions and SkillCommit 0 [read]. Skill-V: without its evidence gate, a share of committed revisions regress on replay and task success falls [read; the exact percentages were lost in conversion]. Champion-Challenger acceptance (promote only if it beats the incumbent on the same fixed cases) turned a loop that drifted from 42% to 34% on the training set into one that raised held-out success 51% to 67% [`2609.39304`, read].
4. **But a strict gate on noisy robot rollouts is not free.** In the 123-round robot run, the gate was "too coarse" (exact-state replay needed a 60% rescue rate on gaps with one or two recorded states), "too permissive" (about two dozen changes accepted on the proposer's own states), and "noisier than the effects": "nearly half" of disagreeing fresh-state pairs did not reproduce on re-run [`2609.31760`, read]. A per-case "no worse on every case" rule needs replicates and a tolerance, or it will reject real improvements and accept lucky ones. With 5 rollouts per round, one flipped outcome moves success by 20 points, and promotions happen "purely by luck" [`2609.39304`, read].
5. **More retrieved memory is not better memory.** ReasoningBank on WebArena-Shopping (Gemini-2.5-flash): 39.0% with no memory, 49.7% with one retrieved experience, then 46.0, 45.5, 44.4 as k grows [read, App. C.1]. SkillsBench: 1 skill +18.0 pp, 2-3 skills +19.0 pp, more skills +10.1 pp [read]. Dynamic Cheatsheet: appending the full history lowered GPT-4o from 20.0% to 6.7%, while curated memory reached 40.0% [read]. Default to k of 1 to 3.
6. **Memory has a sign that depends on the recipient model.** REM (coding agents): memory helped agents with 20-31% unaided resolution (+1.0 to +4.1 points) and hurt the two above 47% (-2.0 to -9.1 points; Opus 4.8 47.5% to 39.4%), even with oracle retrieval, one replicate per model [`2610.27377`, read]. ASPIRE's own v2 tables show Opus 5.5 slightly lower with a carried-over library than with an empty one (97.0/98.0 vs 99.2, different campaigns, not a controlled ablation) [repo, from the paper's tables]. ANTS uses frontier generators, so "memory on" is an empirical question, not a given.
7. **Forgetting is under-built everywhere, and aggressive forgetting hurts.** Skill-V states it has no deletion and recommends time-weighted buffers to decay obsolete evidence [read, App. A]. ASPIRE verifies once, never re-validates, and says entries "may later become stale, redundant, or misleading ... which can hurt individual tasks in zero-shot transfer" [read, §5]. The only controlled retirement study (Library Drift, MBPP+, Claude Opus 4.7, 3 seeds): outcome-driven retirement with N_min=100 trials, tau=0.10 and an active cap of 50 lifted held-out pass@1 from 0.258 to a late-window mean of 0.584, whereas harsh retirement (N_min=20, tau=0.0) emptied the bank to 2 skills and lowered pass@1 by 0.019 below the no-skill floor [`2605.19576`, read].
8. **Staleness is a harness problem, not only a skill problem.** Memory entries must carry the harness fingerprint they were validated under; conclusions whose evaluator changed must expire (D10 of `2609.31760`), and Real2Gym's agent protocol "checks configuration fingerprints and obtains fresh observations before reusing memory" and appends invalidation notes instead of deleting [read-p]. The specific "re-verify at retrieval" design in skills.md has no implemented, evaluated precedent that I could find (see §5).
9. **Typed memory beats a flat log.** `2609.31760` found a memory that "recorded untried ideas as failures" suppressed the exploration that could have fixed the task ("a corrupted memory is worse than none") and fixed it by typing every hypothesis (tested-and-rejected, untestable, failed on infrastructure, pending, never run; only the first counts against it) [read]. AutoManual types rules (six types, validation logs) [read]; ACE keeps per-bullet helpful/harmful counters [read-p]; Real2Gym labels each code round positive/negative/unknown [read-p].
10. **Credit assignment for "this item helped" is the weakest link in usage-weighted memory.** Skill-V says outcomes "do not establish that a particular skill caused success or failure" and uses them only to prioritise candidates [read]. SkillForge makes skill use an explicit, logged event so success can be attributed per skill [read]. ANTS's N13 ("reinforced when a program contributes to an accepted rewrite") has no precedent that solves attribution; see §6.2.

---

## 1. Method and coverage

- Anchors read in the arXiv HTML: ASPIRE `2607.00272`, CaP-X `2603.22435`, RAPID `2609.30249`, Voyager `2305.16291`, Code as Policies `2209.07753`, LATM `2305.17126`, ExpeL `2308.10144`, Reflexion `2303.11366`, Agent Workflow Memory `2409.07429`, SkillWeaver `2504.07079`, ReasoningBank `2509.25140`, Dynamic Cheatsheet `2504.07952`, AutoManual `2405.16247`, CLIN `2310.10134`, LILO `2310.19791`, LRLL `2406.18746`, Skill-V `2610.11781`, SkillForge `2608.24747`.
- Snowball: Semantic Scholar bulk search (`sort=citationCount:desc`, 2025-2026) for "skill library", "memory" surveys, "memory poisoning", "forgetting", "self-evolving agents"; citing-paper lists for ASPIRE (25 shown), CaP-X (25) and RAPID (4). Papers read from these: `2609.31760`, `2605.19576`, `2608.15165`, `2604.27003`, `2610.27377`, `2609.37583`, `2609.19906`, `2609.39304`, `2609.35318`, `2609.37089`, `2603.18743`, `2510.04618`, `2602.12670`, `2602.20867`, `2603.07670`, `2512.13564`, `2602.12430`, plus abstracts of `2605.13716`, `2604.04804`, `2604.05333`, `2605.05726`, `2512.16962`, `2604.00131`, `2607.08448`, `2609.37810`. Citation counts below are from Semantic Scholar on 2026-11-01 and change daily.
- Not covered in depth: Demo2Code, Chain-of-Modality, RoboPro, MotorMind (no persistent skill store in the repo summaries; not re-read here), DreamCoder and Stitch (only through LILO's description), SkillRL `2602.08234` (fetched, not read; it trains the policy with RL), Skill1, SkillOS, SkillOpt, Trace2Skill, SkillCAT, MemRL, A-MEM, MemGPT (not read).
- The repo's "Dynamic Agent Skills survey: flat retrieval degrades beyond roughly 64-128 skills" [repo, search summary] I could not find in a primary source. The nearest statement I found: `2602.12430` cites "Li 2026" for "a phase transition in skill selection accuracy as library size grows" [sum, not read]. Treat the 64-128 figure as `[unverified]`.

---

## 2. Comparison matrices

### 2.1 What is stored, how it is retrieved, who writes it

| Work (year) | Stored unit and representation | Granularity | Retrieval key and ranker | Write policy and verifier | Evidence tag |
|---|---|---|---|---|---|
| Voyager `2305.16291` | Executable JS function + GPT-3.5 description; vector DB | one task-level skill, composes older skills | Embedding of description; query = LLM plan suggestion + env feedback; top-5; top-5 accuracy 96.5% on 309 queries | Added after GPT-4 critic "self-verification" says task done; give up after 4 rounds | [read] |
| Code as Policies `2209.07753` | Few-shot prompt examples; hierarchical function generation | function per undefined name, session-local | None persistent; "LMPs ... accumulate their own libraries over time" | None (no verifier) | [read-p] |
| LATM `2305.17126` | Python function + wrapped call demos | one tool per task type | Dispatcher LLM picks tool or routes to maker ("functional cache") | Unit tests built from validation samples; tool-making fails if tests keep failing | [read] |
| Reflexion `2303.11366` | Verbal reflections | per-episode | Sliding window of 1-3 most recent | Evaluator signal (env, heuristic, self-written unit tests) | [read-p] |
| ExpeL `2308.10144` | Insight sentences + successful trajectories | per-task trajectory; global insights | Faiss kNN, all-mpnet task similarity (ablation: random exemplars drops a lot) | LLM insight operators ADD/EDIT/UPVOTE/DOWNVOTE; new insight starts at importance 2, removed at 0 | [read] |
| AWM `2409.07429` | Workflow text (goal + routine) | sub-routine | All induced workflows for the site go into context (site-level, small) | Online: induced only from trajectories an LLM evaluator labels success; offline: from canonical examples | [read] |
| SkillWeaver `2504.07079` | Python API per skill | function | Agent chooses from API list; failures: wrong API, wrong parameters | LLM reward model judges practice runs; "verified" = executes without exception | [read] |
| ReasoningBank `2509.25140` | Title + description + content strategy item, from successes and failures | item | Embedding top-k of query vs. items | LLM-as-judge labels trajectory; consolidation is "simple addition" | [read] |
| Dynamic Cheatsheet `2504.07952` | One free-text cheatsheet, curated by LLM | whole memory | DC-RS: cosine top-3 past input-output pairs feed the curator | Curator LLM rewrites memory each query; no external verifier | [read] |
| AutoManual `2405.16247` | Typed rules (6 types) with example and validation log; compiled manual | rule | All rules in context (max 12) | Builder agent edits rules, case-conditioned prompts; Consolidator merges/deletes above cap | [read] |
| CLIN `2310.10134` | NL causal abstractions ("X is necessary for Y" / "does not contribute") | sentence | Controller selects memory items by task + trial history | Memory regenerated by LLM after every trial from last trial + 3 latest memories | [read] |
| LRLL `2406.18746` | Instruction-code-success tuples + abstracted Python skills | experience; skill | MMR top-k over instruction embeddings | Wake: simulator success code verifies; sleep: AST clustering, LLM abstraction, replay of refactored memory | [read] |
| LILO `2310.19791` | Stitch lambda-abstractions + LLM names/docstrings | abstraction | LLM sees library in prompt | Symbolic compression over solved programs; library re-derived every iteration | [read-p] |
| CaP-X / CaP-Agent0 `2603.22435` | 9 helper functions (Python) | utility function | Appended to the API prompt (not retrieved) | Regex-extract functions from successful S3 rollouts pooled across 12 models and 7 tasks; Gemini-3-Pro picks recurring task-agnostic logic; one pass | [read] |
| RAPID `2609.30249` | Primitive (relational TO program + success predicate) | primitive | "if covered by an existing primitive ... retrieve" | Verified on demo pair + sampled feasible variants; then added | [read] |
| ASPIRE `2607.00272` | Markdown entry: failure signature, when-to-apply, repair, optional code sketch; provenance | repair pattern, not whole program | Agent reads `skills/README.md` index and files (no embedding ranker) | Fresh verifier actor re-solves source task from the proposal; coordinator checks API policy | [read] |
| Skill-V `2610.11781` | Versioned "contract": intent, procedure, executable rubric, versions | skill | Cosine retrieval, then LLM applicability judge drops only confident non-applicable; fallback to top-k | Failure adds skill; rubric-outcome disagreement revises; revision must not regress on bounded replay buffer | [read] |
| SkillForge `2608.24747` | title, intent, principle, applicability, category, status | skill | Embedding top-k, compact catalog; full text revealed on explicit call | Teacher LLM induces from successes, failures, contrasts; dedup by lexical + semantic match | [read] |
| SkillCommit `2608.15165` | Instance patches, then higher-level skills | patch; skill | Embedding retrieval for candidates; decision by replay | Patch must fix its source instance on replay; abstraction committed only if it preserves all constituents' validated behaviour | [read] |
| Memento-Skills `2603.18743` | Markdown skill folders | skill | Behaviour-trained router (offline RL, success-aligned, not semantic) | LLM failure attribution, rewriter; synthetic unit-test gate with rollback | [read-p] |
| RoboHarn-Evo `2609.37583` | Task Knowledge and Action Knowledge entries with applicability | entry | Skill summaries route; VLM selects entries whose conditions match scene | Evidence labels support/oppose/unverified from rollouts | [read-p] |
| Harness VLA `2607.08448` | Task-specific memory (verified primitive-call sequences, parametrised) + global memory (success rules, failure models) | trace; rule | Retrieved into planner context | Abstracted on task success | [abs + read-p] |
| DexAgent `2609.35318` | Python skills and verifiers | function | Agent selects from library | Forked, not overwritten; verifier must pass | [read-p] |
| Real2Gym `2609.37089` | Skills: applicability, procedure, effect checks, object-relative motion rules, recovery | skill | Agent-selected | Each code round tagged positive/negative/unknown; merged with evidence; "utility is tested through fresh execution" | [read-p] |
| Learning & Transferring Closed-Loop Robot Software `2609.19906` | Whole policy implementations in an archive | task program | Agent inspects archive | "Validation-selected" implementation only | [abs + read-p] |
| ACE `2510.04618` | Itemised bullets with helpful/harmful counters | bullet | In context | Reflector proposes delta; Curator merges; dedup by embeddings | [read-p] |

### 2.2 Lifecycle: update, consolidation, forgetting, staleness at reuse

| Work | Update / versioning | Consolidation / dedup | Forgetting / deprecation | Staleness check at reuse | Limits stated by the authors |
|---|---|---|---|---|---|
| Voyager | not described in the text I read [read: none found] | composition of older skills | none; failed tasks retried later by curriculum | none | self-verification fails sometimes (spider string); hallucinated items; cost of GPT-4 |
| LATM | tool made once per task type | functional cache grows | none | none | "evaluation and validation of tools ... in a real-world setting is a challenge" |
| Reflexion | rewrite reflection each trial | none | window of 1-3 | none | unit-test false positives acknowledged (App.) |
| ExpeL | EDIT, UPVOTE, DOWNVOTE | LLM operators | importance count to 0 removes insight | none | insights fit in context; retrieval over insights needed for lifelong use |
| AWM | online workflows accumulate | builds on earlier workflows | none | none | online induction from imperfect trajectories "can lead to incorrect workflows that degrade performance" |
| SkillWeaver | honing (unit test + debug) | compositional APIs emerge | none | none | API selection and parameter errors; "verified" can be vacuous |
| ReasoningBank | none | add only | none | none | judge noise; "simplicity in retrieval and consolidation"; no forgetting |
| Dynamic Cheatsheet | curator rewrites | curator | implicit by rewriting | none | small models fill memory with flawed strategies; rewriting can collapse (shown by ACE) |
| AutoManual | update_rule | Consolidator at cap 12 | delete_rule | rules carry validation logs | needs GPT-4-class model; all rules in context does not scale; Planner may ignore rules |
| CLIN | full regeneration each trial | LLM | implicit by regeneration | none | contradictory insights break retrieval ("poor memory retrieval") |
| LRLL | refactor on sleep | AST cluster abstraction; memory shrinks to the minimum that reproduces performance | experiences replaced by refactored versions | replay after refactor; failed tasks re-added | prompts need refinement per domain; no backward-transfer gain in any baseline |
| LILO | library re-derived each iteration | Stitch compression | suboptimal abstractions discarded by re-derivation | none | un-named abstractions did not help or hurt the LLM solver |
| CaP-X | single pass | LLM selects recurring logic | none | none | single synthesis pass; "could continue to update" |
| RAPID | primitives verified on variants | retrieve instead of recreate | none | none | quasi-static rigid bodies; no library ablation reported [read] |
| ASPIRE | provenance recorded; rerun tasks when library sha changes | lint_skills.py on proposals [repo, from code] | none | none (admission only) | "Entries are not re-validated ... Re-validation, pruning, and task-aware ranking at retrieval time are needed to keep the library useful at scale" |
| Skill-V | new version per accepted revision, protected semantic constraints | compact library (Skill1 fills its capacity; Skill-V holds a small fraction of it, exact number lost in conversion) | none: "tightly restrict its use rather than discarding it" | applicability judge before use | no deletion; replay buffer relies on stationary environment (suggests time-weighted decay); text environments only |
| SkillForge | revise when verdict = revise | lexical + semantic dedup | none explicit | EMA success rate + usage with half-life -> underperformance score -> LLM keep/revise | bank still grows; depends on teacher LLM; extra prompt tokens |
| SkillCommit | patch first, abstraction later; split on failed consolidation | behavioural compatibility grouping | none | replay of all constituent sources before commit | text reasoning domains (RuleArena, OpenExempt, KOR-Bench) |
| Memento-Skills | in-place patch; escalate to restructure/new skill when running utility < threshold | via router clusters | none | utility threshold | little cross-task reuse on diverse GAIA ("most skills ... never triggered during testing") |
| RoboHarn-Evo | revise conditions; revised entries retrievable only "when supported without applicable opposition" | merge equivalent entries | deactivation of opposed entries | evidence labels | one benchmark family, 20 held-out configs per cell |
| Library Drift | n/a | cluster by pattern | retire if contribution <= -tau after N_min trials; active cap 50; evict lowest contribution | per-skill contribution scores and router-engagement logs | MBPP+ code only, single-call; 3 seeds |
| DexAgent | forks instead of overwriting | n/a | none | n/a | none stated in the parts read |
| Real2Gym | merge lessons, revise contradicted guidance | merge with evidence | invalidation notes, never delete | configuration fingerprint check, fresh observation | 3D reconstruction fidelity limits |
| ACE | in-place counter updates, delta bullets | embedding dedup | prune redundancy | n/a | monolithic rewrite shown to collapse (18,282 to 122 tokens) |

### 2.3 Evidence of effect (memory on versus off)

| Work | Benchmark | Memory off | Memory on | Notes | Tag |
|---|---|---|---|---|---|
| ASPIRE | LIBERO-Pro Long zero-shot, library from LIBERO-90, Opus 4.6 | 4.7% (empty) | 30.5% (full, 90 tasks) | success rises monotonically with library size (Fig. 5b); 10 tasks per axis, 50 seeds | [read + repo] |
| ASPIRE | Backward transfer, LIBERO-Pro Long, Opus 5 | 74.6% (746/1000) | 82.2% (822/1000) | 5 low tasks rerun with final library; one stays 0%; reruns also include "further debugging", so not a pure library effect | [read] |
| ASPIRE | Real robot, with vs without retrieving a simulation skill | soda can 13/20 (65%), drawer 0/20 | soda can 19/20 (95%), drawer 11/20 (55%) | tokens to first success lower with skills; bowl 20/20 both | [read] |
| ASPIRE | Library vs no library, same suite | not run as a clean ablation | - | ablation covers engine (14% to 62%) and evolutionary search (to 72%) only | [read] |
| Voyager | Minecraft exploration | plateau without library | grows | 63 unique items in 160 iterations; ablation shown only as a figure; headline multipliers not extractable from the HTML | [read-p] |
| CaP-X | CaP-Bench, 7 Robosuite tasks | - | skill library one of three added components | per-component numbers only in Fig. 8 (not extractable) | [read-p] |
| ReasoningBank | WebArena-Shopping, Gemini-2.5-flash | 39.0 | 49.7 (k=1), 46.0, 45.5, 44.4 as k grows | up to 20% relative gain overall (Table 1), up to 16% fewer steps | [read] |
| Dynamic Cheatsheet | Game of 24, GPT-4o | 10% (19% with structured prompt, empty memory) | 99% | memory = reusable Python brute-force solver; GPT-4o-mini gains little | [read] |
| Dynamic Cheatsheet | AIME 2020-24, Claude 3.5 Sonnet | 6.7% | 40.6% | full-history appending: 26.7% vs 50.0% (Sonnet), 6.7% vs 40.0% (GPT-4o) | [read] |
| AWM | WebArena | baseline | 35.5% overall (Table 1); gap "as high as" a few points after tens of examples | online degrades when induced from wrong trajectories | [read] |
| ExpeL | HotpotQA, ALFWorld, WebShop | ReAct | each of insights-only and retrieve-only below full ExpeL | random exemplar retrieval: "significant drop" | [read] |
| CLIN | ScienceWorld | no meta-memory 48.6 start | 52.7 start with meta-memory; 69.5 vs 62.2 at trial 4 | meta-memory built from best trial per episode | [read] |
| LRLL | tabletop sim curriculum | static prompt | retrieval + sleep abstraction better forward transfer; "no actual increase in backward task performance in any baseline" | sleep shrinks stored experiences, fewer retrieved examples needed | [read] |
| Skill-V | ALFWorld 95.3%, WebShop 85.9% | frozen policy with no skills (value lost in conversion) | evolved library gives +6.31 points over initial library at fixed policy | gate ablation: gate on -> all revisions pass; off -> task success falls | [read] |
| SkillForge | ALFWorld 87.9 / AppWorld 44.6 | w/o skill bank 79.3 / 34.5 | w/o explicit calling (bulk injection) 77.9 / 33.3 | bulk-injected bank scored **below** no bank | [read] |
| SkillCommit | RuleArena, OpenExempt, KOR-Bench | no skill | exceeds best baseline by 14.07, 28.08, 26.39 avg points (3 model configs) | w/o patch validation -17.78 pts NBA; w/o grouping 32 to 19 correct | [read] |
| Library Drift | MBPP+ hard-100, 100 rounds | 0.258 (no-skill floor, A1 +0.002) | 0.584 late-window mean (peak 0.658) with retirement + cap 50 | A4 harsh retirement -0.019 | [read] |
| RoboHarn-Evo | RMBench held-out, 80 interaction rollouts | GPT-5.5 48.3%, GPT-6 70.0% | 75.0%, 88.3% | vs Raw Memory (append-only): +16.7, +15.0 pts; pool of 40 entries (24 correct, 12 incorrect, 4 unverified): repairs 41.7% / 50.0% of errors, deactivates another 41.7%, keeps 95.8% of correct entries; append-only variants resolve no initial errors | [read-p] |
| Learning & Transferring Closed-Loop Robot Software | RoboCasa, 9 target tasks | 45.2% without references | 41.5% with unvalidated source code; 57.0% with validation-selected source code | unvalidated reference code **lowered** transfer | [abs] |
| REM | SWE-ContextBench Lite | 24.9% | 27.6% (17% lower cost) | sign flips for strong agents (see §0.6) | [read-p] |
| SkillsBench | 84 tasks, 7 configs, 7,308 trajectories | no skills | curated +16.2 pp; self-generated below baseline | 16 of 84 tasks show negative deltas with curated skills | [sum + read-p] |
| Memento-Skills | GAIA, HLE | static read-write baseline | +13.7, +20.8 pp test accuracy (router trained offline) | "most skills optimised during training were never triggered" on GAIA | [read-p] |
| 2609.31760 | RoboCasa fridge task, 123 rounds | - | 57 accepted library changes (51 perception) | target task never succeeded; improvements "did not add up" | [read] |

---

## 3. Recurring design lessons

**L1. Store the cause, scope and check, not only the code.** ASPIRE's entry (failure signature, when-to-apply, repair, sketch, provenance), Skill-V's contract (intent + executable rubric + versions), RoboHarn-Evo's task/action entries with applicability, Real2Gym's skills (applicability, effect checks, recovery) all converge on "procedure + when it applies + how to tell it worked". The `2604.27003` study finds that abstract procedural memories transfer more reliably across tasks than detailed trajectories, while raw trajectories win within a task and lose across tasks (ALFWorld task B: the within-task advantage "disappears or reverses") [read-p]. Negative transfer concentrates on the hard cases, which are exactly the cases an adversary generates.

**L2. Granularity: repair patterns and primitives beat whole programs.** ASPIRE stores "a navigation recovery pattern rather than a complete radio-pickup program" [read]. LRLL's abstraction removes redundancy so fewer examples fit in context [read]. Counter-evidence: `2609.19906` transfers whole closed-loop programs and gets +11.8 pp over no reference when validated [abs]. Both work; neither compares granularities head to head on robots.

**L3. Retrieval is two-stage in the better systems.** Cheap similarity first, then an applicability test (Skill-V's judge + deterministic contract checks; ASPIRE's "when-to-apply guard"; RoboHarn-Evo's VLM matching of entry conditions to the scene; Graph-of-Skills's backward dependency traversal [abs]). Embeddings alone are weak for skills: SkillRet reports off-the-shelf retrievers "struggle on realistic large-scale skill libraries" and that MTEB ranking does not predict skill retrieval [`2605.05726`, abs + section headings]. Memento-Skills trains a router on execution success instead of semantic similarity [read-p] (it trains a small router, not the generator; see §6.2 on the ANTS no-training rule).

**L4. Admission versus maintenance are separate problems, and most papers only solve the first.** Of the roughly 25 systems tabulated in §2, the only ones with an update path that is itself gated: Skill-V (replay non-regression), SkillCommit (full-scope source replay), Memento-Skills (synthetic unit-test gate with rollback), RoboHarn-Evo (support/oppose evidence), Champion-Challenger in `2609.39304` (aggregate, same fixed cases).

**L5. Rewriting by an LLM is risky unless guarded.** ACE: a monolithic rewrite collapsed an 18,282-token context to 122 tokens and accuracy fell from 66.7 to 57.1, below the 63.7 no-adaptation baseline [read]. CLIN regenerates memory every trial and still works, but reports contradictory insights causing retrieval failures [read]. LILO re-derives the library each iteration but with a symbolic compressor that cannot drop information arbitrarily [read-p]. Safe pattern: itemised entries, delta updates, and a check before an edit lands.

**L6. Usage statistics are the common "forgetting" signal.** ExpeL: importance count with up/down votes, removal at 0. SkillForge: EMA success rate and usage with a half-life into an underperformance score, then a keep/revise LLM review. ACE: helpful/harmful counters. Library Drift: per-skill contribution c(s) from paired outcomes, retire at N_min and tau. Oblivion: retention R as a function of turns since last access, utility and access frequency, with a temperature that needs per-task tuning (too low "collapses", too high saturates the buffer) [read-p]. Classification from the 2025 memory survey: time-based, frequency-based, importance-driven forgetting; "overly aggressive pruning risks erasing rare but essential knowledge" [`2512.13564`, read-p]. ANTS's "help count with decay" is frequency-plus-time, and sits in a crowded family.

**L7. Versioning conventions.** DexAgent forks rather than overwrites [read-p]; Skill-V commits a new version per accepted revision and rejects the rest [read]; Real2Gym and the robot-run protocol append invalidation notes [read-p]; the robot-run memory fix is a type system over hypotheses [read].

**L8. Poisoning and trust are a second reason to gate.** MemoryGraft: seeded with 10 poisoned records among 100 benign ones, "union retrieval over lexical and embedding similarity reliably surfaces" them, and the agent imitates their unsafe patterns because retrieved items are "interpreted as trusted prior successes" [abs + read-p]. SoK `2602.20867` lists poisoned retrieval, applicability-condition poisoning and skill drift as skill-specific threats; `2602.12430` cites 26.1% of community skills with vulnerabilities [sum]. ANTS's shared cross-task memory should treat imported entries as untrusted until they pass the local gate.

---

## 4. Contradictions between papers

| Question | Position A | Position B | Reading for ANTS |
|---|---|---|---|
| More retrieved items or fewer? | Voyager puts top-5 in the prompt (top-5 accuracy 96.5%) | ReasoningBank k=1 best; SkillsBench 2-3 skills best | Voyager measures retrieval precision, not task success versus k; the two task-level sweeps both peak at 1-3 |
| Raw trajectories or abstracted insights? | ExpeL ALFWorld: trajectories matter more than insights; DC-RS beats verbatim retrieval DR | `2604.27003`: abstraction transfers across tasks, raw trajectories hurt hard cases cross-task | Task-family-dependent: keep raw evidence for audit and replay, inject abstracted rules |
| LLM judge or execution check for success? | AWM, ReasoningBank, Voyager rely on LLM evaluators and report gains | SkillWeaver's exception-free "verified"; FailBench (repo) shows VLM judges near chance on contact-heavy tasks [repo, abs] | In sim, use the benchmark predicate; use LLM judges only as diagnosers |
| Rewrite or append? | CLIN, DC rewrite and work | ACE collapse; ReasoningBank appends and never prunes | Itemised delta + gate (L5) |
| Delete or restrict? | Library Drift: retirement and cap are load-bearing (+0.328) | Skill-V: restrict boundaries, deletion left as future work; REM: evict after one exposure for the heavy record only | Retire only after enough evidence; soft decay of rank first |
| Does self-generation work? | Voyager, ASPIRE, DC (execution-verified, constrained domains) | SkillsBench self-generated ≈ no gain, no verification | The verifier is the difference, which is the ANTS gate |
| Does memory help strong models? | Memory/skills help weaker models (DC, SkillX plug-in, SkillWeaver strong-to-weak) | REM: strong agents lose 2.0-9.1 pts; ASPIRE v2 carry-over slightly lower for Opus 5.5 | Always report memory-off for the frontier generator |
| Does a strict gate help? | Skill-V, SkillCommit, Champion-Challenger | `2609.31760`: gates too coarse/permissive/noisy; frontier lock | Strictness needs replicates and a tolerance |

---

## 5. What is unsolved, and where ANTS sits

Stated by the authors (quotations) and my reading of the gap:

| Open problem (source) | ANTS component that could address it | Support in the literature | Risk |
|---|---|---|---|
| "Re-validation, pruning, and task-aware ranking at retrieval time" (ASPIRE §5) | Validated envelope + staleness check + help-count decay | Skill-V (replay), RoboHarn-Evo (evidence-gated retrievability), Library Drift (retirement) each solve one piece; no robot system combines them | Retrieval-time replay costs sim time; tolerance design (finding 4) |
| "Skill deletion"; "time-weighted buffers to decay obsolete evidence" (Skill-V App. A) | Decay on help count; adversary refreshes the replay set | Library Drift gives thresholds; Oblivion gives a decay form | Harsh retirement harms (Library Drift A4) |
| "Verification at the point of admission ... without accumulating hidden regressions" (SoK X-A) | Per-case non-regression gate on the ledger of all cases seen | SkillCommit's 0 regressions vs 8; Skill-V's gate ablation | Noise (finding 4), success-predicate trust (finding 2) |
| "Proactive drift detection remains largely absent" (SoK X-D) | Harness fingerprint + envelope + periodic replay of stored evidence | Real2Gym fingerprints; D10 expiry | Needs a defined fingerprint (sim version, API hash, model id) |
| Selection side of the loop is "a model of the world" and "recursion in the wrong place" (`2609.31760`) | Adversary supplies new cases each round (source of novelty); gate over seen cases (regression sentinel) | D9 "separate sentinels from discovery" matches ANTS's split between adversary and ledger | The adversary and the gate are themselves fallible models; no ablation exists |
| Credit assignment of memory items to outcomes (Skill-V, SkillForge) | Constraints cited by id in the program; counterfactual re-run | SkillForge explicit calling; Real2Gym local effect labels | Not evaluated anywhere on code-writing robot agents |
| Cross-task transfer is sparse when tasks are diverse (Memento-Skills GAIA) | Shared memory across LIBERO tasks | ASPIRE LIBERO-90 to Long (4.7% to 30.5%) | LIBERO tasks share structure; real tasks may not |

**Where ANTS design is unsupported (honest list).**
1. **The pheromone formula (N13).** Usage-weighted retrieval with decay and reinforcement exists in spirit (ExpeL votes, SkillForge EMA, Oblivion, ACE counters, Library Drift), but I found no experiment that ablates "reinforce on contribution to an accepted rewrite" against plain similarity or against counts without decay, in any domain. This ablation is a genuine, small contribution if ANTS runs it (§7.6).
2. **Per-case strict non-regression as the gate.** Closest are Skill-V (rubric/outcome statistics, not per-case task success; also RL-trained policy), SkillCommit (source replay of constituents, text domains) and Champion-Challenger (aggregate count on a fixed set). No cited system enforces "no worse on every case seen so far" over stochastic robot rollouts; `2609.31760` is the nearest cautionary evidence.
3. **Validated envelope.** Nearest: Harness VLA "learns the operating range of these fixed primitives" from traces and failure models [abs]; Skill-V applicability conditions; SkillCommit scope expansion; RoboHarn-Evo applicability updates. None records tested parameter ranges from an adversary and uses them to flag extrapolation at retrieval.
4. **Memory sharing across embodiments.** ASPIRE shows sim-to-real guidance transfer on three tasks with n=20 trials [read]; nothing tests whether an ANTS-style gate carries across robots.
5. **Escalation to a human demonstration as a memory-write path.** Not found in the memory literature; closest are LATM's "invoke a human labeler" for novel tasks and ASPIRE's human-provided guidance in the Rubik's cube run.

**Corrections to existing repo docs (from what I read).**
- SkillForge (`2608.24747`) does **not** re-verify skills by replay before reuse. It tracks EMA success and usage during RL training, flags underperformers, and an LLM revises them; its policy is trained with GRPO. The repo's "SkillForge (re-verification before reuse)" is from a search summary and overstates it (module-radar.md B9, skills.md header, aspire-assessment.md). Treat re-verify-at-retrieval as an ANTS design, not a borrowed one.
- Skill-V is built on RL-trained policies (compared against GRPO, SkillRL, Skill1); its non-regression criterion is on rubric-outcome consistency metrics (disagreement rate, false-negative rate, balanced accuracy) over a bounded replay buffer, not per-case task success. Still the closest published admission gate.
- CaP-X's skill library per the paper: regex extraction from pooled successful rollouts plus Gemini-3-Pro selection, 9 functions, one pass. The repo doc's "counted by occurrences and promoted when recurring" describes `capx/skills/library.py` [repo, from code]; the paper does not describe the count rule.
- RAPID adds verified primitives to a library and retrieves covered ones, but reports no library ablation and no forgetting [read].

---

## 6. Take, adapt, avoid

### 6.1 Take

| From | What | Why |
|---|---|---|
| ASPIRE | Entry shape (failure signature, when-to-apply, repair, sketch), provenance, fresh verifier that sees only the stored text, backward-transfer rerun | Best-evidenced robot library; verifier tests whether the record is self-sufficient |
| Skill-V | Versioned records, protected semantic constraints, replay buffer per skill, confident-only applicability filtering with fallback | Closest admission gate; conservative filtering keeps uncertain items |
| SkillCommit | Patch first, abstract later; abstraction committed only if all constituent cases still pass; Help/Hurt reporting per case | Maps one-to-one onto the ANTS per-case ledger; report "newly failing cases" as a metric |
| Library Drift | Contribution score per entry, N_min before retirement, active cap, evidence log | The only quantified retirement thresholds |
| `2609.31760` | Typed hypotheses (D10), reproduce every paired difference (D8), fixed regression panel plus a declared share of fresh states (D9), lockbox never selected against | Direct hazards for ANTS's gate and adversary |
| `2609.39304` | Champion-Challenger with at least 20-100 rollouts behind each promotion | Evidence on how many rollouts a decision needs |
| RoboHarn-Evo | Retention metrics: share of initially valid entries kept, share of invalid entries repaired or deactivated; support/oppose/unverified evidence; "retrievable only when supported without applicable opposition" | A direct way to test a memory store with planted bad entries |
| Real2Gym / DexAgent | Fork not overwrite; invalidation notes; configuration fingerprints | Cheap staleness and audit support |
| ExpeL / ACE | Vote or helpful/harmful counters on itemised entries | Simple precedent for help counts |
| REM | Heavy evidence (full trace) withheld until needed; evict after one exposure | Keep prompts small, avoid biasing later turns |

### 6.2 Adapt

- **Credit assignment for help counts.** Require the program header to list the constraint/skill ids it uses (SkillForge's explicit call event). Count "helped" only if (a) the id was cited, (b) the rewrite was accepted by the gate, and (c) for a sampled fraction of accepted rewrites a counterfactual re-run without that entry fails or scores lower. Skill-V warns that outcomes alone are not causal.
- **Routers.** Memento-Skills's offline-RL router is a trained retrieval component. AGENTS.md forbids training for the generator only, but adding trained code is a decision that "changes results"; ask the user before adding it. A logistic/bandit ranker over logged (item, outcome) pairs is a cheaper stand-in.
- **Decay.** Tie decay to cycles since last verification, not wall time (simulator-only runs have no meaningful wall time).
- **Strict gate.** Keep the guarantee (no regressions on cases seen) but implement it as "no case whose success rate over R replicates drops by more than delta, confirmed by re-run", per D8.

### 6.3 Avoid

- Append-only stores with LLM-judged admission (ReasoningBank, AWM online): no protection against wrong entries (`2604.27003`; RoboHarn-Evo's append-only variants resolve no initial errors).
- "Verified = runs without exception" (SkillWeaver).
- Monolithic LLM rewrites of the whole memory (ACE collapse; DC).
- Bulk injection of the entire bank (SkillForge: 77.9 vs 79.3 with no bank; ASPIRE v2 slight dip).
- Early, harsh retirement (Library Drift A4; the paper gives a Hoeffding epsilon of about 0.20 at 100 trials [read]; scaling by 1/sqrt(n) puts it near 0.45 at 20 trials [computed]).
- Letting a memory record "not yet tested" as "failed" (`2609.31760`).
- Treating imported entries as trusted (MemoryGraft).

---

## 7. Recommendations for ANTS

### 7.1 Record

One JSON record type with `kind in {policy, skill, constraint, correction}`; keep the disc. §7 `Constraint` as the `rule`/`failure_signature` core and add:

```json
{
  "id": "...", "kind": "constraint", "version": 3, "parent_id": "...", "status": "candidate|probation|verified|stale|deprecated",
  "key": {"failure_signature": "...", "when_to_apply": "...", "task_text": "...", "embedding_id": "..."},
  "applicability": {"precondition_code": "def holds(obs)->bool", "categories": ["pose","friction"]},
  "body": {"rule": "...", "check_code": null, "code_sketch": null, "calls_skills": []},
  "envelope": {"category": {"param": [lo, hi], "n_pass": 0, "n_fail": 0}},
  "ledger": [{"case_id": "...", "version": 3, "replicates": 3, "successes": 3, "split": "acceptance"}],
  "usage": {"n_cited": 0, "n_helped": 0, "n_hurt": 0, "n_counterfactual_tested": 0, "last_used_cycle": 0, "last_verified_cycle": 0},
  "harness_fingerprint": {"sim": "...", "api_hash": "...", "generator": "model-id", "prompt_hash": "...", "robot": "..."},
  "provenance": {"source": "own-run|imported", "demo_id": "...", "run_ids": [], "cost": {"tokens": 0, "sim_s": 0}},
  "hypothesis_state": "tested_rejected|untestable|infra_failure|pending|never_run|accepted",
  "relations": [{"type": "specialises|replaces|depends_on", "id": "..."}]
}
```

Rationale: ledger + replicates (finding 4), fingerprint (finding 8), hypothesis state (finding 9), split field keeps acceptance and held-out data separate as AGENTS.md requires, `n_helped`/`n_hurt` separate from `n_cited` (finding 10). Rejected constraints stay in the log with `hypothesis_state` and are not shown to the generator unless `rejected` was tested.

### 7.2 Retrieval ranking (options, simplest first)

| Option | Score | Source | Note |
|---|---|---|---|
| R0 | cosine(task + failure text, key text), top-k | Voyager, ExpeL, ReasoningBank | Baseline; k in {1, 3, 5} |
| R1 | R0, then drop entries whose `precondition_code` is false; LLM applicability judge removes only confident non-applicable, fall back to R0 if judge unavailable | Skill-V, ASPIRE | Runnable precondition first |
| R2 | R1 score x Wilson lower bound of help rate: `sim * LB(n_helped, n_cited + n_hurt)`, with prior Beta(1,1) and a weight alpha | adapts N13; Library Drift contribution; ExpeL votes | Lower bound, not raw count: avoids rich-get-richer for young entries |
| R3 | R2 x `0.5^(cycles_since_verified / H)`, H in {10, 20} cycles (per-cycle factors 0.933, 0.966 [computed]) | Oblivion, Generative Agents (recency x importance x relevance, min-max normalised, equal weights) | Decay lowers rank (accessibility); do not delete |
| R4 | R3 + exploration bonus for entries with `n_cited < n0` | UCB-style, my proposal `[proposal]` | Prevents starvation of new entries |
| R5 | Learned router on execution success | Memento-Skills | Needs user approval (training code); not the default |

Also use MMR diversity (LRLL) if the top-k duplicates one failure family. Default for the first experiment: R1 with k=3, then ablate R2 and R3 (§7.6).

### 7.3 Admission (three options, pick by cost)

| Rule | Procedure | Cost | Evidence | Weakness |
|---|---|---|---|---|
| A. Verifier agent (ASPIRE) | Fresh agent sees stored text only and must reproduce the fix on the source scenario; repo notes 2 attempts and >=4/5 seeds in ASPIRE's code [repo] | 1 extra agent run per entry | ASPIRE: no ablation of the verifier itself | Tests record self-sufficiency, not regression on other cases |
| B. Ledger non-regression (ANTS gate, Skill-V, SkillCommit) | New version must be no worse on every ledger case (with R replicates and re-run of any disagreement), and better on at least one | R x |ledger| rollouts per candidate | SkillCommit: 24 repaired / 0 regressed vs ExpeL 24 / 8; Skill-V gate ablation | Noise (finding 4); cost grows with ledger |
| C. Synthetic unit test with rollback (Memento-Skills, LATM) | Generate a test, run it, roll back on failure | Cheap | Authors report gains | A synthetic test is not the failure the adversary found; weaker than B |

Recommendation: layered **probation**. `candidate` (written) -> `probation` (passes B on its scope-relevant ledger cases plus fresh adversary cases drawn near its envelope) -> `verified` (optionally A, once per entry; and an independent re-run after M cycles). The survey `2603.07670` describes the same shape (hot buffer, promotion after re-verification, deduplication and importance scoring, §9.1) [read-p]. Rule B should also be used for **skill modifications**, as already in skills.md §2.

### 7.4 Deprecation / forgetting

1. **Rank decay** (R3) runs always; nothing is deleted by decay.
2. **Quarantine** an entry when (a) its harness fingerprint is stale, or (b) its Wilson upper bound of `help rate` falls below `tau` with `n_cited >= N_min`.
3. **Deprecate** (kept, not retrieved) after it fails re-verification (replay of its evidence cases) in two consecutive checks, or hits the active cap and has the lowest contribution score (Library Drift: cap 50; AutoManual: 12 rules).
4. **Thresholds.** Library Drift's N_min=100 is unreachable for a 50-case budget; with N_min=20 their run emptied the bank. Use quarantine (reversible) for early evidence and reserve deprecation for repeated replay failure. If a numeric N_min is needed, for a 0/1 outcome Hoeffding gives about 47 trials for epsilon 0.2 and about 21 for epsilon 0.3 at 95% [computed; the paper's own epsilon of 0.20 at 100 trials implies a different outcome scale], so treat anything under about 20 trials as unresolvable.
5. Keep deprecated records for audit with an invalidation note (Real2Gym). Never record "never tried" as "rejected".

### 7.5 Staleness check at retrieval

1. **Fingerprint match** (sim version, API hash, generator id, robot). Mismatch -> `stale`, replay before use.
2. **Envelope check.** If the current scene's perturbation parameters fall outside `envelope`, flag "extrapolation": lower rank or shadow-run alongside the memory-free candidate.
3. **Cheap replay.** Re-run K=3 evidence cases (origin failure and nearest ledger neighbour) under R=3 replicates; on any confirmed regression, demote to quarantine. Cost: K x R = 9 rollouts per stale retrieval `[computed]`; only for entries that would be injected.
4. **Contradiction scan** among entries sharing a scope (CLIN failure mode). Two rules with opposing actions in one scope go to the gate as a pair, not both into the prompt.
5. **Recipient check.** Log memory-on vs memory-off outcomes for the current generator (finding 6); if memory-on loses on a rolling sample, stop injecting for that generator.

### 7.6 Minimal ablation design

Primary question: does the memory help, does the gate matter, does decay matter. Arms (same held-out cases for every arm, same generator, same task order set):

| Arm | Memory | Admission | Ranking | Decay |
|---|---|---|---|---|
| M0 | off | - | - | - |
| M1 | on, append-only | none | R0, k=3 | off |
| M2 | on, gated (rule B) | ledger | R1, k=3 | off |
| M3 | on, gated | ledger | R2 (counts, lower bound) | off |
| M4 | on, gated | ledger | R3 (counts + decay) | on |
| M5 | M2 plus staleness replay at retrieval | ledger | R1 | off |

Then a top-k sweep k in {1, 3, 5} on the best arm only. Add a **planted-bad-entries control**: seed 10-20% incorrect or irrelevant entries (RoboHarn-Evo's 40-entry pool with 12 incorrect; MemoryGraft's 10 of 110) and report share retrieved, share repaired or deactivated, share of valid entries retained.

Design rules that the literature supports: task order matters (path dependency), so run at least 3 random task orders and report leave-one-task-out transfer (ASPIRE Fig. 5b style: library built from 0, k, all tasks); keep acceptance and held-out sets separate; report Help/Hurt (cases newly solved and newly broken) beside success (SkillCommit); log tokens and sim time per cycle; evaluate a strong and a weaker generator (finding 6).

**Sample sizes and Wilson intervals [computed]** (95%):

| Held-out cases per arm | at 50% | at 70% | at 90% |
|---|---|---|---|
| 20 | 10/20 [0.30, 0.70] | 14/20 [0.48, 0.85] | 18/20 [0.70, 0.97] |
| 40 | 20/40 [0.35, 0.65] | 28/40 [0.55, 0.82] | 36/40 [0.77, 0.96] |
| 50 (the concept's held-out budget) | 25/50 [0.37, 0.63] | 35/50 [0.56, 0.81] | 45/50 [0.79, 0.96] |
| 100 | 50/100 [0.40, 0.60] | 70/100 [0.60, 0.78] | 90/100 [0.83, 0.94] |
| 200 | 100/200 [0.43, 0.57] | 140/200 [0.63, 0.76] | 180/200 [0.85, 0.93] |

Cases needed to detect a difference (alpha 0.05 two-sided, power 0.8) [computed]: unpaired two-proportion, per arm: 50% vs 70% needs 93; 60% vs 75% needs 152; 70% vs 85% needs 121; 80% vs 90% needs 199. Paired on the same cases (McNemar, difference d with discordant fraction psi): d=0.15, psi=0.3 needs 103 cases; d=0.20, psi=0.4 needs 77; d=0.10, psi=0.2 needs 155. **Consequence:** 50 held-out cases per arm can resolve only differences of roughly 25 points or more; say so in any write-up, or use 100+ paired cases, or add replicates (majority of 3 replicates turns a 0.8 per-rollout success rate into 0.896 verdict reliability, 5 replicates 0.942 [computed]). Use paired tests across arms (same cases) and report Wilson intervals, not point estimates.

Gate-specific check: for the gate, run the same candidate through the ledger twice and report the share of paired differences that fail to reproduce; `2609.31760` saw "nearly half". If ANTS's rate is similar, set R and delta before the memory ablation.

---

## 8. Reading list ranked by relevance to ANTS memory (read / not read)

| # | Work | Why it matters | Status |
|---|---|---|---|
| 1 | ASPIRE `2607.00272` (97 cit.) | Robot skill entries, verifier admission, backward transfer, stated staleness gap | read |
| 2 | Skill-V `2610.11781` (0) | Versioned contracts, replay non-regression, applicability filter, stated gaps | read |
| 3 | What Stops Recursive Self-Improvement in Robotics? `2609.31760` (5) | Gate noise, typed memory, memory corruption, fixed point | read |
| 4 | SkillCommit `2608.15165` (8) | Replay-validated abstraction, Help/Hurt | read |
| 5 | Library Drift `2605.19576` (19) | Retirement/cap thresholds with ablations | read |
| 6 | RoboHarn-Evo `2609.37583` | Robot knowledge maintenance with retention metrics | read (partial) |
| 7 | Scale and Selection `2609.39304` (3) | Champion-Challenger, rollout scale | read |
| 8 | Voyager `2305.16291` (2735 per repo) | Original library | read |
| 9 | CaP-X `2603.22435` | Skill library by extraction | read (library parts) |
| 10 | RAPID `2609.30249` | Primitive library with verified admission | read |
| 11 | SkillForge `2608.24747` | EMA/half-life underperformance score, explicit skill calling | read |
| 12 | REM `2610.27377` (0) | Sign of memory depends on recipient; evict after exposure | read (partial) |
| 13 | ReasoningBank `2509.25140` | k-sweep, failure memories | read |
| 14 | When Continual Learning Moves to Memory `2604.27003` (15) | Representation, negative transfer on hard cases | read (partial) |
| 15 | SoK: Agentic Skills `2602.20867` (143) | Lifecycle, open problems, security | read |
| 16 | LRLL `2406.18746` (42) | Robot library learning, replay-compressed memory | read |
| 17 | ExpeL `2308.10144` | Vote-based insight maintenance | read |
| 18 | Real2Gym `2609.37089` (3) | Robot skills with applicability, fingerprints, invalidation | read (partial) |
| 19 | DexAgent `2609.35318` (2) | Skills and verifiers, forks | read (partial) |
| 20 | Learning & Transferring Closed-Loop Robot Software `2609.19906` | Validated vs unvalidated reference code | read (abstract, limits) |
| 21 | SkillsBench `2602.12670` | Curated vs self-generated, counts | read (partial) |
| 22 | ACE `2510.04618` | Context collapse, counters | read (partial) |
| 23 | AutoManual `2405.16247` | Typed rules, consolidator, cap 12 | read |
| 24 | SkillWeaver `2504.07079` | Vacuous verification | read |
| 25 | AWM `2409.07429` | Workflow memory, online noise | read |
| 26 | CLIN `2310.10134` | Regenerated causal memory, contradictions | read |
| 27 | Dynamic Cheatsheet `2504.07952` | Curation vs full history | read |
| 28 | LATM `2305.17126` | Tool maker, dispatcher | read |
| 29 | LILO `2310.19791` | Compression and documentation | read (partial) |
| 30 | Memento-Skills `2603.18743` (69) | Success-aligned router, unit-test gate | read (partial) |
| 31 | Memory for Autonomous LLM Agents `2603.07670` (71) | Taxonomy, staleness, forgetting, dual-buffer | read (partial) |
| 32 | Memory in the Age of AI Agents `2512.13564` (312) | Taxonomy; forgetting types | read (partial) |
| 33 | Harness VLA `2607.08448` (88) | Operating range of fixed primitives, two memories | abstract + memory section |
| 34 | Oblivion `2604.00131` | Decay-driven accessibility, temperature trade-off | read (partial) |
| 35 | MemoryGraft `2512.16962` (83) | Poisoned experience retrieval | abstract + method |
| 36 | Agent Skills for LLMs `2602.12430` (121) | Security stats, open challenges | read (challenges) |
| 37 | SkillOps `2605.13716` (21) | Library-time maintenance; note: libraries above 229 skills include synthetic degraded variants | abstract |
| 38 | Graph of Skills `2604.05333`, SkillRet `2605.05726`, SkillX `2604.04804` | Retrieval at scale, hierarchical bases | abstract |
| 39 | RoboSkill (Explore, Execute, Evolve) `2609.37810` | Text + code skills with applicability | abstract |
| 40 | Reflexion `2303.11366`, Code as Policies `2209.07753`, Generative Agents `2304.03442`, MemoryBank `2305.10250` | Foundations: memory window, hierarchical codegen, retrieval score, forgetting curve | read (partial) |
| 41 | RoboRSI `2610.12424`, ENPIRE `2606.19980`, BATON `2608.16889`, Zetta `2608.16590`, PhyAgentOS `2607.16636`, Embodied Turing Machines `2610.12369` | Newer robot self-evolution loops citing ASPIRE | fetched, not read / not fetched |
| 42 | SkillRL `2602.08234` (308), Skill1 `2605.06130`, SkillOS, SkillOpt, Trace2Skill, SkillCAT | RL-trained skill banks; Skill-V and SkillForge baselines | not read |
| 43 | Demo2Code, Chain-of-Modality, RoboPro, MotorMind | ANTS-adjacent; no persistent memory content in the repo summaries | not read |
| 44 | Memory poisoning set: `2601.05504`, `2606.04329`, `2605.15338`, `2602.15654`; forgetting set: `2604.12007`, `2609.33013`, `2606.25115`; PATH-Bench `2608.01149` | Next reads for poisoning, learned forgetting, path-dependent evaluation | not read |

---

## 9. What I could not verify

- Voyager's headline multipliers (unique items, distance, tech-tree speed) and Table A.4 top-1 to top-4 values: the HTML conversion removed the numbers. I quote only the 63 items in 160 iterations and the 96.5% top-5 accuracy, which survived.
- Skill-V's main-table numbers other than 95.3% (ALFWorld), 85.9% (WebShop), the +6.31-point library gain, and the gate-ablation direction; library size, percentage of regressive revisions, and success with and without the gate were lost in conversion. No code link found in the text.
- SkillForge, Skill-V, RAPID, SkillCommit, RoboHarn-Evo, REM, Real2Gym, DexAgent, `2609.31760`: code release is not stated in the text I read.
- SkillsBench's self-generated skill delta (-1.3 pp) comes from a search summary and the SoK; the primary paper says self-generated skills "land below the no-Skills baseline on all three configurations" with values lost in conversion.
- "Flat retrieval degrades beyond 64-128 skills" (repo doc); see §1.
- The Generative Agents decay factor (value lost in conversion).
- The Library Drift and SkillOps results are on text and code benchmarks (MBPP+, ALFWorld, SkillsBench) with small seed counts; none is a robot result, and none is peer-reviewed as far as I could tell. REM is a workshop paper with one replicate per model in its sweep.
- ASPIRE's skill-library retrieval is by the agent reading an index and files; I did not find the retrieval prompt in the text and did not read the repository code.
- Citation counts are Semantic Scholar on 2026-11-01 and I did not cross-check them.
