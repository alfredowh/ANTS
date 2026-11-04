# What ANTS can reuse from hurobo

Source: `hurobo` ("phone video of a human hand to a robot policy in LIBERO"). Written 2026-10-29 after reading `README.md`, `CLAUDE.md`, `docs/review.md`, `docs/status.md`, `docs/design_decisions.md`, `docs/results.md`, `ICL_IDEAS.md`, `JEV_IDEAS.md`, `novaflow_review.md`, and the module headers and class lists under `src/hurobo/` (about 14,000 lines, 33 test files).

**Tags.** **[code]** I read the module header and signatures, not every line. **[doc]** the repo's own notes. I did not run anything.

## 0. Verdict in five lines

1. **hurobo is the better half of ANTS's perception input.** `HumanDemo` (metric hand path, pinch aperture, grasp/release events, object poses, all in a named table frame) is most of ANTS's `DemoSpec`, and ANTS's own discussion already says so (an earlier internal discussion).
2. **Do not import its environment.** Linux, CUDA 12.6 wheels, Python 3.12 only, `lerobot[libero]`, MediaPipe, gsplat, COLMAP, open3d. ANTS must stay pure-Python in `contracts` and cross-platform in CI. Port the NumPy pieces or call hurobo as a separate tool that writes JSON.
3. **Everything that trains a policy is out of scope** (SmolVLA fine-tune, LeRobot export, ACT). ANTS trains nothing.
4. **Its strongest transferable asset is the scientific standard**, not a module: the review that says "no control without human data, so the claim is not isolated" is exactly the review ANTS will get.
5. **Its retargeter is ANTS's baseline M3** (open-loop retarget replay) and a candidate `replay_segment` primitive.

## 1. Map: ANTS block to hurobo asset

| ANTS block | hurobo asset | Effort | Verdict |
|---|---|---|---|
| DemoSpec: hand TCP, aperture, grasp events | `extract.py::DemoExtractor` → `demo.py::HumanDemo`; `hand.py::HandTcpTracker`; `clip_clean.py` [code] | M | **Reuse** as a separate extractor emitting DemoSpec JSON (Phase 2, real phone clips) |
| Object poses from markers | `markers.py::MarkerPoseEstimator`, `BoardMarkerPoseEstimator` [code] | M | **Reuse** for Phase 2 only; markers are a controlled-setup assumption |
| Camera calibration | `camera.py::CameraIntrinsics`, `ChArUcoCalibrator`; `data/camera_intrinsics_*.npz` | S | **Reuse** (Phase 2) |
| Open-loop retarget replay (baseline M3, Q12d) | `retarget.py::ObjectCentricRetargeter`, `PlanExecutor`, `RetargetConfig` [code] | M | **Reuse** as baseline; possibly wrap as a primitive |
| Layout / initial-pose perturbations | `scaled_native.py::LayoutSampler`, `SimLayout`, `layout_feasible_fraction` [code] | S | **Adapt**: sampler for acceptance and held-out layouts, with a feasibility check |
| Phase 1 human demo in the simulator | `teleop.py`, `teleop_app.py` (hand-clip and keyboard teleop of the Panda) [code] | S | **Reuse** if ANTS builds its own LIBERO demos (Q4 default) |
| Real clip to sim scene | `twin.py::SceneTwin`, `RealLayout` [code] | M | **Reuse** for Phase 2 side-by-side and sim-matched scenes |
| Statistics | `utils/stats.py` (Wilson interval) [code] | XS | **Port** into `evalkit/` |
| Frame discipline, transforms | `utils/transforms.py`, `utils/signal.py` (resampling, hysteresis) | S | **Port** |
| Source screening / expansion | `mimicgen.py::MimicGenExpander.screen`, `SourceSelector` | M | **Idea only** (see §2.4) |
| Presentation assets | `utils/dashboard_video.py`, `demo_overlay.py`, `assets/*.gif` | S | **Adapt** for the live demo and pitch |
| Decision log and component register | `docs/design_decisions.md`, rules in `CLAUDE.md` | XS | **Copy the format** |
| Training, datasets | `training.py`, `human_dataset.py`, `generate.py`, `checkpoint_eval.py`, `policy_rollout.py` | – | **Skip** (nothing trained). `policy_rollout` is only useful as a comparison row |
| Splat / scan stack | `scan*.py`, `splat*.py`, `collider.py`, `props.py` (~5,000 lines) | – | **Skip.** Heavy, visual only, did not feed the policy |

## 2. Ideas worth taking

### 2.1 HumanDemo is a DemoSpec seed; know the gap
What `HumanDemo` has [code, `demo.py`]: `timestamps_s`, `tcp_pos_table` (thumb/index midpoint), `pinch_aperture_m`, `is_grasping` (hysteresis), `t_table_bowl`, `t_table_plate`, `t_table_cam`, `grasp_frame_idx`, `release_frame_idx`, `source_video`.

What the ANTS `DemoSpec` asks for and `HumanDemo` lacks:
- **object poses per keyframe**: hurobo assumes objects static within a demo and stores the start pose only (re-detected per demo, not per frame). ANTS needs poses at grasp, lift and release for moving objects, from SAM 3.1 tracks or markers at those instants;
- **hand orientation**: dropped on purpose (fixed top-down grasp). Fine for pick-and-place, wrong for handle-versus-rim grasp choice, which is one of ANTS's Q1 hypotheses;
- **a step list and task text** (L6 steps);
- **a quality block** with track coverage and keyframe confidence. hurobo has a QC report (`ClipReport`) that maps to it.

Mapping rule: express every path in the frame of its **anchor object** (`p_tcp_bowl`), not the table, because ANTS's policy must run on layouts the demo never saw.

### 2.2 The retargeter is both a baseline and the honest control
`ObjectCentricRetargeter` turns a human pick-and-place into robot waypoints relative to the objects, then `PlanExecutor` runs them from the home pose. It cannot branch, retry or accept a constraint. That is exactly why it is the right **M3 baseline**: if ANTS's adversarial loop beats open-loop retarget replay under the same perturbations, the loop earns its cost. hurobo never ran this baseline itself ("open-loop retarget replay: not run" in its README), so ANTS would produce the number first.

### 2.3 Named frames, always
`CLAUDE.md` rule: every pose variable carries its frame (`T_cam_table`, `p_tcp_table`, `T_world_bowl`); "frame bugs are the #1 time-sink in retargeting". ANTS has three frames in flight (video camera, LIBERO world, object-relative demo). Adopt the naming rule in `contracts` and add a check that DemoSpec paths round-trip through the simulator's ground-truth frame (compare the agentic-robot `check_convention.py` idea).

### 2.4 Screening beat sophistication (D-013)
On 7 real clips, MimicGen-style options moved usable-episode yield as follows (D-013 table, one seed, 100 to 120 layouts, differences under ~10 points are noise):
- stock 38 to 47% kept; nearest-neighbour source choice alone made it **worse** (5/120 to 15/120);
- **screening each source on shared layouts and dropping those below 25%**, plus a higher action speed, gave 51 to 72%; noise and nn_k added little.

ANTS translation: the same screening idea applies to candidate programs and constraints. Before a candidate enters the gate or a retrieved policy enters memory, run it on a small shared set and drop it if it is below a threshold. Cheap, measurable, and it counters the failure where one bad stored skill is retrieved often.

### 2.5 Hindsight relabeling for constraints and memory (`ICL_IDEAS.md` §4B)
A failed place that ends 5 cm left of the plate is a perfect demo of "put it left of the plate". For ANTS: a failed rollout is not only a failure to explain. It is a verified record of what the program **did achieve**. Store those as negative examples with their achieved outcome in the failure history H, so the diagnoser can say "this program reliably places 5 cm left of target" instead of only "failed". Cheap, and a cleaner basis for constraints.

### 2.6 Task diversity is what makes a demo matter (`ICL_IDEAS.md`, Behavior Prompting Policy [doc, abstract-level])
BPP's finding as quoted there: task diversity, not demos per task, drives prompting ability, and a demo is weaker than language when diversity is low. This is the same warning as agentic-robot's textspec result and ASPIRE's 99% zero-shot. For ANTS: parameterize the **goal** object-relatively (on / left-of / right-of / in-front-of × distance), so the demo fixes a goal text does not. That is a concrete way to satisfy Q1 on LIBERO without new perception.

### 2.7 Behaviour-similarity as a second metric (`ICL_IDEAS.md` §4E)
Success hides how the robot did it. DTW distance between the policy's object-relative TCP path and the demo's gives an axis for "does the program use what the demo showed". If a no-demo program also succeeds but with a path far from the demo, that quantifies the demo's contribution even when success ties. This directly supports the Q1 metric "what the demo tells the policy that text does not".

### 2.8 Object-flow as the interface (`novaflow_review.md`)
NovaFlow copies the **motion of the object**, not the hand: `T_ee(t) = T_obj(t) · T_grasp`, with a grasp proposal from the object's point cloud and IK. This is the same decomposition ANTS's discussion cites from OKAMI/MT3 (align, then replay the interaction in the object frame). It argues for DemoSpec to store **object motion** with the grasp as a separate, per-object choice, which also lets a program re-plan the grasp when System 2 attacks it. [doc] NovaFlow's licence (RAI) and heavy stack (Wan2.1, MegaSaM, TAPIP3D) mean idea only.

### 2.9 Jev-style typed decisions for the diagnoser (`JEV_IDEAS.md`)
The useful abstraction is a diagnoser that emits an **enum plus a calibrated confidence**, never free text, so the orchestrator can branch on it (grasp miss, collision, timeout, perception, IK). The vendor claims (70 to 500 ms, ~68% on its own eval per one secondary review) are unverified and text-only [doc]; do not depend on the product. Get the same shape from Muse Spark with a JSON schema and measure calibration yourself.

### 2.10 Real-versus-sim gap as a measured number (`ICL_IDEAS.md` §4F)
hurobo kept real marker tracks of the bowl and plate and compares them with simulated trajectories in the twin replay. When ANTS moves to phone video, this is how to report what the sim does not reproduce instead of waving at "sim-to-real".

## 3. What hurobo's results say about ANTS's motivation

- Pretrained SmolVLA LIBERO checkpoints: **10/10 on the stock scene, 6/10 on LIBERO's layout with cleared table, 0/10 on a new layout, 0/20 on 20 held-out layouts in the scaled scene** (`docs/results.md`, README; N = 10 and 20, Wilson intervals up to 28% wide). Learned VLAs are brittle to layout and object size. This is a measured, quotable reason for adversarial testing, and ANTS can cite it as a baseline row with its own caveats.
- Fine-tuned from `smolvla_libero` on 100 generated episodes: **14/20** (Wilson 95%: 48 to 85%); from `smolvla_base`: 3/20. One seed, best-of-six checkpoint chosen on layouts 0 to 9, tested on 100 to 119. Use as context for what "trained" costs (12 clips → 170 rollouts → 100 successes, ~59% yield) versus ANTS's zero training, never as a head-to-head: different task framing, N, and seeds.

## 4. Process assets to copy

- **Held-out protocol that already exists:** select on layouts 0 to 9, test on layouts 100 to 119. ANTS's acceptance / held-out split should use disjoint layout seeds the same way (and the ASPIRE seed protocol in the discussion note). Keep them in separate data paths, as AGENTS.md requires.
- **`docs/design_decisions.md` format:** component register with status words (As-is, Configured, Modified, Novel, Rejected), and a numbered decision entry per change with symptom (with numbers), cause, upstream default, change, evidence command, status and limits, and a "README: added | not added, and why" line. It also records negative results so they are not retried. Adopt it for ANTS; it covers the "log every failure, diagnosis, constraint" rule at the project level.
- **Significance review rule** before anything reaches the README: reproduced from repo code, checked on target data, and applied by the documented command. ANTS's README discipline ("numbers come from logged runs") is the same idea; this makes it checkable.
- **Gates with fallbacks in `PLAN.md`** (MVP replay first, then data, then policy, then stretch; protect the last hours for the README) is the right shape for the Nov 4 window.
- **Every feature gets a notebook, notebooks contain no logic** (`CLAUDE.md`): a good fit for ANTS demos, which are a pitch asset. Optional; the cross-platform rule means keep logic in `src/ants` regardless.
- **Presentation assets:** episode dashboard GIF (video, markers, hand skeleton, TCP path, aperture, state/action in one frame) and the real-clip beside sim-replay view are ready-made figures for "System 1 reads the demo".

## 5. Flaws in hurobo that ANTS must not inherit

hurobo's own `docs/review.md` is unusually candid. In summary:

| Flaw | Source | What ANTS does instead |
|---|---|---|
| **Central claim not isolated.** No condition without human data; a straight-line planner may match | `review.md` §1 | Run the no-demo and retarget-replay arms before any claim about the demo |
| **"New object" overclaim.** Same LIBERO bowl and plate scaled ×1.23 and ×1.86; test layouts from the training generator | `review.md` §5 | Hold out layout **categories**, not only seeds; say "interpolation" if that is what it is |
| **Weak headline comparison.** Pretrained checkpoints never saw the scaled scene | `review.md` §2 | Compare against baselines that had the same information |
| **Confounded init comparison, N = 10 selection, one seed** | `review.md` §4 | N fixed up front, ≥ 3 seeds on final rows, intervals always |
| **Unmeasured marker size**: all object-relative numbers may be scaled wrongly | `review.md` §6 | Measure physical constants before extraction; assert them in config |
| **Controlled-setup perception.** ChArUco board, ArUco marker on each object, one camera, one person, one session | README limitations | Be explicit that Phase 2 inherits this; do not claim "uncontrolled phone video" |
| **Yield loss:** 12 of 26 clips usable; 5 of those 12 pass only with a gate waived; 59% generation yield; no length filter | README, `status.md` | Log rejection reasons per stage; no waived gates in headline numbers |
| **Fixed top-down grasp; hand orientation discarded** | README | Needed if the demo is to carry grasp-part information |
| **Heavy, brittle environment:** cu126 torch pinned to the driver, `opencv-python` override to stop `cv2` clobbering, Python 3.12 only, `lerobot` pin, never download the 70 GB dataset | `CLAUDE.md` | Keep it in a separate venv; ANTS `contracts` imports none of it |
| **Numbered scripts (`00_` to `24_`) are not importable** | repo tree; `CLAUDE.md` itself notes this | Put callable code in `src/ants`; scripts only parse args |
| **Linux/GPU only; some features unverified on other OSes** | `CLAUDE.md` | ANTS CI runs Ubuntu, Windows and macOS on pure-Python parts only |
| **Scope sprawl:** splat scanning, collision meshes and teleop consumed effort without feeding the policy | README "What did not work" | One claim, one scene, two experiments (the I7 discipline) |

Positives to keep: Wilson intervals, failed runs reported, a decision log with negative results, tests (33 files, many on synthetic stand-ins), and a README that says what is not shown.

## 6. Integration plan (how to use it without importing it)

1. **Do not add hurobo as a dependency of `ants`.** Treat it as an external tool with one contract: it reads an `.mp4` plus calibration and writes `DemoSpec.json` (per ANTS's discussion §3.4 caveat).
2. Define `DemoSpec` in `src/ants/contracts/` in pure Python (dataclasses + JSON). Include a `source` field and a frame name on every array.
3. Copy by hand (small, pure NumPy, no heavy deps), with tests: `utils/stats.py` (Wilson), the pinch-aperture hysteresis and resampling from `utils/signal.py`, and the transform helpers from `utils/transforms.py`.
4. Phase 1 (no real video): generate demos in LIBERO by teleop or a scripted oracle so DemoSpec accuracy can be scored against ground truth. Phase 2: a hurobo wrapper converts `HumanDemo` to `DemoSpec`; report it as a separate, smaller, caveated result.
5. Wrap `ObjectCentricRetargeter` behind an adversary-side `baseline_retarget_replay(demo, layout)` that returns success per seed, run in hurobo's own environment via CLI.
6. LIBERO conflict check before anything else: ANTS's discussion picks ASPIRE `cap_harness` (LIBERO-Pro) as the execution substrate, while hurobo drives LIBERO through `lerobot.envs.libero`. They are not interchangeable. Decide which one runs the layouts, and port `LayoutSampler` to that one.

## 7. Not reused, and why

SmolVLA fine-tuning, LeRobot dataset export, ACT fallback, checkpoint evaluation (ANTS forbids training); the Gaussian-splat and COLMAP scanning pipeline and collision-mesh builder (visual only, heavy, did not reach the policy); the challenge brief, slides and PLAN schedule (specific to another competition); `FLYBRAIN_IDEAS.md` (unrelated theme, not read in detail).
