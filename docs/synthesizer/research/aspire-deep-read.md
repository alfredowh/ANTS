# ASPIRE deep read for ANTS (2026-10-31)

**Sources and evidence tags.** Written by a research subagent for [aspire-assessment.md](../aspire-assessment.md); kept as its evidence appendix.
- Repo: `NVlabs/ASPIRE` main, shallow clone at commit `fa00f0e` (2026-10-15). I only read files with cat/grep/sed; I ran, installed and imported nothing. Repo paths below are relative to the repo root.
- Paper: arXiv 2607.00272. I read the v1 (2026-06-30, 4.7 MB) and v2 (2026-10-20, 12.1 MB) HTML as text.
- Evidence tags: **[read]** means I read the text or code myself. **[summary]** means only a tool summary. **[abstract]** means only the abstract or a search snippet. **[est]** is my own estimate, and the reasoning is given.
- Metrics (from `metrics.py`, 2026-10-31): **915 stars**, Apache-2.0, last push 2026-10-16; **97 citations** (Semantic Scholar). ANTS docs currently say 894 stars and 94 citations.

**The title did not change.** The arXiv HTML of both v1 and v2 is titled "ASPIRE: Agentic /Skills Discovery for Robotics" [read]. The expansion "Agentic Skill Programming through Iterative Robot Exploration" is just the acronym, used in the abstract of both versions. v2 adds the 12-model ablation, cost tables, the case study, the Rubik's Cube and System-2 appendix, and the Opus 5.5 near-saturation results.

---

## Corrections to the first-pass ANTS reading (disc. §3.1, §5.1, paper-vs-docs C3)

| ANTS doc says | What is actually there | Evidence |
|---|---|---|
| "LIBERO-Pro, all **0.72**" (v1) | 0.72 is the macro average over **Object, Goal and Spatial only (60 tasks)**, not all 80. Long is reported separately (zero-shot, plus Table 24). | v2 Table 5 [read] |
| Real robot: "4–7× fewer tokens" | Total tokens with skills vs without: bowl 8.65M→5.11M (**1.7×**), soda can 61.94M→6.58M (**9.4×**), drawer 334.92M→81.67M (**4.1×**). So the range is 1.7–9.4×. | v2 Table 1 [read] |
| "At most three replays per debug seed" | True in the **v1 paper appendix** prompts ("Hard limit: at most three replay attempts per debugging seed"). The **current repo removed the cap**: "Do not cap attempts while diagnostics make progress." The only hard caps left are on the verifier (2 attempts, ≥4/5 seeds) and on evosearch (≤5 iterations, stop at ≥80%). | v1 text line ~1554 [read]; `.claude/skills/iterative-debugging/main-agent-prompt.md` §3 [read] |
| Skill entry = failure signature, when-to-apply, repair, code sketch | That is the paper's description (§2.2, App. A). The repo's actual format is a markdown subsection: **Trigger → Code (5–20 lines) → Why it works + Evidence → Limits**, plus an optional **runnable precondition** ("a precondition is code or it is nothing"). Proposals travel as JSON in `skill_report.json` (`proposed_new: {skill, title, trigger, code, evidence}`). | `main-agent-prompt.md` §6c–6f, `subagent-prompt.md` [read] |
| "Agent integration: Claude Code / Codex skills, MCP server"; §5.1 says Muse endpoint "same in both, since both route through an OpenAI-compatible client" | **There is no LLM client in ASPIRE at all.** No `openai`/`anthropic` import anywhere. The "agent" is a coding-agent CLI (Claude Code or Codex) reading markdown skills and calling `cap-harness` through Bash. Swapping in Muse is **not** a config change (see b.6). | grep over the repo [read] |
| Programs "cannot import modules" | Correct for the **program sandbox**. `ALLOWED_IMPORTS={"math"}`, an AST validator bans class/with/global/private names, and builtins are restricted. The README warning about "full import access" refers to the coding agent's own shell scripts, and the sandbox is in-process `exec`, so it is not a security boundary. | `src/cap_harness/runtime.py` [read]; README [read] |
| "LIBERO-Pro fixed seeds" | More precisely: LIBERO uses `--init-mode seeded`. Seeds the env RNG, and BDDL placement re-samples object poses per seed, so seeds 51–65 / 66–80 / 1–50 are distinct procedural layouts. The default `saved` mode **wraps seeds at 50** (seed 51 = saved state 0 = seed 1), which would contaminate the split. The harness has 8 LIBERO-Pro suites: `{goal,object,spatial,10}_{swap,task}` (swap = position perturbation, task = language remap). | `docs/libero-pro.md`, `src/cap_harness/libero/adapter.py:reset`, `libero/registry.py` [read] |
| Split = debug 51–65, held-out 1–50 | There is also a third partition: **unseen-check 66–80**, measured once at the end of Stage 1 as an overfitting detector. Robosuite: dev 101–125, unseen 126–130, held-out 1–100. | `iterative-debugging/SKILL.md` [read] |
| Evolutionary search "selects best on debug seeds" | Confirmed, and more precisely: Algorithm 1 proposes K candidates from `Top3(H)`. The best candidate becomes the new incumbent iff its **aggregate debug-seed score is strictly higher** (`r_i^{k*} > r*`). This is not per-case dominance. | v2 Alg. 1 math alttext [read] |

---

## a. Paper summary

**Problem.** Code-as-policy agents get only coarse rollout-level feedback, and they throw away fixes once a task is done ("the agent solving its hundredth task is effectively no more experienced than the agent solving its first") [read, §1].

**Goal.** Continual learning with no weight updates: a frozen coding agent writes robot programs, and validated repairs accumulate into a text skill library [read].

**Method (all modules)** [read, §2]
1. **Coordinator–actor.** One coordinator manages the skill library and dispatches one actor (coding-agent subagent) per task. Actors exchange only distilled skills, never chat logs or rollouts. The coordinator is also the **curriculum** (§2.4): it picks the next task based on library gaps or strengths.
2. **Robot execution engine.** For every primitive call it records the API, inputs, outputs, status, and RGB keyframes right before and after each *motion* call, plus SAM overlays, grasp candidates and planner results. The actor does not get full video by default (in the repo, videos are recorded and the worker may read them).
3. **Skill library.** Skills are induced from validated repairs. Admission takes two checks: a fresh verifier actor re-solves the source task from the proposal alone, and the coordinator checks the API policy.
4. **Evolutionary search.** K=8 candidates per round, conditioned on the top-3 so far plus failure traces, evaluated on debug seeds. It stops at the success threshold (≥80% in the repo) or after T rounds (5 in the repo). Held-out evaluation runs once afterwards.
5. **Curriculum and backward transfer.** After all tasks finish, low-scoring tasks that ran under an older library are re-run once with the final library.

**Experiments** [read, §3]
- **Benchmarks:** LIBERO-Pro (80 tasks: Object/Goal/Spatial/Long × position/task perturbation, 50 held-out seeds); Robosuite (7 tasks, 100 held-out trials, including two-arm); BEHAVIOR-1K (soda-can and radio navigate-and-pick, 25 held-out seeds, incremental block execution); zero-shot LIBERO-90 → LIBERO-Pro Long.
- **Baselines:** CaP-Agent0 (regenerates a program per seed with test-time retries), OpenVLA, π0, π0.5, and human-written programs (Robosuite and BEHAVIOR).
- **Models:** main results use Claude Code with Opus 4.6 (1M context). The ablation covers 12 models: Opus 4.6/5/5.5, Sonnet 5.5, Haiku 5.5, Fable 5.1, GPT-6 Astra/Sol/Luna, GPT-6.1 Sol, Kimi K3, Qwen 3.8 Max. "Claude and open-weight models run through Claude Code and GPT models through Codex CLI."
- **Seeds:** one program per task, evaluated once on held-out seeds. Variance is reported only for Opus 4.6 on Goal/pos, 3 runs (Table 25).

**Results v1 (Opus 4.6)** [read, v2 Tables 5–8, the same numbers as v1]

| Benchmark | ASPIRE | Best baseline |
|---|---|---|
| LIBERO-Pro Obj/Goal/Spatial macro (60 tasks) | **72.0%** (Obj 98/95, Goal 81/45, Spatial 51/60 for pos/task) | CaP-Agent0 18.0%, π0.5 13.0%, OpenVLA and π0 0% |
| Robosuite mean over 7 tasks | 81.0% (handover 92%, two_arm_lift 71%, nut_assembly 9%) | CaP-Agent0 68.0% (handover 20%) |
| BEHAVIOR soda-can Nav/Task | 92/88% | Human 80/72%, CaP-Agent0 84/72% |
| BEHAVIOR radio Nav/Task | 100/88% | Human 88/36%, CaP-Agent0 80/56% |
| Zero-shot LIBERO-Pro Long (library from LIBERO-90) | 4.7% (empty library) → **30.5%** (full library); pos 22.6%, task 38.3% | CaP-Agent0 3.8%, π0.5 5.0% |

**Results v2 (model scaling)** [read, Tables 3, 4, 13–18]
- Opus 5.5 with evosearch: Object 98.2/100, Goal 98.0/99.4, Spatial 99.4/99.2, Long 97.0/98.8 (pos/task). Mean of the 8 cells ≈ **98.8%**, which is the "99% across 80 tasks". Robosuite 100% on all 7. BEHAVIOR 100/100%.
- Opus 5: Robosuite mean 99% (nut_assembly 9% → 98%). GPT-6 Astra: Robosuite 99%, BEHAVIOR 96%.
- **Goal/pos, empty library, no evosearch (Table 18):** Opus 5.5 99.2% ($18.29/task, 51 min), Sonnet 5.5 98.8% ($12.11), Fable 5.1 96.6% ($42.24), GPT-6 Astra 94.4% ($35.37, 31 min), Opus 5 90.6% ($59.72), GPT-6.1 Sol 88.0% ($9.52), **Kimi K3 78.4% ($58.19, 139 min)**, Haiku 5.5 68.0% ($3.97), GPT-6 Sol 59.2%, **Qwen 3.8 Max 56.0%**, Opus 4.6 55.6%, GPT-6 Luna 14.8% ($0.83).
- Odd detail: Opus 5.5 on Goal/pos **with** a carried-over library (Table 14) scores 97.0/98.0%, slightly below the 99.2% it gets with an empty library. The paper does not discuss this.

**Ablations** [read]
- No engine and no search: 14%. Engine: 62%. Engine plus evosearch: 72% (Opus 4.6, Fig. 7).
- Evosearch moves suite averages by ≤2% for strong models, against up to 34% for Opus 4.6. It still fixes individual hard tasks, e.g. mug-in-microwave 0 → 42% with Opus 5.
- Backward transfer, Opus 5 Long: 74.6% → 82.2% over 20 tasks (Table 2).

**Cost** [read, Tables 20, 22]

| | Opus 4.6 | Opus 5 | Opus 5.5 | Astra |
|---|---|---|---|---|
| Total tokens, 60 tasks | 2,009M | 2,543M | 1,538M | 522M |
| Cache-read share | 98% | 97% | 97% | 97% |
| Output tokens | 8.2M | 13.4M | 8.0M | 2.6M |
| Cost per task | $22.9 | $32.1 | $10.8 | $12.9 |
| Sim rollouts | 12,214 | 10,941 | 10,555 | 7,905 |
| LLM calls | 9,405 | 8,535 | 7,896 | 5,950 |
| Actor time per task (min) | 79 | 60 | 46 | 27 |

- That is roughly **25M tokens and ~175 rollouts per task** (Opus 5.5), and the 175 includes the 50 held-out rollouts.
- Evosearch for Opus 4.6 adds $89 per searched task.

**Real robot** [read]
- Cross-embodiment skill transfer on a bimanual YAM with GPT-5.5 xhigh in Codex: bowl 20/20 → 20/20, soda can 13/20 → 19/20, drawer 0/20 → 11/20.
- Rubik's Cube with GPT-6 Astra: three episodes. Episode 1 unsolved after 51 min. Later episodes solved in 39 and 77 min. Time per turn 17 → 7.8 → 3.1 min; tokens per turn 11.3M → 2.0M; cost $16.85 → $2.89 per turn.

**Stated limitations** [read, §5]: real-world autonomy (a human resets, scrambles and guides); dependence on a frozen frontier LLM; the predefined API bounds behaviour; skills are verified once and can go stale; the loop is compute-heavy.

**Limitations I see**
1. **One program and one held-out pass per task. Variance is barely reported.** The 3-run Opus 4.6 study (Table 25) shows a per-task spread of **0% vs 100%** on "open middle drawer" (mean 63.1%, std 3.4% at suite level). The runs are labelled 1, 3, 4: run 2 is missing and not explained.
2. **The held-out seeds share the generating distribution of the debug seeds** (same BDDL placement sampler). This is in-distribution seed generalization, not robustness to new perturbation types. No physics, camera, lighting or actuation perturbation is ever tested. This is exactly the ANTS gap.
3. The verifier checks that a skill **transmits** on its own source task (5 seeds), not that it **transfers**. The repo says so explicitly.
4. Evosearch acceptance is aggregate-score improvement on 15 seeds, so per-seed regressions are allowed.
5. The case study (Fig. 10) shows **the human LIBERO demonstration contains strategies no model found**. Book under the shelf: "The human holds the book by its top edge, tilts it, and slides it in. No model finds this move." This is direct evidence for the ANTS Q1 premise that a demo can carry information the text does not.
6. Cost is 97% cache reads, so affordability depends on provider prompt caching. Muse pricing and caching on OpenRouter are unknown.
7. GPU and wall-clock budgets are **not in the paper at all** (grep for GPU, A100, H100, L40 and VRAM in v2: no hits). The only hardware evidence is in the repo docs.

---

## b. Repo anatomy

**Packages** [read]
- `src/cap_harness/` (pip name `cap-harness`, v0.1.0, setuptools, Python >=3.10,<3.13).
  - Core: `api.py` (2.1k lines, tool implementations), `runtime.py` (sandbox and trace), `contracts.py` (typed results), `registry.py` (tool allowlist), `run.py` / `batch.py` / `cli.py` (episode runner), `artifacts.py` (recorder), `doctor.py`, `environments.py` (topology and profiles), `geometry.py`.
  - Embodiment adapters: `libero/`, `robosuite/`, `behavior/` (Isaac / OmniGibson), `yam_real/` (real robot and a MuJoCo station sim).
  - `providers/{sam3,graspnet,pyroki,curobo,yam_kinematics}`: each is a light HTTP `client.py` plus a FastAPI `service.py`.
  - `agent/`: MCP server for "System 2" (real YAM, or `--sim` YAM station; **not LIBERO**).
  - `validation/`: structural gates.
- Pipelines live as **agent skills, not code**: `.claude/skills/iterative-debugging/` (coordinator, worker and verifier prompts; `scripts/` for campaign, dispatch, run_validation, watchdog, lint_skills, audit_seeding; `skills/{localize,grasp,transport,manipulation,task-exploration}.md`), `.claude/skills/evosearch/`, `.codex/skills/*` (pointers to the Claude versions), and `.agents/skills/` (real-robot tool usage and manipulation recipes).
- v0.1 (June) had a different layout (`aspire/sim`, `aspire/real`); the README still links some v0.1 paths.

**Primitive API a generated program may call** [read, `docs/api-reference.md`, `runtime.py`]

| Group | Signature | Returns | Advances time |
|---|---|---|---|
| Observe | `get_task_context()` | `TaskContext` | no |
| | `get_observation(camera_names=None)` | `Observation` (calibrated RGB-D, intrinsics, camera_pose) | no |
| | `get_robot_state()` | `RobotState` | no |
| Perceive | `segment_text(camera_name, text)` | `SegmentationSet` | no |
| | `segment_points(camera_name, points_px)` | `SegmentationSet` | no |
| | `mask_to_point_cloud(mask, camera_name, target_frame="robot_base")` | `PointCloud` | no |
| | `crop_point_cloud(point_cloud, lower_xyz, upper_xyz)` | `PointCloud` | no |
| | `estimate_geometry(point_cloud)` | `ObjectGeometry` | no |
| | `localize_object(query, *, camera_name=None, target_frame=None)` | `LocalizationResult` | no |
| Grasp | `generate_grasps(camera_name, mask, backend="contact-graspnet", max_candidates=5)` | `GraspSet` | no |
| | `select_grasp(grasps, strategy="top_down" or "highest_score")` | `GraspCandidate` or `None` | no |
| Plan | `solve_ik(target_pose, seed_joints=None, *, arm="primary", backend=None)` | `IKResult` | no |
| | `plan_motion(goal, start_joints=None, *, arm="primary", strategy=None)` | `PlanResult` | no |
| | `plan_synchronized_motion(targets, strategy=None)` | `SynchronizedPlanResult` | no |
| Act | `step(action)` | `StepResult` (reward stripped) | 1 tick |
| | `execute_trajectory(trajectory, stop_on_termination=True)` | `ExecutionResult` | many |
| | `move_to_joints(target, tolerance=0.01, max_steps=120, *, arm=)` | `ExecutionResult` | many |
| | `move_to_pose(target_pose, tolerance=0.01, max_steps=120, *, arm=, strategy=None)` | `ExecutionResult` | many |
| | `move_synchronized(targets, tolerance=0.01, max_steps=120, strategy=None)` | `ExecutionResult` | many |
| | `set_gripper(position, *, arm=)` (only 0.0 or 1.0 on LIBERO), `set_grippers(positions)`, `open_gripper()`, `close_gripper()`, `go_home()` | `ExecutionResult` | many |
| Extensions | `libero.get_task_metadata()`, `libero.get_controller_metadata()` | read-only mapping | no |

- **Constructors:** `Pose(position, quaternion_wxyz, frame)`, `MotionStrategy(ik_solver="pyroki", trajectory_planner="interpolation", pose_planner="composed")`, `ArmCommand`, `RobotAction`, `Trajectory`, `SynchronizedTrajectory`.
- **Builtins:** abs, all, any, bool, dict, enumerate, float, int, len, list, max, min, print, range, reversed, round, set, sorted, str, sum, tuple, zip, plus Exception, ValueError and TypeError.
- **AST bans:** class, with, async, global, nonlocal, del, `from` imports, any `_`-prefixed name or attribute.
- The program must set a top-level `result`.
- **Important default:** `MotionStrategy()` is PyRoki IK plus straight joint interpolation, which is **not collision-aware**. cuRobo is opt-in per call.

**Execution engine and trace** [read, `runtime.py`, `docs/run-artifacts.md`]
- `ProgramExecutor` wraps every tool. Each call yields a `CallTrace` (tool, ok, duration, input/output summaries, provider, failure_code) and a recorder span. Motion tools also write `before-<tool>` / `after-<tool>` keyframes.
- Run directory (`outputs/<benchmark>/<suite>/<task>/<seed>/<run-id>/`):
  - `run.json`, `outcome.json` (program_ok, task_success, termination_reason, timing buckets), `manifest.json` (sha256)
  - `source/` (program and result), `episode/steps.jsonl` (one action and state per tick)
  - `trace/events.jsonl` (parent-linked spans), `media/videos/*.mp4`, `media/keyframes/`, `media/overlays/` (top-1 SAM mask)
  - `evaluation/protocol.json` (host-only)
- Reward and success never appear in program-visible results or traces.
- `run-batch --workers N` gives each seed a fresh env in spawned workers.
- **This run-directory format is a near drop-in evidence record for the ANTS diagnoser.**

**Skill file format and admission** [read]
- Library: `.claude/skills/iterative-debugging/skills/*.md` with YAML front matter (`name`, `description`) and freeform subsections in the form Trigger / Code / Why + Evidence / Limits.
- A worker writes `skill_report.json`: `consulted[]` with verdict `useful | misleading | wrong | not-applicable`, plus `proposed_edits[]` and `proposed_new[]`.
- `dispatch.py verify` stages a verifier. The verifier gets the library and the proposal but **not** the proposer's code, findings or runs. It has **2 attempts on seeds 51–55 and needs ≥4/5** to return `verified`; otherwise `refuted`, or `void` if the environment broke.
- The coordinator promotes the skill, runs `lint_skills.py`, and the library sha changes. Tasks that ran under an older sha become rerun candidates.
- Each entry states only what is true now; its history goes to `<file>-changelog.md`.

**Evolutionary search** [read, `.claude/skills/evosearch/`]
- K=8 candidates per iteration, with a diversity rule. Candidates are seeded from the top-3 of any prior iteration. The fix-loop `fix_code.py` is `candidate_A`.
- Evaluated with `scripts/evosearch_eval.py` on fixed seeds 51–65 (`--parallel-per-gpu 2`).
- Stops when the best candidate reaches ≥80%, after 5 iterations, or when blocked.
- Then a single held-out run on 1–50. Worst case is 8 × 15 × 5 = 600 episodes per task.

**Coordinator and actor** [read, `main-agent-prompt.md`]
- The coordinator is a Claude Code session. It dispatches `Agent(subagent_type="general-purpose", run_in_background=True)` with a filled-in template, then goes idle until notified.
- It keeps a **GPU ledger**: one job per GPU, and a GPU stays owned from Stage 1 through Stage 2.
- A **Single-GPU mode** exists: strictly serial, the coordinator runs every `cap-harness run`, and subagents only analyse finished run directories.
- `watchdog.py` exists because agents blocked on approval prompts silently stalled one campaign for **29.5 h**.

**b.6 How the coding agent is driven, and plugging in Muse**
- **Driving:** Claude Code (`.claude/skills`, using the Agent/Task tool for subagents) or Codex CLI (`.codex/skills/*/agents/openai.yaml`, which point to the Claude files). The real-robot System 2 uses Codex plus MCP (`scripts/start_system2_agent.sh`, `~/.codex/config.toml` with `model="gpt-6-astra"`) [read].
- **The paper ran Kimi K3 and Qwen 3.8 Max "through Claude Code"** [read, §3.1]. So a non-Anthropic model behind Claude Code is a path that has actually been exercised, at 78% and 56%. The paper does not say how the endpoint was wired.
- **OpenRouter:** it documents Claude Code via `ANTHROPIC_BASE_URL=https://openrouter.ai/api` and `ANTHROPIC_AUTH_TOKEN`. It only guarantees Anthropic models; for others, tool use and prompt caching vary [summary, openrouter.ai blog]. Codex CLI can take a custom OpenAI-compatible provider via `model_providers` in `config.toml` (from my own knowledge, not verified here).
- **Requirements a Muse backend must meet to run ASPIRE unchanged:**
  1. robust multi-turn tool calling (Bash, Read, Write, Edit)
  2. **subagent spawning** (the Agent tool) for coordinator/worker/verifier; otherwise single-GPU serial mode with one agent
  3. **image input** to read keyframes, overlays and videos
  4. long context (Opus ran with 1M, Astra with 258k)
  5. **prompt caching**, or cost explodes (25M tokens per task, 97% cache reads).
- **Thin alternative (my recommendation for ANTS):** skip ASPIRE's agent layer. Use the `cap-harness run` / `run-batch` CLI as the executor, and have ANTS's own Muse client (OpenAI-compatible) write `program.py`, call the CLI, and read `outcome.json` and `trace/events.jsonl`. Copy the program rules and the skill files into the Muse prompt. No ASPIRE code changes are needed for this path.

---

## c. Perturbation hooks (decides System 2 reuse)

**Verdict: there is no public perturbation API.** The only knobs are `--seed`, `--init-mode {saved,seeded}`, `--suite` (`_swap` = object-position perturbation, `_task` = language remap), camera resolution and `--max-steps` [read, `cli.py`, `run.py:run_program`]. There is no friction, mass, lighting, camera-pose, distractor or actuation-noise setting anywhere outside `yam_real` (grep over the repo) [read].

**Host-side seams that make it feasible:**

| Perturbation | Seam (file / function) | Effort |
|---|---|---|
| All, cleanly | `LiberoAdapter.__init__(env_factory=...)` in `src/cap_harness/libero/adapter.py`. When `None`, it calls module-level `_load_offscreen_render_env()`. Every reset, step and sim read goes through that env object. `run_program` in `run.py:239-259` does **not** pass `env_factory`, so you need either (i) a ~10-line patch adding `adapter_kwargs["env_factory"]` (plus the same in `batch.py`), or (ii) a launcher that monkeypatches `cap_harness.libero.adapter._load_offscreen_render_env` before `cli.main()`. Under `run-batch` this must also happen in spawned workers, e.g. via a wrapper module or `sitecustomize`. | small |
| Friction, mass, damping | In a wrapper env's `reset()`: call the inner reset, then edit `sim.model.geom_friction`, `body_mass` etc., then `sim.forward()`. Model params survive `set_init_state` in saved mode. Must happen **before** `LiberoAdapter._settle()`; a wrapper env's `reset()` satisfies that. | small |
| Object poses | Seeded mode already randomizes. For adversary-chosen poses, write free-joint `qpos` in the wrapper's reset. In saved mode `set_init_state` overwrites qpos *after* reset, so use seeded mode or wrap `set_init_state`. | small–medium |
| Camera pose and FOV | Edit `sim.model.cam_pos`, `cam_quat`, `cam_fovy`. **Note:** `_camera_observation` recomputes extrinsics and intrinsics live from the sim every observation, so the program sees a *perfectly calibrated* moved camera. To test **miscalibration**, the adapter must report stale extrinsics, which is a patch inside `_camera_observation`. | small / medium |
| Lighting, textures | `sim.model.light_*`, `mat_rgba`. Rendering is offscreen EGL, so changes apply. | small |
| Distractors | Need new objects at env construction (BDDL or MJCF). LIBERO-Pro generates BDDL variants; the harness registry only exposes the 8 swap/task suites plus whatever LIBERO installs (e.g. `libero_90` is used in `examples/libero/close_microwave.py`). You would need generated BDDL files and a registry entry. | **large** |
| Robot initial state | Wrapper reset: set arm `qpos` before settle. | small |
| Actuation noise and latency | Wrap `env.step(native_action)`: add noise, or hold a k-step delay queue. `LiberoAdapter.native_step` calls `env.step` exactly once per public tick. | small |
| Sensor noise (depth) | `LiberoAdapter(depth_converter=...)` hook exists (`_default_depth_converter`). It is also not reachable from `run_program` without the same patch. | small |

**Integrity.** All perturbation code must live host-side, in the wrapper env. The program sandbox cannot reach `native_env` (private names are banned, and `native_env` is not injected), so the "policy cannot see the perturbation or the success predicate" property holds.

---

## d. Demonstration input

- **Nothing in ASPIRE consumes a demo, video or trajectory** (grep for demonstrat, teleop and hdf5 finds only incidental comments) [read]. LIBERO human demos appear only in the paper's case-study figures [read].
- **Injection points for a DemoSpec, ranked:**
  1. **Prompt / task context (zero code).** A `TASK_CONTEXT.md`-style file next to the task. The real-robot recipes in `examples/yam_real/*/TASK_CONTEXT.md` are exactly this mechanism, routed by `.agents/skills/manipulation-tasks/SKILL.md`. For sim, add a "DemoSpec" section to the worker template (`subagent-prompt.md` Stage 0) or to the ANTS Muse prompt.
  2. **Skill file.** Write the demo-derived strategy (grasp part, approach axis, keyframe order) as a Trigger/Code entry. It then goes through the same verifier gate, which gives a free check of "does the demo-derived hint transmit?".
  3. **Program constants.** Object-frame EE waypoints and gripper keyframes as data in `program.py`. **Conflict:** the provenance rule forbids "hardcoded world poses / object dimensions … that perception can derive", and the coordinator requires `Non-privileged API audit: PASS`. Object-*relative* offsets ("generic relative offsets") are allowed; absolute coordinates are not. A DemoSpec therefore has to be expressed **in object frames** and re-grounded at runtime through `localize_object`. That matches the ANTS design, and the ANTS paper should say so explicitly.
  4. **API (an extension).** Expose a read-only `demo.get_spec()` through the extension namespace (`ToolRegistry(public_extension_allowlist=...)`, same pattern as `libero.get_task_metadata`). This is the cleanest typed path but needs a harness change.

---

## e. Install and platform

| Item | Finding | Evidence |
|---|---|---|
| OS | **Linux x86_64 only** (`[tool.uv] environments = ["sys_platform == 'linux' and platform_machine == 'x86_64'"]`). Uses `prctl(PR_SET_PDEATHSIG)` in `batch.py` and bash bootstrap scripts. | `pyproject.toml`, `batch.py` [read] |
| Python | >=3.10,<3.13; BEHAVIOR needs 3.11; cuRobo venv defaults to `/usr/bin/python3` | pyproject, bootstraps [read] |
| Tooling | **uv** (good fit for ANTS), but via bash `scripts/bootstrap_*.sh` that create **separate venvs**: `.venv-libero`, `.venv-robosuite`, `.venv-behavior`, `.venv-sam3`, `.venv-graspnet`, `.venv-pyroki`, `.venv-curobo`, `.venv-system2` | `configs/environments.json` [read] |
| Pins | numpy 1.26.4, mujoco 3.3.0, scipy<1.18, jax<0.4.30, torch 2.9.1 / cu128, transformers<5; 6 git submodules (LIBERO-PRO fork, robosuite fork, contact_graspnet_pytorch fork, sam3 fork, curobo, BEHAVIOR-1K) | pyproject, `configs/dependency-lock.json` [read] |
| CUDA | Runtime **12.8** (torch cu128). System toolkit **not** required except for BEHAVIOR (CUDA 12.x nvcc). cuRobo is pip-installed editable from the submodule (`curobo[cu12-torch]`) and compiles CUDA extensions with a wheel nvcc. | `docs/host-setup.md`, `scripts/bootstrap_curobo.sh` [read] |
| GPU arch | Profiles only for **sm_89** (l40, rtx4090, rtx5880) and **sm_120** (rtx5090). `cuda_arch_list()` **raises** for an unlisted arch. **The RTX A5500 Laptop is Ampere sm_86**, so you must add an `sm_86` entry to `dependency-lock.json` `gpu_runtime.arches` plus a new `configs/profiles/a5500.json` (copy of rtx4090). torch cu128 supports sm_86; whether pinned cuRobo builds for 8.6 is not verified [est]. | `environments.py:131-136`, profiles [read] |
| Rendering | MuJoCo EGL (`MUJOCO_GL=egl`, needs `libegl1` / GLVND). EGL ignores `CUDA_VISIBLE_DEVICES`, so set `MUJOCO_EGL_DEVICE_ID`. Contention gives "depth conversion produced invalid metric values", which looks like a policy bug. | `docs/libero-pro.md` [read] |
| Gated weights | **SAM3**: HF gated repo, `huggingface-cli login`; the bootstrap succeeds without a token and the failure only shows at first load. | `docs/host-setup.md` [read] |
| Licences | Harness Apache-2.0. **Contact-GraspNet: NVIDIA Source Code License, non-commercial research.** BEHAVIOR data bundle: non-commercial EULA. | `configs/dependency-lock.json` [read] |
| Docker | none in repo | file list [read] |
| Services | Ports 8114 SAM3, 8115 Contact-GraspNet, 8116 PyRoki, 8118 cuRobo, started by `scripts/supervise_services.sh --profile <p>` (default profile `rtx5090`). cuRobo's first plan takes ~50 s (CUDA-graph warmup). | `docs/environments.md`, `main-agent-prompt.md` [read] |

---

## f. Hardware per building block (execution time)

The paper states **no GPU** information. The repo gives these hardware signals [read]:
- `l40` profile = a multi-GPU node with SAM3 on GPU 0, Contact-GraspNet on 1, cuRobo on 3. The evosearch coordinator example checks "GPU 3 4 5 6 7" with "perception services own GPUs 0–2", so the authors used an **8-GPU L40 node, one task per GPU**.
- Single-GPU profiles exist for RTX 4090, 5090 and 5880 ("all providers share GPU 0 with serialized GPU access").
- "Measured on one L40, fifty seeds cost ~37 min one-process-per-seed, ~18 min at `--workers 1`, ~7 min at `--workers 4`." The verifier's 5 seeds take "about a minute".

| Block | GPU needed? | VRAM | CPU fallback | Evidence |
|---|---|---|---|---|
| **LIBERO / robosuite (MuJoCo 3.3 + EGL)** | GPU for EGL offscreen render; physics is CPU | Not stated. [est] ~0.3–1 GB per sim process (EGL context plus two 800×512 RGB-D cameras). A batch worker "holding ~1.4 GB and a GPU context" (`batch.py`, ambiguous whether RAM or VRAM). | Yes in principle (`MUJOCO_GL=osmesa`), but doctor checks EGL and that path is untested here | `docs/libero-pro.md`, `batch.py` [read] |
| **SAM3 service** | Yes (`--device cuda` default, bf16 autocast) | **Measured: ~4.2 GiB idle, grows to 7.73 GiB after one program's segmentation** (cache; the service calls `empty_cache()` after each request). Model ~848M params per the SAM 3 paper [est from memory, not verified here]. | `--device cpu` is accepted by `service.py`, but the supervisor does not pass `--device`, so you would launch it by hand. Expect seconds per call [est]. | `providers/sam3/service.py:76-93` [read] |
| **Contact-GraspNet (PyTorch)** | Yes (`--device cuda`) | Not stated alone. SAM3 + CGN together "about 8 GB" (BEHAVIOR docs), so CGN ≈ 0.5–3 GB [est by subtraction] | `--device` arg exists; untested. **Optional** in the topology. `grasp.md` has a geometric top-down fallback when `generate_grasps` fails. | `configs/environments.json` (`optional: true`), `behavior/SKILL.md` [read] |
| **PyRoki IK** | **No**: `"gpu": false`, concurrency 4–8, JAX (jax<0.4.30, CPU) | 0 | It *is* CPU | `configs/environments.json` [read] |
| **cuRobo service** | Yes (CUDA graphs, tensors on `"cuda"` hard-coded) | Not stated. [est] ~1–3 GB per robot model with warm CUDA graphs. The service caches planners because "fresh MotionPlanner … records CUDA graphs into private pools that are never released". | **None**; it is CUDA-only. **Optional for LIBERO** (default strategy is PyRoki + interpolation; LIBERO `SERVICE_PORTS` = 8114 8115 8116 only). | `providers/curobo/service.py`, `subagent-prompt.md` [read] |
| **Depth / pose models** | None: depth comes from the simulator, pose from `estimate_geometry` on the point cloud | 0 | n/a | `api-reference.md` [read] |
| **BEHAVIOR-1K (Isaac Sim 5.1)** | Yes | **~12 GB VRAM and ~16 GB RAM for the simulator alone**, plus ~8 GB for SAM3 + CGN. "Leaves little headroom on a 24 GB card." Docs ask for 32 GB RAM and 40 GB of datasets. | No | `docs/behavior.md`, `behavior/main-agent-prompt.md`, `docs/host-setup.md` [read] |
| **Coding agent / LLM** | API only | 0 | n/a | |

**16 GB RTX A5500 Laptop verdict [est from the table above]**

| Configuration | Approx. VRAM | Fits? |
|---|---|---|
| SAM3 (≤7.7) + 1–2 LIBERO workers (~0.5–2) + PyRoki (CPU) | ~8–10 GB | **Yes, recommended** |
| + Contact-GraspNet (~0.5–3) | ~9–13 GB | Likely yes; keep `--workers ≤2` |
| + cuRobo (~1–3) | ~10–16 GB | Marginal; the laptop display also takes VRAM. Start cuRobo only when a program asks for it. |
| + a local VLM/LLM | — | **No**; keep all models on the API |
| BEHAVIOR / Isaac | 12 + 8 = 20 GB | **No**; skip |

What to turn off or replace on the laptop:
- Use profile-style concurrency 1 for GPU services and `run-batch --workers 1–2`. Do not use 4.
- Drop cuRobo for the MVP: no collision-aware planning, so programs must approach along clear axes.
- Contact-GraspNet is optional, with the geometric fallback; it is also non-commercial.
- Always wrap runs in `timeout`: orphan sim processes holding "several GB" starve SAM3 into OOM.
- Throughput [est]: about 2–4× slower than one L40 at 4 workers, so ~15–30 min per 50-seed held-out sweep.
- RAM: 62 GB is ample for LIBERO. BEHAVIOR wants 32 GB.

---

## g. Fit verdict for ANTS

**Reuse as-is**
- The `cap-harness` executor: `run` / `run-batch` CLI, typed API, AST sandbox, run-directory artifacts and trace. This is the System 1 primitive set and the System 2 rollout record.
- The LIBERO adapter in `seeded` mode, with ASPIRE's seed partitions (dev 51–65 = ANTS acceptance, unseen-check 66–80 as an extra overfitting probe, held-out 1–50).
- The skill-file format and the **verifier-admission idea** ("does the text alone reproduce the fix?") as the shape of the ANTS `Constraint` record. Add an optional runnable precondition.
- The provenance rule (no absolute world constants) as the ANTS "plan gate".

**Adapt**
- Add an `env_factory` / perturbation-wrapper seam (c), about 10 lines in `run.py`/`batch.py` or a launcher monkeypatch, so the ANTS adversary can set friction, mass, camera, light, init state and actuation noise per case.
- Add an `sm_86` arch entry and an A5500 profile.
- Replace ASPIRE's Claude-Code coordinator with the ANTS orchestrator. Keep the prompts and skills as text the Muse generator receives.
- Replace evosearch's "strictly better aggregate" acceptance with the ANTS per-case monotone gate.
- Keep the harness in its own venvs outside `ants` (it is Linux-only and pins numpy 1.26). ANTS talks to it only via subprocess CLI and the `outcome.json` / `trace` files.

**Avoid**
- BEHAVIOR / Isaac (VRAM).
- The real-robot `yam_real` / MCP System 2 (out of scope; also a naming collision with ANTS "System 2").
- Running the full ASPIRE agent pipeline with Muse as the brain for the MVP: it needs subagents, vision, long context and caching.
- cuRobo on day 1.
- Absolute-coordinate DemoSpecs (they would fail ASPIRE's provenance audit).

**Riskiest integration point.** **Muse as a write-run-debug agent over this API.** ASPIRE shows a 15% → 99% spread driven purely by the model. The best open-weight models (Kimi K3 78%, Qwen 3.8 Max 56%) needed ~$40–58 and 100–140 min per task. Muse is untested. Its tool calling, image reading and prompt caching are unknown, and without caching the 25M-token-per-task regime is unaffordable.

**Second risk: install.** SAM3 gated access, the sm_86 arch gap and the cuRobo build. Mitigate by making the 1-day smoke test (disc. decision 5) start with: `bootstrap_libero` + `bootstrap_sam3` + `bootstrap_pyroki` → `cap-harness doctor` → `examples/libero/object_swap_seed1.py` on seed 1 → one Muse-written program on `libero_goal_swap:0`.

**For the ANTS story.** ASPIRE never tests out-of-distribution perturbations (only same-sampler seeds and language remaps). Its own case study shows human demos containing strategies no model found (book under the shelf). Both strengthen the narrow ANTS delta: **demo-derived strategy + adversary-chosen physical perturbations + monotone gate + human escalation.**
