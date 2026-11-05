# Imperial line and contemporaries: what each work can do for the ANTS stack

Status: research note, 2026-11-01. Nothing here is decided. Builds on [../../dev/instant-learning.md](../../dev/instant-learning.md) (do not re-read for the basics) and extends or corrects it where code and papers were opened this time. Every number is quoted from a paper, repo, page or API, never from our runs. Wilson intervals (95%) are ours, from reported counts.

**Evidence tags.** **[read]** I read the file, code, page or API record myself (repos were cloned shallow into a scratch folder and read, nothing installed or run). **[summary]** only a model-extracted summary of a page or paper was available (all WebFetch results of arXiv HTML and company blogs are this). **[abstract]** abstract or listing only. **[press]** news or company text. **[inference]** my own reasoning, not a source.

**Stack assumed (from AGENTS.md, HANDOFF.md, concept.md, skills.md):** Muse (frozen) writes a program over ASPIRE `cap-harness` primitives on LIBERO-Pro (SAM 3, PyRoki IK, Contact-GraspNet); `DemoSpec` from hurobo (hand + ArUco phone clip) or LIBERO teleop demos; System 2 not yet built (perturbation planner, diagnoser, `Constraint`, per-case regression gate, escalation); memory/skills store planned; nothing trained for the generator; acceptance seeds 51-65, held-out 1-50; deadline 2026-11-04; laptop RTX A5500 16 GB with about 4.5 GB already used by SAM 3 + PyRoki services (HANDOFF §4).

---

## 0. Verdicts in one table

Fit scale: **COVERED** ANTS already does it, **IMPROVES** adds something we lack, **CONFLICTS**, **NOT USABLE**. Effort S (hours), M (about a day), L (days). Licence column is what I read in the repo.

| Work | What it is for ANTS | Fit | Licence | GPU on A5500 16 GB | Verdict |
|---|---|---|---|---|---|
| **SynthICL** (code) | Training code only; no weights, no inference script, no data; data generator is a separate repo needing Isaac Sim | NOT USABLE as a runnable arm; IMPROVES as ideas (keyframe rule, visual-only context, subgoal-image diagnosis) | Apache-2.0 (policy repo) [read]; **no licence file** on the data-generator repo [read] | inference light [inference]; training/data gen out of scope | **NEVER as a model. USE NOW as ideas and citations** |
| **Instant-Fold** | Cloth-top folding, dual-arm, RGB-D; code and a 573 MB FleX checkpoint released | NOT USABLE (garments only); ideas only | MIT code [read]; assets "mixed third-party terms" [read] | n/a | **NEVER** (cite for the "3-4 keyframe human demo" pattern) |
| **MT3** | Retrieval of the most similar demo + pose estimate + replay; code, two small weights | IMPROVES **memory/retrieval design** and the **retarget-replay baseline**; code itself NOT USABLE on LIBERO without a large adapter | MIT [read] | Docker CUDA 11.8, py3.9, PointNet++ ops; VRAM not stated [read] | **USE NOW the design (S); NEVER the code** unless a pose estimator is needed |
| **Instant Policy** | Black-box neural ICL policy. API is generic (segmented point clouds + gripper poses), **not RLBench-only** | IMPROVES as the **neural baseline / System 2 target (H3)** | **PolyForm Noncommercial** [read]; compiled `.so`, no training code | fits (69-178 M params [read via note]; torch 2.2 + cu118) | **LATER** (L, after the loop works); offline baseline only |
| **IGA** | Two-object relative-alignment model (`get_transformation`) | IMPROVES a `place_relative` primitive only; slow, 3 depth cams, complete point clouds | MIT [read] | small (about 5.7 M) | **NEVER for the hackathon, LATER at best** |
| **Rhoda DVA** | Video-model policy; one-shot only qualitative | NOT USABLE; positioning only | none; no release | n/a | **NEVER** (cite as contemporary) |
| **Generalist GEN-1.5** | Claims one-shot ICL, 59% on 10 simple tasks | NOT USABLE; positioning and a pitch fact | none; no release | n/a | **NEVER** (cite) |
| **Skild S1** | Video-demo-as-prompt FM, 66% vs 9% unseen | NOT USABLE; gives a useful **perturbation idea** (execution-strategy shift) and a "demo as spec" phrase | none; early access only | n/a | **NEVER** (cite) |
| **Machenta / USV blog / BI** | Company facts | positioning | n/a | n/a | facts only |
| **ZeroBot / Simify** (Johns coauthor, Sept 2026) | Real2sim from one RGB(-D) view; RL (ZeroBot) or parallel-sim search (Simify) | IMPROVES a *later* real-to-sim step; ZeroBot trains policies, Simify trains nothing | not checked | n/a | **LATER / research tier** |

---

## 1. What is newly verified (and what it changes in the earlier note)

1. **SynthICL code release is training-only.** `README.md` says "This repository contains the model and training pipeline"; files are `scripts/train.py`, `icil/policy/fm_flowact_icil.py`, `icil/data/pseudo_demo_dataset.py`, configs. There is an `inference()` method on the model class (it takes pre-batched tensors: prompt images/actions plus current images) but **no evaluation or robot-deployment script, no checkpoint, no released data** [read]. Open GitHub issue #1 (28 Sept 2026) asks exactly for "policy inference and evaluation" and has no reply as of 2026-11-01 [read via API]. No Hugging Face model repo for it exists under the author [read via HF API]. Repo: Apache-2.0, 7 stars, one commit [read]. The earlier note's "licence unchecked" is now closed.
2. **SynthICL's data generator is a separate repo** (`sNiper-Qian/synthicl-pseudo-demo`): Isaac Sim 5.1.0 (`pip install isaacsim[all]==5.1.0`), torch 2.7 cu128, default 6000 episodes x 2 trajectories per part, four task types (`pick_and_place_gn`, `push_gn`, `pour_gn`, `random_gn`), three cameras (front, side, wrist) with real calibration in `configs/real_cameras.yaml`. **No licence file** (GitHub API: license null) [read]. Objects and GraspNet grasp poses are a 255 MB Hugging Face dataset whose card states no licence [read]. Textures are DTD (research use) [read].
3. **SynthICL appendix facts** [summary]: real-world context frames = initial frames + frames where the gripper state changes + frames where gripper velocity falls under a threshold (value not given), at most 6, zero-padded; context has no actions; segmentation is "SAM and CUTIE" (how they are combined is not said); the real demonstration is "recorded as continuous trajectories" (teleop vs kinesthetic vs video is **not stated**); no train hardware, GPU hours, parameter count, latency or control rate; no statement about releasing weights or data. Per-task real results: 253/320 = 79.1% (Wilson 74.3-83.2), range 7/20 (Scanner on Base) to 20/20 (Stack Bowls). Stated failure causes: identical geometry, poor view coverage for distant targets, collisions. Limits: needs segmented RGB, weak on high precision and contact-rich tasks, short horizon, pseudo-demos lack physics, subgoal images are blurry.
4. **Instant-Fold has a public repo and weights** (`kelthuzadyl/Instant-Fold`, MIT, 12 stars, linked from the Instant-Fold project page) [read]: install needs Linux, CUDA, conda, PyFlex on python 3.9, torch 2.11 cu128 and a gated DINOv3 checkpoint; assets are an encoder LoRA checkpoint (128 MB), an 8-context policy checkpoint (573 MB, simulation-evaluation version, not the one used on the real robot) and a 9.2 GB demo tarball. Body [summary]: human demo = **3-4 keyframe images**, gripper interaction points from a hand tracker or manual labels; keyframes come from gripper open/close events; calibrated overhead RGB-D; training in FleX with 360 Cloth3D tops; **real: 39/64 = 60.9%** (Wilson 48.7-71.9, 8 garments x 8 trials, Fold 1 only) against ClothFunnels 9.4%, UniFolding 29.7%, UniGarment 26.6%. The **99.7%** in the listing is single-mode, in-distribution, FleX, 300 rollouts and uses UniGarment's metric; the broader held-out figure is C-SR@95 = 58.3% (1920 rollouts). No recovery mechanism, no memory beyond the demo context, FPS is nondeterministic. Paper-internal inconsistency: 8 vs 15 training modes.
5. **Instant Policy's API is not RLBench-specific** [read]: `deploy.py` takes `demo = {'pcds': [...], 'T_w_es': [...], 'grips': [...]}` (segmented point clouds in the world frame, 4x4 gripper poses, 0/1 gripper), `sample_to_cond_demo(demo, num_traj_wp=10)`, then per step `model.predict_actions(full_sample)` returns relative end-effector transforms for a horizon and gripper signs. RLBench appears only in `deploy_sim.py` / `sim_utils.py` (three cameras, mask > 60 hack). Weights are on Google Drive via `gdown` (not fetched, so size unknown). Environment file pins python 3.10, torch 2.2.0 cu118, pyg 2.5, open3d 0.18. The `.so` carries no Python tag in its name; I could not tell which CPython it needs (likely 3.10 given the environment) [inference]. No issue has ever been opened, 98 stars, last push 2025-05-05.
6. **MT3 retrieval is two-stage** [read, `hierarchical_retrieval.py`, `language_template_parser.py`]: (1) the task text is parsed by templates into a skill type (`pick_up`, `pick_up_from`, `place_on/in/next_to`, `pour_from_into`, `insert_into`, `open`, `close`, `fold`, `swipe_on`, ...) plus target and "other" object classes, giving the candidate demos; (2) only if more than one candidate remains, a **512-d PointNet++ autoencoder embedding of the target object's segmented point cloud** (5 mm voxels, world frame, centred) is compared by cosine similarity, argmax. The Machenta blog itself cites MT3 as "one way to make the model language-conditioned by using language to retrieve a matching demonstration as the prompt" [summary]. Deployment input per demo: workspace RGB-D, a binary segmentation of the target object, intrinsics, extrinsics, `bottleneck_pose.npy` (4x4) and `demo_eef_twists.npy` (T x 7: velocities plus gripper). No robot driver; BC-Ret marks waypoint tracking "[SIMULATED]".
7. **Machenta facts** [summary of the blog fetched today, plus search results that quote Business Insider]: the blog names IGA and Instant Policy as "our early work", cites MT3 as the language-retrieval route, and says in-context learning "has seen exciting adoption" at Rhoda AI, Generalist and Skild AI via large real-world data collection. Memory, stochasticity, release of code/weights/API: **not mentioned**. Failure handling: "can instantly recover when it fails, without you needing to show these behaviours" and clarifying demos "can add clarification". The Business Insider article itself was not retrievable (search returned only secondary coverage); the "no near-term plans to commercialize" line is attributed to it by those outlets [press]. Team about 11-12 and founding year (2025 vs 2026) differ between outlets [press].

---

## 2. Work by work, by ANTS module

Legend for module rows: C = COVERED already by ANTS, I = IMPROVES, X = CONFLICTS, N = NOT USABLE / not applicable.

### 2.1 SynthICL (arXiv 2606.08154, CoRL 2026; code Apache-2.0)

| ANTS module | Fit | What exactly | Evidence |
|---|---|---|---|
| Perception / DemoSpec extraction | **I (S)** | Keyframe rule: initial frame + gripper-state changes + **low-velocity (dwell) frames**, capped at 6. Ours has aperture-driven grasp/release only (`tools/hurobo_demospec.py` builds a handful of keyframes; `tools/libero_demospec.py` currently writes `"keyframes": []`). Dwell frames add pre-grasp pauses and placement settle points. SAM + CUTIE tracking is covered by SAM 3 / 3.1 video tracking | [summary] rule; [read] our tools |
| Program synthesis | I (M) | Keyframe image strip (<=6 images) as extra evidence in the Muse prompt, if the Muse model on our key accepts images (HANDOFF §8 lists `muse-spark` with an image as untested) | [inference] |
| Primitive API (learned primitive behind same signature) | N | No weights, no inference script, closed loop at chunk level; a `follow_demo(...)` primitive would need a trained checkpoint we do not have and may not train (AGENTS.md) | [read] |
| Rollout / harness | N | Needs RGB-only three-camera inputs at 256x256 and Isaac-Sim-rendered training distribution; LIBERO rendering is out of distribution | [inference] |
| Diagnoser | **I (M)** | Their auxiliary head predicts the *next subgoal image*. ANTS can use the demo's keyframe images (or their object-relative equivalents) as **visual checkpoints** for the diagnoser: first keyframe where the rollout's scene deviates from the demonstration's. Works cleanly only for LIBERO teleop demos (same renderer); human phone clips have a real-vs-sim domain gap | [inference], idea from [summary] |
| Memory / retrieval | I (S) | Context = images only, no actions (so a human video can be a demo). For ANTS: a **visual embedding of the first demo frame** as one retrieval key (see §3). The model itself has no cross-episode memory | [summary] |
| Regression gate (stochastic policy) | I (design only) | Flow matching from Gaussian noise (`sample_noise`, 10 Euler steps) [read]: sampling is seedable per (case, sample), so a neural arm can be gated by paired seeds. The paper reports one pass of 20 rollouts per task, no variance | [read] |
| Escalation / clarifying demo | N | No such mechanism; extra demos just add context frames (zero-padded to 6) | [summary] |
| Baseline arms in LIBERO | N | Cannot run today: no weights, nothing to feed (the training loader expects HDF5 `trajectory_i` groups with `images_front/side/wrist`, `robot_states`, `actions`, `waypoints_idx`, `assigned_wps`) | [read] |
| Pitch / novelty | I (S) | The closest published *neural* relative of the VDA: RGB-only, one demo, 79.1% real on 16 tasks. Use it to say "in-context neural policies already do the first half" (instant-learning X1), and to cite that their authors list "background randomisation" and "physics-based simulation" as future work, i.e. no adversarial testing | [summary] |

**Licence status:** Apache-2.0 for the model/training repo (usable); the generator repo and object dataset have no stated licence (do not copy); DINOv3 checkpoint is gated by Meta's terms (not checked) [read README, inference on terms]. **GPU:** training is 2000 epochs at 64 sampled steps per update with unreported hardware [read config], and Isaac Sim 5.1 data generation is not planned for a 16 GB laptop (NVIDIA's own minimum was not checked) [inference]. **Verdict: NEVER as a runnable arm (no weights, would require training); USE NOW: keyframe rule, visual-checkpoint diagnosis idea, citation.**

### 2.2 Instant-Fold (arXiv 2606.04269; MIT code, 573 MB checkpoint)

| ANTS module | Fit | What exactly |
|---|---|---|
| Perception / DemoSpec | I (S, idea) | A human demo reduced to **3-4 keyframe images + gripper interaction points** from a hand tracker, keyframes cut at gripper open/close. Same shape as our DemoSpec keyframes; supports keeping the human-video demo extremely sparse [summary] |
| Program synthesis, primitive API | N | Garments, dual arm, FleX-trained flow-matching transformer; no skill beyond folding [summary] |
| Rollout / harness | N | PyFlex plus Isaac Lab sim-to-sim; no LIBERO path [read] |
| Diagnoser | N | Lists real failure modes (kinematics, occlusion, slippage, segmentation) but no diagnoser [summary] |
| Memory / retrieval | N | "No memory beyond the demo context"; context library "manually designed and limited" [summary] |
| Regression gate | I (note) | FPS nondeterministic and flow-matching noise unseeded in reports: an example of why a gate over a neural policy needs fixed seeds [summary] |
| Escalation | N | None |
| Baselines | N | Cannot be used on a bowl/plate or book task |
| Pitch | I (S) | Evidence that the same "single human demo as prompt, trained only in sim" recipe was applied to deformables (60.9% real, one fold, 8 garments); also a reminder that the headline 99.7% is one-mode in-distribution |

**Verdict: NEVER (code), cite only.** Effort to reuse: not applicable. Licence MIT, assets mixed.

### 2.3 MT3 "Learning a Thousand Tasks in a Day" (arXiv 2511.10110; MIT)

Can its retrieval and trajectory transfer run on a LIBERO scene or a `DemoSpec`? **Not as shipped; yes as a re-implemented idea.**

- **Inputs it needs** [read]: for the live scene RGB, aligned metric depth (uint16 mm), a binary segmentation of the *target object*, 3x3 intrinsics, camera-to-world extrinsics; for each stored demo the same for its workspace image plus `bottleneck_pose.npy` (the robot pose where the interaction starts, 4x4) and `demo_eef_twists.npy` (T x 7 end-effector velocities with gripper). Two learned weights: the 512-d geometry encoder and a 4-DoF pose regressor (PointNet++), followed by Open3D ICP.
- **Heaviness** [read]: Docker image on CUDA 11.8, python 3.9, PointNet++ custom ops, a separate XMem install; VRAM not stated; the ASPIRE services already use about 4.5 GB. No robot driver.
- **On LIBERO** [inference]: ASPIRE already returns calibrated RGB-D and SAM 3 masks, so the live-scene inputs exist (`get_observation`, `segment_text`, `localize_object`). The demo side exists only for LIBERO teleop demos (hdf5 actions, replayable to render RGB-D) and not for the hurobo clips (human hand, no robot twists). MT3 handles single-interaction tasks of the skill types listed in §1 item 6 (it has `pick_up`, `place_on/in/next_to`, `open`, ...); a bowl-on-plate task is two chained skills, and a book-under-shelf task is not in its repertoire. **Its pose estimator (trained on household objects) adds nothing over ASPIRE's `localize_object` for the objects we use.** The cheap, honest port is: *alignment* = `localize_object` -> transform the demo's bottleneck pose by the object pose change (4-DoF: x, y, z, yaw) -> `move_to_pose`; *interaction* = replay the object-frame end-effector path from `DemoSpec.ee_path_obj`. That is the retarget-replay baseline of Q12d, about 100-200 lines, no MT3 code needed.

| ANTS module | Fit | What exactly |
|---|---|---|
| Perception / DemoSpec | C | Alignment/interaction split is already the DemoSpec shape (discussion §3.3a); `bottleneck_pose` = our grasp keyframe |
| Program synthesis | N | No LLM |
| Primitive API | I (S) | Gives the clean contract for a `replay_segment(anchor_obj, path)` primitive, MT3's interaction phase; also its stated weakness: open loop, cannot correct errors [read, from the note] |
| Rollout / harness | C | Replay runs on the existing ASPIRE harness |
| Diagnoser | I (S) | MT3's attribution (seen tasks: retrieval 22.3%, segmentation 19.5%, pose estimation 23.9% of failures [note, read]) is a ready **failure taxonomy for retrieval-based policies** to reuse as rule-based diagnoser labels (retrieval, segmentation, pose, execution) |
| Memory / retrieval | **I (S)** | Two-level key (symbolic schema, then geometry embedding of the target object) with the single most similar demo as the prompt; our `Skill` store should mirror it and add help counts and decay (skills.md). Details in §3 |
| Regression gate | C | Deterministic given seed (open-loop replay) so the per-case gate applies unchanged |
| Escalation | I (S) | If retrieval finds no candidate for the schema (their `No demonstrations exist for skill ...` branch) that is a natural **"no memory match -> ask for a demo"** trigger, in addition to "stalled after K cycles" |
| Baselines | I (S) | Arm (d) of Q12: retarget replay. Also hypothesis: replay solves nominal seeds but fails under perturbation categories that need re-localisation or recovery |
| Pitch | I (S) | "1,000 tasks, one demo each, 78.25% seen / 68% unseen, no neural policy": evidence that retrieval+replay is a strong, cheap baseline we must beat |

**Licence MIT. GPU:** unknown VRAM, probably modest [inference]. **Verdict: USE NOW the retrieval design and failure taxonomy and the replay baseline re-implemented over ASPIRE (S-M); NEVER install the repo** unless a learned relative pose estimator is later needed.

### 2.4 Instant Policy (arXiv 2411.12633; PolyForm Noncommercial)

Can its released weights run on LIBERO? **Probably yes, with an adapter, because the interface is point clouds + gripper poses, not RLBench objects.** Not verified by running (we install nothing).

What would be needed [inference unless marked]:
1. A separate environment with python 3.10, torch 2.2 + cu118, pyg-lib, open3d (matches the `environment.yml` [read]); conda is what the repo documents, which conflicts with the uv-only rule (see §5 C2). Run it as a **subprocess/HTTP service** so ANTS does not import it.
2. Weights from Google Drive (`gdown`), size unknown.
3. **Demo conversion:** LIBERO teleop demo -> replay in `LiberoAdapter` to render depth and masks -> segmented point cloud (task objects only) in the world frame, gripper `T_w_e` and open/closed per step -> `sample_to_cond_demo(demo, num_traj_wp=10)`. Ground-truth instance masks or SAM 3 masks via `segment_text` + `mask_to_point_cloud` provide the segmentation. The hurobo human clips cannot be used directly (no robot-embodied point clouds); a bridge would be *DemoSpec -> retarget replay in sim -> rendered robot demo -> IP prompt* (only if the replay succeeds).
4. **Live loop:** each step: segmented point cloud of task objects, current `T_w_e`, gripper bit -> `predict_actions` -> transform relative actions to a world pose -> ASPIRE `move_to_pose` (PyRoki IK; ASPIRE drives LIBERO with absolute joint targets, HANDOFF §6). Execute until the gripper state flips, then re-query (README note). Each step needs SAM 3 or GT masks.
5. Known limits that matter on LIBERO [read, README and paper note]: needs well-segmented objects, Markovian short tasks, no collision avoidance, imprecise in contact-rich cases, "when an object is grasped there needs to be at least one more object in the observation"; the "put the bowl on the plate" task satisfies the last point, the book-under-shelf task (tilted carry, 63 degrees) is outside its pseudo-demo distribution [inference].

| ANTS module | Fit | What exactly |
|---|---|---|
| Perception / DemoSpec | N | Needs a robot-side point-cloud demo, not a DemoSpec |
| Program synthesis | N | |
| Primitive API (learned primitive) | I (L) | `ip_follow(demo_ref, n_steps)` primitive behind the same status-returning signature; the LLM program would call it for contact-light motions and keep branching and recovery. This is the paper's own future-work item (§XII per the earlier note) |
| Rollout / harness | I (L) | Needs the step-wise adapter above; each episode is hundreds of model calls and SAM 3 calls (no LLM tokens) |
| Diagnoser | N | Black box; our diagnoser sees only the `EpisodeTrace` |
| Memory | N | Demos are just context; no store |
| Regression gate | I (M) | Stochastic (4-step diffusion default in `deploy.py` [read]): use the stochastic-gate protocol in §4 item 5 |
| Escalation | I (S, idea) | Its quality is "sensitive to demo quality" and improves with more demos (40% at N=1 to 90% at N=4 on a four-task test, per the earlier note): a natural escalation answer is "add a demo of the failing segment" |
| Baseline arms | **I (L)** | The neural ICL arm for H3 (instant-learning §6): same LIBERO cases, same gate, compare found-failure rate and repairability. **Today nothing neural runs in LIBERO** (all arms in `data/runs` are Muse programs) |
| Pitch | I (S) | "We test and repair what the neural prompt-policies leave untested" needs this baseline to be credible, but only as a later, honest side result |

**Licence:** PolyForm Noncommercial 1.0.0, compiled model, no training code, no pseudo-demo generator [read]; conflicts with a commercial layer (paper N22) and needs a hackathon-rules check (to-do #5). **GPU:** fits [inference]. **Verdict: LATER (L).** Not before 2026-11-04. A 2-hour feasibility spike (replay one LIBERO demo, feed one live frame, check that the predicted poses move toward the bowl) is the only cheap first step.

### 2.5 IGA (arXiv 2310.12238; MIT)

[read] README: input pickle `{'pcds_a': [...], 'pcds_b': [...]}` (first element is live, the rest context), **complete** point clouds in the end-effector frame, objects grasped "in a similar way"; `iga.get_transformation(...)` returns `T_e_e_new`. Weights and demo data by download scripts. Paper limits [summary of the earlier note]: up to 15 s inference, rigid grasps, three depth cameras, two-object tasks only.

| ANTS module | Fit | What exactly |
|---|---|---|
| Perception / DemoSpec | N | Needs complete (not partial) object clouds; single-view LIBERO gives partial clouds |
| Program synthesis | N | |
| Primitive API | I (L) | `place_relative(obj_a, obj_b)` for unseen shapes; ASPIRE's grasp and `move_to_pose` plus the program's own object-frame offsets already cover the bowl/plate task (COVERED for our tasks) |
| Rollout, diagnoser, memory, gate | N / C | Deterministic only after the Langevin seed is fixed [inference]; no store |
| Escalation | N | |
| Baselines | N | 3-4 kinesthetic demos, not one |
| Pitch | N | Older (CoRL 2023); Instant Policy supersedes it for the same authors |

**Verdict: NEVER now; LATER only if a task needs relative placement of unseen shapes that Muse programs cannot do.**

### 2.6 Rhoda AI "Direct Video-Action" (blog dated Mar 10, 2026) [summary]

A causal video model, pre-trained on web video, predicts future video; a small inverse-dynamics model (about 10 h per embodiment) converts it to end-effector motion, closed loop several times per second ("leapfrog" inference). Post-training with 11 h (Decanting) and 17 h (Container Breakdown) of robot data. **One-shot** is stated for a single human demo in context, qualitative (drawing a shape; sorting novel objects). Memory = a context window of "hundreds of frames" (an 8-frame context repeated completed steps). Correction: qualitative re-grasps. No baselines, rates, trials, latency or release.

| ANTS module | Fit | Note |
|---|---|---|
| All execution modules | N | No release |
| Memory | X (conceptually) | Their memory is **in-episode context only**; no cross-episode store. ANTS's store is external and editable |
| Escalation / correction | N | No human-in-the-loop correction, only "operated for 1.5 h / 160 min without intervention" |
| Pitch | I (S) | Cite as a contemporary; their claim of unsolved "self-improvement through interaction" is exactly ANTS's loop |

**Verdict: NEVER (cite).**

### 2.7 Generalist GEN-1.5 (blog, Aug 19, 2026) [summary]

Claim: new task "in seconds, from a single example, without gradient updates"; 3-12 s physical prompts from handheld-gripper demos; **59% (+-10% std) average one-shot on 10 tasks**; 10 gradient steps on about 50 demos gives 83% (+-9%); no architecture, hours, trial counts, hardware or release. Memory = 30 s of rolling context. Reuse: prompts can be composed ("physical prompt engineering"), selected by a human through a drag-and-drop UI. The authors state: tasks simple and short-horizon, in-context skills "more brittle than finetuned models".

Fit: N for execution. For ANTS: **the brittleness statement is the strongest third-party motivation for System 2** (an in-context policy that is brittle by its own makers' account), and their "humans select prompts" step is the manual form of our retrieval + escalation. **Verdict: NEVER (cite).**

### 2.8 Skild AI S1 (blog, Aug 2026) [summary]

Built "as an in-context learner": a video demo (egocentric human video shown) is the prompt, same weights for all tasks. Internal benchmark of 4-8 minute tasks: unseen tasks, 100k hours, **ICL 66% vs language-prompted VLA 9%**; seen tasks at 1k hours ICL 43% vs VLA 53%, rising to 96% at scale; one demonstration "worth roughly 380 post-training examples" (an interpolated estimate); under a perturbation test that forces execution onto the opposite arm the VLA degrades "up to three times as much" as ICL; failure recovery ("tries again") qualitative; "treats the demonstration as a specification of the goal, not a trajectory to reproduce". No memory beyond the context window, no learning from feedback, no release (early access sign-up; an "August 2026 S1 release" milestone with no details). The post has an internal timestamp inconsistency (11 min claimed vs 9:22 to 9:27 listed) and no trial counts or intervals.

Fit: N for execution. Useful for ANTS in two ways: (1) the phrase "demonstration as a specification" matches what `DemoSpec` is and is a good pitch sentence; (2) its **execution-strategy-shift perturbation** (force a different arm/route) is a concrete perturbation category for System 2 beyond pose/physics: swap the arm or mirror the scene and see whether the demo-derived program still works. **Verdict: NEVER (cite); take the perturbation idea.**

### 2.9 Machenta, the USV blog and Business Insider (facts only)

| Fact | Source |
|---|---|
| $40M seed, co-led by Creandum and Union Square Ventures, announced 2026-10-27 | USV blog by Rebecca Kaden [summary]; tech.eu / TNW and others [press] |
| Johns is CEO and co-founder with Vitalis Vosylius; Johns directs the Imperial Robot Learning Lab and is described as Head of Robot Learning at Dyson | USV [summary], press |
| "Show the robot a task once, and it starts doing it"; trained "entirely on synthetic data", no real-world training data | USV [summary] |
| "Physical vibe coding": iterate on the physical prompt; no formal definition | USV [summary], Machenta blog |
| No benchmarks, architecture, hardware, customers, pricing, competitors named | USV [summary] |
| About 11-12 people, King's Cross London office, "no near-term plans to commercialize" (attributed to Business Insider; the article itself was not retrieved) | search results quoting BI [press] |

**For ANTS:** USV's own line "imagination instead of capability becomes the constraint" supports the pitch that after one-shot learning the bottleneck is *knowing what the policy can survive*, which is System 2. Do not quote the BI line as read.

### 2.10 Other works from the same lab or authors since June 2026 (arXiv API listing for author "Edward Johns", 2026-11-01) [read]

| Date | arXiv | Title | Relevance |
|---|---|---|---|
| 2026-06-06 | 2606.08154 | SynthICL | covered above |
| 2026-06-02 | 2606.04269 | Instant-Fold | covered above |
| 2026-09-27 | 2609.34010 | ZeroBot: Learning from Scratch in Minutes with Generative Real2Sim (Kapelyukh, Zhang, James, Herlant, Johns; IEEE RA-L 2026) | [abstract] image-to-3D mesh from one view, large-scale parallel **RL** in sim, 87% real success, 119 s average training time. It trains a policy per task, so it is outside "nothing trained", but its image-to-3D-to-sim step is the real-to-sim copy of a cell that ANTS needs for in-cell tasks (instant-learning §3b) |
| 2026-09-27 | 2609.33982 | Test-Time Spatial Reasoning for Robot Manipulation Using Generative Real-to-Sim ("Simify", IROS 2026; Kapelyukh, Hu, Gong, May, Kusnur, Herlant, Schmeckpeper, Johns, Zhang) | [abstract] training-free, reconstructs sim-ready assets from one RGB-D image, thousands of parallel rollouts with evolutionary search over arrangements. Same idea family as an adversary that searches in sim; not a policy |
| 2026-08-02 | 2608.07558 | Survey on tactile/force-aware robot learning | listed under the name search; not relevant |

The lab page `robot-learning.uk` shows only three items (MT3 Nov 2025, Neural Stochastic Flows Oct 2025, Instant Policy Apr 2025) and no 2026 items or Machenta mention [read], so arXiv is the better listing. Searches by author for Vosylius, Dreczkowski, Papagiannis, Ruomeng Fan, Yifei Ren found **no other 2026 papers on robot learning** [read]. (A Dreczkowski co-authored AWARE, 2610.32742, is crane anomaly detection from Cully's group, not this lab.) I did not check Google Scholar, only the arXiv API; absence from arXiv does not rule out workshop papers.

**Adjacent 2026 work not from this lab, found by the same search, [abstract] only, flagged for follow-up:** JEDI (2610.40356, Oct 2026: compresses demonstrations into latent slots, **selects demonstrations from a bank**, evaluates on **LIBERO**); SAIL (2603.08269, Mar 2026: test-time scaling of in-context imitation with a VLM scorer, **an archive of successful trajectories for retrieval**, MCTS over trajectory refinements); RA-VLA (2608.25585: retrieval-augmented VLA on LIBERO); ContextFlow (2609.06852); ICI-VLA (2609.07581). SAIL and JEDI are closer to the ANTS loop than any Imperial paper; I did not read them.

---

## 3. The "memory" in these works, and what ANTS can borrow

### 3.1 What the demonstration-conditioning mechanism is equivalent to

| Work | How the demo conditions the policy | Equivalent in a language-model stack | Persistence across episodes |
|---|---|---|---|
| SynthICL | up to 6 context frames, no actions, encoded by an 8-layer context encoder; current observation cross-attends to the context (`inference()` computes `feat_emb = encoder(f_sa)` once per query) [read] | a **prompt prefix whose encoding can be cached** for the episode (a KV/context cache), plus meta-learned weights as the "pretrained prior" | none; the context is the demo |
| Instant Policy | demo reduced to 10 waypoints, graph edges to live observation and action nodes | same, as a graph-structured prompt | none |
| Instant-Fold | 3-4 keyframes -> spatial-then-temporal attention with summary tokens | same | none; "context library manually designed" |
| GEN-1.5 / Rhoda / Skild | demo or recent frames in the context window (30 s; "hundreds of frames") | literally a long-context prompt | none beyond the window |
| MT3 | **no learned conditioning**; an external store of demos, retrieved by a two-stage key | an **external retrieval store** (RAG) with symbolic and embedding keys | yes, the store is the memory |
| ANTS | DemoSpec text + constraints + retrieved skills in the Muse prompt; Muse's prompt cache (`data/llm_cache/`) | a prompt prefix, cached by hash | yes if the skills store is built |

So: **SynthICL-style models give the demo a transient, cached encoding; they have no memory in the ANTS sense.** MT3 is the only one of the family with a persistent library, and the Machenta blog points to it as the language-retrieval route. Their "memory" never learns from failure; ANTS's gets help counts, decay and re-verification (skills.md). [inference]

### 3.2 What ANTS can borrow for the demo store and retrieval keys

1. **Two-level key (MT3).** Level 1, symbolic: a parsed schema of the task text (`pick_up`, `place_on`, target class, other-object class); this is robust, free, and already available from the Muse task text or a small template. Level 2, only if more than one candidate: a geometry or visual similarity. Hypothesis: level 1 alone resolves most retrievals in a LIBERO-sized library (MT3 needed level 2 only for ties; this is [read] code logic, the hypothesis is [inference]).
2. **Geometry key for the target object.** MT3 uses a 512-d PointNet++ autoencoder embedding of the segmented target (5 mm voxels, centred). For ANTS the cheap equivalent needs no model: **DemoSpec scalar features** (object extents from `localize_object`, rim radius, height, observed grasp offset in object radii). The hurobo extraction already measures these (rim pinch at 1.05-1.26 bowl radii, 5.5 cm high). Learned embeddings only if scalars fail. [inference]
3. **Visual key.** Embed the **first frame of the demo (and the live scene's first frame)** with a frozen image encoder (SynthICL freezes DINOv3 ViT-S/16+; the checkpoint is gated [read]; SigLIP/DINOv2 are alternatives) and keep the cosine as a *secondary* key and a human-readable thumbnail on the skill card. Not needed to win the hackathon. [inference]
4. **Keyframe selection (SynthICL + Instant-Fold).** Select context keyframes by: (a) the first frame, (b) every gripper-aperture state change (grasp, release) which we already compute, (c) **dwell frames** where end-effector or hand speed drops under a threshold, (d) cap at 6. Practical use in ANTS: the images and the (time, anchor, kind) tuples become DemoSpec `keyframes`, a prompt strip for Muse (if the endpoint takes images), the retrieval thumbnail, and the checkpoints for the diagnoser. Threshold must be tuned on the acceptance demos, not the held-out ones. [summary for the rule, inference for the use]
5. **Language retrieves the demo (MT3 via Machenta).** Keep the retrieval keyed by task text first. That also gives an escalation trigger: "no stored skill matches this schema" -> ask for a demo (MT3's own `No demonstrations exist for skill ...` branch). [read]
6. **Store both the demo and the verified program.** MT3 stores only demos; ANTS stores demo + program + envelope + evidence (skills.md §1). Retrieval returns the program as the prompt's starting point, the demo as evidence. [inference]
7. **What not to borrow:** meta-training, pseudo-demonstration generation, or any trained context encoder (AGENTS.md); nor treat the retrieved demo as the answer when the layout differs (MT3 is open loop and fails when retrieval picks the wrong demo, 22.3% of seen failures [read]). ANTS's "retrieved skill must pass its runnable precondition" (skills.md §2) is the guard.

---

## 4. Ranked integrations (at most 8)

Ranked by value for the pitch and the next two weeks, then by cost. Dates: hackathon 2026-11-04.

| # | Integration | Source | Hypothesis | Cheap test | Effort | Before Nov 4? |
|---|---|---|---|---|---|---|
| 1 | **Retarget-replay baseline arm** over ASPIRE primitives (MT3 alignment + interaction, from `DemoSpec.ee_path_obj`) | MT3 | Replay solves the nominal acceptance seeds but fails on perturbation categories that need re-localisation or recovery; the program + gate beats it on held-out perturbed cases | Run on the 5 acceptance seeds and the 3 hand-picked perturbations of experiment 01; report success with Wilson intervals; no model tokens | S-M | yes, if time; it is baseline (d) of Q12 |
| 2 | **Stochastic-gate protocol** for non-deterministic policies (`Policy.deterministic=False`) | Instant Policy, SynthICL, Instant-Fold | A per-case gate with one noisy rollout flip-flops; k seeded samples per case with a pass-rate rule (with margin) cuts spurious reject/accept | Use actuation-noise perturbation on the existing winning program as a stand-in stochastic policy; measure flip-flop rate for k=1 vs k=5 on the 5 acceptance seeds. Doc the rule in `docs/` | S | yes (design + stand-in test) |
| 3 | **Keyframe rule** (first frame + aperture changes + dwell frames, cap 6) in `tools/libero_demospec.py` and `tools/hurobo_demospec.py` | SynthICL, Instant-Fold | Dwell frames add pre-grasp and settle keyframes that the prompt and the diagnoser can anchor on; the LIBERO DemoSpec currently has none | Fill `keyframes` for the 50 book demos and the 4 usable hurobo clips; check that the grasp/release keyframes agree with the existing aperture events and report how many extra dwell keyframes appear | S | yes |
| 4 | **Two-level skill retrieval key** (task-schema, then DemoSpec scalar/geometry, then help count) | MT3, skills.md | Retrieving a verified program for a near variant lowers repairs-to-first-pass versus cold start | 3 variants of bowl-on-plate (stock, scaled scene, shifted plate): seed the store with the exp-01 winner, count Muse repairs and tokens with/without the retrieved program on the acceptance seeds only | M | design now, test after the loop |
| 5 | **Demo keyframes as diagnoser checkpoints** ("first keyframe where the rollout diverges") | SynthICL subgoal head | The diagnoser localises the failing phase better with demo keyframes than with the rollout trace alone | On LIBERO book demos (same renderer), take 10 logged failures with known phase labels (from the rule-based diagnoser); compare Muse Spark with and without keyframe pairs against the label | M | no (after System 2 v0) |
| 6 | **Targeted second demo vs random second demo** as the escalation answer | Machenta "clarifying demos", Instant Policy N-demo curve | A second demo of the failing segment fixes more failure signatures than a random second demo | Offline, using the 4 hurobo clips / 50 LIBERO demos as the oracle answer; count signatures fixed after 1 added demo | M | no |
| 7 | **Execution-strategy-shift perturbation category** (mirror or swap the arm/route) | Skild S1 | A program that hard-codes an approach side breaks under a mirrored layout; a constraint "choose the approach side from the object's pose" repairs it | Add one category to the planner with a severity bound; run the exp-01 winner on 5 mirrored acceptance seeds | S-M | maybe, as one more category |
| 8 | **Instant Policy as a black-box System 2 target (H3)** | Instant Policy | A neural ICL policy has similar nominal success but the adversary finds failures faster, and only the program can be repaired by a written constraint | 2-h spike: LIBERO demo replay -> point clouds -> one `predict_actions` call; if poses move toward the bowl, then run 20 nominal cases and 20 perturbed cases | L | no |

Everything else (IGA primitive, SynthICL reproduction, Instant-Fold, Simify/ZeroBot real-to-sim) is below the cut.

---

## 5. Conflicts that need a decision from the user

| # | Conflict | Detail | Default I would take |
|---|---|---|---|
| C1 | **Licence of Instant Policy vs the commercial layer** | PolyForm Noncommercial with a compiled model; paper N22 describes a commercial layer; hackathon rules on third-party models and code (to-do #5) are unread | Use only as an offline research baseline, outside any product path; decide after reading the rules |
| C2 | **uv-only rule vs conda/Docker repos** | Instant Policy documents conda (python 3.10, torch 2.2 cu118, pyg), MT3 documents Docker (CUDA 11.8, python 3.9), Instant-Fold conda + PyFlex. AGENTS.md says no conda/pip outside uv | Run any such code as a separate subprocess service in its own environment, not as an ANTS dependency; ask before installing (also per "ask before adding a large dependency") |
| C3 | **A trained neural arm next to a "nothing trained" claim** | The neural arm's weights come from someone else's training. A comparison where it wins nominally can undercut the pitch | Report honestly; keep the claim as "the loop", as instant-learning X1 already says; label the arm "third-party pretrained, not ours" |
| C4 | **Per-case gate for stochastic policies** (Q10) | The current default (fixed seed, one rollout) is only valid for deterministic programs. A neural arm needs k samples per case and a margin | Decide k and the pass rule before any neural arm is added (item 2) |
| C5 | **Muse image input** | Keyframe images in the prompt (items 3, 5) depend on whether the Muse endpoint takes images and what it costs; HANDOFF §8 lists it as untested | Test one image call before relying on it; text-only keyframes otherwise |
| C6 | **Scope vs deadline** | Items 1-3 fit before 2026-11-04 alongside System 2 v0; items 4-8 do not. The three-day plan in HANDOFF §7 is already full | Do 2 and 3 now (S), 1 if the baseline arm slot is free, defer the rest |
| C7 | **GPU contention** | SAM 3 + PyRoki (about 4.5 GB) plus two sim workers plus a neural policy on 16 GB; contended EGL gives false "invalid depth" failures (HANDOFF §6) | Never run the neural arm concurrently with sim workers; serialise |
| C8 | **Pitch wording** | Third parties now claim one-shot learning with real-robot numbers (Machenta 249/251 on three simple tasks, GEN-1.5 59% on ten, Skild 66% unseen, SynthICL 79.1% on 16, MT3 78.25%). "One demo" cannot be the novelty | Say "in-context neural policies do the first half; ANTS adds adversary-chosen tests, a never-regress gate, readable constraints and targeted escalation" |

---

## 6. Unknowns

**Verified in this pass but still open**
- Whether Instant Policy's `instant_policy.so` loads in the python version we can provide (no Python tag in the filename; likely 3.10); the weights' size and checksum (Google Drive, not fetched).
- Whether the Instant Policy checkpoint behaves sensibly on a LIBERO camera setup (its pseudo-demos randomise cameras only via point clouds; 2 depth cameras advised). Not tested.
- Whether Muse accepts images on our key.

**About the works**
- SynthICL: weights/data release plans; compute; latency; how the real demo is recorded; any human-hand result; SAM + CUTIE combination. The issue #1 has no response. The summaries of the appendices are model-extracted; I did not read the PDF.
- Instant-Fold: inference latency and sampling steps; the human-video pipeline; reconciling the 8 vs 15 mode inconsistency; the last 33 k characters of the HTML were not read.
- MT3: inference time, VRAM, control rate; I did not run it; the Science Robotics version was not read.
- Rhoda, Generalist, Skild: model sizes, data size, trial counts, intervals, any release. Their numbers are company-curated; the Skild post has an internal timing inconsistency. All three pages were read through a summariser, not directly.
- Machenta: the Business Insider text itself (only secondary quotes were available); team size (11 vs 12) and founding year (2025 vs 2026) differ between outlets.
- JEDI, SAIL, RA-VLA, ContextFlow, ICI-VLA: abstracts only; they may matter more to ANTS than the Imperial line (see §2.10).
- Google Scholar was not used; only the arXiv API (author name matches "Edward Johns" and the other authors named) and the lab page.

**About ANTS**
- Whether a replay baseline (item 1) exceeds the Muse program on nominal seeds on this laptop; unmeasured.
- Whether dwell-frame keyframes add information over aperture events on the hurobo clips (hand pauses are noisy); unmeasured.
- Whether the human phone clips can serve as a prompt for any neural arm (embodiment gap); unknown.
