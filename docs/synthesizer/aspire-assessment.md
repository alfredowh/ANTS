# Should System 1 build on ASPIRE? Assessment and plan

Status: research note, 2026-10-31. Nothing here is decided. Every number is quoted from a paper, a repo or an API. None comes from our own runs, because none exist yet.

**Evidence tags.** **[read]** means the text or code itself was read. **[summary]** means only a model-extracted summary was available. **[abstract]** means only the abstract or listing. **[est]** is our own estimate, with the reasoning given. Citations come from Semantic Scholar and stars from the GitHub API, both queried 2026-10-31 unless noted.

**Detailed appendices** (full evidence, repo paths, tables):
- [research/aspire-deep-read.md](research/aspire-deep-read.md): ASPIRE paper v1/v2 and repo at commit `fa00f0e`. The repo was read, not run.
- [research/output-format.md](research/output-format.md): primitives vs program vs hybrids, the evidence and a decisive experiment.
- The [Robot Research Radar](https://claude.ai/artifact/3epiiPPS6AcpPoVyWfRfS5) artifact lists labs and works with metrics and ANTS reviews. It is private; share it from its Share menu. Its skill is in `.claude/skills/robot-research-radar/`.

---

## 0. Short answer

1. **Yes, base System 1's execution layer on ASPIRE, but not its agent layer.** Reuse `cap-harness`: the typed primitive API, the AST sandbox, the per-call trace, the run-directory artifacts and the seed protocol. ASPIRE contains **no LLM client**. Its "agent" is Claude Code or Codex reading markdown skills [read]. So plugging in Muse is not a configuration change, contrary to discussion.md §5.1. Instead, our own Muse client writes `program.py` and calls `cap-harness run` / `run-batch` as a subprocess (§5.1 below).
2. **For System 1's *method*, the closest precedent is RAPID, not ASPIRE.** RAPID (MIT LIS and NUS, with UPenn and NVIDIA, [arXiv 2609.30249](https://arxiv.org/abs/2609.30249), Sept 2026) takes **one human demonstration** to a coding agent. The agent writes primitives with per-phase success predicates, rebuilds the scene in MuJoCo and verifies on sampled scene variants with a feasibility filter [read, abstract and HTML; parts summary]. It has no adaptive adversary, no gate over all seen cases, and no escalation to a human. Code release is not stated. **The ANTS novelty claim must now be stated against RAPID and ASPIRE together** (§2.3).
3. **Output format: write a function (program) that calls primitives.** Keep the model out of the run-time loop. Per-step primitive calls cost 31–120 model calls and $0.20–0.50 per episode in published measurements [read]. They are not deterministic, which breaks the regression gate. They do not score better on LIBERO-Pro once model strength is controlled for (§3).
4. **The laptop GPU (RTX A5500, 16 GB) is enough for System 1 on LIBERO**, if every LLM/VLM stays on the API and the GPU runs SAM 3 + 1–2 LIBERO workers, with PyRoki on the CPU [est from repo numbers]. It needs a new `sm_86` profile, because ASPIRE ships only sm_89/sm_120 and errors on other GPU architectures [read]. Skip BEHAVIOR/Isaac and SAM 3D Objects, which do not fit (§5).
5. **The biggest risk is unchanged:** whether Muse can sustain a write-run-debug loop. ASPIRE's own model ablation runs from 15% to 99% on the same task suite, and the model alone explains the gap [read]. The 1-day smoke test (discussion.md decision 5) remains step 1.

---

## 1. ASPIRE in one page

**ASPIRE: Agentic Skills Discovery for Robotics.** NVIDIA GEAR with UMich, UIUC, Berkeley and CMU. [arXiv 2607.00272](https://arxiv.org/abs/2607.00272), v1 2026-06-30, v2 2026-10-20. [Code](https://github.com/NVlabs/ASPIRE): Apache-2.0, **915★, 97 citations**. Our docs said 894 and 94; the title did not change between versions [read].

| | |
|---|---|
| **Problem** | Code-as-policy agents get only coarse rollout feedback and forget their fixes: "the agent solving its hundredth task is effectively no more experienced than the agent solving its first" [read]. |
| **Goal** | Continual learning with **no weight updates**. A frozen coding agent writes robot programs; validated repairs accumulate as a text skill library. |
| **Method** | (1) A coordinator plus one actor per task; actors share only distilled skills. (2) An execution engine traces every primitive call (inputs, outputs, status, before/after keyframes). (3) A skill library: an entry is admitted only if a fresh verifier agent reproduces the fix from the text alone (≥4/5 seeds). (4) Evolutionary search: K=8 programs per round, conditioned on the top 3 and their failure traces. (5) A curriculum, plus reruns of weak tasks with the newer library. |
| **Experiments** | LIBERO-Pro (80 tasks, position and language perturbations), Robosuite (7 tasks), BEHAVIOR-1K (2 tasks), zero-shot LIBERO-90 → LIBERO-Pro Long, a real bimanual YAM. Baselines: CaP-Agent0, OpenVLA, π0, π0.5, human-written code. 12 generator models in v2. |
| **Protocol** | LIBERO: debug seeds 51–65, unseen check 66–80, held-out 1–50, run once. Must use `--init-mode seeded`: the default mode wraps seeds at 50, so seed 51 equals seed 1 [read]. |
| **Results** | v1 (Opus 4.6): **72.0%** over LIBERO-Pro Object/Goal/Spatial (60 tasks, not all 80 as our docs said), against CaP-Agent0 18%, π0.5 13%. v2 (Opus 5.5): **≈99% across all 80 tasks**, Robosuite 100%. Model ablation on Goal/position: Opus 5.5 99.2% ($18/task), Sonnet 5.5 98.8% ($12), Kimi K3 78.4%, Qwen 3.8 Max 56.0%, GPT-6 Luna 14.8% [read]. |
| **Ablations** | No engine and no search 14% → engine 62% → engine + search 72% (Opus 4.6). Search moves strong models by ≤2% [read]. |
| **Cost** | Opus 5.5: about **25M tokens and ~175 rollouts per task, 97% of the tokens being cache reads**, $10.8 per task [read]. Affordable only with prompt caching. |
| **Real robot** | Skills transferred across embodiments: soda can 13/20 → 19/20, drawer 0/20 → 11/20, and 1.7–9.4× fewer tokens (our docs said 4–7×) [read]. |
| **Stated limitations** | Needs a frozen frontier LLM. The predefined API bounds what can be expressed. Skills are verified once and can go stale. Compute-heavy. A human still resets the real robot. |
| **Limitations we see** | One program and one held-out pass per task; variance is barely reported (one task swings from 0% to 100% across runs). Held-out seeds come from the **same sampler** as the debug seeds, and no physics, camera, lighting or actuation perturbation is ever tested. Search accepts a better *aggregate* score, so per-seed regressions pass. GPU budget is not in the paper. **Its case study shows a human LIBERO demo using a strategy no model found** ("book under the shelf"), which is direct support for the ANTS premise that a demo carries information the text does not [read]. |

---

## 2. ASPIRE vs ANTS: same, different, which module

### 2.1 Module by module

| ANTS block | ASPIRE has | Same / different | Use it? |
|---|---|---|---|
| Frozen generator, context-only improvement | Yes, the core claim | **Same** | The framing is shared, so cite it |
| Demo input (System 1 perception, DemoSpec) | **Nothing consumes a demo, video or trajectory** [read] | **Different: the ANTS delta** | Inject a DemoSpec via prompt or `TASK_CONTEXT.md`, a skill entry, or a read-only API extension. It must be **object-relative**: ASPIRE's provenance audit rejects absolute world constants [read] |
| Primitive API | 25 typed calls (`localize_object`, `generate_grasps`, `move_to_pose`, ...), each returning a status | Same idea, more granular than the paper's four primitives | **Reuse.** Put the paper's `locate / move_to / grasp / place` in `contracts` and adapt it onto these calls |
| Policy synthesis | Claude Code / Codex writes `program.py` | Same format (L5); different driver | Reuse the program rules and skills as prompt text; **our Muse client** writes the code |
| Plan gate (static checks) | AST sandbox: `math` only, no class/with/private names, builtins restricted [read] | Same | **Reuse** as the ANTS plan gate. It is not a security boundary (in-process `exec`) |
| Rollout engine | `cap-harness run` / `run-batch`, a run directory per seed | Same need | **Reuse** as the System 2 rollout runner |
| Perturbations | Seeds, initial mode, swap (position) and task (language) suites only. **No physics, camera, light, distractor or actuation API** [read] | **Different: the ANTS delta** | Add a host-side wrapper env via `LiberoAdapter(env_factory=…)`: about 10 lines in `run.py`/`batch.py`, or a launcher monkeypatch. Distractors need new BDDL files (large) |
| Diagnoser evidence | Per-call trace, keyframes, SAM overlays, `outcome.json` | Same need | **Reuse** the run directory as the evidence record |
| Constraint | Skill entry: Trigger → Code → Why + Evidence → Limits, optional runnable precondition | Close to the discussion.md §7 `Constraint` | Adopt the shape plus the **verifier-admission** idea |
| Gate | Evolutionary search accepts if the aggregate debug score is strictly higher | **Different**: ANTS is per-case and monotone over every case seen | Our own `orchestrator/regression_gate.py` |
| Adaptive testing | None (a fixed seed list) | **Different: the ANTS delta** | System 2 |
| Memory | A flat markdown library; tasks rerun when the library changes | Partly the same | Add help counts, decay and re-verification at retrieval (§4) |
| Escalation to a human demo | None (a human only resets the real robot) | **Different: the ANTS delta** | System 2 / orchestrator |
| Acceptance / held-out split | 51–65 / 1–50, plus 66–80 as an overfitting probe | **Same** | **Reuse as-is.** ANTS acceptance = 51–65, held-out = 1–50 |

### 2.2 What is similar
Both freeze the model and improve only through context. Both use code-as-policy over a typed API, a failure trace per call as evidence, a text skill/constraint library, and a strict split between tuning and reporting seeds.

### 2.3 What is different, now stated against RAPID too

| | ASPIRE | RAPID | ANTS |
|---|---|---|---|
| One demonstration as input | no | **yes** (one human demo + language) | yes |
| Coding agent writes primitives + composition | composes given primitives | **writes** primitives (trajectory-optimisation programs) with per-phase success predicates | composes given primitives; DemoSpec as data |
| Scene variants | fixed seeds from the same sampler | **randomly sampled** (appearance, size, pose, mass, friction, elasticity) + agent-written feasibility filter | **adversary-chosen** within a severity bound, adaptive over categories |
| No regression on every seen case | no (aggregate) | not stated (loop until all variants pass) | **yes** (monotone gate) |
| Memory | flat skill library | primitive library reuse | library + help count + decay + re-verification |
| Escalation to a targeted human demo | no | not stated | **yes** |
| Code released | yes, Apache-2.0 | not stated | – |

**Proposed claim:** "ANTS adds an adversary that chooses where to test, a gate that never regresses on any case seen so far, and escalation to one targeted human demonstration, on top of demo-to-program synthesis (RAPID) and an execution harness (ASPIRE)." Two more papers say "demo → coding agent" now. The contribution is System 2 and the loop, not System 1 alone.

### 2.4 Is it reasonable to base the project on ASPIRE?
**Yes for the substrate, no for the brain.** It is Apache-2.0, maintained (last push 2026-10-16), already has LIBERO-Pro with our split, and its trace and run directory are what the diagnoser needs. Its agent layer assumes a frontier model with subagents, image input, a 258k–1M context and prompt caching. Muse has not been shown to meet any of these. Our own client and orchestrator should drive it.

### 2.5 What to reuse from CaP-X (CaP-Agent0)

[CaP-X](https://github.com/capgym/cap-x) (NVIDIA, Berkeley, Stanford, CMU; MIT licence; repo read at `53e9966`, 2026-04-09). CaP-X and ASPIRE share a lineage: both pin the same SAM 3 fork commit (`Max-Fu/sam3@6fe87d6`), and ASPIRE reports CaP-Agent0 as its baseline [read].

| CaP-X part | Where | Reuse for ANTS |
|---|---|---|
| **CaP-Agent0**: multi-turn loop where the model writes code, sees stdout/stderr (and optionally a text description of visual change), then answers `REGENERATE` + new code or `FINISH`; optional parallel ensemble | `capx/envs/trial.py`, `env_configs/libero/franka_libero_cap_agent0.yaml` | **The no-demo baseline arm (M4).** ASPIRE and RAPID both report against it, so our numbers stay comparable. Hackathon: port the prompt and loop onto our API. Research: run CaP-X itself for an exact baseline |
| **API tiers** per task: `privileged` → `reduced` → `reduced_exampleless`, plus `reduced_skill_library` | `capx/integrations/franka/*_{privileged,reduced,…}.py` | **Abstraction ablation for Muse** (Q7): which API level Muse needs before it writes working programs |
| **Visual differencing (VDM)**: a VLM describes what changed between frames, in text | `trial.py::_get_visual_differencing_feedback` | The diagnoser's feedback format (text, not raw images) |
| **Human oracle programs** (nut assembly, cube stack/restack, two-arm, LIBERO object swap 7) | `env_configs/human_oracle_code/` | **Oracle arm** (upper bound), especially for T3 nut assembly |
| **LLM client**: OpenAI-compatible `server_url`, OpenRouter, ensembles | `capx/llm/client.py` | Pattern for our Muse client (Meta API + OpenRouter) |
| **Skill library**: functions extracted from successful code, counted, promoted when they recur across tasks | `capx/skills/library.py` (211 lines) | Seed of the C1 memory |
| **LIBERO-PRO suites beyond swap/task** (Obj, Sem, Env) | `docs/libero-tasks.md`, `third_party/LIBERO-PRO` | Extra fixed perturbation sets for held-out reporting |

**Do not reuse:**
- The RL stack (`verl`, GRPO): it trains a model.
- Its program execution: programs get full Python (they may `import numpy`), with no sandbox like ASPIRE's, and API results are untyped dicts.
- Its LIBERO seed mapping `state_idx = (seed - 1) % len(init_states)`: with 50 stored states, seed 51 equals seed 1, the same wrap as ASPIRE's `saved` mode [read, `capx/envs/simulators/libero.py`].

**Verdict:** ASPIRE stays the executor, because the gate and the diagnoser need the sandbox, typed statuses and traces. CaP-X supplies the baseline arm, the API-tier ablation, the oracle programs and the text visual-diff format.

---

## 3. Primitive or function?

Your two options in the terms of [research/output-format.md](research/output-format.md):
- **(A) primitive:** the model picks one primitive per step during the episode (it sits in the control loop).
- **(B) function → primitive:** the model writes one program between episodes; the program calls the primitives and runs to completion with its own checks.
- **(C) hybrids:** a skill library of functions (C1), code calling learned VLA skills (C2), a program plus a VLM monitor at checkpoints (C3).

| ANTS need | A, per-step primitives | B, function → primitives |
|---|---|---|
| Regression gate (same case must give the same result) | **Breaks.** Hosted APIs are not reproducible even at temperature 0 | **Holds** (deterministic per seed) |
| Cost of 50 cases × 20 cycles | ≈ $200–500 and 42–243 h at the measured $0.20–0.50 and 150–874 s per episode (WAA, Show-Harness) [read]. That is not Muse pricing, which is unknown | 0 model calls per rollout |
| Failure → constraint | prompt note, effect visible only by rerunning | prompt rule **and** a code diff ("the diff is the explanation") |
| Blame (perception vs program vs primitive) | spread over 30–120 decisions | one traced call |
| Weak or unknown generator | small models collapse with tools (Llama-3.1-8B: 3.7 vs 68.5 with code, ALRM) [read] | robust |
| Where A is better | re-perceives mid-episode: on LIBERO-Pro Spatial, WAA 80/73 vs ASPIRE 51/60 [read] | needs an explicit re-localise or search loop |
| Contact-rich (insertion, pouring) | brittle | brittle. The field's fix is C2, and every C2 system found trains its low level |

**Recommendation: B, at the "high-level API with examples" tier.** Have every primitive return a typed result with a status; the program writes its own checks (gripper width after close, lift height, re-localise after approach); feedback to the generator is text, not raw images (CaP-X: raw images in the loop hurt, text descriptions of visual change help [read]).
- **Hackathon:** B only. If time allows, one small A arm (same primitives as tools, same Muse model, ~10 cases) to show "why code" with our own numbers.
- **Research:** C3 (the program calls `api.verify(...)` only when a typed check fails, capped at K=3, answers cached by observation hash so the gate stays deterministic), then C1 (functions that recur across accepted programs become shared skills), then C2 only for contact-rich steps with an existing checkpoint.
- **Keep the option open in `contracts`:** one `PrimitiveAPI`, a `PolicyRunner.run(api, spec, budget) -> EpisodeTrace` with `ProgramRunner` / `AgentRunner` / `MonitoredProgramRunner`, and `Policy.kind` + `Policy.deterministic`. If `deterministic` is false, the gate needs k seeds per case with Wilson bounds.
- **What settles it:** arms B / A / C3 with the same generator, API, DemoSpec and cases (30 acceptance, 50 held-out). Measure held-out success per category, € per robust policy, gate flip rate and cycles to robust. Decision rule fixed in advance; details in the appendix.

---

## 4. What ASPIRE does not cover, and where to take it from

| Gap for System 1 | Take it from | Lab · cites · ★ | Tier |
|---|---|---|---|
| Demo → segments → per-phase success predicates; scene variants + feasibility filter | **RAPID** ([2609.30249](https://arxiv.org/abs/2609.30249)) | MIT, NUS, UPenn, NVIDIA · 5 · no code | hackathon (pattern only) |
| Hand the demo to the generator without raw video | **RV-ICL** ([2610.06843](https://arxiv.org/abs/2610.06843)): keyframes, phase text, a moment index and short clips as read-only tools. LIBERO-PRO 96.5% vs 92.6% for text memory; raw full video did worse than text [summary] | · 1 · 4 | hackathon |
| Human video → metric hand path, aperture, grasp events | **hurobo** `HumanDemo` (our sibling repo); HaMeR or WiLoR for hands | Berkeley · 487 · 1.2k; Imperial · 229 · 731 | research (Phase 2) |
| Keyframes / moments from video, second-opinion progress signal | **Gemini Robotics-ER 2** (API preview since 2026-07-30; ER 1.6 shut down 2026-08-31) [summary] | Google DeepMind · 106 (1.5 report) | hackathon *if a Google key is approved* |
| Constraints as checkable code | **ReKep** (constraint form), **Code-as-Monitor** (+28.7% under disturbance [abstract]) | Stanford · 517 · 993; PKU et al. · 95 | research |
| Memory that never regresses and does not go stale | **Skill-V** (versioned skills admitted only without regression on replay) + **SkillForge** (re-verify before reuse) | · 0 / 5 | hackathon (design) |
| Turning a human correction into stored code | **ARCHITECT** (corrections tied to code via traces, stored as skills) | UW · 4 | research |
| Demo value depends on the model | **LIBERO-Agent**: video lifted GPT-6 Astra 36% → 66% but not Opus (8.3% → 5.8%) [summary] | · 4 | hackathon: run the no-demo arm on ≥2 model families |
| Asking a human when unsure | **KnowNo** (conformal "ask for help") | Princeton, Google · 499 | research |

Existing picks that remain the best per the radar: SAM 3.1, HaMeR/WiLoR, FoundationPose (Any6D when there is no mesh), CoTracker3, PyRoki, ReKep, Code-as-Monitor, ASPIRE with CaP-X as fallback. Upgrades: Depth Anything 3 (904 cites, 6.6k★) for DA-V2; MoGe-2 for MoGe; GraspGen (NVIDIA, 616★) for Contact-GraspNet, which is also non-commercial only; cuRoboV2 (Apache-2.0 now, but its API breaks v1). **Skip:** world models as verifiers (the simulator plus the benchmark predicate already is the verifier), human-video data engines that train policies, AnyGrasp (licence key).

---

## 5. Hardware: your setup per building block

Setup: one **RTX A5500 Laptop, 16 GB, Ampere sm_86**, 62 GB RAM, Linux; LLMs/VLMs via API.

| System 1 block | Runs where | GPU memory | Fits 16 GB? | If not: alternative |
|---|---|---|---|---|
| LIBERO / robosuite (MuJoCo 3.3, EGL render) | GPU render, CPU physics | ~0.3–1 GB per worker [est] | yes, 1–2 workers | `MUJOCO_GL=osmesa` (untested) |
| SAM 3 / 3.1 (segmentation) | GPU service | **4.2 GiB idle, 7.7 GiB after use** [read, repo] | yes | Meta Model API serves sam-3.1 [summary]; CPU is possible but slow |
| Contact-GraspNet (grasps) | GPU service | ≈0.5–3 GB (SAM 3 + CGN ≈ 8 GB together) [est from repo] | likely | geometric top-down fallback already in ASPIRE's `grasp.md`; optional in its topology |
| PyRoki IK | **CPU** (JAX) | 0 | yes | – |
| cuRobo (collision-aware motion) | GPU only | ~1–3 GB [est] + ~50 s warmup | marginal | leave off for MVP; approach along clear axes |
| Code generator, diagnoser (Muse; others as reference) | API | 0 | – | – |
| Demo perception, sim demo | from LIBERO state (free ground truth) | 0 | yes | – |
| Demo perception, phone video (Phase 2) | GPU: HaMeR (ViT-H) or WiLoR, Depth Anything 3 / MoGe-2, FoundationPose (~7 GB peak [summary]) | one model at a time [est] | yes, run **offline and sequentially**, not alongside the sim | hurobo MediaPipe path (CPU) |
| SAM 3D Objects (mesh from image, real2sim) | GPU | **32 GB documented** | **no** | skip; use object meshes from the sim, or a cloud GPU for offline runs |
| BEHAVIOR-1K / Isaac | GPU | ~12 GB sim + 8 GB perception | **no** | skip |
| Local VLM (Qwen3-VL-8B 4-bit ≈ 7.3 GB, agentic-robot) | GPU | 7.3 GB | only without SAM 3 + sim | API |

**Recommended live configuration:** SAM 3 + 1–2 LIBERO workers + PyRoki on the CPU ≈ 8–10 GB; add Contact-GraspNet if needed (~9–13 GB) [est]. The laptop display also takes VRAM. Wrap every run in a timeout, because orphan sim processes can starve SAM 3 into out-of-memory errors [read, ASPIRE docs].

**SAM 3 vs SAM 3.1** [read, code]. ASPIRE and CaP-X both call `build_sam3_image_model()` from the same fork, which always downloads `facebook/sam3` / `sam3.pt`. In Meta's upstream `sam3` package, the 3.1 checkpoint (`facebook/sam3.1`, `sam3.1_multiplex.pt`) is used only by `build_sam3_multiplex_video_model`, the video multi-object tracker. The image model still loads `sam3.pt`. So:
- **Inside the harness:** SAM 3 is required (per-frame segmentation of the sim camera). 3.1 would add nothing there, and loading its checkpoint into the image model is unverified.
- **For System 1 demo perception** (tracking hand, bowl and plate through a phone clip): use SAM 3.1's video predictor in its own environment with upstream `sam3`. It needs access to `facebook/sam3.1` as well.

**Install gaps on this machine:**
- add an `sm_86` arch entry plus an `a5500` profile (a copy of `rtx4090`); torch cu128 supports sm_86, but the cuRobo build is unverified
- SAM 3 weights are gated on Hugging Face (needs a token; the failure only shows at first load)
- ASPIRE runs in its own Linux-only venvs (numpy 1.26 pin), so keep it **outside** the `ants` package and call it via subprocess

---

## 6. Building-block checklist (high level)

**MVP** = needed for the hackathon demo (by 2026-11-04). **Next** = right after. **Research** = later. ☐ = not started; nothing has been built yet.

**A. Demonstration**
- ☐ MVP: Demo source, a rendered LIBERO demo (simulator ground truth for every extracted quantity)
- ☐ Research: Demo source, a real phone video of a human hand (hurobo path)
- ☐ Next: Demo quality check (complete, visible, usable); a low score escalates before any rollout

**B. Human video → robot data**
- ☐ MVP: Object identity and segmentation/tracking (from sim state first, SAM 3.1 for video)
- ☐ MVP: Grasp/release events and gripper aperture over time
- ☐ MVP: Phases and keyframes (approach, grasp, lift, transport, release) plus a step list
- ☐ MVP: Embodiment mapping: human hand → robot grasp part, approach axis and offsets, **in object frames**
- ☐ Research: 3D lifting from monocular video (depth, object pose, hand pose)
- ☐ MVP: **DemoSpec**, one structured and checkable summary with quality scores
- ☐ MVP: DemoSpec accuracy measured against simulator ground truth

**C. Grounding the scene**
- ☐ MVP: Task context (instruction, objects); the success predicate stays hidden from the policy
- ☐ Research: Real-to-sim scene from video (RAPID / SimFoundry style)

**D. Policy synthesis**
- ☐ MVP: Typed primitive API with status results (ASPIRE `cap-harness` behind our `contracts`)
- ☐ MVP: Generator context: API docs + examples + DemoSpec (as queryable tools, RV-ICL style) + constraints + retrieved policies
- ☐ MVP: Program generation with Muse; one reference model as an arm
- ☐ MVP: Per-phase success checks inside the program (RAPID predicates, ProgPrompt asserts)

**E. Verification before System 2**
- ☐ MVP: Plan gate: static checks (allow-list, no imports, no absolute world coordinates)
- ☐ MVP: Nominal replay on the unperturbed scene, with bounded self-repair
- ☐ Next: Feasibility check for every test case (shared with System 2)
- ☐ Research: Checkpoint monitor (C3) for ambiguous checks

**F. Memory and reuse**
- ☐ MVP: Store accepted policies and constraints with provenance
- ☐ Next: Retrieval by similarity × help count, with decay
- ☐ Research: Re-verification before reuse (staleness) and promotion of shared functions (C1)

**G. Interfaces to System 2 (so it extends cleanly)**
- ☐ MVP: Contracts: `DemoSpec`, `PrimitiveAPI`, `Policy`, `PolicyRunner`, `EpisodeTrace`, `Constraint`
- ☐ MVP: Constraint intake into the generator's context
- ☐ Next: Escalation hook: request a targeted demo and merge it into the DemoSpec
- ☐ Next: Perturbation seam in the harness (`env_factory` wrapper), the only harness change System 2 needs

**H. Evaluation and observability**
- ☐ MVP: No-demo arm (text only), on ≥2 model families
- ☐ Next: Text-spec, retarget-replay, oracle and per-step (A) arms
- ☐ MVP: Logging: tokens, € , model calls, wall time, determinism check
- ☐ MVP: Model-call cache and a rescore script
- ☐ Next: Report generated from logs

---

## 7. Recent work worth adding (by block)

Picked from the module radar for fit with this architecture and for traction (big lab, citations, stars). Lab-level lists with reviews are in the Robot Research Radar artifact.

| Rank | Add | Block | Why | Tier |
|---|---|---|---|---|
| 1 | RAPID's per-phase predicates + feasibility-filtered variants; restate the delta | D, E | variants alone moved RAPID from 0.532 to 0.759 [summary] | hackathon |
| 2 | RV-ICL demo-as-tools hierarchy | B, D | beats text memory and raw video on LIBERO-PRO/Plus [summary] | hackathon |
| 3 | Gemini Robotics-ER 2 for moments and progress | B, E | only off-the-shelf API returning event timestamps | hackathon, **needs a Google key (your approval)** |
| 4 | Skill-V admission + SkillForge re-verification | F | reuses the regression gate; fixes ASPIRE's staleness | hackathon (design) |
| 5 | ARCHITECT-style correction → code | G, F | closest precedent for escalation; targeted-demo requests remain an open gap | research |
| 6 | No-demo arm on two model families | H | demo value is model-dependent (LIBERO-Agent) | hackathon |
| 7 | Perception refresh: SAM 3.1 + Depth Anything 3 / MoGe-2 + HaMeR/WiLoR + FoundationPose/Any6D + SpatialTrackerV2 | B | best current picks, all fit 16 GB | research |
| 8 | GraspGen + cuRoboV2 behind the same API | D | maintained successors, permissive licences | research |

---

## 8. Proposed build plan for System 1 (not started)

The principle is a thin vertical slice first, with contracts that System 2 plugs into unchanged.

1. **Smoke test (day 1).** `cap-harness` with LIBERO + SAM 3 + PyRoki in its own venv, an `a5500` profile, `doctor`, one example program on seed 1. Then **one Muse-written program** on `libero_goal_swap:0` via our client. This answers Q7 (can Muse write a working program over this API?) before anything else is built.
2. **Contracts (pure Python, CI-safe).** `DemoSpec`, `PrimitiveAPI`, `Policy(kind, deterministic)`, `PolicyRunner`, `EpisodeTrace`, `Constraint` (ASPIRE skill-entry shape), `CaseSpec` (seed + perturbation, for System 2).
3. **Harness adapter.** `ProgramRunner` calls `cap-harness run` as a subprocess and parses `outcome.json` and `trace/events.jsonl` into an `EpisodeTrace`. Seeded mode; ANTS acceptance = seeds 51–65, held-out = 1–50.
4. **DemoSpec from simulator ground truth** (LIBERO demo hdf5: gripper events, object poses, object-frame EE path). The no-demo arm and the demo arm run on the same task, chosen by Q1.
5. **Generator.** Muse client with a call cache; prompt = API docs + examples + DemoSpec tools + constraints. Plan gate before every rollout; nominal replay with bounded repair.
6. **System 2 seam.** An `env_factory` perturbation wrapper (friction, mass, pose, camera, light, actuation), so System 2 only adds a planner, a diagnoser and the gate.

**Decided 2026-10-31 (by the user):**
- Harness: ASPIRE `cap-harness` approved, checkout at `ASPIRE`. SAM 3 access available; SAM 3.1 wanted for demo tracking (see §5).
- Budget: Muse via the Meta API, $15 total. Other models via OpenRouter, $5 total. No reference model for now.
- Tasks: T1 (hurobo scaled bowl → plate, real phone clips; hurobo reused read-only) and T2 (LIBERO "book under the shelf") are the main experiments; T0 is the smoke test.
- T1 demo: process the newer clips in `hurobo/data/raw/e1/clips/`, with a 6.0 cm marker size until it is measured.
- README and concept.md restated against RAPID, ASPIRE and CaP-X.
- Ask the user before any run longer than about 15 minutes.

**Decisions needed (default in bold):**
1. **Harness = ASPIRE `cap-harness` in its own venv, driven by our client (not its Claude Code agent layer).** Large dependency; needs your approval (AGENTS.md).
2. **Output format = B (program over primitives); A as a small measured arm.**
3. **Restate the ANTS delta against RAPID + ASPIRE** (§2.3) in concept.md, the README and the paper.
4. Gemini Robotics-ER 2: **not for the MVP** unless you approve a Google API key.
5. **Patch `run.py`/`batch.py` for `env_factory` (~10 lines, kept as a local patch)** vs a launcher monkeypatch.

---

## 9. Corrections to existing docs

| Doc | Says | Should say |
|---|---|---|
| discussion.md §0, §3.1 | ASPIRE "0.72 on LIBERO-Pro, all" | 0.72 = Object/Goal/Spatial macro (60 tasks) |
| discussion.md §3.1 | real robot "4–7× fewer tokens" | 1.7–9.4× |
| discussion.md §3.1 | "at most three replays per debug seed" | v1 paper only; the current repo removed the cap |
| discussion.md §5.1 | Muse endpoint "is a configuration change" in ASPIRE | ASPIRE has no LLM client; we drive `cap-harness` with our own client |
| discussion.md §3.1, §4.1 | ASPIRE 894★, 94 citations | 915★, 97 citations (2026-10-31) |
| paper-vs-docs.md C2 | closest work = ASPIRE | RAPID is closer for System 1 |
