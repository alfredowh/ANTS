# Scene reconstruction probe (cuRobo Mapper)

Status: **offline probe, working, not wired into any owned package.** 2026-11-03.

## What this is

A standalone two-stage tool, `tools/mapper_probe/`, that answers one question: can ANTS fuse a
multi-view camera scan of the LIBERO scene into a persistent 3D reconstruction (not just the
single-frame point cloud cuRobo's planner already uses, see `dev/curobo/`), and can a policy later
plan against that reconstruction instead of raw per-step geometry?

1. **`scan_orbit.py`** (`ASPIRE/.venv-libero`): orbits a LIBERO camera around the scene (16 frames
   by default, `agentview` by default), saving RGB-D + the world-frame camera pose per frame with
   the same camera-convention math `cap_harness`'s `LiberoAdapter._camera_observation` already uses
   (read-only reuse, not a fork of it), so the convention stays consistent with the rest of the
   pipeline.
2. **`fuse_mapper.py`** (`ASPIRE/.venv-curobo`): fuses the saved frames with cuRobo's
   `curobo.perception.Mapper` (NVIDIA Warp backend; nvblox is vendored inside cuRobo but not a
   separate dependency here) into a block-sparse TSDF, computes an ESDF, extracts a triangle mesh,
   and renders a few shaded views.

Run with `uv run python -m ants.evalkit.runbook cmd scene_recon.scan` and
`... cmd scene_recon.fuse` (see `docs/runbook/commands.json`).

## Result (logged run, 2026-11-03, `data/runs/mapper_probe/`)

- 16 orbit frames of `libero_goal_swap` task 8, seed 51 (the bowl-on-plate task).
- Fused mesh: 23,441 vertices, 44,253 faces, saved as `reconstructed_scene.ply`.
- Three rendered views (`reconstructed_view_0.png` .. `_2.png`) confirm the reconstruction matches
  the real scene layout (cabinet, bottle, bowl, plate in their real relative positions).
- Interactive viewer published as a Claude artifact (Three.js, mesh embedded as base64, portable
  single-file HTML for embedding elsewhere):
  https://claude.ai/artifact/1YhU9TBJAhwBdmUBhVLpzS

## Real arm-driven scan (2026-11-03, `tools/mapper_probe/scan_arm.py`)

Added a second scan mode that drives the actual Franka arm instead of teleporting a camera body:
it closed-loop controls the arm's shoulder-pan joint through a 6-waypoint sweep using the exact
delta-joint formula `cap_harness.libero.codec.LiberoActionCodec.encode` uses
(`native = (target - current) * control_frequency`, clipped to the native action bounds), so
`robot0_eye_in_hand` moves through real forward kinematics, not an overwritten camera pose. Logged
run: 6 waypoints, joint error converged to <0.02 rad each time, fused into a 5,948-vertex mesh
(`data/runs/mapper_probe/arm_scan/`) showing the close-range table surface and gripper edge the
wrist camera actually saw. Sparser than the 16-frame orbit (fewer, narrower-swept views, and the
wrist camera sits much closer to the surface than `agentview`), but it is genuine robot motion.

Run with `uv run python -m ants.evalkit.runbook cmd scene_recon.scan_arm`, then fuse with
`fuse_mapper.py --frames-dir data/runs/mapper_probe/frames_arm --out-dir data/runs/mapper_probe/arm_scan`.

## Fuller scan: pan x tilt grid (2026-11-03, `tools/mapper_probe/scan_arm.py`)

Extended the arm scan from a 1-DOF pan sweep to a 2-DOF raster: 5 shoulder-pan offsets
(-0.5 to +0.5 rad) x 3 shoulder-lift offsets (-0.15 to +0.15 rad), 15 waypoints, same
closed-loop delta-joint drive. Old single-sweep defaults are superseded; new frames go to
`data/runs/mapper_probe/frames_arm_full/` (the 6-frame run is preserved untouched).

Logged run: 14/15 waypoints converged to <0.02 rad. One corner (pan=-0.5, lift=+0.15)
stalled at 0.145 rad after 120 steps -- still saved with its true forward-kinematics pose,
so fusion stays correct, just with one viewpoint slightly off its target.
Fused mesh (`data/runs/mapper_probe/arm_scan_full/`): **10,320 vertices, 18,437 faces**,
up from 5,948 with the 6-frame sweep. Renders stay coarse (close-range wrist views of
mostly table surface at 1 cm voxels) but consistent with the earlier arm-scan look.

## HTML viewer (2026-11-03, `tools/mapper_probe/make_viewer.py`)

Single-file portable viewer, `data/runs/mapper_probe/viewer.html` (regenerate with
`uv run python -m ants.evalkit.runbook cmd scene_recon.viewer`): embeds the orbit and
full arm-scan meshes as base64, three.js r160 orbit/zoom/pan controls, a mesh toggle
with live vertex/face counts, and a slow-spin switch. Verified headless in system
Chrome at desktop and phone sizes with zero console errors; one real defect found and
fixed along the way (z-up PLY rendered standing vertical until a -90° X rotation).

## IK look-at scan (2026-11-03, `tools/mapper_probe/scan_lookat.py`)

Third scan mode: waypoints are world-frame camera poses on an arc around the bowl,
each oriented to fixate it, converted to end-effector poses via the camera-in-hand
transform measured at reset, solved with the PyRoki IK service (needs
`scripts/supervise_services.sh --providers pyroki`), seeded with current joints, and
driven with the same closed-loop delta-joint formula. Run with
`uv run python -m ants.evalkit.runbook cmd scene_recon.scan_lookat`, fuse with
`fuse_mapper.py --frames-dir data/runs/mapper_probe/frames_lookat
--out-dir data/runs/mapper_probe/lookat_scan`.

Logged runs: the mechanism is validated — projecting the bowl body into the one
converged frame puts it 0.4° off image center, and its RGB shows the bowl/plate/bottle
fixated. But the reachable set is narrow: 5/8 waypoints fail PyRoki's residual limits
(2 cm / 0.15 rad) and solved-but-distant waypoints stall the straight-line joint drive
(errors 0.09–0.50 rad after 150 steps), plausibly the elbow swinging through the table
on the direct joint path. Only the az=-20° column converges reliably. Fused the 3 saved
frames anyway: **14,995 vertices, 27,256 faces** (`data/runs/mapper_probe/lookat_scan/`,
dense around the fixated bowl area). Fixing the stall needs collision-aware joint
interpolation — which is exactly what the ESDF-as-obstacle step below would provide.

## Planning against the fused mesh (2026-11-03, `tools/mapper_probe/plan_esdf.py`)

Closes the loop at the mechanism level: builds cuRobo's `MotionPlanner` exactly the
way ASPIRE's curobo service does (`franka.yml`, `update_world(Scene(mesh=...))`) but
with the fused orbit-scan mesh as the world obstacle, and compares against the live
single-frame path (one orbit frame back-projected to world points through ASPIRE's
own patched `_voxelized_scene_mesh`). Same query both arms: home → home + 0.5 rad
shoulder pan, an elbow sweep the real arm physically executed. Run with
`uv run python -m ants.evalkit.runbook cmd scene_recon.plan_esdf` (needs CUDA).

Logged run: **both arms succeed** — fused: 2.62 s, path 0.5 rad; single-frame: 0.55 s,
path 0.5 rad. No face-flip needed (Mapper marching-cubes winding is outward-correct,
unlike the hand-rolled voxel extraction the service had to patch). Honest reading: the
reconstruction is proven plannable — the planner accepts the fused mesh as its world
and returns a valid trajectory — but this free-space sweep needs no avoidance under
either representation, so it shows parity, not superiority. The discriminating query
(a motion threading the wine-rack bars from `dev/curobo/`, where the single-frame
filter drops thin obstacles) is the follow-up, and it belongs in System 2's package —
flag with Daniel before landing it there.

## Fused reconstruction: all scans combined (2026-11-04, `fuse_mapper.py --frames-dir ...`)

`fuse_mapper.py` now accepts multiple `--frames-dir` values and fuses them into one `Mapper`
instance instead of one scan at a time. Ran it on all 34 frames collected so far (16 orbit +
15 arm pan-tilt + 3 IK look-at) at a finer `--voxel-size 0.008` (was 0.01): **44,180 vertices,
82,957 faces** (`data/runs/mapper_probe/fused_combined/`), up from 23,441/44,253 for the orbit
scan alone. Renders show bowl, bottle, plate and cabinet as distinct, low-noise shapes with a
sharp table surface — visibly cleaner than any single scan, because the extra wrist-camera
viewpoints fill in the multi-view constraint that was sparse in the orbit-only mesh and badly
sparse in the look-at-only mesh. `make_viewer.py` now ships this as the default mesh in
`viewer.html`, with the three individual scans kept as toggle options for comparison.

## Higher resolution and a robot-free map (2026-11-04)

Two more orbit rings (`scan_orbit.py`, 32 frames each, camera height 0.95 m and 1.35 m) and a finer
voxel (0.005 m). Frame counts: orbit 16, ring 1 32, ring 2 32, arm grid 15, look-at 3.

| Mesh | Frames | Voxel | Vertices |
|---|---|---|---|
| `fused_hires/` | ring 1 + ring 2 + arm grid + look-at = 82 | 0.005 | 122,122 (232,615 faces) |
| `fused_orbit_hires/` | orbit + ring 1 + ring 2 = 80, robot at home pose only | 0.005 | 124,743 |

`fused_hires` contains ghost copies of the arm and fingers seen by the moving wrist camera, so it
is not a clean obstacle map. `fused_orbit_hires` is the map used for planning; the home-pose robot
is carved out of it before use (see the rack test). A persistent map therefore needs the robot
removed at scan time; this is a requirement, not a detail.

## Sim-ready gate, first version (2026-11-04)

`gate_truth.py` (libero venv), `gate_extract.py` (curobo venv), `gate_settle.py` (libero venv).
Object: the bowl (`akita_black_bowl_1_main`, 5.6 g), cropped out of `fused_hires` by its true box.
Thresholds were fixed before the run (chamfer mean 5 mm, p95 10 mm, bbox 10 mm, hull volume 15%).

| Check | Reconstruction | Limit |
|---|---|---|
| Chamfer mean / p95 vs true vertices | 4.48 / 9.90 mm | 5 / 10 mm |
| Bounding-box error | 9.59 mm | 10 mm |
| Convex-hull volume error | 2.9% | 15% |
| Raw crop watertight | no (underside never seen); hull is watertight | informational |
| Settle, upright and 10 deg tilt (3 s) | rest height -0.24 mm, final tilt 0.06 deg, resting penetration 0.24 mm | 2 mm, 5 deg, 2 mm |
| Same settle on the true hull (control) | -0.19 mm, 0.74 deg, 0.19 mm | |

Result: geometry pass and settle pass, so `sim_ready` is true for this crop, **with thin margins**
(bbox and p95 are within 0.4 mm and 0.1 mm of the limits at a 5 mm voxel).
Negative control (crop scaled 1.3): bbox error 25.4 mm, hull volume error 113%, `sim_ready` false.
Chamfer alone barely separates them (4.5 vs 5.8 mm); bbox and volume do the work.

Limits, stated plainly:
- The collision body is the convex hull, which discards the bowl's concavity. No convex
  decomposition (CoACD) is installed; adding it is a new dependency and needs a decision.
- The settle test is weak on its own: any convex hull settles. The first settle run failed the true
  hull as well, because MuJoCo re-aligns meshes to their inertia axes (my tilt measure read a
  principal axis) and because peak penetration (about 6 mm for both hulls) is a drop-impact
  transient. I fixed the tilt measure and switched to resting penetration after seeing that the
  control also failed; peak values are kept in the report.
- One object, one scene, one seed. Mass is read from the simulator, not estimated.

## Wine-rack planning test (2026-11-04, `plan_rack.py`)

Scene `libero_goal_swap` task 8, seed 51; incident from `dev/curobo/README.md`. The logged contact
point (0.477, -0.175, 0.237) in the robot base frame lies inside the rack's true box. Goal: the
gripper at that point, pointing down (not the logged orientation). Start: IK pose at a height above
the contact. Same planner, four worlds. Single-frame baseline: ASPIRE's own sparse-voxel filter,
robot carve (5 cm) and voxel mesh, on the orbit frame with the most rack points (favours the
baseline). The fused mesh has the home-pose robot carved out once.

| Start above contact | World | Goal at contact | Free-space goal |
|---|---|---|---|
| 0.15 m | blind (no obstacle) | plans, ends inside rack | plans |
| 0.15 m | fused mesh | blocked | plans |
| 0.15 m | single frame, carved | blocked | plans |
| 0.15 m | single frame, uncarved | blocked | plans |
| 0.03 m | blind | plans, ends inside rack | plans |
| 0.03 m | fused mesh | blocked | blocked (start rejected) |
| 0.03 m | **single frame, carved** | **plans, ends inside rack** | plans |
| 0.03 m | single frame, uncarved | blocked | plans |
| 0.06 / 0.09 / 0.12 m | fused mesh | blocked | blocked (start rejected) |
| 0.06 / 0.09 / 0.12 m | single frame, carved or not | blocked | plans |

What this supports:
- **The carve bug reproduces.** With the start 3 cm from the contact, the carve removes 629 rack
  points (39,438 to 38,809) and the planner then plans the gripper into the rack. The uncarved
  cloud and the fused mesh do not.
- **The fused mesh is not affected by the carve**, by construction (robot removed once at scan time).
- Beyond 3 cm the carve removes no rack points, so it does not change the result.

What it does not support:
- The fused mesh is stricter than the single frame: it rejects starts 3 to 12 cm above the contact
  that the single frame accepts. I did not check in MuJoCo whether those starts truly collide, so I
  cannot say whether the fused mesh is correct there or over-conservative (5 mm voxels, truncation
  band, or leftover robot geometry are candidate causes). Until that is checked, "fused plans
  correctly where the single frame fails" is not shown: at 3 cm the fused world refuses to plan at
  all.
- One scene, one seed, hand-picked goal orientation, no execution in simulation.

## Correction to the earlier parity result

`plan_esdf.backproject_frame` applied the OpenGL flip a second time and mis-projected the
single-frame cloud (0 points on the rack in all 16 frames; the correct projection gives 1,900 to
17,500). The single-frame baseline in "Planning against the fused mesh" above used that wrong cloud,
so its 0.55 s versus 2.62 s comparison is not a valid baseline. The function is fixed; that
comparison has not been re-run.

## Honest caveats

- The original orbit scan (`scan_orbit.py`, `agentview`) is a **virtual camera teleport**, not
  robot motion. `scan_arm.py` fixes this for `robot0_eye_in_hand` but only sweeps one joint over a
  modest range so far; a fuller scan (more joints, a real look-at trajectory via IK) is still open.
- Coverage is table-top only: a single orbit at roughly table height never observes the scene from
  below or very close up, so most of the configured 2m x 2m x 1.5m extent is unobserved/far-field in
  the ESDF.
- Resolution is coarse (`voxel_size=0.01`, 16 views, no color blending pass) — expect a sharper
  reconstruction with more views and a finer voxel size, at a GPU time cost not yet measured.
- No LLM/Muse tokens involved; cost is pure GPU time (untimed so far, order of a minute or two for
  16 frames including first-run Warp kernel compilation).

## Where this goes next

1. Ground-truth the near starts in MuJoCo (do those arm poses touch the rack?) to decide whether the
   fused mesh is over-conservative; re-run the free-space parity comparison with the fixed baseline.
2. Online mapping: integrate wrist-camera frames during a rollout and feed the ESDF to the planner
   each replan, with the robot masked per frame. Not built. Landing it in the rollout or planning
   path of `src/ants/adversary/` needs Daniel first.
3. Gate: convex decomposition, more objects, a settle case that can fail, and per-object
   segmentation of the scene mesh. Real2sim from the hurobo clips is in
   the local dev note `real2sim-research.md` (research only, nothing run; not in the repo).

## Why this isn't `dev/curobo/`

`dev/curobo/` is about *why cuRobo's planner fails* against a raw point-cloud obstacle (the wine
rack case). This probe is a different mechanism entirely: a persistent fused volumetric map
(TSDF/ESDF via `curobo.perception.Mapper`) as a *replacement* obstacle representation, not a
diagnosis of the point-cloud path.
