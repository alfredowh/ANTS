# Real2sim overnight run — 2026-11-04 (Muse, autonomous while user slept)

Goal: any video of the room → simulation scene with LIBERO objects + sim robot URDF.
Handoff: [real2sim-handoff-muse.md](real2sim-handoff-muse.md). Every step timeboxed to 10 min when stuck.

## TL;DR result

A sim-ready twin **was built and load-tested** from the real phone scan, without gsplat:
`tools/real2sim/build_twin.py` → `data/runs/real2sim/setup_01/twin/{twin.xml, bowl.obj, plate.obj, room_background.ply, twin_manifest.json}`.
MuJoCo (ASPIRE venv, mujoco 3.3.0) loads it, steps 200 steps, bowl/plate settle at z≈0.399/0.391 on the table.
It is kinematic/visual only, with starter object placements — not marker-registered, not dynamics-calibrated.

## 1. What Claude Code left (verified by re-reading logs, not trusting chat)

| Item | Evidence |
|---|---|
| COLMAP SfM on `table_scene_zoom_02/03` frames | `data/runs/real2sim/setup_01/scan.log`: **registered 120/120 images** |
| Metric scale | Same log: ChArUco scale **0.2218 m/unit, corner RMS 0.8 mm** |
| Splat training | **Crashed**: gsplat has no prebuilt `csrc`; JIT fallback hits torch `_jit_compile` signature mismatch; final symptom "Ninja is required". Installing ninja alone won't fix it |
| Committed 3D work | `9fb5041` (sim-ready gate, wine-rack probe), `2ed62f8` — were ahead 2, **pushed this run in `e1b38f2`** with the Muse handoff |

## 2. Research (what to reuse, what not)

| Source | What it is | Reuse for ANTS? |
|---|---|---|
| **PolaRiS** (polaris-evals.github.io, arXiv 2512.16881) | 2–5 min scan + ChArUco → 2DGS visuals, extracted collision meshes, TRELLIS-generated physics-ready objects, kinematics-aware robot splats; sim scores correlate with real (20 real / 50 sim rollouts) | **Closest match to our goal.** Copy its architecture (same ChArUco choice we already have), not necessarily its code. Its real↔sim correlation protocol is our Level A/B template |
| **NVIDIA Video-to-Data** | Hand/object trajectory reconstruction (GroundingDINO+SAM2+SAM3D+FoundationPose), not whole-scene | No (48 GB GPU, Docker stack, wrong problem). Borrow only: prompt-based object masks → 3D |
| **3D World Simulator** (jwang771.github.io/3dworldsimulator) | Learned action-conditioned world model, code "coming soon", no license | No code. Borrow idea: room / robot / objects as separate swappable assets — our twin already does this |
| **nvblox** | GPU TSDF/ESDF | Not needed separately: cuRobo's vendored Mapper already does TSDF/ESDF (proven in `tools/mapper_probe/`) |
| **cuRobo** (local, Apache-2.0) | Mapper + MotionPlanner; Franka URDF at `ASPIRE/third_party/curobo/.../franka_panda.urdf` | Yes — planner + URDF source. Caveat below |
| **ASPIRE / LIBERO-PRO** (local) | Bowl/plate meshes at `ASPIRE/third_party/LIBERO-PRO/libero/libero/assets/stable_scanned_objects/{akita_black_bowl,plate}/`, MuJoCo 3.3.0 in `.venv-libero` | Yes — twin uses these exact meshes, scaled bowl ×1.245, plate ×1.86 to real sizes from `hurobo/data/raw/setup_01/measurements.yaml` |

**Real2sim / digital-twin verdict:** the twin is *scene-as-asset + LIBERO objects + robot base placement*,
exactly PolaRiS's decomposition. Scanning "whole LIBERO" is unnecessary — LIBERO scenes are already
sim-native; scan only the real room, drop LIBERO assets in. Background: sparse COLMAP cloud now
(`room_background.ply`, 30,086 points), Gaussian splat later once gsplat is fixed (cosmetic only).

## 3. What was built (step B, "figure it out yourself")

`tools/real2sim/build_twin.py` (stdlib only — ANTS venv has no numpy):

1. Parses COLMAP `points3D.bin` (fixed two parser bugs found by running it: RGB is 3 bytes, track stride 8 B).
2. Applies ChArUco scale 0.2218 m/unit; RANSAC-fits the dominant plane (4,492/6,000 inliers on subsample).
   Honest limit: fitted normal is diagonal, i.e. the dominant plane is not cleanly the table top —
   table *size* comes from measurements (1.445×0.60 m), plane only anchors height. ChArUco-frame
   registration is the next fix, not done tonight.
3. Emits MuJoCo scene: floor, measured table box collider, scaled LIBERO bowl+plate with freejoints,
   robot-base placeholder at (-0.55, 0, 0.40), full room cloud as background PLY.

**Verification (observed):** `MjModel.from_xml_path(twin.xml)` → 5 bodies, 4 geoms; after 200 steps
bowl z=0.399, plate z=0.391 (resting, no explosion/sinking). Franka URDF does **not** load directly in
MuJoCo (it resolves `meshes/collision/link0.obj` to the URDF dir root — a known MuJoCo URDF mesh-path
quirk); load it via cuRobo/robosuite as the rest of ANTS already does. Recorded, not hacked around.

## 4. Not done / next (in order)

1. Register twin into the ChArUco frame (use `images.bin` poses) so object placement is measured, not starter.
2. Fix gsplat (pin matching torch/gsplat in hurobo env; ninja alone insufficient) → background splat.
3. Level A overlay: render twin from calibrated camera vs real frames (pose error mm, mask IoU).
4. Place robot with cuRobo IK reachability grid instead of the fixed base; pin the scaled on-top tolerance bug.
5. Level B physics trials (mass/friction) → bound adversary severity. Level C impossible (no real arm).

## 5. Commits this run

- `e1b38f2` — Muse handoff + pushes Claude Code's `9fb5041`, `2ed62f8`.
- This doc + `tools/real2sim/build_twin.py` + test (see git log on `synthesizer`).
