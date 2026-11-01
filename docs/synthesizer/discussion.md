# System 1 (synthesizer): stack, method and policy format, a discussion

Status: discussion draft, 2026-10-28. Nothing here is decided. Every number is quoted from a paper, a README or an API listing, not from our own runs. Our own runs do not exist yet.

**Evidence tags.** **[read]** means the text or code itself was read. **[summary]** means only a model-extracted summary of part of the page was available. **[abstract]** means only the abstract or a search snippet was read. Citation counts come from the Semantic Scholar API and GitHub stars from the GitHub API, both queried on 2026-10-28. Counts for 2026 papers move quickly.

---

## 0. Short version

1. **Policy format.** We recommend **code-as-policy**: one Python program over a typed primitive API. Parameters taken from the demonstration live as data inside the program. This is the only format that meets all four of our constraints together. The model stays frozen. A failure can be written as a constraint in context. The rollout needs zero model calls, so adversarial testing is cheap. The rollout is deterministic for a given seed, so the regression gate is well defined. Section 2 explains the reasoning.
2. **Stack.** Do not build a robot harness from scratch. NVIDIA's [ASPIRE](https://github.com/NVlabs/ASPIRE) harness (`cap_harness`, Apache-2.0) already ships LIBERO-Pro with typed RGB-D, SAM3, Contact-GraspNet, PyRoki and cuRobo. Its seed split matches our acceptance and held-out sets. Its skill-file format is close to our constraint memory. [CaP-X](https://github.com/capgym/cap-x) (MIT) is the lighter fallback. Use either one as the execution substrate behind our `contracts`. Section 5 compares them.
3. **Method.** Run demonstration → **DemoSpec** (a structured, checkable intermediate) → program. Do not go from video straight to code. This gives System 2 two things to blame (perception or program) and lets us score extraction against ground truth. Section 4 has the details.
4. **The biggest risk is not technical.** ASPIRE v2 reports **99% on all 80 LIBERO-Pro tasks with Claude Opus 5.5 and no demonstration at all** (abstract). On a plain LIBERO pick-and-place task, a frontier coding agent may not need our demonstration. Our sibling project agentic-robot found the same thing: a written text spec matched video for the strong models (section 3.5). ANTS must therefore choose a task and metric where the demonstration carries information that text does not, and run a no-demo arm. Section 6 and Q1 cover this.

---

## 1. The questions we need to answer

These are the questions that change what we build. Each has a proposed default, so the answer can be "go with defaults". Section 8 collects them as the decision list.

| # | Question | Why it matters | Proposed default |
|---|---|---|---|
| Q1 | **What does the demonstration tell the policy that the task text does not?** | If nothing, a zero-shot coding agent matches us, as ASPIRE shows. | Pick a task where the instruction is ambiguous and the demonstration resolves it: which part to grasp, the final pose or orientation, the order of steps, or a path shape. Report a no-demo arm. |
| Q2 | **What is the policy's output level?** (joint targets, end-effector deltas, waypoints, constraints, primitive calls, code) | It sets what "a constraint in context" can change, the cost per rollout, and the meaning of the gate. | Code over typed primitives (section 2). |
| Q3 | **Who closes the loop at run time?** The program's own checks, or a model called at every step? | Per-step model calls (Show-Harness style, about 120 per episode) make 50 perturbed cases × N cycles expensive. | The program closes the loop with checks. The model acts only between episodes. |
| Q4 | **Where does the demonstration video come from?** (rendered LIBERO demo, real phone video, or a human acting in a sim-matched scene) | Ground truth for scoring extraction is only available in simulation. | Phase 1: a rendered LIBERO human-teleop demonstration, with gripper aperture read directly. Phase 2: a real phone clip through the hurobo pipeline. |
| Q5 | **What exactly is extracted from the video (DemoSpec)?** | Defines the System 1 input contract and what perception must deliver. | Object masks and tracks, keyframes (grasp, lift, release), object-relative end-effector waypoints, gripper aperture over time, and a step list. |
| Q6 | **Which harness and primitive API do we use?** | It is the largest dependency decision, and every later choice depends on it. | ASPIRE `cap_harness` in its own uv group or venv. CaP-X as fallback. |
| Q7 | **Can Muse Wonder / Muse Spark sustain a write-run-debug loop?** | ASPIRE reports 15–59% for weaker models on one suite and 99% for the strongest. Our generator is not one ASPIRE tested. | Measure it first: a 1-day smoke test on 3 LIBERO-Pro tasks, Muse versus one reference model. |
| Q8 | **What is a constraint, concretely?** | It is the unit that flows from System 2 to System 1. | ASPIRE-style entry: failure signature, when-to-apply, rule or repair, optional code sketch, evidence (run ids). |
| Q9 | **What is in memory and how is it retrieved?** | It is the claim "skills are shared". | Policies and constraints keyed by task text plus a scene embedding (DINOv3 or SAM 3.1 features), weighted by help count, with decay. Start with exact task-text match. |
| Q10 | **What does the gate compare?** Success on every seen case, per category, with how many seeds? | A code policy is deterministic per seed, so "at least as good on every case" is well defined. A stochastic VLA is not. | Per-case success with a fixed seed. The candidate must pass every case the current best passes, and the set of seen cases only grows. |
| Q11 | **When do we escalate to a human?** | It is part of the demo story. | After K=3 cycles with no gate pass on the same failure signature. |
| Q12 | **What is the baseline set?** | Without baselines the closed-loop claim is not isolated. | (a) Zero-shot coding agent, no demo. (b) Demo, no adversary (one-shot program). (c) Uniform instead of adaptive testing. (d) Open-loop retarget replay of the demo (hurobo). |

---

## 2. Policy output formats: what the model emits

The main design choice is what the generator writes. The levels below run from lowest to highest. "Loop" says who reacts to the world at run time.

| Level | The model emits | Rate | Loop closed by | Example works | Training needed? | Fits ANTS? |
|---|---|---|---|---|---|---|
| **L0 Joint targets / torques** | joint position, velocity or torque per tick, often in chunks | 20–1000 Hz | the neural policy | ACT, Diffusion Policy, π0 / π0.5 (action chunks in the robot's action space), GR00T N1.x, "Prompt a Robot to Walk" (an LLM emits PD joint targets) | Yes: imitation learning or fine-tuning. The LLM-as-joint-controller variant is an exception. | No. It violates "nothing is trained", and a failure cannot become a readable constraint. |
| **L1 End-effector deltas** | Δxyz, Δrpy, gripper per tick (LIBERO's native 7-D action) | 10–20 Hz | the policy, or a VLM every step | OpenVLA, SmolVLA (hurobo), Show-Harness (a frozen VLM picks discrete 2–4 cm Cartesian moves) | VLA: yes. Show-Harness: no. | Only the Show-Harness variant fits. It costs about 120 model calls per episode [summary in agentic-robot notes], which is too slow and costly for an adversarial loop. |
| **L2 Waypoints / trajectories in object frame** | a few SE(3) keyframes or a path relative to the objects, then IK | per segment | a geometric controller, re-anchored to object poses | OKAMI (object-aware retargeting of human motion), MimicGen / DemoGen (transform source segments to new layouts), hurobo `retarget.py`, Instant Policy (a graph-diffusion model predicts waypoints) | Retargeting: no. Instant Policy: a pretrained model. | Yes, as **data inside the program**. On its own it has no logic for branching or recovery. |
| **L3 Spatial constraints / cost maps** | code that defines costs or constraints over keypoints or voxels; an optimizer finds the motion | 10 Hz re-solve | the optimizer and keypoint tracking | VoxPoser (LLM code composes 3D value maps), ReKep (Python cost functions over keypoints, `f(k) ≤ 0`), MOKA, OmniManip; Code-as-Monitor uses the same form for failure checks | No | A strong option for the "constraint" vocabulary. Needs keypoint tracking and an optimizer at run time. |
| **L4 Primitive / tool calls** | one parameterized skill call per step, such as `pick(obj)` or `move_to(pose)`, chosen by the model at every step | per step | the model at every step | Show-Harness, WAA, MotorMind, SeeDo (action list), agentic-robot I12 `pick_place(part, slot)` | No | Readable, but the model sits in the run-time loop. Each rollout costs model calls. |
| **L5 Code-as-policy** | a whole program: perception calls, geometry, motion calls, loops, checks, retries | runs to completion | the program's own control flow; the model edits between episodes | Code as Policies, CaP-X, **ASPIRE**, Real2Gym, Demo2Code, Chain-of-Modality, RoboPro | No (CaP-RL is an optional GRPO variant) | **Recommended.** A constraint becomes a code change or a rule in context. The rollout costs zero model calls and is deterministic per seed. The diff between versions is the explanation. |
| **L6 Task plan** | an ordered list of symbolic or language subgoals | per subtask | a lower-level executor | SayCan, ProgPrompt, Inner Monologue, SeeDo | No | As a step list inside DemoSpec only. |
| **L7 Task and reward code, then RL** | environment, reward or success code; RL then trains a neural policy | offline | the trained policy | Eureka, GenSim, RoboGen, Video2Policy | Yes (RL) | No, because it trains. Video2Policy's video → task code idea is still useful for building scenes. |
| **L8 In-context neural** | actions from a meta-trained model that takes the demonstration as its prompt | 10–20 Hz | the neural policy | Instant Policy, MT3 (retrieval), Machenta "VDA", Zero-WAM, HOST | No per-task training, but a large pre-training run | No. The model is frozen, but constraints cannot be added as context, and there is no LIBERO checkpoint to reuse. |

How the levels nest:

- **L5 code calls L4 primitives**, which call L1/L0 controllers through IK and motion planners (PyRoki, cuRobo).
- The demonstration enters as **L2 data**: object-relative waypoints, grasp offset, release height, aperture timing.
- A failure enters as an **L3-style rule** in natural language, or as a code patch.

ASPIRE's API makes this concrete [read, `docs/api-reference.md`]. Generated programs call `localize_object`, `generate_grasps`, `select_grasp`, `move_to_pose` and `close_gripper`. Each call returns a typed result with a status. Programs "cannot import modules and do not receive NumPy, filesystem, network, native simulator, reward, or success-predicate access." That last rule matters for an honest evaluation: the policy cannot read the success check.

**Hybrid for later.** CaP-X's limitations section says programmatic control is "brittle for contact-rich behaviors" such as insertion and pouring, and suggests a code planner that calls a VLA skill [summary]. Agentic WAM (AW-0) generates code, video and actions together and reports 71.1% real-world versus 32.9% without code. That model is trained at 8-GPU scale. Both are out of scope now. They mark the upgrade path if L5 hits a contact-rich wall.

---

## 3. Sources studied

### 3.1 ASPIRE: Agentic Skill Programming through Iterative Robot Exploration (NVIDIA GEAR, with UMich, UIUC, Berkeley, CMU)

[arXiv 2607.00272](https://arxiv.org/abs/2607.00272) · [project](https://research.nvidia.com/labs/gear/aspire/) · [code](https://github.com/NVlabs/ASPIRE), Apache-2.0, 894★ · 94 citations · [read] v1 HTML, README, docs; v2 via the abstract

**Policy.** L5 code-as-policy. A frozen coding agent (Claude Code with Opus 4.6 in v1; real robot: Codex with GPT-5.5) writes Python over the typed API. No weights are trained. Skills are markdown files injected as context.

**Loop.**
1. **Coordinator and actors.** One actor per task. Actors share only distilled skills, never chat logs.
2. **Execution engine.** It records every API call's inputs, outputs, status, and RGB keyframes just before and after the call. The agent debugs from this trace.
3. **Evolutionary search.** It samples K programs conditioned on the top three so far and their failure traces, and evaluates them on debug seeds.
4. **Skill admission.** A skill is admitted only after a fresh verifier agent reproduces the fix. Each entry holds a failure signature, a when-to-apply condition, a repair strategy and optionally a code sketch.
5. **Curriculum and backward transfer.** Low-scoring tasks are rerun with the newer library.

**Protocol.** LIBERO-Pro: learn on seeds 51–65, evaluate on seeds 1–50. Robosuite: learn on 101–125, evaluate on 1–100. BEHAVIOR-1K: learn on 26–35, evaluate on 1–25. The fix loop allows at most three replays per debug seed and no seed-specific branches. Held-out seeds run once, after the fix is final [read, App. E.3]. **This is our acceptance and held-out split, already implemented.**

**Results** (v1, Opus 4.6):

| Benchmark | ASPIRE | Comparison |
|---|---|---|
| LIBERO-Pro, all | **0.72** | CaP-Agent0 0.18, π0.5 0.13, OpenVLA and π0 0.00 |
| Robosuite two-arm handover | 0.92 | 0.20 before |
| BEHAVIOR radio task | 0.88 | 0.56 before |

- Ablation: about 14% with no engine and no search, 62% with the engine, 72% with both.
- Zero-shot LIBERO-Pro Long using skills learned on LIBERO-90: 0.047 (0 tasks) rising to 0.305 (90 tasks).
- v2 abstract: Opus 5.5 reaches **99% across all 80 LIBERO-Pro tasks**. Model ablation, Goal suite under position perturbation: GPT-6 Luna 15%, Opus 4.6 56%, Sonnet 5.5 and Opus 5.5 99%. Sonnet 5.5 costs about $12 per task.
- Real YAM robot with skills: lift soda can 13/20 → 19/20, open drawer 0/20 → 11/20, and 4–7× fewer tokens.

**Limitations they state.** The loop depends on a frozen frontier LLM. The predefined API bounds what can be expressed. Skills are verified only once and can go stale. The loop is compute-heavy. Real-world use still needs a human for resets and guidance.

**For ANTS.**
- (a) Its harness as our System 2 rollout engine and System 1 primitive API.
- (b) The per-call trace as the diagnoser's evidence.
- (c) The skill-entry schema as our constraint schema.
- (d) The seed protocol as our acceptance/held-out split.
- **What ASPIRE does not have:** a demonstration as input, an adversary that *chooses* perturbations (it uses LIBERO-Pro's fixed seeds), a monotone gate over all cases seen so far (it selects the best program on debug seeds), and escalation to a human demonstration. **This is the ANTS delta and it should be stated that narrowly.**

### 3.2 CaP-X: benchmarking and improving coding agents for manipulation (NVIDIA, Berkeley, Stanford, CMU)

[arXiv 2603.22435](https://arxiv.org/abs/2603.22435) · [project](https://capgym.github.io/) · [code](https://github.com/capgym/cap-x), MIT, 891★ · 144 citations · [read] README and repo tree; paper HTML partly [summary]

**What it is.**
- **CaP-Gym** is a Gymnasium REPL: one turn means the agent writes a program and it runs to completion. It has 39 tasks across Robosuite, LIBERO-PRO and BEHAVIOR.
- **CaP-Bench** has 8 tiers. S1–S4 vary abstraction, from privileged state down to raw primitives with no examples. M1–M4 vary feedback: text, raw images, visual differencing.
- **CaP-Agent0** adds multi-turn visual differencing, an auto-synthesized skill library and 9 parallel queries (3 each to GPT-5.2, Opus 4.5 and Gemini-3-Pro).
- **CaP-RL** applies GRPO to Qwen2.5-Coder-7B.

**Perception and control.**
- SAM 3 text and point prompts, Molmo 2 pointing, OWL-ViT, SAM 2.
- Contact-GraspNet for grasps.
- PyRoki for IK, cuRobo optional.
- All run as local servers launched from YAML (`capx/serving/`).

**Results.**
- LIBERO-PRO: CaP-Agent0 0.18 average against π0.5 0.13. π0.5 is higher on goal-position and spatial-position cells.
- BEHAVIOR radio task: 56% against a human-written 36%.
- CaP-RL in sim: 20% → 72% average. Real Franka: cube lift 84%, stack 76% (N=25).
- Findings: higher abstraction helps weak models most. Raw images in the multi-turn context *hurt* compared with text feedback (M2 < M1). A text visual-difference description helps (M3).

**Code structure** [read].
- `capx/envs/simulators/` holds one file per task.
- `capx/integrations/franka/*_{privileged,reduced,reduced_exampleless,reduced_skill_library}.py` are the API tiers.
- `capx/skills/library.py` stores skills as functions extracted from successful code by regex, counted by occurrences and promoted when they recur across tasks.
- `capx/llm/client.py` plus `serving/openrouter_server.py` make any model a configuration change.
- `env_configs/**.yaml` holds one YAML per task × tier.
- Caveat: LIBERO needs a separate venv (robosuite 1.4 vs 1.5 conflict). The base install uses Python 3.10.

**For ANTS.**
- (a) Proof that the tier matters. Muse may need the "reduced API with examples" tier.
- (b) The finding that **text descriptions of visual change beat raw images** in the feedback loop. This shapes the diagnoser's output format.
- (c) A simpler skill library to copy if ASPIRE is too heavy.

### 3.3 Machenta "Instant Robot Learning" and the Imperial line of work (Edward Johns)

[blog](https://machenta.com/blog/instant-robot-learning), 2026-10-27 · [read]. The blog index had one post. **Deeper note (all five Imperial works, SynthICL as the likely basis of the "VDA", licences, what ANTS covers): [instant-learning.md](../dev/instant-learning.md).**

**Policy.** L8 in-context neural. A "vision-demo-action" model replaces the language input of a VLA with one demonstration. It is meta-trained on simulation data so that it "learns how to learn a task", then runs closed-loop on six robots and four teaching modes, including the teacher's own hands.

**Results.** Self-reported reliability over one hour per task: 74/74 block placements, 78/78 handovers, 97/99 bottle uprighting. There is no benchmark, no baselines and no independent evaluation. The model and its size are not named.

**Cited lineage.**
- **Instant Policy** ([arXiv 2411.12633](https://arxiv.org/abs/2411.12633), ICLR 2025, 66 citations, [code](https://github.com/vv19/instant_policy) 94★). A graph-diffusion model trained on procedurally generated pseudo-demonstrations, given 1–2 demonstrations in context. RLBench, 24 tasks: 0.97 seen / 0.82 unseen against about 0.6 for the baselines.
- **MT3 / Learning a Thousand Tasks in a Day** (Science Robotics 2025, [code](https://github.com/kamil-dreczkowski/learning_thousand_tasks) 153★). Retrieval plus trajectory transfer: an alignment phase, then replay of the interaction phase. 1000 tasks from one demonstration each.
- **Implicit Graph Alignment** (CoRL 2023).

**For ANTS.**
- (a) MT3's **alignment then interaction** split is the same decomposition our DemoSpec should use: reach the object pose with a motion planner, then replay the demonstrated interaction segment in the object frame. hurobo and MimicGen do the same.
- (b) Machenta's "physical vibe coding" (iterate on the *demonstration* until the behavior works) is our escalation step in another form.
- (c) This is the competing paradigm. It needs no LLM, but it cannot take a constraint and it is not readable. We should say so in the pitch rather than ignore it.

### 3.4 hurobo (sibling repo, our own)

[read] README, CLAUDE.md, docs, module headers · [github.com/alfredowh/hurobo](https://github.com/alfredowh/hurobo)

**Stack.**
- Phone video at 1080p30 on a tripod, ChArUco calibration.
- ArUco markers on the table and objects.
- MediaPipe Hand Landmarker plus `solvePnP` gives a metric hand TCP (thumb-index midpoint) and pinch aperture, giving `HumanDemo` (table frame, 20 Hz, grasp signal by hysteresis).
- A LIBERO scaled-native scene.
- MimicGen-style object-centric retargeting (`retarget.py`, `mimicgen.py`), kept only on success.
- LeRobotDataset v3, then a SmolVLA fine-tune.

**Policy.** L1, a neural VLA trained on generated data.

**Result.** 14/20 on held-out layouts (Wilson 95% CI 48–85%) against 0/20 for the pretrained checkpoints. The repo's own review says the key control (synthetic path, no human data) was not run, so the human video is not shown to be necessary.

**For ANTS.**
- (a) `HumanDemo` already *is* most of a DemoSpec: TCP path, aperture, grasp segments and object poses in a stated frame. Map it straight into `contracts`.
- (b) `retarget.py` is the **open-loop retarget replay baseline** (Q12d), and could back a `replay_segment` primitive.
- (c) Its lessons carry over: frames named explicitly (`T_table_bowl`), real-size objects so the human path fits the simulator, and the honest review standard.
- Caveat: hurobo is Linux, CUDA 12.6, Python 3.12, LeRobot 0.6 and markers. Do not import its environment into ANTS. Port only the pure-NumPy pieces, or call it as a separate tool that writes DemoSpec JSON.

### 3.5 agentic-robot (sibling repo, our own): I12 "film the worker once"

[read] handoff.md, docs/results-i12.md, docs/ideas.md, docs/robot-llm-project.md · [github.com/alfredowh/agentic-robot](https://github.com/alfredowh/agentic-robot)

**Stack.**
- A frozen VLM turns a kitting video into a JSON plan (`pick_place(part_type, slot_index)`, L4/L6).
- A MuJoCo cell with a gate checks schema, whitelist, slot range and stock, then runs a per-step verifier with one repair.
- SAM 3 grounds the tray pose: "grid tray" prompt, ≤1.5 mm error on renders.
- An OpenRouter client (Gemini 3.8 Flash, Muse Spark 1.3) and local models (Qwen3-VL-8B, Cosmos-Reason2-2B).
- A harness with arms oracle / compile / icl / zeroshot / textspec.

**Results.** All on 5 drawn synthetic videos, labelled V (verified) in that repo:
- Compile from video: Gemini and Muse Spark 1.00, Qwen and Cosmos 0.00.
- **Text spec with no video:** Muse 1.00, Qwen 0.80, Cosmos 0.65.
- No model ever filled the `unclear` field.
- Cross-model step disagreement flags wrong steps (AUROC 0.98, inflated).

**For ANTS.**
- (a) **The textspec result is the warning behind Q1.** For strong models the video was convenience, not capability.
- (b) A plan gate before execution (schema, whitelist, ranges) catches bad programs cheaply. Put it in front of every rollout.
- (c) Self-reported uncertainty does not work. Use disagreement across samples or models, or verifier failure, as the "ask a human" trigger.
- (d) Muse Spark 1.3 works through OpenRouter and handles video input. The spend history is in that repo: 2.06 USD of a 5 USD cap.
- Its related-work audit found several close relatives (Real2Gym, Agentic RSR, DexAgent; section 4) and concluded "the video builds the cell" is no longer novel. The same audit applies to ANTS.

---

## 4. Related work landscape

Prioritized by lab and by uptake, as requested. Cit. = Semantic Scholar citations, ★ = GitHub stars (both 2026-10-28). "–" means no public repo was found.

### 4.1 Code-as-policy and agentic program synthesis

| Work | Lab | Venue | Cit. | ★ | Format | Takeaway for ANTS |
|---|---|---|---|---|---|---|
| Code as Policies | Google | ICRA 2023 | 2183 | (in google-research monorepo) | L5 | The origin of the format |
| ProgPrompt | NVIDIA, USC | ICRA 2023 | 1192 | – | L6 → L5 | Program-style prompts with asserts |
| Inner Monologue | Google | CoRL 2022 | 1773 | – | L6 + feedback | Success and scene feedback as text in the loop |
| VoxPoser | Stanford | CoRL 2023 | 1301 | 837 | L3 | LLM code composes value maps |
| ReKep | Stanford | CoRL 2024 | 514 | 991 | L3 | Constraints as Python cost functions over keypoints; real-world 44.3% auto vs VoxPoser 10% [summary] |
| Voyager | NVIDIA, Caltech | TMLR | 2735 | 7295 | L5 + skill library | The skill-library pattern (verified code, retrieved by embedding) |
| MOKA | Berkeley | RSS 2024 | 190 | 101 | L3 (marks) | VLM visual prompting for keypoints |
| OmniManip | PKU, AgiBot | CVPR 2025 | 112 | – | L3 | Object-centric interaction primitives as constraints |
| **CaP-X** | NVIDIA, Berkeley, Stanford, CMU | 2026 | 144 | 891 | L5 | Section 3.2 |
| **ASPIRE** | NVIDIA, UMich, UIUC, Berkeley, CMU | 2026 | 94 | 894 | L5 + skills | Section 3.1 |
| Show-Harness | NUS Show Lab | 2026 | 32 | 592 | L4 discrete Cartesian | Frozen VLM picks one unit per step; about 120 calls per episode |
| World Action Agent | HKUST, CUHK | 2026 | 4 | – | L4 tools + rehearsal | Expert video → evolved skills; LIBERO-Pro 28.9% → 75.6% [agentic-robot notes] |
| MotorMind | UIUC | 2026 | – | 115 | L4, five roles | Planner, executor, verifier, monitor, memory on one frozen VLM |
| Agentic WAM (AW-0) | Berkeley, NVIDIA, UPenn | 2026 | 0 | 125 | code + video + action | Trained jointly; code ablation 32.9% → 71.1% |
| Real2Gym | Shanghai AI Lab, SJTU | 2026 | 3 | – | L5 per subtask | Video → MuJoCo gym; code with entry conditions, checks and a completion condition; skills with applicability and recovery |
| RoboInspector | – | ACM TIST | 2 | – | analysis | Why LLM policy code is unreliable; a checklist for the diagnoser |

### 4.2 One demonstration or one human video to a robot

| Work | Lab | Venue | Cit. | ★ | What is extracted → policy format | Takeaway for ANTS |
|---|---|---|---|---|---|---|
| MimicGen | NVIDIA | CoRL 2023 | 558 | 661 | object-centric segments → L2 replay → BC | The segment-in-object-frame idea behind DemoSpec |
| MimicPlay | Stanford, NVIDIA | CoRL 2023 | 404 | – | human play → latent plans | – |
| OKAMI | UT Austin, NVIDIA | CoRL 2024 | 134 | 37 | one RGB-D video → plan steps with object point clouds and hand trajectories → L2 retarget plus IK | Keyframes from CoTracker velocity changes; GPT-4V names objects, Grounded-SAM and Cutie track them. 71.7% real |
| ORION | UT Austin | Auton. Robots | 87 | – | open-world object graphs from one video | The OKAMI predecessor |
| Demo2Code | Cornell | NeurIPS 2023 | 67 | 6 | demonstrations → recursive language spec → L5 code | The closest "demo → spec → code" design. Pass rate 0.88 vs 0.19 for language-only, tabletop [summary] |
| SeeDo | NYU (ai4ce) | IROS 2025 | 65 | 92 | keyframes from hand tracking + SAM2 → step list → CaP code | Uniform frame sampling instead of keyframes drops task success to about 0–1% |
| Chain-of-Modality | Google DeepMind, Stanford | ICRA 2025 | 10 | – | video + EMG / audio + HaMeR fingertips → L5 code over `Grasp/Twist/Insert(..., force)` | Process the modalities in sequence; 73% real |
| VLMimic | – | NeurIPS 2024 | 25 | – | keypoints and waypoints from human video → skill code with refinement | – |
| Video2Policy | Tsinghua, Berkeley, UCSD | 2025 | 38 | – | internet video → task and reward code → RL (L7) | GroundingDINO, SAM-2, FoundationPose pipeline from video to a sim task |
| DemoGen | Tsinghua | RSS 2025 | 141 | 259 | one demonstration → synthetic demonstrations | One-demo data multiplication |
| Phantom | Stanford | CoRL 2025 | 122 | – | human video → robot-rendered training data | – |
| EgoMimic | Georgia Tech | ICRA 2025 | 318 | – | egocentric video co-training | – |
| Gen2Act | Google DeepMind, CMU | 2024 | 217 | – | generated human video → policy | – |
| Im2Flow2Act | Stanford, Columbia | CoRL 2024 | 208 | 159 | object flow as the interface | – |
| NovaFlow | – | ICRA | 60 | – | generated video → 3D object flow → execution, training-free | – |
| Instant Policy | Imperial | ICLR 2025 | 66 | 94 | demonstrations in context → graph diffusion (L8) | Section 3.3 |
| DexAgent | Stanford, Columbia | 2026 | 2 | – | one egocentric video → verified sim trajectories, with verifiers per stage | Growing library of skills **and verifiers**: 85 skills and 168 verifiers after 100 samples |
| Zero-WAM / HOST | HKUST / BIT, Tsinghua | 2026 | 21 / 10 | – | trained in-context video-action models | Competing L8 line |

### 4.3 Failure explanation, monitoring and memory

| Work | Lab | Venue | Cit. | ★ | Takeaway for ANTS |
|---|---|---|---|---|---|
| Reflexion | Princeton, MIT, Northeastern | NeurIPS 2023 | 6355 | – | Verbal feedback in memory instead of gradients: the agent-side form of "constraints as context" |
| REFLECT | Columbia, Stanford | CoRL 2023 | 335 | 113 | Hierarchical summary of robot experience → failure explanation → correction: a template for the diagnoser |
| AHA | NVIDIA, UW | ICLR 2025 | 219 | 77 | A VLM fine-tuned to detect and explain manipulation failures, with a failure taxonomy |
| Code-as-Monitor | Beihang, PKU, BAAI | CVPR 2025 | 94 | – | VLM-written monitor code over constraint elements returns a failure flag and a reason: constraints as executable checks |
| DROC | Stanford | ICRA 2024 | 93 | – | Language corrections distilled and retrieved later: correction memory |
| FailBench | – | 2026 | 3 | – | VLM failure judges near chance on contact-heavy tasks, biased toward "success": do not let a VLM be the only success signal [agentic-robot notes, abstract] |

### 4.4 Robustness and adversarial testing (relevant to System 2, listed here because constraints come from it)

| Work | Lab | Venue | Cit. | ★ | Perturbations and severity |
|---|---|---|---|---|---|
| LIBERO-PRO | HUST, Tsinghua, Lehigh | 2025 | 224 | 346 | Objects, initial positions, instructions, environment. Severity is a bound `dist_k ≤ δ_k` plus a requirement that behavior changes. VLAs drop from over 90% to 0.0% |
| LIBERO-Plus | NUS, Fudan | 2025 | 369 | 485 | 7 dimensions with parameters: camera, robot initial state, language, light, background, sensor noise, layout. OpenVLA-OFT drops from 97.1 to 37.2 under robot-init perturbation |
| Embodied Red Teaming | MIT (Improbable AI), Amazon | 2024 | 26 | – | A VLM proposes hard instructions, with failure feedback and a diversity filter: CALVIN 90% → 53% |
| Geometric Red-Teaming | CMU, NIST | CoRL 2025 | 6 | – | Budgeted mesh deformations ("CrashShapes"), real success 90% → 22.5% |
| RoboMD | – | 2024 | 9 | – | Failure-mode search with semantic potential fields |

All of these test learned policies. For a code policy the dominant failure modes are expected to differ: perception and segmentation errors, grasp selection, IK and joint limits, and wrong object frames. This is a hypothesis for System 2 to test.

### 4.5 Building blocks

| Block | Option | Lab | ★ | Note |
|---|---|---|---|---|
| Segmentation and tracking | **SAM 3 / 3.1** | Meta | 12125 | SAM 3 paper: 1354 citations. In the hackathon stack. Text prompts plus video tracking. The 3.1 checkpoint needs Meta's `sam3` package, not transformers (agentic-robot, untested) |
| | SAM 2 | Meta | 20067 | 4685 citations. Fallback |
| | Grounded-SAM-2 | IDEA | 3798 | Open-vocabulary boxes → masks |
| Point tracks | CoTracker3 | Meta | 5174 | Keyframes from velocity changes (OKAMI) |
| Hand pose | HaMeR | Berkeley | 1179 | 483 citations. Used by OKAMI and Chain-of-Modality |
| | WiLoR | Imperial | 726 | Faster detector plus reconstruction |
| | MediaPipe | Google | – | What hurobo uses, CPU only |
| Object 6D pose | FoundationPose | NVIDIA | 3659 | 895 citations. Needs a mesh (simulation has one) |
| Object mesh from an image | SAM 3D Objects | Meta | 7596 | Phase 2 real-video path only |
| Monocular depth | Depth Anything V2 | HKU, TikTok | 9040 | Phone video has no depth |
| | MoGe | Microsoft | 3102 | Metric geometry |
| Features / retrieval key | DINOv3 | Meta | 11640 | Memory scene embedding |
| Grasps | Contact-GraspNet | NVIDIA | 542 | In ASPIRE and CaP-X |
| IK and motion | PyRoki | Berkeley | 1812 | Default IK in ASPIRE and CaP-X |
| | cuRobo | NVIDIA | 1942 | Collision-aware planning |
| Simulator | LIBERO / LIBERO-Pro | UT Austin / HUST | 2484 / 346 | In the hackathon stack. 2091 citations (LIBERO) |
| | robosuite | Stanford, UT Austin | 2685 | Under LIBERO; version pin conflicts (1.4 vs 1.5) |
| | ManiSkill3 | UCSD | 3470 | GPU-parallel; not supported by ASPIRE or CaP-X |
| VLAs (contrast only) | openpi π0/π0.5 · GR00T · OpenVLA · LeRobot/SmolVLA | Physical Intelligence · NVIDIA · Stanford · Hugging Face | 14430 · 8279 · 7225 · 28531 | L0/L1 baselines from the papers above; not part of ANTS |

---

## 5. How to use their stacks in ANTS

### 5.1 Harness options

| | **A: ASPIRE `cap_harness`** | **B: CaP-X `capx`** | **C: our own thin LIBERO wrapper** |
|---|---|---|---|
| License | Apache-2.0 (the same as ANTS) | MIT | ours |
| LIBERO-Pro | 80 tasks, 20 Hz, calibrated RGB-D, typed contracts | 130+ LIBERO tasks, YAML per task × tier | write it ourselves (hurobo `sim.py` is a start) |
| Primitive API | typed, documented, no imports in the program, statuses on every call | tiers S1–S4 per task file | ours |
| Trace for the diagnoser | per-call trace plus before/after keyframes | execution logger plus visual differencing | ours |
| Skill / constraint store | markdown skills with verifier admission | regex-extracted functions, frequency promotion | ours |
| Agent integration | Claude Code / Codex skills, MCP server | OpenAI-compatible proxy (OpenRouter, vLLM) | ours |
| Platform | Linux plus NVIDIA GPU; gated SAM3 weights | Linux plus CUDA; LIBERO in a separate venv | any |
| Risk | heavy bootstrap (cuRobo built from source); breaks our "Windows, Ubuntu, macOS" rule | robosuite conflict; Python 3.10 base | time; we would rebuild what both already have |

**Recommendation: A, fall back to B, never C for the full system.** Changing the Muse endpoint is the same in both, since both route through an OpenAI-compatible client.

Keep the harness **outside the `ants` core install**:
- `uv sync --group adversary` installs nothing heavy into the base package.
- `src/ants/adversary/rollout.py` talks to `cap-harness` through its CLI or HTTP provider.
- `contracts` stays pure Python, so the cross-platform CI still passes.

This needs your approval: it is a large dependency (rule from AGENTS.md).

### 5.2 Which module serves which ANTS block

| ANTS block | Borrow from | How |
|---|---|---|
| Demo perception (System 1) | SAM 3.1 tracks; hand keypoints from HaMeR or MediaPipe (hurobo); CoTracker3 keyframes (OKAMI); SeeDo keyframe rule | Writes `DemoSpec` (section 7). In simulation, check against LIBERO ground truth |
| Policy synthesis (System 1) | ASPIRE API as the primitive set; Demo2Code "spec first, then code"; MT3 alignment then interaction | Muse Wonder writes `policy.py` with the DemoSpec and constraints in its prompt |
| Plan gate before rollout | agentic-robot I12 gate; ASPIRE "no imports" rule | AST check: allowed calls only, no imports, parameter ranges |
| Rollout under perturbation (System 2) | `cap_harness` LIBERO-Pro adapter; LIBERO-Plus parameters for camera, light, noise and robot initial state | The adversary picks a category and severity δ; the harness runs it |
| Diagnoser (System 2) | ASPIRE per-call trace; CaP-X finding that text beats raw images; REFLECT summaries; AHA failure taxonomy | Produces a `Failure` with a signature and evidence |
| Constraint (System 2 → 1) | ASPIRE skill entry; ReKep and Code-as-Monitor "constraint as checkable code" | A `Constraint` record, optionally with a check snippet |
| Gate | – (our own; ASPIRE selects the best on debug seeds, which is not monotone) | Per-case comparison over a growing case set |
| Memory | Voyager / CaP-X skill library; DINOv3 key | Store accepted policies plus constraints, with help counts and decay |
| Escalation | Machenta "clarifying demonstrations"; agentic-robot disagreement trigger | Ask for one demonstration targeted at the stuck failure signature |

---

## 6. Method options for System 1

| Option | Pipeline | Pros | Cons | Use as |
|---|---|---|---|---|
| **M1 video → code directly** | frames to Muse Wonder, which writes `policy.py` | simplest | When it fails, we cannot tell whether perception or code is at fault; there is no ground truth to score | ablation arm |
| **M2 video → DemoSpec → code** (recommended) | SAM 3.1 + hand + keyframes → JSON spec → Muse Wonder writes code that uses the spec's numbers | Two blame points; extraction is scored on its own (agentic-robot found plan accuracy and execution success must be reported separately); a constraint can target spec or code | More moving parts | **main** |
| **M3 video → retarget replay** | DemoSpec → hurobo/MimicGen-style object-frame replay, no LLM | strong, cheap, no model | no branching or recovery; cannot take constraints | baseline (Q12d) |
| **M4 text only → code** | task text and scene → coding agent (CaP-Agent0 / ASPIRE style) | the comparison every reviewer will ask for | – | **required baseline** (Q1, Q12a) |
| M5 in-context neural | Instant Policy with the demonstration as prompt | no LLM | no LIBERO checkpoint; cannot take constraints | not planned |

**Where the demonstration has to earn its place** (hypotheses, untested):

1. **Under-specified instructions.** "Put the mug like this": the handle orientation or placement pose comes only from the video.
2. **Grasp choice.** Rim versus handle, or a specific part.
3. **Order and multi-step structure.** This was where Show-Harness ICL went from 20% to 20/20 on ordering tasks.
4. **Path shape.** Wiping, pouring, going around an obstacle.
5. **Cost.** The demonstration starts the loop closer to robust, so fewer cycles and tokens are needed to pass the gate. Measure tokens to robust: with and without the demonstration.
6. **Weaker generators.** Q7: if Muse is closer to the weak end of ASPIRE's model ablation, a demonstration may help more.

---

## 7. Formats (a proposal for `src/ants/contracts/`)

Keep the formats as dataclasses serialized to JSON. Every frame is named explicitly (a hurobo rule).

```python
@dataclass
class DemoSpec:  # System 1 perception output; scored against sim ground truth
    source: str  # "libero_render:<task>/<demo_id>" | "phone:<clip_id>"
    task_text: str
    objects: list[
        ObjectTrack
    ]  # name, SAM 3.1 track id, pose per keyframe in T_world_obj (if known)
    keyframes: list[
        Keyframe
    ]  # t_s, kind in {"approach","grasp","lift","transport","release","retreat"}
    ee_path_obj: dict[
        str, Array
    ]  # per segment: TCP path expressed in the frame of its anchor object
    aperture: Array  # gripper/pinch aperture over time, normalized 0..1
    steps: list[str]  # L6 step list, e.g. ["grasp bowl rim", "place on plate center"]
    quality: dict[str, float]  # track coverage, keyframe confidence; low values trigger escalation


@dataclass
class Policy:  # System 1 output, one accepted or candidate version
    policy_id: str
    parent_id: str | None
    code: str  # policy.py: def run(api, spec) -> None; only allowlisted API calls
    spec_ref: str  # which DemoSpec it uses
    constraints_used: list[str]  # Constraint ids in the prompt
    model: str
    prompt_hash: str
    tokens: int


@dataclass
class Constraint:  # System 2 -> System 1, ASPIRE skill-entry shape
    constraint_id: str
    failure_signature: str  # e.g. "grasp_miss: gripper closed on empty, object yaw > 30 deg"
    when_to_apply: str  # scope: category, task, object
    rule: str  # natural-language repair, e.g. "re-localize after approach; align yaw"
    check_code: str | None  # optional Code-as-Monitor-style predicate over API results
    evidence: list[str]  # run ids, keyframe paths
```

`Failure`, `Perturbation` and `GateDecision` belong to System 2 and the orchestrator. The cross-system rule: a Constraint is the only thing System 2 sends to System 1.

---

## 8. Decisions needed (default in bold)

1. **Q1 task choice.** **LIBERO-Pro pick-and-place in which the demonstration fixes something the text leaves open (placement pose or grasp part)**, or plain "bowl on plate" with the tokens-to-robust metric only.
2. **Q2 format.** **L5 code over the ASPIRE API, with DemoSpec numbers as data.** Alternative: L3 ReKep-style constraints.
3. **Q4 demonstration source.** **A rendered LIBERO demonstration first**, then a hurobo phone clip.
4. **Q6 harness.** **ASPIRE `cap_harness` in a separate group or venv**, or CaP-X, or our own wrapper. This is a large dependency and needs your approval.
5. **Q7.** **A 1-day Muse smoke test on 3 LIBERO-Pro tasks before building the loop.**
6. **Q12 baselines.** **All four** (no demo; one-shot without the adversary; uniform testing; retarget replay).
7. **Folder name.** The request said `docs/synthetizer/`. This file lives in `docs/synthesizer/` to match `src/ants/synthesizer/`. Say if you want the other spelling.

---

## 9. Sources

Primary sources read for this note:

- ASPIRE: [arXiv 2607.00272](https://arxiv.org/abs/2607.00272), [HTML v1](https://arxiv.org/html/2607.00272v1), [project](https://research.nvidia.com/labs/gear/aspire/), [code](https://github.com/NVlabs/ASPIRE) (`docs/api-reference.md`, `docs/libero-pro.md`, `docs/system2.md`)
- CaP-X: [arXiv 2603.22435](https://arxiv.org/abs/2603.22435), [project](https://capgym.github.io/), [code](https://github.com/capgym/cap-x) (README, `capx/skills/library.py`, repo tree)
- Machenta: [blog post](https://machenta.com/blog/instant-robot-learning); [Instant Policy](https://arxiv.org/abs/2411.12633); [MT3](https://www.robot-learning.uk/learning-1000-tasks); [Implicit Graph Alignment](https://www.robot-learning.uk/implicit-graph-alignment)
- Sibling repos: `../hurobo` (README, `docs/frameworks_and_references.md`, `docs/review.md`, `src/hurobo/*`), `../agentic-robot` (`handoff.md`, `docs/results-i12.md`, `docs/ideas.md`, `docs/robot-llm-project.md`, `docs/meta-models-for-llm-robot-project.md`)
- Representations: [OKAMI](https://arxiv.org/abs/2410.11792), [Chain-of-Modality](https://arxiv.org/abs/2504.13351), [Video2Policy](https://arxiv.org/abs/2502.09886), [ReKep](https://arxiv.org/abs/2409.01652), [Demo2Code](https://arxiv.org/abs/2305.16744), [Code-as-Monitor](https://arxiv.org/abs/2412.04455), [Real2Gym](https://arxiv.org/abs/2609.37089)
- Robustness: [LIBERO-PRO](https://arxiv.org/abs/2510.03827), [LIBERO-Plus](https://arxiv.org/abs/2510.13626), [Embodied Red Teaming](https://arxiv.org/abs/2411.18676), [Geometric Red-Teaming](https://arxiv.org/abs/2509.12379)
- Searches: [SeeDo](https://github.com/ai4ce/SeeDo), [ROBOGATE](https://arxiv.org/abs/2603.22126), [RoboInspector](https://arxiv.org/abs/2508.21378), [RoboMD](https://arxiv.org/abs/2412.02818), [VLMimic](https://arxiv.org/abs/2410.20927), [Zero-WAM](https://arxiv.org/abs/2608.26103)

**Limits of this note.**
- Several papers were read only partly (tagged).
- Numbers from competing papers were not reproduced.
- 2026 citation counts are small and change fast.
- OpenAlex gave much lower counts for the same papers (for example, MimicGen 11 against 558), so only Semantic Scholar counts are used.
- Muse model capabilities and prices come from agentic-robot's notes, not from Meta's documentation.

---

## 10. Reusing a ran project: agentic-robot build order against this note

Added 2026-10-30. Sections 0 to 9 are unchanged. This section checks a six-step build order, taken from [reuse-from-agentic-robot.md](../dev/reuse-from-agentic-robot.md) (§6 there), against what this note already decides. Nothing here is decided. For each step it says what is **covered** already, what **conflicts**, and a **proposal**. Evidence tags: **[read]** is the text of this note or the linked doc. The V/P/U levels are agentic-robot's own (measured / partly / unverified); none was re-run.

The order under review:

1. Port the VLM client.
2. Run the no-demo arm.
3. Build the gate and the feasibility check.
4. Build the baseline harness.
5. Add the disagreement-based escalation trigger.
6. Add evidence export.

### 10.1 Step by step

| # | Step | Covered already here | Conflict with this note | Net |
|---|---|---|---|---|
| 1 | VLM client | §3.5(d) Muse via OpenRouter; §5.1 both harnesses use an OpenAI-compatible client; Q7 smoke test (decision 5) | Overlaps harness clients; no video input there | Keep, but small |
| 2 | No-demo arm | Q1, Q12a, M4 "required baseline" (§6), §0 point 4 | Needs a runner and an executor that step 4 and Q6 only provide later | Covered; reorder |
| 3 | Plan gate and feasibility check | Plan gate: §5.2 row "Plan gate before rollout", §3.5(b). Feasibility: not covered | "Gate" means two things here; module placement | Half new |
| 4 | Baseline harness | Q12 (four baselines), Q10, §6 M1 to M4, CaP-X tiers (§3.2) | Extra arms; where it lives; overlap with ASPIRE's seed protocol | Mostly covered |
| 5 | Disagreement trigger | Q11, §3.5(c), §5.2 Escalation row | Q11's default has no disagreement term; a third trigger exists; K programs are not independent | Covered, needs a decision |
| 6 | Evidence export | Not in this note (AGENTS.md rule: numbers come from logged runs) | Two tag systems | New |

### 10.2 Step 1: port the VLM client

**Covered.** Muse Spark 1.3 works through OpenRouter and takes video (§3.5(d)). CaP-X already has `capx/llm/client.py` plus an OpenRouter server, and both harnesses make the model a configuration change (§5.1). Q7 asks for a 1-day Muse smoke test on 3 LIBERO-Pro tasks before the loop (decision 5), which is what agentic-robot's order calls step 1.

**Conflict or overlap.**
- ASPIRE drives Claude Code or Codex agents and CaP-X's client is text-in, code-out. Neither feeds frames or video to a model, which DemoSpec extraction needs. So the client is not redundant, but it should cover only perception and spec calls, not code writing.
- Only Muse **Spark** compile was measured there. Muse **Wonder** (the code writer in §5.2) and the write-run-debug loop (Q7) are still unmeasured.
- Traps recorded there (V): reasoning tokens count against `max_tokens`; `<think>` blocks must be stripped before JSON parsing; a looping local model needs a guard; a salvaged parse is not a good plan.

**Proposal.** One `ask(backend, frames, prompt)` returning a typed object with tokens and seconds, plus a call cache keyed by `(model, prompt_hash, input_hashes)`. Merge it with the Q7 smoke test: the first call it makes is that test.

### 10.3 Step 2: run the no-demo arm

**Covered.** This is the warning that opens §0 (point 4), Q1, Q12a and the "required baseline" row M4 in §6. The agentic-robot textspec result (§3.5) is the evidence: Muse 1.00 / Qwen 0.80 / Cosmos 0.65 with no video, matching video compile for the strong models (V, 5 synthetic videos). ASPIRE's 99% with no demonstration points the same way.

**Conflict.** Order, not content. The arm needs an executor and a runner, but the order builds the harness at step 4, and Q6 (which harness, a large dependency needing approval, decision 4) is still open. So step 2 cannot run before either of those.

**Proposal.**
- Do Q6 first, or run step 2 on a stub executor, then fold it into the harness as one arm.
- Choose the task by Q1 before measuring: if the no-demo arm already solves it, change the task, not the claim.
- Report "tokens to robust, with and without the demonstration" (§6 item 5) as the fallback metric.

### 10.4 Step 3: gate and feasibility check

**Covered.** The pre-rollout program check is §5.2 row "Plan gate before rollout" (AST check: allowed calls only, no imports, parameter ranges) and §3.5(b). ASPIRE's "no imports, no success-predicate access" rule is quoted in §2.

**Not covered.** The feasibility check: every perturbation must be solvable (by a scripted oracle or an IK reachability check), otherwise it is discarded and logged. §4.4 mentions LIBERO-PRO's bound `dist_k ≤ δ_k` and a requirement that behaviour changes, but nothing says the case must be winnable. This matters here because the gate (Q10) requires "at least as good on every case seen so far, and the set only grows". An unwinnable case in that set makes the gate unsatisfiable or meaningless. In agentic-robot a `missing` perturbation scored 0.00 for every arm by construction, which capped the full-suite mean at 0.83 even for the oracle (V).

**Conflicts.**
- **Two meanings of "gate".** Here (Q10, §5.2 row "Gate") it is the **regression gate** between candidate policies. The order means the **plan gate** before a rollout. Name them separately in code and docs.
- **Placement.** The reuse doc puts the plan gate at `adversary/gate.py`. AGENTS.md assigns the regression gate to `orchestrator/`, which is also the only package that knows both systems. A plan gate checks a System 1 output before a System 2 rollout, so it sits between them. A feasibility check is System 2 only.
- ASPIRE's own LIBERO-Pro seeds are fixed, so feasibility is only needed once our adversary chooses perturbations. That is the ANTS delta (§3.1), so the check is a cost of the delta, not an extra.
- **Severity bound δ.** §4.4 gives LIBERO-PRO's bound but not a method to set it. agentic-robot's tray shifts of 30 to 80 mm against a ~10 mm tolerance made the oracle score 0.00 (V). Calibrate δ per category against measured task tolerance and log both.

**Proposal.** `orchestrator/plan_gate.py` (pure function: code string, allow-list, DemoSpec ranges), `adversary/feasibility.py` (oracle or IK check), and keep the regression gate as a separate module. Report `held` (program refused or aborted safely) beside `failed`, never `safe` alone.

### 10.5 Step 4: baseline harness

**Covered.** Q12 lists four baselines (no demo; one-shot without the adversary; uniform instead of adaptive testing; retarget replay). §6 lists M1 to M4. CaP-X's tiers S1 to S4 (§3.2) already express "arms differ in what the model sees". Q10 fixes the per-case, per-seed gate comparison.

**New arms from agentic-robot.**
- **oracle** (hand-written DemoSpec and program): the upper bound.
- **textspec**: a text description of the demo's content (separate from M4, which gets only the task text).
- **with vs without a re-localization primitive**.
- **gate on/off** and **memory on/off** as ablations.

**Conflicts.**
- **Overlap with ASPIRE.** Its harness already has the acceptance and held-out seed protocol (§3.1). Our harness should run arms on top of it, not re-implement the protocol.
- **Placement.** An arm run calls both systems, so by AGENTS.md it belongs in `orchestrator/`. `evalkit/` (split, metrics, logging) should hold only arm configs, the call cache, metrics, Wilson intervals and rescore, with no import of either system.
- **Seeds.** agentic-robot used 3 seeds per cell. A code policy is deterministic for a given seed (Q10), so repeating a seed adds nothing. Fix the number of **cases** up front (the reuse doc suggests e.g. 50 held-out) and put the intervals over cases.
- **Three metrics** are not yet in this note: DemoSpec accuracy (against LIBERO ground truth), program validity (passes the plan gate), rollout success. They extend the "two blame points" argument for M2 (§6).

**Proposal.** Arms as config. One frozen model and one executor per row. Success always from the benchmark's own predicate, never from a policy report or a VLM (FailBench, §4.3). A rescore script from day one, because two scoring bugs in agentic-robot invalidated its first numbers.

### 10.6 Step 5: disagreement-based escalation trigger

**Covered.** Q11 sets escalation after K=3 cycles with no gate pass on the same failure signature. §3.5(c) says to use disagreement across samples or models, or a verifier failure, instead of self-report, and §5.2 lists "agentic-robot disagreement trigger".

**Conflicts.**
- **Q11's default is failure-only.** The reuse doc requires failure recurrence **and** step disagreement. That changes Q11 and should be a decision, not a silent edit.
- **A third trigger already exists.** `DemoSpec.quality` (§7) says low values trigger escalation. Three signals now exist (stalled cycles, disagreement, low spec quality) and nothing says how they combine.
- **Independence.** ASPIRE samples K programs **conditioned on the top three so far** (§3.1), so they share context and their disagreement is correlated. Independent candidates need extra calls, extra models, or both, and a second model may need credentials or paid APIs (AGENTS.md: ask first).
- **Inflated evidence.** The 0.98 AUROC came from four sources, two of them always right. Across configs of one model it fell to 0.73 to 0.83 (V). It was not tested where strong models share an error, nor on real footage. A shared wrong step gets high support and no flag.
- **Unit.** The source compared `(part, slot)` strings. Here the unit should be the primitive-call sequence or the keyframe list, normalised (rounded poses, aliased objects).

**Proposal.** `orchestrator/escalation.py`. Tune the threshold on the acceptance set only. Measure precision and recall against simulator ground truth, include a shared-error case, and compare with two simple triggers (failure count only; self-report). K, thresholds and the failure signature definition go in the logged config.

### 10.7 Step 6: evidence export

**Covered.** Not in this note. AGENTS.md covers it: results in the README must come from logged runs, with a link to the run or doc.

**Conflicts.**
- **Two tag systems.** This note uses [read] / [summary] / [abstract] for sources. agentic-robot uses V / P / U for results. Keep both and say so, since they describe different things (how a source was read vs how a result was verified).
- The source exporter deletes `results/` before writing. Use a versioned run directory instead.

**Proposal.** `evalkit/export.py` writing one results file per run from logs, a README beside it, and raw runs and videos kept out of git. Every number in `docs/` and the README links to it.

### 10.8 Cross-cutting

- **Dependency order.** Steps 2, 4 and 5 all need Q6 (harness choice, decision 4) settled. Until then only steps 1, 3 (pure parts) and 6 can start.
- **Out-of-order risk.** Step 5 multiplies model calls per cycle. With the budget in agentic-robot's notes (about 50 EUR total; OpenRouter capped at 5 USD, 2.06 USD spent as of 2026-10-27; recheck), build the call cache before it, so disagreement can be evaluated by re-sampling and rescoring cached outputs.
- **Not in this order, still open.** The retrieval-time validity check for stored policies (skill staleness, ASPIRE's stated limitation in §3.1) and the Q9 memory design are not covered by these six steps.

### 10.9 Decisions needed (default in bold)

1. **Order.** Move Q6 (harness) and a stub executor **before** step 2, or accept that step 2 waits for step 4.
2. **Naming.** **"plan gate" for the pre-rollout check, "regression gate" for Q10.** Alternatively keep "gate" for both.
3. **Placement.** **Plan gate and escalation in `orchestrator/`, feasibility in `adversary/`, arm configs, metrics and cache in `evalkit/` (no system imports).** The reuse doc's `adversary/gate.py` would change.
4. **Q11.** **Escalate when the failure signature recurs for K=3 cycles AND candidates disagree on the implicated step.** Alternative: keep failure-only.
5. **Trigger precedence.** **Low `DemoSpec.quality` escalates immediately, before any rollout cycles are spent;** the other two combine as in decision 4.
6. **Independent candidates for disagreement.** **Re-sample the same Muse model with different seeds,** accepting that errors are correlated. Alternative: a second model, which needs approval.
7. **Case count.** **Fix N (e.g. 50 held-out cases) up front, with Wilson intervals over cases.**
8. **Tags.** **Keep [read]/[summary]/[abstract] for sources and add V/P/U for our own results.**
