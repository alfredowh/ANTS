# What should the System 1 action model emit: primitives, a program, or a hybrid?

Status: research note, 2026-10-31. It builds on an earlier internal discussion (levels L0–L8) and does not repeat that table. Every number below is quoted from a paper. None comes from our own runs.

**Evidence tags.** **[read]** means the paper's text (HTML) was read for that number. **[summary]** means a model-extracted summary of the full text. **[abstract]** means only the abstract or listing. Some numbers sit only in figures; those are marked "figure only, not extracted". Citation and star counts were **not refreshed**: the radar `metrics.py` timed out on every query today (it is probably rate-limited). The counts in the discussion doc §4.1 (2026-10-28) still apply.

---

## 1. Definitions

The three options differ on four things: what the model emits, when it is called, who reacts to the world during an episode, and how many model calls one rollout costs. In every option the **primitive API is the same**, for example the paper's `locate / move_to / grasp(width, force) / place`, or ASPIRE's `localize_object / generate_grasps / select_grasp / move_to_pose / close_gripper`.

| | **A. Per-step primitives (agent in the loop)** | **B. Program (code-as-policy)** | **C. Hybrids** |
|---|---|---|---|
| Model emits | one tool call per decision: `pick(obj)`, `move_tcp_delta(dx)`, `grasp(w,f)`, … (discussion L4, and L1 when the units are Cartesian deltas as in Show-Harness) | one `run(api, spec)` program with perception calls, geometry, loops, typed-status checks and retries (L5) | C1: reusable functions in a skill library that a program or planner composes. C2: a program whose primitives include learned VLA skills. C3: a program plus a VLM monitor or verifier at checkpoints. C4: incremental block-wise code, where the model writes the next block after each observation |
| When the model is called | at every decision step during the rollout | **between episodes only** (write, then edit after diagnosis) | C1: between episodes. C2: between episodes; the VLA runs every tick. C3: at K checkpoints or on events. C4: once per block |
| Who closes the loop at run time | the model, on every observation | the program's control flow over the typed API results (status, poses, gripper width) | C1: program. C2: program at the high level, VLA at 10–50 Hz. C3: program, with the model as an alarm. C4: model, at block granularity |
| Model calls per rollout | ≈30–120 (WAA 31, Show-Harness 120; see §2) | **0** | C1: 0. C2: 0 LLM calls, plus T VLA forward passes on the local GPU. C3: K, typically 1–5. C4: the number of blocks (ASPIRE BEHAVIOR: one call per block) |
| Deterministic per seed? | No, unless calls are temperature 0 **and** the API is reproducible, which hosted APIs do not guarantee | **Yes** (sim seed plus fixed perception models) | C1: yes. C2: yes only if VLA sampling is seeded. C3, C4: no, same as A |
| What "improving" changes | the agent's system prompt or skill notes | the code and its data (DemoSpec), plus constraints in the generator prompt | C1: library entries. C2: code, but not skill internals. C3: code plus monitor predicates |

A short way to keep them apart: **A is a policy that is a model, B is a policy that is an artifact, and C moves the line between them.** ANTS's gate, memory and "diff as explanation" all assume an artifact.

---

## 2. Evidence

| Work | Lab | Year | Format | Benchmark | Key number | Model calls / episode | Tag |
|---|---|---|---|---|---|---|---|
| **ALRM** (arXiv 2601.19510) | TII Abu Dhabi, DCU | 2026 | **direct A vs B**: "Code-as-Policy" (one Python run per subtask) vs "Tool-as-Policy" (nested tool calls) | 54–56 high-level tasks; lightweight sim with placeholder poses (no perception, no physics); ground truth checked in Gazebo | Strong models are about even. Claude-4.1-Opus: CaP 92.6 vs TaP 93.5. GPT-5: 90.7 vs 85.2. Gemini-2.5-Pro: 73.1 vs 87.0. DeepSeek-V3.1: 84.3 vs 85.2. **Small models collapse under tools.** Llama-3.1-8B: 68.5 vs 3.7. Falcon-H1-7B: 84.3 vs 14.8. Granite-3.3-8B: 53.7 vs 0.0. Latency is usually lower for code (Opus 33 s vs 83 s; Gemini 53 s vs 117 s), but not for GPT-5 (146 s vs 114 s) | not reported (latency only); no variance or run count reported | [read] |
| **CaP-X / CaP-Bench** (2603.22435) | NVIDIA, Berkeley, Stanford, CMU | 2026 | B with tiers: S1 privileged high-level → S2 high-level on real perception → S3 low-level with examples → S4 low-level, signatures only. Feedback: M1 text stdout/stderr, M2 raw image, M3 text visual differencing, M4 = M3 on the S3 API | 39 tasks (Robosuite, LIBERO-PRO, BEHAVIOR), 12 models | Success rises monotonically from S4 to S1 ("performance improves with human-crafted abstractions but degrades as these priors are removed"). M1 helps every model, **M2 (raw images) hurts**, M3 helps. For Gemini-3-Pro, M4 beats both single-turn S3 and S2. Human expert code: 88.5% single-turn average. LIBERO-PRO average: CaP-Agent0 0.18 vs π0.5 0.13; π0.5 is higher on goal-Pos (0.38 vs 0.26) and spatial-Pos (0.20 vs 0.12). Per-model, per-tier numbers are in figures only (not extracted); the weak-vs-strong split is **not stated in the text** | single-turn: 1 generation; multi-turn: turn count in App. H.5 (not extracted); CaP-Agent0 uses 9 parallel queries per turn | [read] text, figures not extracted |
| CaP-X limitations (App. A) | same | 2026 | → C2 | – | Programmatic control "remains brittle for contact-rich behaviors that require tight visual servoing" (insertion, pouring). Future work: "hybrid CaP-VLA policies, in which a coding agent manages high-level task logic" | – | [read] |
| **ASPIRE** v2 (2607.00272) | NVIDIA GEAR, UMich, UIUC, Berkeley, CMU | 2026 | B + C1 skill library. On BEHAVIOR-1K: **C4** ("incremental block execution, generating each next code block from the current multimodal trace") | LIBERO-Pro (position and task perturbations only), Robosuite, BEHAVIOR-1K | v1 LIBERO-Pro all: 0.72 vs CaP-Agent0 0.18 vs π0.5 0.13. v2: Opus 5.5 averages 99% across 80 LIBERO-Pro tasks. Model ablation (Goal, position perturbation, no search, empty library): GPT-6 Luna 15%, Opus 4.6 56%, Sonnet 5.5 and Opus 5.5 99%. Cost per task: Sonnet 5.5 $12, Opus 5.5 $18, Opus 5 $60 (91%). **No API-granularity ablation**; "predefined API" listed as a limitation | LIBERO/Robosuite eval: 0 (one program evaluated across seeds); BEHAVIOR: one call per block | [summary] v2 HTML |
| **World Action Agent (WAA)** (2609.29964) | HKUST, CUHK (per disc. §4.1) | 2026 | **A**: one tool call per turn (query tools, preview/"imagine" tools, `move_tcp_delta`, `close_gripper`, …), skills distilled from expert video | LIBERO-Pro, 6 cells, 60 episodes per split, Gemini 3.7 Flash | zero-shot 28.9, + seed skills 43.3, **+ skills evolved from LIBERO-90 videos 75.6** (vs ASPIRE 72.0 and RATs 43.8 taken from their papers, and Show-Harness 6.7 rerun). Spatial: WAA 80/73.3 vs ASPIRE 51/60. Goal-Task: WAA 48.3 vs ASPIRE 45 | **31.05 calls, $0.20, 150 s, 194K input tokens per episode** | [read] |
| **Show-Harness** (2609.10522) | NUS Show Lab | 2026 | **A at L1**: one discrete semantic unit per step (MV_±xyz 2–4 cm, ROTATE 15°, GRASP, RELEASE, DONE) | real Franka/AgileX, ManiSkill, RoboLab | Video in context: tidy-up ordering 20% → 20/20. Peg/stack with 2→1 cm steps: zero-shot 60 → 82%. Rerun by WAA on LIBERO-Pro: **6.7% average** | ≈30 steps on average at 96% success (50-step cap). WAA measured **119.8 calls, $0.50, 874 s, 347K input tokens per episode** | [read] |
| **MotorMind** (2609.38078) | UIUC | 2026 | **A with roles**: Planner (subgoals), Executor (short action batches validated by a deterministic controller), Monitor (alert only), Verifier, Memory; one frozen VLM | LIBERO-PRO Goal/Spatial/Object, Qwen3.8-Flash-Next | base 66.7%, **perturbed 53.8%**, vs CaP-X (10 loops) 13.3 / 19.2 on different backbones. Fine-tuned π0.5 63.3 and MolmoAct2 62.9 are higher under perturbation. Ablation: no replanning 36.7, no verifier 60.0, no planner 0.0 | not reported; **223–249 s per episode**; 276 ms per query | [read] |
| Code as Policies (2209.07753) | Google | 2023 | B, hierarchical code generation | tabletop sim, 50 trials per task | vs "NL Planner" (few-shot LLM that emits a natural-language step list over skills, i.e. an open-loop L6/A-like plan): long-horizon unseen/unseen **80.0 vs 64.0**; split totals 94.3 / 88.5 / 71.0 vs 86.4 / 88.0 / 64.0. Spatial-geometric: the NL planner cannot express it ("N/A"). RoboCodeGen, hierarchical vs flat: Codex-davinci 95 vs 81, GPT-3 175B 84 vs 68 | 1 per instruction | [read] |
| ProgPrompt (2209.11302) | NVIDIA, USC | 2023 | B with asserts (in-program checks) | VirtualHome, GPT-3 | SR 0.34 with asserts vs 0.28 without, vs 0.00 for a step-list LLM planner (Huang et al.). Codex best: 0.40 | 1 (asserts drive recovery, not the LLM) | [read] |
| SayCan (2204.01691) | Google | 2022 | A: LLM scores every skill at every step, combined with value functions | 101 real kitchen instructions | 84% planning, 74% execution. No-VF 67%, generative 74% planning | 1 scoring query per step | [read] |
| Inner Monologue | Google | 2022 | A + text feedback | – | (carried from disc. §4.1; no new number read) | per step | – |
| Voyager (2305.16291) | NVIDIA, Caltech | 2023 | C1 skill library of verified code | Minecraft | 3.3× more unique items, 2.3× more distance, up to 15.3× faster tech-tree milestones | per task iteration, not per tick | [abstract] |
| Demo2Code (2305.16744) | Cornell | 2023 | B from demonstrations (recursive summarization → spec → recursive code expansion) | Robotouille and others | no numbers in the abstract | 1 pipeline per demo | [abstract] |
| Chain-of-Modality (2504.13351) | Google DeepMind (per disc.) | 2025 | B from video + EMG/audio → plan and force parameters | real robot | "threefold improvement in accuracy" extracting plans and parameters | 1 pipeline per demo | [abstract] |
| Real2Gym (2609.37089) | Shanghai AI Lab, SJTU (per disc.) | 2026 | B per stage + C1 (procedures, object-relative motions, recovery) | sim + real Franka | +16.7% success vs GPT-6 Astra direct mode, **≈74.9% fewer policy-execution tokens**, +33.3% real | – | [abstract] |
| Code-as-Monitor (2412.04455) | PKU et al. | CVPR 2025 | **C3**: VLM-written code checks spatio-temporal constraints at run time | 3 sims + real | +28.7% success, −31.8% execution time under severe disturbance | monitor code runs per tick; VLM called to write it | [abstract] |
| CodeAct (2402.01030) | UIUC | ICML 2024 | B vs JSON/text tool calls (general agents, not robots) | API-Bank + M3ToolEval, 17 LLMs | up to +20% success for code actions | – | [abstract] |
| Gemini Robotics 1.5 (2510.03342) | Google DeepMind | 2025 | **C2-like**: ER 1.5 orchestrator decomposes the task, detects success, calls tools, and calls the VLA as a "specialized tool" in natural language | 8 long-horizon tasks, ALOHA and bi-arm Franka | "thinking" VLA alone ≤44% progress; agent ≈80%. Gemini 2.5 Flash as orchestrator: total failures 44.5% vs 22% for ER 1.5 (planning 25.5 vs 9) | orchestrator call rate not stated | [read] partial |
| Hi Robot (2502.19417) | Physical Intelligence | ICML 2025 | C2: fine-tuned VLM emits language subtasks to π0 | real, 3 platforms | ">40% higher instruction accuracy than GPT-4o" as the high level | high level reruns every 1 s or on user input | [read] partial |
| π0.5 (2504.16054) | Physical Intelligence | 2025 | same model predicts subtask then actions (trained) | real homes | no numbers in the abstract | per chunk | [abstract] |
| GR00T N1 (2503.14734) | NVIDIA | 2025 | System 2 VLM + System 1 diffusion, **jointly trained end-to-end** | – | – | – | [abstract] |
| Agentic WAM AW-0 (2610.30136) | Berkeley, NVIDIA, UT, GT et al. | 2026 | trained code + video + action streams | RoboTwin 2.0, real bimanual | abstract has no numbers. The disc. doc's 71.1% vs 32.9% (with vs without code) was **not re-verified** today | – | [abstract] |

### What the evidence says

1. **Only one same-benchmark A-vs-B comparison exists (ALRM), and it is weak.** It has no perception, no physics, placeholder poses and no variance. The pattern is still clear. Frontier models do about as well, or slightly better, with per-step tools, at roughly 2× the latency. Small models fail badly with tools and keep 50–85% with code. **Code is the safer choice when generator strength is unknown,** and Muse Wonder/Spark is untested (disc. Q7).
2. **On LIBERO-Pro under perturbation the two families are close, but nothing there is controlled.** WAA (A, 75.6%, Gemini 3.7 Flash, skills from LIBERO-90 videos) vs ASPIRE v1 (B, 72.0%, Opus 4.6). ASPIRE v2 reaches 99% with Opus 5.5. MotorMind (A) 53.8% vs CaP-X 19.2% used different models. The real driver in every paper is **model strength + skill memory**, not the output format. Where A wins clearly, it wins on Spatial (WAA 80/73 vs ASPIRE 51/60), because it re-perceives during the episode.
3. **Raw per-step images in the model loop do not help reliably.** CaP-X M2 < M1, and M3 (a text description of the visual change) wins. Show-Harness, the purest per-step design, scores 6.7% on LIBERO-Pro in WAA's rerun. The A papers that do well add heavy structure: rehearsal, skills, verifier, planner.
4. **A's cost is measured and large:** 31–120 calls and $0.20–0.50 per episode (WAA, Show-Harness), and 150–874 s per episode (MotorMind 223–249 s). B costs 0 calls per rollout. Real2Gym reports ≈75% fewer execution tokens for a skill/code design than a direct-mode model.
5. **In-program checks are the cheap substitute for a model in the loop.** ProgPrompt asserts raise SR from 0.28 to 0.34. Code-as-Monitor adds +28.7% under disturbance. MotorMind loses 30 points without replanning, so recovery logic matters, wherever it lives.
6. **Contact-rich behavior is a wall for both A and B.** CaP-X calls programs brittle for insertion and pouring. Show-Harness has no force feedback and its errors concentrate in fine grasping and placement. The field's answer is C2: a planner (code or ER model) on top of a learned VLA skill (Gemini Robotics 1.5, Hi Robot, the CaP-X future work). Every C2 system we found **trains** its low level.

---

## 3. Scoring against ANTS criteria

Scale: ++ strong fit, + fit, 0 neutral, − poor, −− blocks the design. C is scored per variant where they differ.

| Criterion | A per-step | B program | C1 lib | C2 code+VLA | C3 code+monitor | Notes |
|---|---|---|---|---|---|---|
| Frozen generator | + | ++ | ++ | − | ++ | C2's VLA is frozen but has to be fine-tuned on LIBERO first (π0.5 0.13 zero-shot on LIBERO-Pro; fine-tuned 63.3 perturbed per MotorMind's table). That fine-tuning violates "nothing is trained" unless an existing checkpoint is used. |
| Failure → constraint expressible in context | + | ++ | ++ | + | ++ | A: the constraint goes into the agent's prompt, and its effect can only be measured by rerunning the model. B: the constraint is in the generator's prompt **and** its effect is visible as a code diff. C3 adds an executable form (Code-as-Monitor predicate = the `check_code` field already in disc. §7). |
| Gate determinism ("no worse on every seen case") | −− | ++ | ++ | + | − | A: hosted APIs are not bit-reproducible even at temperature 0, so the same policy can flip pass/fail on the same seed. The gate then needs k seeds per case, which multiplies cost. C3: a monitor call flips only at checkpoints; caching monitor answers by observation hash restores replay. |
| Rollout cost (calls × 50 cases × N=20 cycles) | −− | ++ | ++ | + (local GPU) | + | A at WAA's measured $0.20 and 150 s per episode: 1,000 rollouts ≈ $200 and ≈ 42 h. At Show-Harness's $0.50 and 874 s: ≈ $500 and ≈ 243 h. Either one exceeds the €50 budget several times over before any held-out run. Those prices are Gemini Flash and GPT-class prices, **not Muse**. Muse pricing must be checked. B: only generation and diagnosis calls, about 1 + (#failures diagnosed) per cycle. |
| Diagnosability (perception vs program vs primitive) | − | ++ | ++ | − | + | B: ASPIRE-style per-call trace (inputs, outputs, status, keyframes) pins blame to one API call. A: blame is spread over 30–120 decisions, and the fix is a prompt note with no diff. C2: a VLA failure is opaque inside the skill. |
| Pose | + | + | + | + | + | Both re-localize at run time. B must call `locate` after approach, which is a typical constraint. |
| Physics (friction, mass) | + | 0 → + with checks | + | + | ++ | B needs explicit checks (gripper width after close, lift-height check, retry). A only notices slip if it is visible. |
| Clutter | + | + | + | + | + | Perception-bound in both. WAA's Spatial lead suggests per-step re-perception helps. |
| Camera (extrinsics) | 0 | − | − | 0 | 0 | B's back-projection breaks if calibration is stale. A, working from image space, is somewhat more tolerant (untested). |
| Lighting | 0 | 0 | 0 | − | 0 | Perception-bound (SAM 3.1 or the VLM). VLAs are known to be fragile here (LIBERO-Plus, disc. §4.4). |
| Occlusion | + | − | 0 | + | + | A can "look again" (Show-Harness hidden-object search 35 → 85%). B needs an explicit search loop, which C1 makes reusable. |
| Actuation (noise, latency) | 0 | + | + | 0 | + | B: `move_to` through IK plus a reached-pose check. A: small closed-loop steps correct noise, but model latency (seconds per step) is itself an actuation-latency problem. |
| Contact-rich limit | − | − | − | ++ | − | Only C2 addresses it, at the price of training. |
| Extensibility to System 2 | − | ++ | ++ | + | ++ | B: the adversary perturbs the sim and replays a fixed artifact. The trace is the diagnoser's input, and the paper's rule-based fallback diagnoser reads the same event log. |
| Demo usefulness | + | ++ | ++ | + | ++ | A: the demo is in-context (Show-Harness 20% → 20/20 on ordering; WAA video → skills). B: the demo becomes **DemoSpec data** inside the program (waypoints in object frame, aperture, order, grasp part). That is checkable against sim ground truth and gives a clean no-demo ablation. |
| Hackathon feasibility by 2026-11-04 (4 days) | − | ++ | + | −− | + | B is the path the team paper and contracts already assume (`run(robot)`). A needs a run-time agent harness plus budget. C2 needs a VLA checkpoint on a 16 GB GPU plus LIBERO integration. C3 is a small add-on once B runs. |

**Totals (qualitative):** B dominates on everything ANTS's loop needs: gate, cost, diagnosis, memory and demo-as-data. A's real advantage is per-step re-perception (spatial, occlusion), and only with a strong model and heavy scaffolding. C3 recovers part of that advantage at a small, bounded cost. C2 is the only answer to contact-rich tasks, and it breaks "nothing is trained" unless an off-the-shelf checkpoint is used.

---

## 4. Recommendation

**Choose B: a program over a typed primitive API, with the demo as data and deterministic in-program checks. Keep the generator out of the run-time loop.** Treat A as a measured baseline arm, not the main system. Keep C3 and C2 as the research-tier upgrades.

### Hackathon tier (until 2026-11-04)
1. **B only, at the "high-level API with examples" tier** (CaP-X S2 with examples; ASPIRE-style typed results with `status`). The ALRM and CaP-X findings both say weaker or unknown generators need the higher abstraction. Use the paper's four primitives, each returning a typed `Result(status, value, evidence)`, plus `observe()` for state checks (gripper width, object pose). The program writes its own checks; no LLM is called inside `run`.
2. **Feedback to the generator as text, not raw images** (CaP-X M3 > M2): the diagnoser sends a failure signature and a text visual-difference description.
3. **Per-episode logging of `model_calls` (0 for B), tokens, wall time and a determinism check** (replay one accepted policy on 5 seeds twice; flip rate must be 0). This makes the cost slide honest.
4. If time allows, run **one small A arm**: the same primitives exposed as tools, the same Muse model, about 10 acceptance cases. It shows the "why code" claim with our own numbers instead of borrowed ones.

### Research tier
- **C3, program + event-triggered VLM monitor:** the program calls `api.verify(question)` only when a typed check fails or is ambiguous. Cap it at K per episode. Cache answers by (case seed, step, observation hash) so gate replays stay deterministic. Also log the monitor's misses as constraints.
- **C1, skill library:** promote functions that recur across accepted programs (CaP-X `skills/library.py` and ASPIRE skill entries) into memory. This is the "skills are shared" claim.
- **C2, code calling a VLA skill** for contact-rich steps only, behind the same primitive signature (the paper's N2: "primitives may later be learned skill policies"). Use an existing LIBERO checkpoint, seed its sampling, and log it as a non-deterministic primitive.
- **C4, block-wise generation:** only if long-horizon tasks appear (ASPIRE's BEHAVIOR setting).

### Keeping the option open in `src/ants/contracts/`
- **One `PrimitiveAPI` Protocol**, the same for every option (`locate`, `move_to`, `grasp(width, force)`, `place`, `observe`). Each returns a typed `Result` with `status`, and an adapter maps it onto the ASPIRE or CaP-X harness (paper-vs-docs C3). A per-step agent receives exactly this API as its tool schema, so A and B differ only in who calls it.
- **`PolicyRunner` Protocol:** `run(api: PrimitiveAPI, spec: DemoSpec, budget: RunBudget) -> EpisodeTrace`. Implementations: `ProgramRunner(code)` (B, C1, C2), `AgentRunner(model, system_prompt, skills)` (A), `MonitoredProgramRunner(code, monitor, cache)` (C3). The orchestrator and System 2 see only `PolicyRunner` and `EpisodeTrace`.
- **`Policy` gets `kind: Literal["program", "agent", "monitored_program"]`, `deterministic: bool`, and the payload (code, or prompt plus skills).** The gate reads `deterministic`: if it is false, the gate requires `k` seeds per case and compares with Wilson bounds instead of per-case booleans. The rule is explicit and logged.
- **`EpisodeTrace`** = the list of `(primitive, args, Result, keyframe refs)` plus `model_calls`, `tokens`, `wall_s`. It is the same for every runner, so the diagnoser does not care which kind produced it.
- **`Constraint`** stays as written in disc. §7 (NL `rule` plus optional `check_code`). For B it goes to the generator prompt; for A, to the agent's system prompt; for C3, `check_code` becomes a monitor predicate.

### The experiment that settles it
**Arm comparison at fixed generator, API, DemoSpec, task and perturbation set:**

| Arm | Runner | Run-time model calls |
|---|---|---|
| B | program, typed checks | 0 |
| A | per-step tool calling over the same API | per step (cap 50) |
| C3 | program + event-triggered monitor (cap K=3) | ≤ 3 |
| (optional) B-weak / A-weak | same arms with a smaller reference model | – tests ALRM's interaction |

- **Cases:** the acceptance set for tuning (30) and the held-out set for reporting (50), across the seven categories, with the severity clamp in code. If budget is short, run A on a pre-registered subset (for example 10 held-out cases × 7 categories at one seed) and say so.
- **Metrics:** held-out success with Wilson 95% CI, overall and per category. Model calls, tokens, € and wall time per episode **and per robust policy** ("cost to pass the gate"). **Gate flip rate**: the same policy, same seeds, run twice. Cycles to robust. Diagnosis attribution (perception / program / primitive) agreement with sim ground truth.
- **Hypotheses (falsifiable):** H1: B ≥ A on held-out success at ≤ 1/10 of A's € per robust policy. H2: A beats B on occlusion and spatial-pose categories (WAA's Spatial lead). H3: C3 closes most of the H2 gap at ≤ 3 calls per episode. H4: A's gate flip rate > 0 at temperature 0 on the hosted API, while B's = 0. H5 (ALRM): the A–B gap grows in B's favor for the weaker generator.
- **Decision rule, fixed in advance:** keep B unless A beats it on held-out success by more than the CI overlap **at a cost the budget can sustain for N=20 cycles**. Move to C3 if H2 holds and H3 holds.

---

## Sources

- ALRM: <https://arxiv.org/html/2601.19510> [read]
- CaP-X: <https://arxiv.org/abs/2603.22435>, <https://arxiv.org/html/2603.22435> [read; figures not extracted]
- ASPIRE: <https://arxiv.org/abs/2607.00272>, <https://arxiv.org/html/2607.00272v2> [summary]
- World Action Agent: <https://arxiv.org/html/2609.29964> [read]
- Show-Harness: <https://arxiv.org/html/2609.10522> [read]
- MotorMind: <https://arxiv.org/html/2609.38078> [read]
- Code as Policies: <https://arxiv.org/abs/2209.07753>, <https://ar5iv.labs.arxiv.org/html/2209.07753> [read]
- ProgPrompt: <https://ar5iv.labs.arxiv.org/html/2209.11302> [read]
- SayCan: <https://ar5iv.labs.arxiv.org/html/2204.01691> [read]
- Voyager: <https://arxiv.org/abs/2305.16291> [abstract]
- Demo2Code: <https://arxiv.org/abs/2305.16744> [abstract]
- Chain-of-Modality: <https://arxiv.org/abs/2504.13351> [abstract]
- Real2Gym: <https://arxiv.org/abs/2609.37089> [abstract]
- Code-as-Monitor: <https://arxiv.org/abs/2412.04455> [abstract]
- CodeAct: <https://arxiv.org/abs/2402.01030> [abstract]
- Gemini Robotics 1.5: <https://arxiv.org/html/2510.03342> [read, first half]
- Hi Robot: <https://arxiv.org/html/2502.19417v2> [read; figure values not extracted]
- π0.5: <https://arxiv.org/abs/2504.16054> [abstract]
- GR00T N1: <https://arxiv.org/abs/2503.14734> [abstract]
- Agentic WAM AW-0: <https://arxiv.org/abs/2610.30136> [abstract]

**Not checked today:** RoboCodeX, Inner Monologue (no new number), Gemini Robotics-ER tool-calling docs (the page did not render), and the AW-0 71.1% vs 32.9% figure.
