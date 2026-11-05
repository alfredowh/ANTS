# FULL REPORT: Memory and cache radar shortlist

Date 2026-11-01, branch `synthesizer`. Nothing here changes any ANTS design.

**Sources mined**
- Radar export of 2026-11-01, read-only: `works` (287) and `orgs` (87).
- The ANTS docs: AGENTS.md, concept.md, discussion.md (§4.3, Q9, §10), module-radar.md (Block 9 and 11), aspire-deep-read.md, aspire-assessment.md (§4), skills.md, dev/instant-learning.md, dev/reuse-from-hurobo.md (§2.4, §2.5), dev/reuse-from-agentic-robot.md (§2.8), dev/paper-vs-docs.md (C11).
- Four sibling notes written today, read only for cross-reference: memory-skill-libraries-llm-agents.md, memory-correction-and-failure-libraries.md, memory-management-and-caching.md, memory-audit-codebase.md. They cite about 100 works missing from the radar. I verified their titles against arXiv but did not re-derive their findings.

**Evidence tags**
- `[arxiv]` id, title, date and authors checked on the arXiv API, 2026-11-01.
- `[s2]` citations from the Semantic Scholar batch API, 2026-11-01, after heavy 429 backoff. "cit/mo" is citations divided by months since first arXiv submission, a crude growth proxy. The radar (2026-10-31) and discussion.md (2026-10-28) are too recent for a real cited-by growth measure, so deltas are small and noisy.
- `[abs]` abstract only. `[web]` web summary. `[recall]` my background knowledge, unchecked. `[doc]` quoted from an ANTS doc.
- No full paper was read. Every "ANTS can take" line is a hypothesis for the deep read.

## 0. Findings in one page

1. **The radar is thin where ANTS memory needs it.** Of 287 works, 42 touch memory, skills, correction or failure. Only Reflexion is a text-agent experience-memory paper. There are 0 caching papers and 0 test-selection papers. The agent-memory literature that holds the established citations is absent: MemGPT 1750, A-MEM 1329, ExpeL 1239, ACE 500, ReasoningBank 316.
2. **The ANTS gate has a published relative for memory: GRASP (2605.29668).** It admits a skill edit only if it nets an improvement on a balanced held-out probe under a hard regression budget, in a bounded library. It is in neither the radar nor the docs. With Skill-V (in docs), SkillCommit and Library Drift it forms a 2026 governance cluster. All are frontier (citations 0 to 19).
3. **Established lineage for similarity x help x decay exists.** Generative Agents (retrieval = recency + importance + relevance, 6293 citations), MemoryBank (forgetting curve, 854), ExpeL (rule list with votes, 1239) and Prioritized Experience Replay (4769). None is robot-specific.
4. **Robot memory papers are mostly within-episode** (MemoryVLA, ReMEmbR, KARMA, RoboMemory, MemER). Cross-task, weights-free robot skill memory is a 2026 cluster with almost no citations: RoboSkill, Teach and Grow, RPG, RACaP, SEAR, ENPIRE. These are the closest peers for the ANTS claim and need reading before the pitch.
5. **Caching has no robot-specific literature.** The papers are serving-side (SGLang 1773, Prompt Cache 414), semantic (GPT Semantic Cache 33, vCache 19) or agent-level (Agentic Plan Caching 31, AgentRR 29, Don't Break the Cache 25). I found no representative paper on rollout or simulator-result caching. That is an engineering result for us, not a literature item. memory-audit-codebase.md §0 reports 63 of 65 repeat groups byte-identical.
6. **Radar data-quality issues** are in section 5.

## 1. Family map (a)

Status: **R** in radar, **D** named in docs, **N** new to both. Citations `[s2]` 2026-11-01.

| ID | Family | Established anchors (cit.) | Frontier 2025-2026 (cit.) | Status |
|---|---|---|---|---|
| A | Code and skill libraries; library learning | Voyager 2761, LATM 390, DreamCoder 280, LILO 63 | ASPIRE 97, CaP-X 148, RoboSkill 3, Teach and Grow 2, RPG 6, RACaP 3, ENPIRE 61, SkillRL 308, SkillX 83 | Voyager, ASPIRE, CaP-X R+D; rest N |
| B | Skill-library governance (admission, regression, drift, forgetting, retrieval at scale) | Generative Agents 6293, MemoryBank 854, Prioritized Experience Replay 4769 (lineage) | GRASP 13, Skill-V 0, SkillCommit 8, Library Drift 19, SkillsBench 345, SkillForge 5, SkillOps 21, SkillGuard 3, Dynamic Agent Skills survey 9, Graph of Skills 67, SkillRet 56, FadeMem 14 | Skill-V, SkillForge, SkillOps, SkillGuard, survey R+D; GRASP, SkillCommit, Library Drift, SkillsBench N |
| C | Text-agent experience, procedural, reflective memory | Reflexion 6440, MemGPT 1750, A-MEM 1329, ExpeL 1239, Mem0 862, CoALA 575 | ACE 500, AWM 450, ReasoningBank 316, Dynamic Cheatsheet 191, Memp 100, ReMe 76, Skill-Pro 58 | Reflexion R+D; rest N |
| D | Robot and embodied memory | JARVIS-1 243, MemoryVLA 279, ReMEmbR 125, Optimus-1 117 | MemER 94, Instance-Oriented Memory 0, T2Mem 2, RoboMME 81 | RoboMME R+D (skip); rest N |
| E | Retrieval of demos and policies; in-context stores | VINN 244, Behavior Retrieval 89, FlowRetrieval 57, STRAP 65, DINOBot 80 | MT3 24, RICL 34, REGENT 24, ICRT 92, Instant Policy 67, RA-VLA 2, FERT 0, RV-ICL 1 | DINOBot, MT3, R+X, RHyME, Instant Policy, RV-ICL R+D; rest N |
| F | Human corrections and recovery | Recovery RL 362, RT-H 281, Sirius 190, Yell At Your Robot 179, DROC 94 | RACER 72, LYRA 7, ARCHITECT 4, LIBERO-RECOVER 9, FLARE 16, RESETTLE 1 | DROC, ARCHITECT R+D; HIL-SERL, Hi Robot R; rest N |
| G | Failure corpora, detectors, explainers | REFLECT 337, AHA 223, Sentinel 121, Code-as-Monitor 95 | FIPER 58, RoboFAC 51, FailSafe 47, REBOOT 1, FailBench 3 | REFLECT, AHA, Code-as-Monitor, FIPER, FailBench R+D; RoboFAC, FailSafe, REBOOT, Sentinel N |
| H | Test-case and scenario libraries; adaptive failure discovery | Rainbow Teaming 260, Scenic 364, Colosseum 201, LIBERO-Plus 377, LIBERO-PRO 231 | VLATest 65, Embodied Red Teaming 26, FATE-VLA 1, ROBOGATE 0, Coverage Aware Active Evaluation 0 | LIBERO-PRO/Plus, ERT, FATE-VLA, ROBOGATE R+D; Rainbow Teaming, VLATest N |
| I | Caching: LLM calls, KV, plans, rollouts | SGLang 1773, Prompt Cache 414, Anthropic prompt-caching docs | Agentic Plan Caching 31, AgentRR 29, Don't Break the Cache 25, vCache 19 | N (call cache D: discussion §10) |
| J | Lifelong and continual robot learning, replay | LIBERO 2126, Experience Replay for Continual Learning 1949, LOTUS 103 | Memory Anchors 4, ExpReS-VLA 9 | LIBERO R+D; rest N |
| K | Self-improvement, program evolution | AlphaEvolve 1133, Eureka 851, Darwin Godel Machine 471 | SEAR 1, ENPIRE 61, "123 rounds" report 5, surveys 175/214 | Eureka R; rest N |
| L | Case-based reasoning | classical CBR (Aamodt and Plaza 1994, `[recall]`) | Memento 119, CBR review 22 | N |
| M | Memory security | PoisonedRAG, AgentPoison (counts not retrieved) | MemoryGraft, Zombie Agents, A-MemGuard | N (sibling note covers) |
| N | Memory and skill evaluation | LongMemEval (count not retrieved) | Evo-Memory 149, SkillsBench 345, SkillFlow 30, SEAR 1 | N |

## 2. Per family (b)

Doc links are relative to `docs/synthesizer/research/`.

### A. Code and skill libraries; library learning
- **Anchors.** Voyager 2305.16291 (TMLR, 2761, 66.8 cit/mo). LATM 2305.17126 (ICLR 2024, 390). DreamCoder 2006.08381 (Phil. Trans. R. Soc. A, 280). LILO 2310.19791 (ICLR 2024, 63). `[arxiv][s2]`
- **Frontier.** ASPIRE 2607.00272 and CaP-X 2603.22435 (both R). 2026 robot loops: RoboSkill 2609.37810, Teach and Grow 2608.17209, RPG 2610.02204, RACaP 2609.29394, ENPIRE 2606.19980, LYRA 2509.18597. Text agents: SkillRL 2602.08234 (308), SkillX 2604.04804 (83), Memento-Skills 2603.18743 (69). `[abs]`
- **ANTS can take.**
  - Promote functions that recur across accepted programs into shared skills and auto-document them (LILO AutoDoc). The documentation becomes the retrieval text.
  - Teach and Grow and RPG make the same claim as ANTS (no weight update, demos become reusable skills). Read them first to keep the delta narrow.
  - Caution: the sibling note reports SkillWeaver counted an API as verified if it ran without an exception, and the model learned to silence exceptions. `[doc, not re-checked]`
- **In our docs.** Voyager: [discussion.md §4.1](../discussion.md). ASPIRE skills: [aspire-deep-read.md](aspire-deep-read.md), [aspire-assessment.md §1](../aspire-assessment.md). CaP-X library: [aspire-assessment.md §2.5](../aspire-assessment.md). LRLL: [module-radar.md Block 9](module-radar.md). Skill definition: [skills.md](../skills.md). LATM, LILO, DreamCoder and the 2026 robot loops are not in the docs.

### B. Skill-library governance
- **Anchors (lineage, not robotics).** Generative Agents 2304.03442 (UIST 2023, 6293, 146.7 cit/mo): recency, importance and relevance. MemoryBank 2305.10250 (AAAI 2024, 854): forgetting curve. Prioritized Experience Replay 1511.05952 (ICLR 2016, 4769). No highly cited paper treats skill-library regression directly, which is itself a finding. `[arxiv][s2]`
- **Frontier.**
  - GRASP 2605.29668 (13): admission only on net gain on a balanced probe under a regression budget.
  - Skill-V 2610.11781 (0, R+D): versioned contracts, non-regression on replay.
  - SkillCommit 2608.15165 (8): consolidation only after behavioral validation.
  - Library Drift 2605.19576 (19): unbounded accumulation causes retrieval degradation and false-positive injections.
  - SkillsBench 2602.12670 (345): per Library Drift, LLM-authored skills gave +0.0 points against +16.2 for human-curated ones (second hand).
  - When Not to Imitate 2608.22339 (4): success-derived skills mislead on look-alike tasks.
  - Retrieval at scale: Graph of Skills 2604.05333 (67), SkillRet 2605.05726 (56). Forgetting: FadeMem 2601.18642 (14).
  - Already in radar: SkillForge, SkillOps, SkillGuard, Dynamic Agent Skills survey. `[abs]`
- **ANTS can take.**
  - Treat admission as the gate applied to memory writes (GRASP, Skill-V).
  - Bounded library plus explicit decay is supported from both ends (Library Drift symptom, FadeMem mechanism).
  - Add an applicability check at retrieval (When Not to Imitate), which matches the validated envelope in skills.md.
  - Cite Generative Agents as the form of similarity x help x decay.
- **In our docs.** Skill-V, SkillForge, survey: [module-radar.md Block 9](module-radar.md), [aspire-assessment.md §4](../aspire-assessment.md). Staleness: [reuse-from-agentic-robot.md §2.8](../../dev/reuse-from-agentic-robot.md). Screening before admission: [reuse-from-hurobo.md §2.4](../../dev/reuse-from-hurobo.md). Open memory item: [paper-vs-docs.md C11](../../dev/paper-vs-docs.md). GRASP, SkillCommit, Library Drift, SkillsBench and Generative Agents are not named.

### C. Text-agent experience, procedural and reflective memory
- **Anchors.** Reflexion 2303.11366 (NeurIPS 2023, 6440; R+D). MemGPT 2310.08560 (1750). A-MEM 2502.12110 (NeurIPS 2025, 1329). ExpeL 2308.10144 (AAAI 2024, 1239, 32 cit/mo). Mem0 2504.19413 (ECAI 2025, 862). CoALA 2309.02427 (TMLR, 575). Surveys: 2404.13501 (ACM TOIS, 888) and Memory in the Age of AI Agents 2512.13564 (312). `[arxiv][s2]`
- **Frontier.**
  - ACE 2510.04618 (ICLR 2026, 500).
  - AWM 2409.07429 (ICML 2025, 450).
  - ReasoningBank 2509.25140 (ICLR 2026, 316).
  - Dynamic Cheatsheet 2504.07952 (191).
  - Memp 2508.06433 (ACL Findings 2026, 100; code `zjunlp/MemP` per web).
  - ReMe 2512.10696 (76).
  - Skill-Pro 2602.01869 (58). The arXiv title is now "Skill-Pro" while search results still show "ProcMEM" (ICML 2026).
  - AutoGuide 2403.08978 (NeurIPS 2024, 94).
- **ANTS can take.**
  - ACE: the constraint list in context is a playbook. Per-item delta updates avoid the "context collapse" that rewriting the whole list causes, and the abstract names brevity bias. This is a direct recipe for the Constraint list. `[abs; item-level helpful/harmful counters are recall, verify]`
  - ReasoningBank and Memp: learn from failures as well as successes, and give ablation templates for update strategy and for the memory on/off arm.
  - ExpeL: a rule list with importance counts and add/edit/up/down operations is the nearest text-agent version of a help count. `[recall; a sibling note also quotes it]`
  - AWM: compare workflow induction with inducing skills only from gate-accepted programs.
- **In our docs.** Reflexion: [discussion.md §4.3](../discussion.md). Q9: [discussion.md §1](../discussion.md). Pheromone score: [paper-vs-docs.md N13](../../dev/paper-vs-docs.md). The rest are only in the sibling notes.

### D. Robot and embodied memory
- **Anchors.** JARVIS-1 2311.05997 (TPAMI, 243). MemoryVLA 2508.19236 (ICLR 2026, 279). ReMEmbR 2409.13682 (ICRA 2025, 125). Optimus-1 2408.03615 (NeurIPS 2024, 117). KARMA 2409.14908 (54). RoboMemory 2508.01415 (17). RAEA 2404.11699 (CVPR 2024, 49). Most memorise the scene or history within an episode.
- **Frontier.**
  - MemER 2510.20328 (ICLR 2026, 94): experience retrieval to select history keyframes.
  - Instance-Oriented Memory "Try Once, Then Optimal" 2607.23702 (0): object-centric procedure memory keyed on object features, recorded after one encounter whether or not it succeeds.
  - Also T2Mem 2609.36720, Memory as Plans 2609.11561, Learning to Forget 2604.11306, MemoryVLA++ 2606.09827. `[abs]`
- **ANTS can take.** Only Instance-Oriented Memory is close (an object-feature key, a procedure written after one encounter). The rest are policy-internal memory that ANTS excludes. The radar already has RoboMME (skip).
- **In our docs.** RoboMME: [module-radar.md Block 9](module-radar.md). DINOv3 key: [discussion.md §4.5](../discussion.md).

### E. Retrieval of demonstrations and policies; in-context demonstration stores
- **Anchors.** VINN 2112.01511 (RSS 2022, 244). Behavior Retrieval 2304.08742 (RSS 2023, 89, count via title match). FlowRetrieval 2408.16944 (CoRL 2024, 57). STRAP 2412.15182 (ICLR 2025, 65): retrieves sub-trajectories, not whole demos, evaluated on LIBERO. In radar: DINOBot (80), MT3 (24), R+X (66). `[arxiv][s2]`
- **Frontier.**
  - RICL 2508.02062 (34): frozen pi0-FAST plus retrieval from a demo buffer. `[web]`
  - REGENT 2412.04759 (ICLR 2025, 24). ICRT 2408.15980 (ICRA 2025, 92). RA-VLA 2608.25585 (2).
  - Collective Experience Learning, FERT 2610.25736 (0): retrieval by failure context, pooled across 96 robots, but it fine-tunes.
  - RESETTLE 2610.12185 (1): disagreement-triggered retrieval for recovery. `[abs]`
  - In radar: Instant Policy, RV-ICL, BPP.
- **ANTS can take.**
  - The retrieval unit matters (STRAP): store and retrieve sub-programs or per-phase predicates, not only whole policies.
  - Key by failure context as well as scene (FERT).
  - MT3 attributes 22.3% of its failures to retrieval `[doc: instant-learning.md §1.4]`, so retrieval needs its own metric.
- **In our docs.** [instant-learning.md §1.4 and §4](../../dev/instant-learning.md) and [discussion.md Q9](../discussion.md). DINOBot, R+X and RHyME are in the radar only.

### F. Human corrections and recovery libraries
- **Anchors.** Recovery RL 2010.15920 (RA-L, 362). RT-H 2403.01823 (RSS 2024, 281). Sirius 2211.08416 (RSS 2022, 190). Yell At Your Robot 2403.12910 (RSS 2024, 179). DROC (R+D, 94). HIL-SERL (R, 291). Hi Robot (R, 319). `[arxiv][s2]`
- **Frontier.** RACER 2409.14674 (ICRA 2025, 72). LYRA 2509.18597 (RA-L, 7): human feedback distilled into skills in a lifelong code-generation loop. ARCHITECT (R+D, 4). LIBERO-RECOVER 2609.05178 (9): recovery benchmark on LIBERO. FLARE 2608.26645 (16). FRAMES 2609.22538 (0). `[abs]`
- **ANTS can take.**
  - DROC, LYRA and ARCHITECT turn a human correction into stored code-level knowledge, which is the ANTS escalation path.
  - Yell At Your Robot and Sirius store corrections as training data, so they are contrast cases.
  - LIBERO-RECOVER could be a ready testbed on the ANTS simulator, if its protocol and license allow.
- **In our docs.** DROC: [discussion.md §4.3](../discussion.md). ARCHITECT and SHRIMP: [module-radar.md Block 11](module-radar.md), [aspire-assessment.md §4](../aspire-assessment.md). Hindsight relabeling: [reuse-from-hurobo.md §2.5](../../dev/reuse-from-hurobo.md).

### G. Failure corpora, detectors and explainers
- **Anchors.** REFLECT (R+D, 337). AHA (R+D, 223). Sentinel 2410.04640 (CoRL 2024, 121). Code-as-Monitor (R+D, 95).
- **Frontier.**
  - FIPER (NeurIPS 2025, 58; id 2510.09459 missing in the radar).
  - RoboFAC 2505.12224 (51): 9,440 failed trajectories, 16 tasks, 53 scenes, QA pairs. `[web]`
  - FailSafe 2510.01642 (47): failure cases paired with executable recovery actions in ManiSkill. `[web]`
  - REBOOT 2609.22591 (1): 2,160 demonstrations, 18 assembly tasks, phase-decomposed, failure as a first-class signal. `[abs]`
  - FailBench (R+D, 3).
- **ANTS can take.** The shape of an entry (failure signature, phase, recovery action) from FailSafe and REBOOT, and a taxonomy from RoboFAC and AHA. FIPER-style novelty can trigger retrieval or escalation.
- **In our docs.** [discussion.md §4.3](../discussion.md), [reuse-from-agentic-robot.md §2.3](../../dev/reuse-from-agentic-robot.md). RoboFAC, FailSafe, REBOOT and Sentinel are not named.

### H. Test-case and scenario libraries; adaptive failure discovery
- **Anchors.**
  - Rainbow Teaming 2402.16822 (NeurIPS 2024, 260): a quality-diversity archive of attacks across categories.
  - Scenic 1809.09310 (PLDI 2019, 364). Colosseum 2402.08191 (RSS 2024, 201). VLATest 2409.12894 (PACMSE 2025, 65).
  - LIBERO-Plus (R, 377) and LIBERO-PRO (R, 231).
  - Regression test minimisation, selection and prioritisation: Yoo and Harman, STVR 22(2), 2012, pp. 67-120. Existence confirmed by web search, no arXiv version.
- **Frontier.** Embodied Red Teaming (R, 26), FATE-VLA (R, 1), ROBOGATE (R, 0). Coverage Aware Active Evaluation for Failure Discovery 2608.13719 (0): cheap proxy evaluations under a test budget. RL for test prioritisation, Spieker 1811.04122, is cited by a sibling note. `[abs]`
- **ANTS can take.**
  - Keep the failure history H as a quality-diversity archive indexed by category x severity.
  - The gate replays every case seen so far, so its cost grows linearly. Test-suite minimisation and selection, and Memory Anchors (J), are where to borrow a case-selection rule. Select for speed, then run the full set at final acceptance, so the per-case guarantee holds.
- **In our docs.** [discussion.md §4.4](../discussion.md), [adversary/spec.md](../../adversary/spec.md) (history/). Rainbow Teaming, VLATest, Colosseum, Scenic and test selection are not named.

### I. Caching of LLM calls, plans and rollouts
- **Anchors.** SGLang 2312.07104 (NeurIPS 2023, 1773). Prompt Cache 2311.04934 (MLSys 2024, 414). Anthropic prompt-caching docs: per a web search today, 5-minute writes cost 1.25x, 1-hour writes 2x, reads 0.1x base input by default, with 5% or 2.5% listed for newer models; check the live pricing page. `[arxiv][s2][web]`
- **Frontier.**
  - Agentic Plan Caching 2506.14852 (NeurIPS 2025, 31): about 46 to 50% cost cut reported. `[web]`
  - AgentRR 2505.17716 (29).
  - Don't Break the Cache 2601.06007 (25).
  - vCache 2502.03771 (19): semantic cache with a verified error bound.
  - "Silent and Costly" 2610.34817 (0): prompt-caching mis-integration found in 120 pull requests of 10 agent systems. `[abs]`
  - Semantic caches: GPT Semantic Cache 2411.05276 (33), MeanCache 2403.02694 (count not retrieved).
- **Gap.** No representative paper on rollout caching or content-addressed simulator results. A rollout is deterministic for a given program hash, seed, scene and simulator version `[doc: memory-audit-codebase.md §0.3]`.
- **ANTS can take.**
  - Use provider prompt caching for the Muse calls (ASPIRE reports 97% cache reads, [aspire-deep-read.md](aspire-deep-read.md)). Put the stable part (API docs, DemoSpec tools, constraints) first in the prompt.
  - Do not put a semantic cache inside the gate. A near-miss answer breaks a deterministic comparison. Plan-template caching is acceptable for proposal cost only, never for scoring.
- **In our docs.** Call cache keyed by (model, prompt hash, inputs): [discussion.md §10 (lines 480, 551)](../discussion.md), [reuse-from-agentic-robot.md](../../dev/reuse-from-agentic-robot.md), [HANDOFF.md](../../HANDOFF.md).

### J. Lifelong and continual robot learning, replay
- **Anchors.** LIBERO (R+D, 2126). Experience Replay for Continual Learning 1811.11682 (NeurIPS 2018, 1949). LOTUS 2311.02058 (ICRA 2024, 103): a growing skill library, weight-based. Lifelong Robot Learning with Human Assisted Language Planners 2309.14321 (28).
- **Frontier.** Memory Anchors 2608.26545 (4): a small subset of past experiences carries most of the protection against forgetting. ExpReS-VLA 2511.06202 (9): retrieval-seeded replay for fine-tuning. Also 2605.26820 and 2603.03818 (counts not retrieved). `[abs][web]`
- **ANTS can take.** ANTS has no forgetting in weights but does have regression through context edits. Memory Anchors is a candidate rule for which stored cases the gate must always replay. LOTUS and the replay papers support the "context, not weights" argument.
- **In our docs.** LIBERO only: [discussion.md §4.5](../discussion.md).

### K. Self-improvement and program evolution
- **Anchors.** AlphaEvolve 2506.13131 (1133). Eureka (R, 851). Darwin Godel Machine 2505.22954 (ICLR 2026, 471): an archive of validated agent variants.
- **Frontier.** SEAR 2610.18792 (1). ENPIRE 2606.19980 (61). "What Stops Recursive Self-Improvement in Robotics" 2609.31760 (5): 123 rounds, with evaluator gaming per the sibling note. Surveys: 2507.21046 (175), 2508.07407 (214), Weights or Skills? 2608.01851 (1), Recursive Self-Improvement in Physical AI 2610.38266 (0). `[abs]`
- **ANTS can take.** SEAR's two questions (learning or just trying more; does it transfer) are the memory on/off ablation. DGM is a precedent for keeping non-best variants for later parent selection.
- **In our docs.** ASPIRE's evolutionary search: [aspire-deep-read.md](aspire-deep-read.md).

### L. Case-based reasoning
- Memento 2508.16153 (119): a case bank plus a learned retrieval policy over a frozen LLM. Review of Case-Based Reasoning for LLM Agents 2504.06943 (22). The retrieve, reuse, revise, retain cycle is from Aamodt and Plaza 1994 `[recall]`. A third-party summary says random sampling matched similarity retrieval in some settings `[web, unverified]`. Treat that as a reason to ablate retrieval, not a result.
- **ANTS can take.** The four-phase vocabulary. A learned retrieval policy conflicts with "nothing is trained", so use the non-learned ranking.
- **In our docs.** Not named.

### M and N. Memory security; evaluation protocols
- M. Because the vision is "skills shared through memory", poisoning matters: PoisonedRAG 2402.07867, AgentPoison 2407.12784, MemoryGraft 2512.16962, A-MemGuard 2510.02373, Zombie Agents 2602.15654. Ids and titles verified on arXiv, counts not retrieved. Covered by memory-management-and-caching.md. Not in the radar or our docs.
- N. Evo-Memory 2511.20857 (149), How Memory Management Impacts LLM Agents 2505.16067 (ACL 2025, 138), SkillFlow benchmark 2604.17308 (30), SkillsBench (345), SEAR (1), RoboMME (R). These define how to test "memory helps". Only RoboMME is in our docs.

## 3. Deep-read shortlist (c): 25 works

P1 = before the 2026-11-04 design freeze. P2 = after.

| # | P | Work | arXiv | Why | Expected takeaway |
|---|---|---|---|---|---|
| 1 | P1 | GRASP | 2605.29668 | Closest analogue of the ANTS gate on a skill library | Admission rule, probe construction, regression budget, handling of "better on at least one" |
| 2 | P1 | Skill-V | 2610.11781 | In docs at abstract level only | Contract fields, replay set, applicability filter; verify the 71.9/89.1/95.3 numbers a sibling note quotes |
| 3 | P1 | ACE | 2510.04618 | Evolving playbook; names context collapse | Delta-update procedure for the constraint list, per-item metadata, curator prompt |
| 4 | P1 | ReasoningBank | 2509.25140 | Memory from failures and successes; retrieval-k ablation | How failures are distilled; retrieval count effect |
| 5 | P1 | Memp | 2508.06433 | Compares build, retrieve, update strategies | Which update policy wins; strong-to-weak transfer |
| 6 | P1 | ExpeL | 2308.10144 | Rule list with votes | Add/edit/vote operations as a model of help counts and removal |
| 7 | P1 | Rainbow Teaming | 2402.16822 | QD archive across categories | Archive design for failure history H |
| 8 | P1 | SEAR | 2610.18792 | "Learning or trying more?" benchmark | Memory on/off and transfer protocol, metrics |
| 9 | P1 | Teach and Grow | 2608.17209 | Training-free few demos to skills, the same claim as ANTS | Skill format, retrieval, what it lacks (adversary, gate) for the delta statement |
| 10 | P1 | RPG | 2610.02204 | Weights-free skill refinement with simulator practice | How diagnosis becomes a skill edit and a prompt edit; cost |
| 11 | P1 | Agentic Plan Caching | 2506.14852 | Only agent-level cache paper at NeurIPS | Template extraction and adaptation; when reuse is unsafe |
| 12 | P2 | RoboSkill | 2609.37810 | Robot skill library from execution records | Evolution rule, record format |
| 13 | P2 | RACaP | 2609.29394 | Frozen typed APIs plus experience memory | Where memory sits relative to the typed API |
| 14 | P2 | LYRA | 2509.18597 | Human feedback distilled into lifelong code skills | Escalation-to-memory path; storage form of a correction |
| 15 | P2 | DROC | 2311.10678 | In radar; correction memory with retrieval | Distillation prompt and retrieval key, reusable for Constraint records |
| 16 | P2 | Library Drift | 2605.19576 | Mechanism of retrieval degradation | Size cap and decay thresholds |
| 17 | P2 | SkillCommit | 2608.15165 | Behavior-validated consolidation | Validation before merging, relevant to deduplicating constraints |
| 18 | P2 | Dynamic Agent Skills survey | 2607.10113 | Source of the "flat retrieval degrades near 64-128 skills" claim in the docs | Verify the claim before it appears in the pitch |
| 19 | P2 | STRAP | 2412.15182 | Retrieval unit on LIBERO | Embedding, unit size, ablation versus whole-demo retrieval |
| 20 | P2 | FERT / Collective Experience Learning | 2610.25736 | Failure-context retrieval; fleet sharing | Failure-context key; evidence for "skills are shared" |
| 21 | P2 | Memory Anchors | 2608.26545 | Which few cases protect old behaviour | Anchor selection to cut gate replay cost |
| 22 | P2 | RoboFAC | 2505.12224 | Largest explicit failure corpus | Taxonomy, annotation schema |
| 23 | P2 | Yoo and Harman, regression testing survey (STVR 2012) | no arXiv; Wiley STVR 22(2):67-120 | Established literature on replay-cost control | Selection rules that preserve fault detection (minimisation section only) |
| 24 | P2 | Memory in the Age of AI Agents | 2512.13564 | Shared vocabulary | Forms, functions and dynamics mapped to ANTS components |
| 25 | P2 | Generative Agents (retrieval and reflection) | 2304.03442 | Citable retrieval score | Score definition, normalisation, importance scoring |

Left off on purpose: MemoryVLA, ReMEmbR and KARMA (within-episode memory); Prompt Cache and SGLang (self-hosted serving); Memento (a learned retrieval policy conflicts with "nothing is trained").

## 4. Proposed radar additions (d)

- `status` is `queued`, so the skill's sync mode fills `solves`, `limitation`, `outlook`, `org_ids`, `github` and `review` from primary sources.
- `url` is `https://arxiv.org/abs/<arxiv>`.
- `citations` are `[s2]` and `metrics_date` is `2026-11-01`.
- `authors` is the first author et al. (arXiv API).
- `ants_fit_reason` is the short note. Fit scores are my proposals from abstracts only, not full reviews.
- Suggested `workspace_ref`: `docs/synthesizer/research/memory-radar-shortlist.md`.
- Venues come from Semantic Scholar, with the web-confirmed venue where S2 only said "arXiv".
- A machine-readable copy with all fields is at `scratchpad/adds_out.json` (53 entries).

```json
[
{"short_name":"GRASP","title":"GRASP: Gated Regression-Aware Skill Proposer for Self-Improving LLM Agents","authors":"Johannes Moll et al.","year":2026,"venue":"arXiv","arxiv":"2605.29668","citations":13,"ants_blocks":["memory-skills","verification"],"ants_fit_score":3,"tier":"hackathon","ants_fit_reason":"Admits a skill edit only on net gain on a balanced held-out probe under a hard regression budget, in a bounded library: closest published analogue of the ANTS gate applied to memory."},
{"short_name":"ACE (Agentic Context Engineering)","title":"Agentic Context Engineering: Evolving Contexts for Self-Improving Language Models","authors":"Qizheng Zhang et al.","year":2025,"venue":"ICLR 2026","arxiv":"2510.04618","citations":500,"ants_blocks":["memory-skills"],"ants_fit_score":3,"tier":"hackathon","ants_fit_reason":"Context as an evolving playbook (generation, reflection, curation); names brevity bias and context collapse, the failure mode of rewriting a growing constraint list."},
{"short_name":"Generative Agents","title":"Generative Agents: Interactive Simulacra of Human Behavior","authors":"Joon Sung Park et al.","year":2023,"venue":"UIST 2023","arxiv":"2304.03442","citations":6293,"ants_blocks":["memory-skills"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Retrieval score = recency x importance x relevance: the established template for similarity x help count x decay."},
{"short_name":"ExpeL","title":"ExpeL: LLM Agents Are Experiential Learners","authors":"Andrew Zhao et al.","year":2023,"venue":"AAAI 2024","arxiv":"2308.10144","citations":1239,"ants_blocks":["memory-skills","diagnosis"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Extracts rules from success and failure trajectories; rule list edited by add, edit, up-vote, down-vote: nearest text-agent analogue of constraints with help counts."},
{"short_name":"Agent Workflow Memory","title":"Agent Workflow Memory","authors":"Zora Zhiruo Wang et al.","year":2024,"venue":"ICML 2025","arxiv":"2409.07429","citations":450,"ants_blocks":["memory-skills"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Induces reusable workflows offline or online and injects them selectively; compare with skill induction from accepted programs."},
{"short_name":"Memp","title":"Memp: Exploring Agent Procedural Memory","authors":"Runnan Fang et al.","year":2025,"venue":"ACL Findings 2026","arxiv":"2508.06433","citations":100,"ants_blocks":["memory-skills"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Compares build, retrieve, update strategies for procedural memory (add, filter, reflect on failures): empirical basis for Q9 design choices."},
{"short_name":"ReasoningBank","title":"ReasoningBank: Scaling Agent Self-Evolving with Reasoning Memory","authors":"Siru Ouyang et al.","year":2025,"venue":"ICLR 2026","arxiv":"2509.25140","citations":316,"ants_blocks":["memory-skills","diagnosis"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Memory distilled from self-judged successes and failures, retrieved at test time, plus memory-aware test-time scaling."},
{"short_name":"Memory in the Age of AI Agents","title":"Memory in the Age of AI Agents","authors":"Yuyang Hu et al.","year":2025,"venue":"arXiv","arxiv":"2512.13564","citations":312,"ants_blocks":["memory-skills"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Survey vocabulary: token-level, parametric, latent forms; factual, experiential, working functions; formation, evolution, retrieval dynamics."},
{"short_name":"Memento","title":"Memento: Fine-tuning LLM Agents without Fine-tuning LLMs","authors":"Huichi Zhou et al.","year":2025,"venue":"arXiv","arxiv":"2508.16153","citations":119,"ants_blocks":["memory-skills"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Case-based reasoning agent: case bank plus a learned retrieval policy over a frozen LLM; contrast with non-learned similarity x help ranking."},
{"short_name":"LATM (LLMs as Tool Makers)","title":"Large Language Models as Tool Makers","authors":"Tianle Cai et al.","year":2023,"venue":"ICLR 2024","arxiv":"2305.17126","citations":390,"ants_blocks":["memory-skills","policy-synthesis"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"A strong model writes a tool (Python function), a cheap model reuses it; tool verified by unit tests."},
{"short_name":"LILO","title":"LILO: Learning Interpretable Libraries by Compressing and Documenting Code","authors":"Gabriel Grand et al.","year":2023,"venue":"ICLR 2024","arxiv":"2310.19791","citations":63,"ants_blocks":["memory-skills","policy-synthesis"],"ants_fit_score":1,"tier":"research","ants_fit_reason":"Library induction by compressing recurring code and auto-documenting it; model for promoting functions that recur across accepted programs."},
{"short_name":"SkillWeaver","title":"SkillWeaver: Web Agents can Self-Improve by Discovering and Honing Skills","authors":"Boyuan Zheng et al.","year":2025,"venue":"arXiv","arxiv":"2504.07079","citations":212,"ants_blocks":["memory-skills"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Agent discovers and hones skills as APIs; cautionary case on weak verifiers being gamed."},
{"short_name":"Darwin Godel Machine","title":"Darwin Godel Machine: Open-Ended Evolution of Self-Improving Agents","authors":"Jenny Zhang et al.","year":2025,"venue":"ICLR 2026","arxiv":"2505.22954","citations":471,"ants_blocks":["memory-skills","verification"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Open-ended archive of agent variants, each validated empirically before entering the archive."},
{"short_name":"Rainbow Teaming","title":"Rainbow Teaming: Open-Ended Generation of Diverse Adversarial Prompts","authors":"Mikayel Samvelyan et al.","year":2024,"venue":"NeurIPS 2024","arxiv":"2402.16822","citations":260,"ants_blocks":["adversary-testing"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Quality-diversity archive of adversarial prompts across categories; design pattern for failure history H as a categories x severity archive."},
{"short_name":"STRAP","title":"STRAP: Robot Sub-Trajectory Retrieval for Augmented Policy Learning","authors":"Marius Memmel et al.","year":2024,"venue":"ICLR 2025","arxiv":"2412.15182","citations":65,"ants_blocks":["memory-skills","human-video-to-robot"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Retrieves sub-trajectories (not whole demos) with DINO features and DTW; retrieval-unit choice matters; evaluated on LIBERO."},
{"short_name":"Behavior Retrieval","title":"Behavior Retrieval: Few-Shot Imitation Learning by Querying Unlabeled Datasets","authors":"Maximilian Du et al.","year":2023,"venue":"RSS 2023","arxiv":"2304.08742","citations":89,"ants_blocks":["memory-skills","demo-to-spec"],"ants_fit_score":1,"tier":"research","ants_fit_reason":"Foundational retrieval from unlabeled data for few-shot imitation."},
{"short_name":"RICL","title":"RICL: Adding In-Context Adaptability to Pre-Trained Vision-Language-Action Models","authors":"Kaustubh Sridhar et al.","year":2025,"venue":"arXiv","arxiv":"2508.02062","citations":34,"ants_blocks":["memory-skills","vla-baseline"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Retrieval-augmented in-context learning on a pretrained pi0-FAST from a demo buffer (DINOv2 retrieval); no fine-tuning at deployment."},
{"short_name":"Yell At Your Robot","title":"Yell At Your Robot: Improving On-the-Fly from Language Corrections","authors":"Lucy Xiaoyang Shi et al.","year":2024,"venue":"RSS 2024","arxiv":"2403.12910","citations":179,"ants_blocks":["diagnosis","escalation"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Language corrections during execution, logged and used later; ANTS would store them as constraints in context instead of fine-tuning."},
{"short_name":"Sirius","title":"Robot Learning on the Job: Human-in-the-Loop Autonomy and Learning During Deployment","authors":"Huihan Liu et al.","year":2022,"venue":"RSS 2022","arxiv":"2211.08416","citations":190,"ants_blocks":["escalation","adversary-testing"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Operator interventions during deployment become training data; contrast case for correction handling."},
{"short_name":"RACER","title":"RACER: Rich Language-Guided Failure Recovery Policies for Imitation Learning","authors":"Yinpei Dai et al.","year":2024,"venue":"ICRA 2025","arxiv":"2409.14674","citations":72,"ants_blocks":["diagnosis","escalation"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Language-guided failure recovery policies."},
{"short_name":"RoboFAC","title":"RoboFAC: A Comprehensive Framework for Robotic Failure Analysis and Correction","authors":"Zewei Ye et al.","year":2025,"venue":"arXiv","arxiv":"2505.12224","citations":51,"ants_blocks":["diagnosis","adversary-testing"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Failure corpus (9,440 failed trajectories, 16 tasks, 53 scenes) with taxonomy and QA pairs: model for organising a failure corpus."},
{"short_name":"FailSafe","title":"FailSafe: Reasoning and Recovery from Failures in Vision-Language-Action Models","authors":"Zijun Lin et al.","year":2025,"venue":"arXiv","arxiv":"2510.01642","citations":47,"ants_blocks":["diagnosis"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Failure cases paired with executable recovery actions in ManiSkill: the shape of a correction-library entry."},
{"short_name":"REBOOT","title":"REBOOT: From Failure to Recovery - A Dataset and Benchmark for Precision Assembly","authors":"Nana Yaw Owusu Ofori-Ampofo et al.","year":2026,"venue":"arXiv","arxiv":"2609.22591","citations":1,"ants_blocks":["diagnosis"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Failure as first-class dataset: 2,160 demonstrations over 18 assembly tasks with phase decomposition; abstract-level."},
{"short_name":"LIBERO-RECOVER","title":"LIBERO-RECOVER: Beyond Task Success Towards Failure Recovery in Robotic Manipulation Models","authors":"Lin Liu et al.","year":2026,"venue":"arXiv","arxiv":"2609.05178","citations":9,"ants_blocks":["adversary-testing","diagnosis","simulation"],"ants_fit_score":3,"tier":"research","ants_fit_reason":"Failure-recovery benchmark on LIBERO, the ANTS simulator; abstract-level, check protocol and license."},
{"short_name":"LOTUS","title":"LOTUS: Continual Imitation Learning for Robot Manipulation Through Unsupervised Skill Discovery","authors":"Weikang Wan et al.","year":2023,"venue":"ICRA 2024","arxiv":"2311.02058","citations":103,"ants_blocks":["memory-skills"],"ants_fit_score":1,"tier":"research","ants_fit_reason":"Continual imitation with a growing skill library on LIBERO; weight-based, a contrast to context-only memory."},
{"short_name":"Agentic Plan Caching","title":"Agentic Plan Caching: Test-Time Memory for Fast and Cost-Efficient LLM Agents","authors":"Qizheng Zhang et al.","year":2025,"venue":"NeurIPS 2025","arxiv":"2506.14852","citations":31,"ants_blocks":["memory-skills"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Extracts plan templates from completed runs and adapts them for similar requests (about 46-50% cost cut reported). Formerly titled Cost-Efficient Serving of LLM Agents via Test-Time Plan Caching."},
{"short_name":"AgentRR (Record and Replay)","title":"Get Experience from Practice: LLM Agents with Record & Replay","authors":"Erhu Feng et al.","year":2025,"venue":"arXiv","arxiv":"2505.17716","citations":29,"ants_blocks":["memory-skills"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Records agent traces and replays them with checks; relevant to the gate and rollout reuse; abstract-level."},
{"short_name":"Don't Break the Cache","title":"Don't Break the Cache: An Evaluation of Prompt Caching for Long-Horizon Agentic Tasks","authors":"Elias Lumer et al.","year":2026,"venue":"arXiv","arxiv":"2601.06007","citations":25,"ants_blocks":["memory-skills"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Prompt-caching evaluation for long-horizon agents; guidance on prompt layout so the cache hits."},
{"short_name":"Prompt Cache","title":"Prompt Cache: Modular Attention Reuse for Low-Latency Inference","authors":"In Gim et al.","year":2023,"venue":"MLSys 2024","arxiv":"2311.04934","citations":414,"ants_blocks":["memory-skills"],"ants_fit_score":1,"tier":"skip","ants_fit_reason":"Attention-state reuse; self-hosting concern, not relevant to API-only Muse calls."},
{"short_name":"SGLang (RadixAttention)","title":"SGLang: Efficient Execution of Structured Language Model Programs","authors":"Lianmin Zheng et al.","year":2023,"venue":"NeurIPS 2023","arxiv":"2312.07104","citations":1773,"ants_blocks":["memory-skills"],"ants_fit_score":1,"tier":"skip","ants_fit_reason":"Prefix KV-cache reuse across calls; serving-side background."},
{"short_name":"VLATest","title":"VLATest: Testing and Evaluating Vision-Language-Action Models for Robotic Manipulation","authors":"Zhijie Wang et al.","year":2024,"venue":"PACMSE (FSE 2025)","arxiv":"2409.12894","citations":65,"ants_blocks":["adversary-testing"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Testing framework generating manipulation scenes to test VLAs."},
{"short_name":"Coverage Aware Active Evaluation","title":"Coverage Aware Active Evaluation for Failure Discovery with Paired Systems","authors":"Anjali Parashar et al.","year":2026,"venue":"arXiv","arxiv":"2608.13719","citations":0,"ants_blocks":["adversary-testing"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Adaptive failure discovery using cheap proxy evaluations under a test budget: same problem as the ANTS adaptive planner."},
{"short_name":"Prioritized Experience Replay","title":"Prioritized Experience Replay","authors":"Tom Schaul et al.","year":2015,"venue":"ICLR 2016","arxiv":"1511.05952","citations":4769,"ants_blocks":["memory-skills"],"ants_fit_score":1,"tier":"skip","ants_fit_reason":"Classic: sample replay items by learning signal; background for which stored cases the gate replays first."},
{"short_name":"Library Drift","title":"Library Drift: Diagnosing and Fixing a Silent Failure Mode in Self-Evolving LLM Skill Libraries","authors":"Xing Zhang et al.","year":2026,"venue":"arXiv","arxiv":"2605.19576","citations":19,"ants_blocks":["memory-skills","verification"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Unbounded skill accumulation causes retrieval degradation and false-positive injections; argues for outcome-driven lifecycle."},
{"short_name":"SkillCommit","title":"SkillCommit: Evolving Agent Skills through Behaviorally Validated Scope Expansion","authors":"Yu He et al.","year":2026,"venue":"arXiv","arxiv":"2608.15165","citations":8,"ants_blocks":["memory-skills","verification"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Merges skills only when behaviorally validated; warns that merging by semantic similarity or LLM judgment degrades performance."},
{"short_name":"When Not to Imitate","title":"When Not to Imitate: Boundary-Aware Skill Memory for Reliable Tool-Use LLM Agents","authors":"Zihan Lin et al.","year":2026,"venue":"arXiv","arxiv":"2608.22339","citations":4,"ants_blocks":["memory-skills","verification"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Success-derived skills can mislead on look-alike tasks (skill imitation trap); supports the validated-envelope idea."},
{"short_name":"SkillsBench","title":"SkillsBench: Benchmarking How Well Agent Skills Work Across Diverse Tasks","authors":"Xiangyi Li et al.","year":2026,"venue":"arXiv","arxiv":"2602.12670","citations":345,"ants_blocks":["memory-skills"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Benchmark of how well agent skills work; per Library Drift, LLM-authored skills gave no gain versus +16.2 points for human-curated."},
{"short_name":"SkillFlow (benchmark)","title":"SkillFlow: Benchmarking Lifelong Skill Discovery and Evolution for Autonomous Agents","authors":"Ziao Zhang et al.","year":2026,"venue":"arXiv","arxiv":"2604.17308","citations":30,"ants_blocks":["memory-skills"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Lifelong skill discovery, repair and library maintenance (166 tasks, 20 families). Name clashes with 2605.14089 SkillFlow."},
{"short_name":"Evo-Memory","title":"Evo-Memory: Benchmarking LLM Agent Test-time Learning with Self-Evolving Memory","authors":"Tianxin Wei et al.","year":2025,"venue":"arXiv","arxiv":"2511.20857","citations":149,"ants_blocks":["memory-skills"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Benchmark for test-time learning with self-evolving memory; protocol for a memory on/off ablation."},
{"short_name":"How Memory Management Impacts LLM Agents","title":"How Memory Management Impacts LLM Agents: An Empirical Study of Experience-Following Behavior","authors":"Zidi Xiong et al.","year":2025,"venue":"ACL 2025","arxiv":"2505.16067","citations":138,"ants_blocks":["memory-skills"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Empirical study of memory add/delete policies; storing everything was worse than curated memory (per sibling note)."},
{"short_name":"RoboSkill (Explore, Execute, Evolve)","title":"Explore, Execute, Evolve: A Skill Acquisition and Reuse Loop for Embodied Agents","authors":"Sicheng Xie et al.","year":2026,"venue":"arXiv","arxiv":"2609.37810","citations":3,"ants_blocks":["memory-skills","policy-synthesis"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Robot agent evolving a skill library from execution records; abstract-level, check code and benchmark."},
{"short_name":"Teach and Grow","title":"Teach and Grow: An Agent-Centered Architecture for General Robot Learning","authors":"Chang Nie et al.","year":2026,"venue":"arXiv","arxiv":"2608.17209","citations":2,"ants_blocks":["demo-to-spec","memory-skills"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Training-free: a few successful demonstrations become reusable skills with weights frozen; overlaps ANTS one-demo plus memory; abstract-level."},
{"short_name":"RPG (Reconstruct, Practice, Go Real)","title":"Reconstruct, Practice, Go Real: Guided Self-Improvement for Embodied Agents","authors":"Yen-Jen Wang et al.","year":2026,"venue":"arXiv","arxiv":"2610.02204","citations":6,"ants_blocks":["policy-synthesis","diagnosis","memory-skills"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Weights-free self-improvement: practice in simulation, diagnose with privileged state, write or refine symbolic skills and revise the system prompt; abstract-level."},
{"short_name":"RACaP","title":"RACaP: Agentic Reasoning, Acting, and Coding as Policies for Evolvable Robot Learning","authors":"Zexi Li et al.","year":2026,"venue":"arXiv","arxiv":"2609.29394","citations":3,"ants_blocks":["policy-synthesis","memory-skills"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Coding moved to an offline evolution phase; deployment calls frozen typed Policy APIs with an experience memory; abstract-level."},
{"short_name":"SEAR","title":"SEAR: Self-Evolving Agentic Robotics","authors":"Xinyi Wang et al.","year":2026,"venue":"arXiv","arxiv":"2610.18792","citations":1,"ants_blocks":["memory-skills","simulation"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Framework and benchmark asking whether the agent learns or just tries more, and whether it transfers; relevant to memory ablation design."},
{"short_name":"ENPIRE","title":"ENPIRE: Agentic Robot Policy Self-Improvement in the Real World","authors":"Wenli Xiao et al.","year":2026,"venue":"arXiv","arxiv":"2606.19980","citations":61,"ants_blocks":["policy-synthesis","memory-skills"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Agentic real-world policy self-improvement loop (reset, execute, evaluate, improve); named in a 2026 survey as one of the few open-ended loops."},
{"short_name":"What Stops Recursive Self-Improvement in Robotics","title":"What Stops Recursive Self-Improvement in Robotics? Lessons from 123 Rounds of Agentic Skill Discovery","authors":"Jiaming Wang","year":2026,"venue":"arXiv","arxiv":"2609.31760","citations":5,"ants_blocks":["memory-skills","verification"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"123 rounds of agentic skill discovery in simulation; documents evaluator gaming (per sibling note)."},
{"short_name":"LYRA","title":"Robotic Ultra-Long-Horizon Manipulation Skills via Human-guided Lifelong Code Generation","authors":"Yuan Meng et al.","year":2025,"venue":"IEEE RA-L","arxiv":"2509.18597","citations":7,"ants_blocks":["escalation","memory-skills"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Human feedback distilled into skills in a lifelong code-generation loop: closest to the ANTS escalation-to-memory path."},
{"short_name":"Instance-Oriented Memory (Try Once, Then Optimal)","title":"Try Once, Then Optimal: De-Redundified Procedure Memory for Cross-Episode Exploration Amortization","authors":"Haizhou Ge et al.","year":2026,"venue":"arXiv","arxiv":"2607.23702","citations":0,"ants_blocks":["memory-skills"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Object-centric procedure memory keyed on object features, recorded after a single encounter whether or not it succeeds."},
{"short_name":"MemER","title":"MemER: Scaling Up Memory for Robot Control via Experience Retrieval","authors":"Ajay Sridhar et al.","year":2025,"venue":"ICLR 2026","arxiv":"2510.20328","citations":94,"ants_blocks":["memory-skills"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Experience-retrieval memory for long-horizon robot control (keyframe selection)."},
{"short_name":"Collective Experience Learning (FERT)","title":"Learning from Fleet Experience: Collective Experience Learning Across 96 Robots","authors":"Chao Yu et al.","year":2026,"venue":"arXiv","arxiv":"2610.25736","citations":0,"ants_blocks":["memory-skills","escalation"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"Failure-context-conditioned experience retrieval pooled across 96 robots; fine-tunes, but the retrieval key is the idea."},
{"short_name":"Memory Anchors","title":"Memory Anchors for Continual Robot Learning","authors":"Maximilian Du et al.","year":2026,"venue":"arXiv","arxiv":"2608.26545","citations":4,"ants_blocks":["memory-skills","verification"],"ants_fit_score":2,"tier":"research","ants_fit_reason":"A small set of past experiences anchors old performance in continual learning: candidate rule for which cases the gate must always replay."},
{"short_name":"Weights or Skills? (survey)","title":"Weights or Skills? A Survey of Robot-Learning Techniques: from Action-Predicting Weights to Robots that Write their Own Skills","authors":"Gaytri Jena et al.","year":2026,"venue":"arXiv","arxiv":"2608.01851","citations":1,"ants_blocks":["memory-skills","policy-synthesis"],"ants_fit_score":1,"tier":"research","ants_fit_reason":"Survey placing code-as-policy systems on a self-improvement ladder; names ASPIRE and ENPIRE."}
]
```

**Second tier** (id and title verified on arXiv, cited in the sibling notes, left out of the JSON): CoALA 2309.02427 (575), MemoryBank 2305.10250 (854), SkillRL 2602.08234 (308), SkillX 2604.04804 (83), Memento-Skills 2603.18743 (69), Graph of Skills 2604.05333 (67), SkillRet 2605.05726 (56), FadeMem 2601.18642 (14), CLIN 2310.10134 (109), AutoManual 2405.16247 (88), vCache 2502.03771 (19), FLARE 2608.26645 (16), RESETTLE 2610.12185 (1), RA-VLA 2608.25585 (2), REM 2610.27377 (0), RESKILL 2609.15684 (0), Embodied Turing Machines 2610.12369 (3), Sentinel 2410.04640 (121), AgentPoison 2407.12784, MemoryGraft 2512.16962, Zombie Agents 2602.15654, A-MemGuard 2510.02373, LongMemEval 2410.10813, PATH-Bench 2608.01149, RoboHarn-Evo 2609.37583.

## 5. Data-quality issues (e)

Found by comparing all 268 radar arXiv ids against the arXiv API and about 50 memory-related counts against Semantic Scholar on 2026-11-01. All 268 ids resolve; 4 titles differ. Nothing was fixed, as instructed.

| # | Entry | Issue | Evidence |
|---|---|---|---|
| 1 | LeRobot (`2506-01844`) | The arXiv id is **SmolVLA** ("SmolVLA: A Vision-Language-Action Model for Affordable and Efficient Robotics"). Title and "Software" venue are LeRobot's, stars (28603) are the repo's, and the 705 citations are SmolVLA's. The LeRobot paper is **2602.22818** ("LeRobot: An Open-Source Library for End-to-End Robot Learning", 127 citations). | arXiv API; S2 title for 2506.01844 |
| 2 | N2M2 (`2206-13033`) | The id resolves to an unrelated statistics paper ("Normalized/Clipped SGD with Perturbation for Differentially Private Non-Convex Optimization"). `citations` is null, so metrics never caught it. The right id was not found by arXiv title search; take it from the project page. | arXiv API |
| 3 | FIPER | No `arxiv` value, so `metrics.py` skips it and the count (58) was entered by hand. Id is **2510.09459** ("Failure Prediction at Runtime for Generative Robot Policies", NeurIPS 2025, S2 58). | arXiv API; S2 |
| 4 | ASPIRE (`2607-00272`) | The arXiv/S2 title is now "ASPIRE: Agentic /Skills Discovery for Robotics" (submitted 2026-06-30). Radar and docs use "Agentic Skill Programming through Iterative Robot Exploration". The docs already note v1/v2 differences ([aspire-deep-read.md](aspire-deep-read.md)); choose which title to show. Counts agree (97). | arXiv API; S2 |
| 5 | BPP (`2606-30457`) | Radar title "Behavior Prompting Policy: Demonstrations as Prompts for Manipulation". arXiv title is "What Enables In-Context Behavior Prompting for Manipulation?". | arXiv API |
| 6 | Mis-tagged `memory-skills` block | ANYmal Parkour (fit 0), DINOv3, V-JEPA 2, LeRobot and Open X-Embodiment carry `memory-skills`, so a memory-block filter returns them next to real skill libraries. | radar export |
| 7 | `unverified` flags now checkable | ARCHITECT (`2607-23784`): arXiv confirms title "A Few Words Go a Long Way: Language Guided Robot Policy Synthesis", first author Daphne Chen, so `title` and `arxiv` can leave `unverified_fields`. SkillGuard (`2605-10990`): S2 title "Skill Drift Is Contract Violation: Proactive Maintenance for LLM Agent Skill Libraries" matches. Orgs remain unverified. | arXiv API; S2 |
| 8 | Fit scores too low | LRLL (fit 1, tier skip, ICRA 2024, 42 citations) is the nearest published robot skill-library precursor (memory, abstractor, human-added skills): suggest 2. MotorMind (fit 1) has an explicit memory role. | radar fit text vs abstract |
| 9 | Name clashes when adding | Two different "SkillFlow" papers (2604.17308 benchmark, 2605.14089 method). "Memento" (2508.16153) versus "Memento-Skills" (2603.18743). "Skill-Pro" is called ProcMEM in search results. "Agentic Plan Caching" is the new title of "Cost-Efficient Serving of LLM Agents via Test-Time Plan Caching". | arXiv API; web |
| 10 | Counts across sources | Radar (2026-10-31), discussion.md (2026-10-28), S2 (2026-11-01): Reflexion 6426, 6355, 6440; Voyager 2758, 2735, 2761; CaP-X 148, 144, 148; ASPIRE 97, 94, 97; REFLECT 337, 335, 337; LIBERO-PRO 231, 224, 231; LIBERO-Plus 377, 369, 377. Consistent and fresh; the older discussion.md tables are slightly low, not wrong. | S2 |
| 11 | `year` mixes venue year and arXiv year | 45 radar entries differ from the arXiv year by one (for example Instant Policy 2025, arXiv 2024-11). Harmless, but sorting by year is inconsistent. | arXiv API |
| 12 | Radar blind spots by construction | All 287 works have `source` "seed-crawl" and `metrics_date` 2026-10-31. The seed was labs plus ANTS docs, so the agent-memory, caching and test-selection literatures were never crawled. | radar export |

## 6. Method and limits

- **Radar filter.**
  - Keyword pass over title, short name, solves, limitation, outlook, fit reason, review and workspace_ref gave 114 of 287 works.
  - Terms: memory, skill, librar, retriev, cache, recover, correct, failure, reflect, lifelong, continual, experience, replay, workflow, tool-making, program synth, case-based, episodic, curricul, self-improv, evolv, agent.
  - I then read the 42 with a `memory-skills` block or a memory or failure title.
- **Gap search.**
  - arXiv API listing and id queries (cs.RO, cs.AI, cs.CL, newest first) plus web search.
  - Every added id exists on the arXiv API. The 2026 papers are beyond my own knowledge, so their content comes from abstracts only.
- **Semantic Scholar.**
  - Batch endpoint, 30 ids per call, with backoff.
  - A few ids never returned and are listed without counts: PATH-Bench, MeanCache and the security group.
  - Behavior Retrieval's count came from the title-match endpoint.
- **Not checked.**
  - GitHub stars and licences of any added work.
  - Classical references (Aamodt and Plaza; FunSearch in Nature) are from memory and marked.