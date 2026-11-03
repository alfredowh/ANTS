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

## Honest caveats

- The scan is a **virtual orbiting camera** (the `agentview` MuJoCo camera body is teleported
  through waypoints each frame), not yet the Franka's own eye-in-hand camera driven by
  `move_to_pose`. That is the next step.
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
