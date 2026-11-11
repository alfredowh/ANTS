# Handoff for Muse Code only: real2sim / 3D reconstruction (2026-11-04, ~05:15)

For Muse continuing this in `/home/eeschner/alfredo/workspace/ANTS`, branch `synthesizer`.
User is asleep and asked for autonomous work. Read `AGENTS.md` first. Do not touch
`src/ants/adversary/` or `src/ants/orchestrator/` without Daniel. hurobo is read-only:
outputs go to `ANTS/data/`, never into `hurobo/`. Push with `git -c http.proxy= push`
(global proxy is stale, per `HANDOFF.md` (dev note, not in repo) §2).

## What the user wants (final goal)

Turn any video of their room (e.g. `hurobo/data/raw/setup_01/table_scene_zoom_0*.mp4`)
into a simulation scene / digital twin: scanned room (incl. background) as the static
environment, LIBERO asset objects placed in it, and the sim Franka (URDF) placed in it,
so ANTS policies can run in the twin. Kinematic/visual only for now (no dynamics
calibration yet). Research anchors: Polaris (https://polaris-evals.github.io/),
NVIDIA Video-to-Data (https://nvidia-isaac.github.io/video_to_data/), nvblox, ASPIRE,
cuRobo, 3D World Simulator (https://jwang771.github.io/3dworldsimulator/).

## Already committed (this branch, pushed in this handoff commit)

- `9fb5041` — sim-ready gate + wine-rack planning probe for the cuRobo Mapper
  reconstruction: `tools/mapper_probe/{gate_truth,gate_extract,gate_settle,plan_rack}.py`,
  multi-dir fusion at 5 mm, `docs/perception/{real2sim-research,scene-reconstruction-probe}.md`.
- `2ed62f8` — corrections to `docs/perception/real2sim-research.md`.
- Probe summary (`docs/perception/scene-reconstruction-probe.md`): orbit scan 23,441 verts,
  arm scan, look-at scan, ESDF planning, sim-ready gate with failing negative control.

## The overnight phone scan: SUCCEEDED at SfM, FAILED at splat — read this first

Command run by the previous session (output `data/runs/real2sim/setup_01/`, log `scan.log`):

- COLMAP SfM: **registered 120/120 images**, 1 model.
- ChArUco alignment: **scale 0.2218 m/unit, corner RMS 0.8 mm** — metric scale is solved.
  This contradicts the older fear in `real2sim-research.md` that registration would fail.
- Then gsplat training crashed, in order:
  1. `ImportError: cannot import name 'csrc' from 'gsplat'` (no prebuilt extension), then
  2. JIT fallback: `TypeError: _jit_compile() missing 2 required positional arguments`
     (torch/gsplat version mismatch in `hurobo/.venv`), then the visible symptom
  3. `RuntimeError: Ninja is required to load C++ extensions`.
- **Installing ninja alone will NOT fix it** — error 2 is upstream of error 3. Fix the
  torch/gsplat pair in hurobo's env, or bypass gsplat (see next section). Sparse COLMAP
  output is preserved: `data/runs/real2sim/setup_01/work/setup01/colmap/sparse/0/`
  (`cameras.bin, images.bin, points3D.bin`) + 120 extracted frames in `.../images/`.
- Table measurements: `hurobo/data/raw/setup_01/measurements.yaml` (table 1.445×0.60 m,
  centre [0.6925, -0.28], ChArUco square 0.037 m, bowl Ø0.138×0.067 m, plate Ø0.255×0.028 m).
  Real→LIBERO scale: bowl ≈1.24–1.26, plate ≈1.86 wide / 1.65 tall (`dev/curobo/README.md`
  logs bowl 1.227, plate 1.855). Known bug to pin: scaled-scene on-top tolerance is scaled
  by the bowl factor, not the plate's.

## Agreed plan from the last user conversation (do not re-ask)

1. Robot base: no real robot exists; copy LIBERO's table→base transform into the scanned
   table frame (simplest), or grid-search base poses with cuRobo IK reachability (better).
2. Task: LIBERO bowl+plate assets, scaled to real sizes, placed from marker poses,
   existing `On(bowl, plate)` predicate.
3. Dynamics: kinematic + visual only.
4. Sim-to-real measurement, layered: A) geometry overlay from calibrated camera
   (pose error mm, mask overlap); B) passive object physics (mass/friction, ~20 drop/slide
   trials, calibrate on some, report held-out); C) robot contact — impossible, no hardware.
   Level B friction range should bound the ANTS adversary's physics severity.

## What Muse built overnight after this handoff was requested

See `docs/perception/real2sim-overnight-2026-11-04.md` (research: Polaris, Video-to-Data,
3D World Simulator, nvblox, cuRobo, ASPIRE — what is reusable and what is not) and
`tools/real2sim/` (scan→sim-ready twin builder that does NOT depend on gsplat: COLMAP
sparse cloud + measured table box → MuJoCo scene with LIBERO assets + Franka URDF).
If that doc is absent, Muse was cut off; start from "Next steps" below.

## Next steps (in order)

1. Fix or bypass gsplat (torch/gsplat versions in `hurobo/.venv`; 10-min timebox, then bypass).
2. Build the twin from COLMAP sparse + measurements (do not wait for a pretty splat).
3. Render twin from the calibrated camera, overlay on real frames (Level A numbers).
4. Only then retry splat for background visuals (`--background` splat is cosmetic).
5. Fix/pin the scaled on-top tolerance before trusting any scaled-scene gate result.

## Traps

- Never commit `data/` (git-ignored), `.env`, or ASPIRE submodule changes.
- Uncommitted files in this checkout (`src/ants/studio/console*`, `scene2d/3d*`,
  `dashboard*`, `docs/studio/`) are the live-console work — separate topic, see
  `live-console-handoff.md` (dev note, not in repo). They are NOT part of this commit.
- Seeds: always `--init-mode seeded`. GPU: don't run two sims + SAM3 at once.
