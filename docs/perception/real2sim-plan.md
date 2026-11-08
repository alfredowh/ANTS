# Real2sim plan: shared backbone, two projects, three categories (2026-11-07)

Plan only; nothing here is built or run. Literature: [real2sim-literature.md](real2sim-literature.md).
Earlier evidence: [scene-reconstruction-probe.md](scene-reconstruction-probe.md),
[real2sim-overnight-2026-11-04.md](real2sim-overnight-2026-11-04.md),
[../studio/digital-twin-feasibility.md](../studio/digital-twin-feasibility.md),
`docs/dev/curobo-notes-2026-11-05.md`, `dev/curobo/README.md`.

## Decisions (user, 2026-11-06/07)

| Topic | Decision |
|---|---|
| Categories | A real2sim simulator (PolaRiS-style policy evaluation), B realtime digital twin, C cuRobo planning (shown **and** measured) |
| Order | C → B → A in both projects |
| Twin source | simulator first, then real cameras; RGB and RGB-D both supported |
| Code home | a **standalone package repo** (working name `real2sim`), robot/camera/simulator-agnostic; ANTS and the thesis keep thin adapters |
| Simulators | P1: MuJoCo/LIBERO first, Isaac export second. P2: Isaac Sim primary (USD exists) |
| Dependencies | post-hackathon; heavy deps allowed after asking per dependency; RTX 6000 Pro and a 32 GB GPU available for heavy steps or fine-tuning |

## Two deployments of one backbone

| | P1: ANTS / own (proof of concept) | P2: thesis |
|---|---|---|
| Robot | none real; sim Franka (LIBERO) | dual UR5e + Robotiq, real |
| Cameras | S24 RGB; S24 + S10e as a stereo pair | 2 wrist RGB, 1 context RGB-D (RealSense), 1 front target RGB facing the robot; **not calibrated yet** |
| Simulator | MuJoCo/LIBERO (ASPIRE `cap_harness`) | Isaac Sim (existing USD), cuRobo/cuMotion |
| Ground truth | simulator state; ChArUco; passive physics trials | real robot: real-vs-sim rollouts become measurable |
| What it proves | the pipeline works from constrained hardware (RGB only) | the pipeline holds on a real robot (sim–real correlation) |

P1 assumes a robot will exist one day, so every P1 module must also run with P2 inputs.

## Backbone modules (the overlap)

Each module has one interface and possibly several back-ends. **Reuse rule:** a shared back-end
is used for a consumer only if it passes that consumer's metric gate (thresholds fixed before the
run and logged). If it fails, keep a dedicated back-end in parallel (redundancy), and log which
one ran.

| # | Module | Back-ends | Used by | Notes |
|---|---|---|---|---|
| M0 | Calibration | intrinsics (ChArUco), extrinsics (multi-camera ChArUco), hand-eye for wrist cameras, phone stereo pair | all | P2 step 0; P1 has S24 intrinsics |
| M1 | Camera sources | sim camera (LIBERO / Isaac), recorded video, live RealSense, live phone | all | same frame record: rgb, depth?, K, T_world_cam, t, source |
| M2 | Depth front-end | sensor depth; stereo (FoundationStereo / Fast-FS); mono (MoGe-2, DA3); multi-view feed-forward (VGGT, MapAnything); SfM (COLMAP) | A, B, C | the RGB vs RGB-D switch lives here; each back-end scored against sim depth and RealSense |
| M3 | Segmentation | SAM 3 (have), robot self-mask (sim segmentation / SAM 3 / rendered robot from FK) | A, B, C | the FK-rendered robot mask replaces cuRobo's 5 cm carve |
| M4 | Fused map | cuRoboV2 `Mapper` TSDF/ESDF (have, v0.8) | A, B, C | **two instances**: static high-res prior (5 mm, offline) and dynamic decaying layer (1 to 2 cm, online) |
| M5 | Appearance | 2DGS / PGSR-D (gsplat), 3DGUT → NuRec for Isaac, DISCOVERSE renderer for MuJoCo | A (B later) | never used as collision geometry (splat geometry is worse; ReVeal) |
| M6 | Objects + sim-ready gate | LIBERO/USD assets, scanned TSDF crop, SAM 3D Objects (scale fixed by depth/ChArUco), CoACD; gate v1 exists | A, B, C | gate: chamfer, bbox, hull volume, settle, plus a case that can fail |
| M7 | Pose tracking | sim truth; FoundationPose (RGB-D); RGB path (FoundationPose + M2 depth, or RGBTrack); POGS later | B, C | attached-object pose for the planner |
| M8 | Scene state | one record: objects, poses, robot q, map refs, timestamps, provenance (SIM TRUTH / PLANNER BELIEF / RECONSTRUCTED / APPROXIMATION) | all | the only thing consumers read |
| M9 | Exporters | MJCF (LIBERO scene), USD (Isaac), cuRobo world (mesh / ESDF / attached spheres) | A, C | from M8 only |
| M10 | Evaluation kit | map vs sim truth, pose error vs sim truth, overlay error and mask IoU, NVMF/APGF, refusal FN/FP (goal labeler), path contacts in sim, plan time, sim–real agreement | all | numbers in docs only from logged runs |
| M11 | Viewer | existing plan viewer and `scene3d`, live mirror with badges | B, C | read-only |

Relationship of the categories: **C consumes the backbone's world** (M3, M4, M7 → M9 cuRobo
world). **B is the backbone running online** and keeps M8 current. **A is the backbone run offline at
high quality** plus M5 appearance and M9 simulator export. A's static map is B's and C's prior. B in
simulator-first mode is the test bench for every module, because simulator state scores it.

## Category C: cuRobo planning (first)

Goal: fewer false refusals and no forbidden contacts, with the world built from perception, shown
in a viewer. Seeds: acceptance 51 to 65 only.

| Step | Work | Reuses | Done when |
|---|---|---|---|
| C0 | Finish pending evidence: `replay_seeds` (attach vs sparse, seeds 51–53), `goal_confusion.py`, re-run the rack guard | dev/curobo, tools/mapper_probe | fix confirmed or refuted across seeds; no rise in `plan_colliding` |
| C1 | Planner-world adapter (M9): robot removed by mask, not carve; held object as attached spheres from M7; target excluded for grasp moves | M3, M7 | goal-labeler FN and FP per run, logged |
| C2 | Static prior + dynamic layer (M4 × 2): scan once with the robot masked, then per-plan wrist/agentview depth into the decaying layer | M4 | rack test: plans where single frame fails, and the near-start rejections checked in MuJoCo (over-conservative or true) |
| C3 | Belief-vs-truth viewer: planned path, spheres, world, contacts | M11 | per plan, badges shown |
| C4 | Optional: MPPI reactive mode, CAPT point-cloud collision, learned seeds | — | only if `planning_failed` stays high after C1 to C2 |
| P2 | Same adapter on cuRobo/cuMotion in Isaac with the UR5e USD, then on the real robot with RealSense + wrist cameras | M0 calibration first | real executions without contact; refusals vs a hand-labelled set |

Metric gate for C (to agree before the runs): FN refusal rate, forbidden-contact steps (collision
validator), plan time, clean success, on seeds 51 to 65.

## Category B: realtime twin (second)

| Step | Work | Done when |
|---|---|---|
| B0 | Determinism test: launcher hooks change nothing (steps.jsonl line by line) | identical outcomes |
| B1 | Live mirror from simulator truth (robot + scene meshes + contacts), streaming M8 | 10 Hz in the viewer |
| B2 | Perceived twin in sim: sim cameras → M2/M3/M4/M7 → M8, scored live against sim truth | pose error (mm, deg) and map error logged per step; RGB-D vs RGB back-ends compared |
| B3 | P1 real: S24 (+ S10e stereo) streaming the real table; objects tracked by M7 | overlay error and mask IoU against held-out frames |
| B4 | P2 real: 4 calibrated cameras, real UR5e joints drive the twin robot | twin vs real images; later Real-is-Sim style correction (research) |

## Category A: real2sim simulator (third)

| Step | Work | Done when |
|---|---|---|
| A0 | Register the P1 scan to the ChArUco frame (COLMAP images.bin), replace starter placements with measured ones | table and objects within a fixed mm bound in the overlay |
| A1 | Collision from TSDF (M4 static), visuals from 2DGS/PGSR-D (fix gsplat env or train on the 32 GB GPU) | ReVeal-style NVMF/APGF and held-out PSNR logged |
| A2 | MJCF export with LIBERO assets / scanned objects passing M6; robot base from IK reachability | ANTS policy runs in the twin |
| A3 | USD export → Isaac with NuRec splat (P2 primary, P1 second) | same scene loads in both; same fidelity numbers |
| A4 | Passive physics (P1): ~20 drop/slide trials, calibrate on part, report held-out; bounds the adversary's physics severity | logged |
| A5 | P2 correlation: real vs sim rollouts of the same policies (PolaRiS / YUBI protocol) | rank agreement and correlation reported |

## Risks

- GPU contention: simulator + SAM 3 + cuRobo + mapping on 16 GB; heavy steps go to the 32 GB / RTX 6000 Pro.
- RGB-only depth (mono/stereo) may fail the C gate; then P1 planning keeps sim depth and the RGB path stays for A/B only (logged as such).
- Splat geometry is not collision geometry; never shortcut that.
- Phone stereo: sync and baseline are uncontrolled; calibrate and measure before trusting.
- Ownership: anything entering `src/ants/adversary/` or `orchestrator/` needs Daniel.

## Decided 2026-11-07

- Repo name **`twinkit`**; created locally at `../twinkit` (uv package, Python 3.10), not on GitHub yet. Deps so far: `coacd`, `trimesh`, `numpy`.
- Gate purpose: a metric threshold, fixed before the run, that picks which back-end of a module a consumer uses (shared if it passes, a dedicated one in parallel if not).
- Dependencies approved; heavy ones (FoundationPose, FoundationStereo, MoGe-2 / DA3, MapAnything / VGGT, gsplat or 3DGUT, SAM 3D Objects) get their own uv groups and are installed when their step starts.

## Open (to decide before building)

1. Visibility of `twinkit` on GitHub (private by default) and thesis IP.
2. Metric thresholds per gate (C first).
3. New dependencies, one by one: gsplat fix, FoundationStereo, MoGe-2 / MapAnything, FoundationPose, SAM 3D Objects, CoACD, Isaac NuRec.
4. P2 calibration tooling (hand-eye for the wrist cameras).

## Compute: start local, options if bigger compute is unlocked

Side project first: everything is installed and tried on the local laptop (RTX A5500, 16 GB).

| Step | Fits 16 GB locally? | With the 32 GB GPU | With the RTX 6000 Pro (96 GB) |
|---|---|---|---|
| C (cuRobo, Mapper, SAM 3, simulator) | yes, one simulator at a time | run sim + services + mapping together | many seeds in parallel |
| FoundationPose tracking | yes (inference) | live tracking next to the simulator | multiple objects/cameras live |
| FoundationStereo / MoGe-2 / DA3 | yes, Fast-FoundationStereo or small models | full-size models | fine-tune on own stereo pairs (S24 + S10e, thesis cameras) |
| VGGT / MapAnything | small scenes, few frames | ~100 frames | full scans, all thesis cameras |
| 2DGS / PGSR-D / 3DGUT training | tight; short schedules | normal schedules | high-res, many scenes; batch for the adversary |
| SAM 3D Objects | likely too tight | yes | yes |
| Isaac Sim + NuRec + cuRobo | heavy; scene + robot only | comfortable | thesis: 4 cameras + dual arm live |
| Fine-tuning (optional) | no | small adapters | depth/stereo or pose models on own data; only if a gate fails because of domain gap |
