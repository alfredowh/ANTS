# Live view and digital twin: feasibility

Written 2026-11-04 for the Studio owners. Research only; nothing here was built or run. No GPU
rollout and no Muse tokens were used. **Measured** means taken from a logged run named here.
**Read** means read in the code. **Estimate** is my judgement and has not been run.

## Verdict

| Layer | Verdict | Effort (estimate) | Live rate (estimate) | Risk to results |
|---|---|---|---|---|
| Two real LIBERO camera views | small hook in our launcher | 0.5 day | 5 to 10 Hz | none expected; to test |
| (a) Panda mirroring joints and gripper | possible today from a file tail | 0.5 to 1 day | 10 Hz | none: read-only tail |
| (b1) Scene from simulator meshes, objects moving | small hook | 1 day | 10 Hz | none expected; to test |
| (b2) Scene from SAM 3 and the Mapper, before the rollout | possible offline, in a separate process | 2 to 3 days | static | none if a separate process |
| (b3) Scene rebuilt live during the rollout | research, not built | unknown | not known | high GPU contention |
| (c) cuRobo path | possible, per plan and not per optimiser step | 0.5 to 1 day | one update per plan | **needs the cuRobo planner, which changes the run** |
| (d) Collision bodies | possible; robot and world differ in fidelity | 1 day | robot 10 Hz; world per plan | none extra once (c) is on |

Short answer: the twin the user described is possible as a **mirror**, drawn from simulator state
and planner data. It is not a live reconstruction. The honest headline is "what the planner
believed versus what the simulator did", and the repo already has most of those pieces.

## 1. What exists

### Earlier discussion

No document covers the live version. The nearest material:

- `src/ants/studio/scene3d.py:5-7` calls the realtime view "the separate, not-yet-ready
  realtime/cuRobo viewer".
- `docs/perception/scene-reconstruction-probe.md`, "Where this goes next", item 2: online mapping
  during a rollout, "Not built", and landing it in the planning path "needs Daniel first".
- `docs/perception/real2sim-overnight-2026-11-04.md` section 2: "Scanning 'whole LIBERO' is
  unnecessary — LIBERO scenes are already sim-native; scan only the real room". That is about the
  real room twin. I agree with it for simulation, and it bounds what (b2) can claim.

### Reconstruction quality and latency (measured, offline)

From `docs/perception/scene-reconstruction-probe.md`:

- Best map: `fused_hires`, 82 frames at a 5 mm voxel, 122,122 vertices and 232,615 faces. It has
  **ghost copies of the arm**. `fused_orbit_hires` (80 frames, robot at home) is the planning map.
- Bowl crop against the true mesh: chamfer 4.48 / 9.90 mm (mean / p95), bounding box 9.59 mm, hull
  volume 2.9%. It passes with thin margins, for one object, one scene and one seed.
- Planning against the fused mesh: 2.62 s for one query. The 0.55 s single-frame comparison in that
  doc is **invalid** (the doc corrects it) and has not been re-run.
- Fusion time: **untimed** ("order of a minute or two for 16 frames" is an unmeasured remark).
- The orbit scan teleports a virtual camera, so it cannot share a seeded rollout's simulator.
- The fused map is stricter than the single-frame world: it rejected starts 3 to 12 cm above the
  rack contact, and whether those are true collisions was not checked.

### What a rollout writes while it runs (read)

| Data | Where | Live? |
|---|---|---|
| Joints, velocities, gripper, end-effector pose per step | `episode/steps.jsonl`, flushed every step (`ASPIRE/src/cap_harness/artifacts.py:510-511`) | yes |
| Spans with timing | `trace/events.jsonl`, flushed (`artifacts.py:744-745`) | yes |
| Plan result per call | `trace/calls/<id>/output.json` plus a `payloads/*.npy` | after each call |
| Keyframes (PNG) | `media/keyframes/` | about twice per motion call |
| Video | `media/videos/.<camera>.partial.mp4`, renamed at finalize (`artifacts.py:662-669`) | **no**: not playable until closed |
| Contacts per step | `contacts.jsonl`, only with the launcher's `contacts` key (`tools/aspire_launch.py:936-938`) | yes |
| **Object poses** | not in `steps.jsonl` | **no** |

I did not observe `steps.jsonl` growing live: the one check I tried during the active run found no
rollout running at that moment. The flush is read from the code. A nominal run measured below
wrote 474 lines.

Observed cameras: `agentview` and `robot0_eye_in_hand`, both 800x512 by default.

**Reading MuJoCo from outside the subprocess is not possible**: `mjData` lives in the simulator
process and ASPIRE has no state server. The only routes are the files above or a hook inside the
process.

### The minimal hook

`tools/aspire_launch.py` is ours (System 1), runs inside the simulator process and already patches
ASPIRE without modifying it. `PerturbedEnv.step` is the natural place, next to the existing
read-only contact log, and the recorder can be wrapped for frames (`artifacts.py:755-768` receives
`observation.cameras[...].rgb`, so no extra render is needed).

Getting nominal runs through the launcher needs no edit to Daniel's code: a nominal case only calls
`cap-harness` directly when the scene spec is empty, and `AspireConfig.scene` already carries extra
launcher keys (`src/ants/adversary/rollout/aspire_backend.py:71,108-125`). Whether a run through
the launcher with no perturbation matches a direct run is unverified and is the first test below.
`src/ants/evalkit/aspire_harness.py:76-86` follows the same rule for generation.

### Timing (measured, per run)

Default planner, nominal seed 57, 474 steps, `task_success` true, 36.3 s wall
(`data/runs/aspire/20261104_042355_0000_s57_nominal/.../outcome.json`):

- `adapter_step` 18.93 s for 474 steps: **about 25 steps per second**, against a 20 Hz simulator
  clock (23.7 simulated seconds).
- Two SAM 3 calls about 2.7 s each; `plan_motion` about 10 ms; 34 keyframes 3.19 s; 476 video
  encodes 1.46 s.

cuRobo planner with the SAM 3 robot mask (`data/runs/curobo/exp10/clip_233859/demo/sample0/debug_attempt3/`),
527 steps, success, 315 s attributed:

- `curobo.plan_to_joints` mean 4.04 s, max 5.93 s, 14 calls.
- `plan_motion` overall mean 19.5 s, because each plan also segments.
- 86 SAM 3 calls (100.4 s) and 86 overlays (117.1 s).

These are different programs, so the ratio is not a clean comparison. It does show that the live
cuRobo view means a pause of about 20 s per motion, and the camera views will freeze during it.

### What cuRobo exposes (read)

- HTTP response: **joint path and dt only** (`providers/curobo/service.py:93-95,1109`). Measured
  example: 52 waypoints at 0.05 s, `planner: curobo_v2_cspace`, `scene_points: 41195`.
- The optimiser runs inside one blocking `plan_pose` or `plan_cspace` call (`service.py:1089,1104`).
  **No intermediate iterations reach us**, so planning cannot be animated as it happens.
- The world mesh is built inside the service (`_voxelized_scene_mesh`, `service.py:413`, with robot
  carve and sparse-voxel filter) and is not returned.
- The input cloud is available: `cloud_dir` in the launcher's planner spec saves one per plan
  (`tools/aspire_launch.py:501-511`; example 41,139 points, about 1 MB).
- Robot spheres: 61 across 11 links in `src/ants/evalkit/panda_spheres.json` (from cuRobo's
  `franka.yml`), with pure-Python forward kinematics in `src/ants/evalkit/panda.py`.

**An offline version already exists.** `dev/curobo/plan_view3d_template.html` with
`plan_data.py` and `make_viewer.py` draws the cloud, start and goal spheres, straight path and
planned path, in three.js 0.128. See `data/runs/curobo/exp10/clip_233832/plan_viewer/`. It replays
with its own sphere-against-cloud check, not a second cuRobo run. The first twin should reuse it.

## 2. Feasibility per layer

### Two camera views

Wrap the recorder's frame method in the launcher and write a downscaled JPEG to `live/<camera>.jpg`
by atomic rename. The server pushes the newest frame. Frames that the browser misses are dropped,
never queued. The rollout never waits on the viewer.

The earlier watcher (`watch_aspire_live`, `004a852`) only read keyframes, and `f75b89e` removed it
when the Perception tab went. Its stale-run guard and test idea are worth reusing, and it never ran
on a real GPU rollout. Frames freeze during SAM 3 and planning, so show a "planning / segmenting"
label from `events.jsonl` rather than letting it look hung.

### (a) Robot

Tail `steps.jsonl`, apply the joints, map the normalised gripper value to the fingers (`0.04 *
gripper`, from `robosuite/adapter.py:336`, to confirm for both fingers). Meshes: robosuite's
`robots/panda/meshes`. The collision STLs total 0.73 MB and the `_vis` STLs 6.7 MB (measured);
start with the visual ones decimated, or the collision ones if they look acceptable. Convert once on the server to binary buffers.

Trap: `panda.py` follows cuRobo's URDF frames and the meshes come from the MJCF. Their alignment is
unverified, so check against the camera image. Steps are in `robot_base`, the scene in world
coordinates, so use the transform from the scene dump. Note `docs/perception/real2sim-overnight`:
the Franka URDF does not load directly in MuJoCo.

Frame rate: 10 Hz is plenty, by tailing every second or third line. Cost to the rollout: zero.

### (b) Scene

**b1, simulator meshes: recommended.** `_dump_scene` (`tools/aspire_launch.py:734`) already has
bodies and geoms but not vertices (`scene3d.py` says "mesh (7) has no vertex data here"). Add a
one-time mesh export at reset and per-step `xpos`/`xquat` for free bodies. This is ground truth,
including the moving bowl, and shows the perturbed scene correctly (pose, scale, clutter), which
makes attacks visible.

**b2, reconstruction before the rollout.** Run the existing probe in a second process with the same
seed, then overlay it on b1. Blockers: the robot must be removed at scan time (probe doc), a
perturbed scene needs a fresh scan, and fusion is untimed. Identical scene state across the two
processes is an assumption, to test.

**b3, live.** Not recommended now. Nothing is built, SAM 3 takes about 2.5 s per image, and the
GPU is shared with SAM 3, cuRobo and the simulator on one 16 GB card.

### (c) cuRobo trajectory

Available the moment each plan returns. Draw the planned path, then let the mirrored robot follow
it, so divergence is visible. That divergence is new information and useful in the failure story.

**Blocker.** `/policy-dev` does not use cuRobo today. It runs `demo_vs_nodemo` without `--planner`
(default `default`, `orchestrator/demo_vs_nodemo.py:285`; `src/ants/studio/policy_dev.py:343`), and
plans there come from `pyroki+joint_interpolation` with `collision_aware: false` (measured in the
seed 57 run above, about 10 ms each), so there is no collision-aware path to draw. Turning cuRobo on changes programs' outcomes and costs many times
the wall clock, so **it must be a run setting that is logged, never a viewer toggle.** Its use by
the Adversary also has to be agreed with Daniel, even though `AspireConfig.scene` can carry it.

### (d) Collision bodies

- **Robot spheres:** the 61 cuRobo spheres from the joints. Exact for what the planner models,
  except the attached bowl spheres, which come from the launcher hook (`aspire_launch.py:525-576`).
- **World as the planner saw it:** approximate by voxelising the saved cloud at 1 cm on the viewer
  side, or return the real mesh from a patched service. ASPIRE is third party and `ASPIRE/` already
  has uncommitted local edits in `service.py`, so do not add more there; `dev/curobo/service_dev.py`
  is the place. Label an approximation as such.
- **Actual contacts:** `contacts.jsonl` per step as markers. This is ground truth and it is the most
  honest layer: a gripper pressing the wine rack is exactly what `dev/curobo/README.md` diagnosed
  (`gripper0_right_gripper | wine_rack_1_main`, 410 to 479 steps).

### Does any of this perturb results?

Physics should be unaffected: the hooks read state, render nothing new and write files. That is an
expectation, **not a measurement**. Results come from these runs, so before use:

1. Same seed and program, direct `cap-harness` against the launcher with hooks: compare
   `robot_state` in `steps.jsonl` line by line and `outcome.json`. Any difference blocks the hook.
2. Measure added wall time against `adapter_step`.
3. Log `live_view: on` in `settings.json`, so a run can be excluded if doubt appears. Wall clock is a
   safety net only (900 s), and cuRobo runs at 315 s leave less margin.

## 3. Build order

1. **Two views** (what the user asked for now). Enabled only during a run, as a mode in the
   Synthesizer view.
2. **Determinism test** above. Cheap and it protects everything after it.
3. **Thinnest twin: robot plus simulator scene** (a + b1), tail-driven, in a third "3D" panel beside
   the two views. Attack perturbations become visible.
4. **Contacts and robot spheres** (d, partial).
5. **cuRobo layer** (c, world part of d) by moving the existing plan viewer to live data, once a run
   setting exists and Daniel agrees.
6. **Reconstruction overlay** (b2), for the story and for real2sim. Live reconstruction stays research.

### Rendering

three.js r128 from cdnjs is already used by `scene3d_template.html`; cdnjs does not host the
`examples/` files, so take OrbitControls from jsdelivr `three@0.128.0` as `plan_view3d_template.html`
does. Preprocess meshes on the server into binary buffers and use `BufferGeometry`, so no loader is
needed. Use one `InstancedMesh` for spheres and `Points` for the 41k cloud. Stream state over the
existing `/events` connection at most 10 Hz, with a separate fetch for frames, because Chrome's
six-connection limit has already bitten this page.

### Labels, so the demo does not mislead

Every layer gets a visible badge and its own toggle:

| Badge | Layers |
|---|---|
| **SIMULATOR TRUTH** | robot, object poses, scene meshes, contacts |
| **PLANNER BELIEF** | cuRobo spheres, cloud, voxel world, planned path (with its age: "from plan 6, 12 s ago") |
| **RECONSTRUCTED, OFFLINE** | Mapper mesh, with the scan date and its known ghost or carve limits |
| **APPROXIMATION** | anything voxelised on the viewer side |

Do not call b1 "reconstructed", and do not call the whole view a "digital twin" while it is drawn
from simulator state. "Live mirror" is accurate. Do not animate planning between request and result,
since nothing observes it. In a recorded demo video, state the speed if it is sped up past the
planning pauses.

## Sim-to-real relevance

The mirror itself transfers partly. Robot state, planner belief and contacts come from sources a
real robot also has, except that contacts have no simulator ground truth there. The simulator-mesh
scene does not transfer, since no real robot has it: b2 is what transfers, and only from the camera
views a real robot has (wrist, plus a fixed camera). Today's reconstruction was mostly built from
virtual orbit cameras. Separately, the real-room twin (`tools/real2sim/`) is unregistered and
kinematic-only, there is no hardware for contact validation, and none of this measures a sim-to-real
gap. It shows the belief-versus-truth gap in simulation, which is the same kind of failure a real
system would have, not evidence about real performance.

## Top risks

1. Hooks silently changing results. Test 1 above is the guard.
2. cuRobo being expected in the demo though the pipeline doesn't run it, and it pauses about 20 s
   per motion and changes outcomes.
3. GPU contention on one 16 GB card if reconstruction runs near the rollout.
4. Mesh and frame alignment (MJCF against URDF, world against `robot_base`) looking almost right.
5. Over-claiming: "digital twin" for a view drawn from simulator truth.
