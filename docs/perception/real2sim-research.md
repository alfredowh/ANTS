# Real2sim research: scan an environment into a digital twin

Date 2026-11-04. Research only, no runs. "Verified" = read in the source or in this repo today;
"unverified" = inference or search snippet. Question: can we scan the whole LIBERO scene, or the
user's recorded table (`hurobo/data/raw/setup_01/table_scene_zoom_0*.mp4`), into a twin where other
objects can be placed, and what can we reuse?

## 1. Key finding: most of the capture side already exists in hurobo

`hurobo/` (the user's phone-video project, separate repo checkout) already implements the pipeline
that NVIDIA's page describes in outline. Do not rebuild it.

| Stage | Already in repo | Status (from `hurobo/docs/*.md`) |
|---|---|---|
| Orbit video to posed frames | `hurobo/src/hurobo/scan.py` (pycolmap SfM) | run on real clips; COLMAP defaults registered 39 of 120 frames on one clip, so SIFT threshold is lowered (design log) |
| Metric scale and table frame | ChArUco board, `scan.py --charuco` | worked on 2 real clips, corner RMS 0.5 to 1.1 mm (D-009); failed on 4 of 6 table clips (board too small / tablet colours) |
| Gaussian splat | `scan.py` (gsplat), `splat.py` (DISCOVERSE `gaussian_renderer` loader, depth-composited with the mesh robot) | visual only; "did not feed the policy" |
| Object cut-out | `scan_crop.py` (RANSAC floor plane, cluster on it) | needs hand-measured cylinders (`--object X Y R H`) |
| Collision body | `collider.py`: splat depth, Open3D TSDF, CoACD convex pieces, patched copy of LIBERO asset | built; mass conserved, not estimated |
| Hand-modelled room | `hurobo/outputs/setup_01_room/` (Blender `build.py`, `scene.glb`) | path A, not a scan |
| Gap analysis vs NVIDIA | `hurobo/outputs/setup_01_room/nvidia_compare.md` (gaps G1 to G9, phases 0 to 4) | written 2026-11-03 by another agent session; its "sim-ready gate" is its Phase 0 |

The "sim-ready gate" in that file is a Blender/hurobo-side plan, not something in `src/ants/`.

## 2. The three external sources (stage by stage)

### 2.1 NVIDIA Video to Data (V2D)
Sources: [site](https://nvidia-isaac.github.io/video_to_data/),
[reconstruction docs](https://nvidia-isaac.github.io/video_to_data/reconstruction/),
[repo](https://github.com/nvidia-isaac/video_to_data) (README and LICENSE read).

| Stage | What it does (verified) |
|---|---|
| Video ingestion agent | LangGraph workflow: action clips, scene graph, SigLIP-2 frame embeddings, queryable database |
| Reconstruction, ego path | Grounding DINO finds the prompted object, SAM2 tracks the mask, SAM3D builds a textured mesh, FoundationPose gives a smoothed 6D pose trajectory; hand via HaMeR/DynHaMR; MoGe depth gives metric scale; EKF smoothing; optional gravity alignment and gsplat trajectory refinement |
| Reconstruction, multi-view | calibrated multi-view rosbag, stereo depth, human and object segmentation, object pose tracking, SMPL body; produces the FORM-HOI dataset |
| Object mesh | BundleSDF (textured mesh from a multi-view scan), SAM3D (single-image mesh, silhouette scale), or a given mesh |
| Robotic grounding | retarget human motion, train RL in Isaac Lab (RSL-RL PPO), deploy; docs "coming soon" |

What it is not: a whole-static-scene reconstructor. It reconstructs hand, body and the manipulated
object trajectories. Its page does not mention a settle test or watertight check (not found in the
pages read; `nvidia_compare.md` cites a `simready` validator and drop test, which I did not
re-verify).

| Item | Fact |
|---|---|
| License | dual: documentation CC-BY-4.0, source Apache-2.0 (LICENSE file head) |
| GPU | full workflow runs on one RTX A6000 48 GB; verified on L40/L40S; Blackwell `sm_120` unsupported for TensorRT/cuVSLAM (README). Our RTX A5500 16 GB: not stated, treat as unlikely for the full chain (unverified) |
| Packaging | Docker per module, NVIDIA Container Toolkit; driver 580.x recommended for robotic grounding (our hurobo notes pin driver 560.35; unverified whether it changed) |

### 2.2 3D World Simulator (Wang et al.)
Sources: [project page](https://jwang771.github.io/3dworldsimulator/),
[repo](https://github.com/jwang771/3d-world-simulator) (README read).

| Stage | Fact |
|---|---|
| What it is | learned action-conditioned world model: hybrid particle-voxel autoencoder plus 3D latent dynamics (3D U-Net), predicts 3D Gaussians, renders any view, adds tactile |
| Input | colored point clouds from several calibrated stereo cameras (3 static plus 2 wrist in their setup), one trained model per task family |
| Scene handling | room is a separate 3D Gaussian splat of a room scan, robot is a Gaussian splat with a kinematic model, both swappable |
| Code | README says data, checkpoints and inference code are "coming soon"; training scripts only; GitHub reports no license (None). Runs 50+ FPS on an RTX 5090 (page) |

Not a scene-capture or physics tool: it replaces the simulator with a learned model that needs
robot interaction data. Reusable idea only: keep room, robot and manipulated objects as separate
assets. Do not plan on its code.

### 2.3 nvblox and cuRobo (local)
| Item | Fact |
|---|---|
| cuRobo | `ASPIRE/third_party/curobo/LICENSE` is Apache-2.0 (verified); v0.8 dev, Warp backend |
| `curobo.perception` | `Mapper` (TSDF, ESDF, mesh extraction, renders), used in `tools/mapper_probe/` (see [scene-reconstruction-probe.md](scene-reconstruction-probe.md)) |
| nvblox | [repo](https://github.com/nvidia-isaac/nvblox): GPU TSDF/ESDF library; GitHub license field is NOASSERTION, a search snippet says Apache-2.0 (unverified, read its LICENSE before copying code); cuRobo's Mapper already covers the same job without a separate install |

## 3. What we can reuse, by need

| Need | Reuse | Missing |
|---|---|---|
| Static scene from phone video | hurobo `scan.py`, ChArUco scale, S24 intrinsics (`hurobo/data/camera_intrinsics_s24.npz`, 1920x1080, with distortion) | reliable registration on the table clips; board visibility |
| Metric surface of the whole scene | splat to TSDF (`collider.py`), or fuse rendered depth with `curobo.perception.Mapper` | quality of splat geometry is unmeasured; floaters |
| Per-object segmentation | `scan_crop.py` cylinders (manual); V2D uses Grounding DINO + SAM2 (not installed here; SAM3 exists in `ASPIRE/third_party/sam3`) | prompt-based masks lifted to 3D |
| Sim-ready gate | drop/settle test in LIBERO/MuJoCo, `trimesh` watertight check, CoACD (already in hurobo), true mass/inertia for sim-sourced objects | gate code, thresholds, `simready_report.json` (plan in `nvidia_compare.md` Phase 0) |
| Inserting new objects | LIBERO object assets plus hurobo patched asset folder | importing a scanned table scene as a MuJoCo scene (static collision mesh plus background splat) |
| MuJoCo/LIBERO import | hurobo `sim.py`, `splat.py` bodies, `collider.py` XML patch; Blender `scene.glb` exists for path A | a LIBERO task defined on the scanned room (BDDL plus XML) |

## 4. Minimal path for the table_scene clips (RTX A5500 16 GB)

Clips (verified with ffprobe): three 1920x1080 files, about 29.97 fps, 801 to 938 frames
(26.8 to 31.4 s), 57 to 67 MB. Hand measurements and board geometry: `hurobo/data/raw/setup_01/measurements.yaml`.
The design log says the board filled a few hundred pixels and all 17 markers were found in
`table_scene_zoom_02` and `_03` (D-009 area); `_01` is not mentioned there.

| Step | Action | Effort (my estimate) | Risk |
|---|---|---|---|
| 1 | Run hurobo's existing scan with `--charuco` on `_02`, `_03`; read the printed RMS and registered fraction | 0.5 day | COLMAP registration; scale only over part of the table |
| 2 | Fuse splat depth into a TSDF mesh (hurobo `collider.py`) and into `curobo.perception.Mapper`; compare with the orbit mesh from `tools/mapper_probe/` | 1 day | splat depth is noisy near edges |
| 3 | Sim-ready gate on the extracted table and each cut-out object: watertight, convex pieces, mass from material density or known size, MuJoCo drop and settle test with fail thresholds | 1 to 2 days | thresholds are ours to choose; log them |
| 4 | Build a MuJoCo/LIBERO scene from the table mesh plus background splat for render, then place LIBERO objects on it | 2 to 3 days | new BDDL/XML plumbing, no LIBERO task exists on this room |
| 5 | Run one ANTS policy rollout in the twin and compare with LIBERO | 1 day | only a visual and kinematic check; dynamics are not calibrated |

Out of scope for this path: V2D full pipeline (48 GB GPU, Docker stack, hand-object focus),
the 3D World Simulator (no code), Isaac Sim migration.

## 5. nvblox / cuRobo: have vs missing

| Have | Missing |
|---|---|
| TSDF, ESDF, mesh from posed RGB-D (works on the 112-frame sim scan, 122,122 vertices) | real RGB-D: phone clips have no depth, so depth must come from splat render, MoGe-like monocular depth, or stereo |
| ESDF as a collision world for `MotionPlanner` (parity check passed) | the discriminating wine-rack plan test, online incremental updates, robot self-mask |
| Persistent map independent of the robot pose | physical properties, per-object segmentation, articulation, any dynamics |

## 6. Recommendation

1. Treat the hurobo scan chain as the capture stack; wire its outputs into ANTS rather than
   adopting V2D or the 3D World Simulator.
2. Build the sim-ready gate first (step 3), because every later twin object depends on it.
3. Ownership: capture and gate stay in `tools/` or `synthesizer/`/`evalkit/` (Alfredo). Anything
   that lands in `src/ants/adversary/` or `orchestrator/` needs Daniel (AGENTS.md, D3, D17).
4. Numbers for any write-up must come from logged runs; none of the timings above are measured.

## Sources
- V2D: https://nvidia-isaac.github.io/video_to_data/ , https://nvidia-isaac.github.io/video_to_data/reconstruction/ , https://github.com/nvidia-isaac/video_to_data
- 3D World Simulator: https://jwang771.github.io/3dworldsimulator/ , https://github.com/jwang771/3d-world-simulator
- nvblox: https://github.com/nvidia-isaac/nvblox
- Repo: `hurobo/docs/real2sim_options.md`, `hurobo/docs/scanning_guide.md`, `hurobo/docs/design_decisions.md`, `hurobo/REAL2SIM_IDEAS.md`, `hurobo/outputs/setup_01_room/nvidia_compare.md`
