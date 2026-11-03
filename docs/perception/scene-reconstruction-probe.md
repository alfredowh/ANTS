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

## Where this goes next (not yet built)

1. **Real arm-driven scan**: replace the virtual orbit with the Franka's `robot0_eye_in_hand`
   camera, driven through the same waypoints via `move_to_pose` (reuses existing `cap_harness`
   motion, no new motion code).
2. **Wire into collision-aware planning**: feed `mapper.compute_esdf()` into cuRobo's
   `plan_motion`/`ss_cur` path as the obstacle representation, replacing today's single-frame point
   cloud (see `dev/curobo/` for the known point-cloud-obstacle weak spot, the wine-rack case). This
   step touches System 2's package (`src/ants/adversary/`, owned by Daniel per `AGENTS.md`) — flag
   it with him before landing it there; this doc only covers the standalone probe.

## Why this isn't `dev/curobo/`

`dev/curobo/` is about *why cuRobo's planner fails* against a raw point-cloud obstacle (the wine
rack case). This probe is a different mechanism entirely: a persistent fused volumetric map
(TSDF/ESDF via `curobo.perception.Mapper`) as a *replacement* obstacle representation, not a
diagnosis of the point-cloud path.
