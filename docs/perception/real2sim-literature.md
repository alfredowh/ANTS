# Real2sim literature, by category (2026-11-06)

Research notes for three goals: (A) a real2sim **simulator** good enough for PolaRiS-style policy
evaluation, (B) a **realtime digital twin** (simulator first, then a real RGB or RGB-D camera), and
(C) **cuRobo trajectory planning**, shown and measurably improved. Earlier notes:
[real2sim-research.md](real2sim-research.md), [real2sim-overnight-2026-11-04.md](real2sim-overnight-2026-11-04.md),
[scene-reconstruction-probe.md](scene-reconstruction-probe.md), [../studio/digital-twin-feasibility.md](../studio/digital-twin-feasibility.md).

**Method.** Citation graph from the anchor works (cuRobo, ASPIRE, PolaRiS, and the parts of NVIDIA
Video-to-Data: FoundationPose, BundleSDF, MoGe, FoundationStereo; plus nvblox, SplatSim,
Real2Render2Real, RoboGSim). The top 200 citers of each, ranked by citation count from OpenAlex,
give 730 works, tagged by keyword. That was followed by targeted web searches for 2025–2026 work that
OpenAlex indexes poorly. OpenAlex counts lag for recent arXiv papers, so treat counts as relative.
V2D has no paper, so its parts stand in for it.
**Evidence tags:** *abstract* = read the abstract or project summary only; *repo* = checked in this
checkout; *claim* = the authors' own number, not reproduced here.

## Local facts that change the reading

- `ASPIRE/third_party/curobo` is at `v0.8.0-36` (*repo*). cuRoboV2 tells v1 users to pin `v0.7.8`,
  so we already run the **cuRoboV2** codebase: B-spline optimisation and the depth-fused TSDF/ESDF
  `Mapper` (the one `tools/mapper_probe/` used). nvblox is not needed as a separate install.
- GPUs: RTX A5500 16 GB (this laptop), plus an RTX 6000 Pro and a 32 GB card for heavy steps and
  possible fine-tuning. Isaac Sim is available.

## A. Real2sim simulator (policy evaluation)

| Work | What it gives us | Tag |
|---|---|---|
| **PolaRiS** (arXiv 2512.16881) | Phone scan plus ChArUco → 2DGS visuals, extracted collision meshes, generated objects, robot splat; sim–real correlation protocol. Already our template | abstract, earlier notes |
| **YUBI-Real2Sim** (arXiv 2610.17521) | 3DGS scene placed **in MuJoCo** for closed-loop evaluation; reproduces the real policy ranking in 8 of 9 comparisons; tests whether novel-view quality predicts ranking reliability (task-dependent, so only partly) | abstract, claim |
| **ReVeal** (arXiv 2609.23910) | Fidelity metrics for a reconstructed scene: NVMF (novel-view mesh fidelity), APGF (planar geometry); PGSR-D adds monocular depth supervision; higher fidelity gives better real–sim agreement (PGSR-D > PGSR > 2DGS) | abstract, claim |
| **A Practical Recipe for Sim-and-Real Correlation in VLA Evaluation** (arXiv 2606.10366) | 11,800 sim and 1,115 real rollouts: ranking, correlation, failure patterns under perturbations. Directly relevant to "does an attack in the twin mean anything" | abstract |
| **DISCOVERSE** (arXiv 2507.21981, IROS 2025) | 3DGS renderer + **MuJoCo** physics + ROS2; real captures, AIGC and assets turned into 3DGS + mesh. hurobo already uses its `gaussian_renderer` (*repo*) | abstract |
| **NVIDIA NuRec / 3DGUT** (nv-tlabs/3dgrut) | 3DGUT trained on COLMAP → USDZ → Isaac Sim 5+/6; handles distorted cameras; collider proxy mesh added separately. The Isaac route for splat visuals | docs/blog |
| SplatSim (23 cites), RoboGSim, Real2Render2Real, GS-Playground, Gaussian2Sim, Novel Demonstration Generation with GS | Splat rendering over a physics sim for data or evaluation; mostly PyBullet or Isaac, rigid objects | citation graph |
| Real-to-Sim Policy Eval with GS soft-body (arXiv 2511.04665), **PhysTwin** (ICCV 2025) | Deformables: spring-mass + GS from sparse multi-view video. Out of scope unless tasks become deformable | abstract |
| **Video2Sim2Real** (arXiv 2606.08828) | Sim-ready twin from one human video via SAM 3 + SAM 3D + HaMeR + CoTracker. Closest to our "show once" story on the scene side | abstract |
| **SAM 3D Objects** (Meta, 2025-11) | One image + mask → textured mesh, splat and pose. A Meta model (fits the hackathon story); geometry is generative, so scale must be fixed with our ChArUco or depth | summaries |
| BundleSDF (167), Scalable Real2Sim (physics-aware assets from pick-and-place), DRAWER (articulation) | Measured object meshes; physical parameters from robot interaction; articulated scenes | citation graph |
| CAST (single-RGB component-aligned scene) | Whole scene from one image; useful only as a generative fallback | citation graph |

**Reading for ANTS.** The field has settled on one decomposition: **splat for appearance, a separate
measured mesh for collision, assets for manipulated objects, and an explicit fidelity gate.** Two 2026
papers add what PolaRiS lacked: fidelity metrics that predict real–sim agreement (ReVeal), and a MuJoCo
version (YUBI). Without a real robot we cannot measure the real–sim correlation itself. We can
measure reconstruction fidelity and passive physics.

## B. Realtime digital twin (simulator first, then RGB / RGB-D)

| Work | What it gives us | Tag |
|---|---|---|
| **Real-is-Sim** (arXiv 2504.03597, ICRA 2026) | Twin always in the loop at 60 Hz: policy acts on the sim, real robot follows, camera images correct the sim. Built on **Embodied Gaussians** (GS visuals + particle physics, corrected by render-vs-image) | abstract |
| **GaussTwin** (arXiv 2603.05108) | Realtime twin: position-based dynamics + Cosserat rods + GS for rendering and visual correction; rigid and deformable | abstract |
| **FoundationPose** (367 cites) | Model-based or model-free 6D pose estimation and tracking, RGB-D. The V2D workhorse | citation graph |
| RGBTrack (depth-free FoundationPose-style tracking), HIPPo, UA-Pose, InstantPose | RGB-only or model-free pose; the RGB path of the twin | citation graph |
| **POGS** (TRI, 2025) | Persistent object splat, tracks objects moved by people and robots from one stereo camera after one scan | abstract |
| 6DOPE-GS | Joint online pose + GS reconstruction, 3.5 Hz (claim) | abstract |
| **nvblox** (45) / **cuRoboV2 Mapper** (arXiv 2603.05493) | Incremental TSDF/ESDF from depth with a decaying layer for dynamic obstacles. V2 claims 2–10× faster ESDF than nvblox, 1.69 ms full ESDF at 10 mm, dense distances (nvblox only in occupied blocks) | docs, claim |
| Lost & Found (dynamic 3D scene graphs from egocentric changes) | Object-level change tracking, keeping a scene graph current | citation graph |
| **Robo3R** (arXiv 2602.10101) | Feed-forward metric geometry from RGB + robot state in realtime, claimed better than depth sensors | abstract, claim |
| VGGT, MapAnything, Depth Anything 3, MoGe(-2/-3), FoundationStereo, Fast-FoundationStereo | RGB → metric depth and poses: mono, stereo or multi-view. The depth front-end when there is no RGB-D | citation graph |

**Reading for ANTS.** Two patterns: (1) **tracking**: perception estimates object poses and the twin
copies them (FoundationPose / POGS); (2) **correction**: the twin simulates forward and images
correct it (Real-is-Sim, GaussTwin). Pattern 1 is the right first step. Pattern 2 needs a
differentiable or particle renderer. In simulator-first mode, LIBERO gives the **ground truth** every
twin estimate can be scored against, which no real setup offers.

## C. cuRobo trajectory planning (show + improve)

| Work | What it gives us | Tag |
|---|---|---|
| **cuRoboV2** (arXiv 2603.05493) | Depth-fused distance fields, B-spline optimisation, dynamics-aware; up to 99% collision recall (claim). We already have this code | abstract, repo |
| cuRobo docs: depth camera + nvblox, MPPI reactive mode | Reactive MPC on a live ESDF; docs call the reactive mode experimental, with lower success | docs |
| Parallel MPPI with gradient-velocity SDF cost (38 cites) | Realtime dynamic obstacle avoidance on an SDF; the next step after one-shot planning | citation graph |
| **SPLANNING** (risk-aware trajectory optimisation in a normalised Gaussian splat), Splat-Nav | Plan directly against splats with a collision-probability bound; real manipulator tested | abstract |
| **RGB-Only Reconstruction of Tabletop Scenes for Collision-Free Manipulator Control** (2023) | RGB-only reconstruction → cuRobo planning; the RGB path for C | citation graph |
| Collision-Affording Point Trees (CAPT), VAMP (motions in microseconds) | Plan against raw point clouds without voxelising; an alternative to the carve + voxel mesh that caused the wine-rack bug | citation graph |
| Conformalized reachable sets with spheres | Calibrated safety margins for sphere models; principled carve or attach margins | citation graph |
| ORB (operating-room bot) | cuRobo + nvblox TSDF/ESDF from RGB-D in a real deployment, with plan preemption on grasp failure | abstract |
| Motion Planning Diffusion, DiffusionSeeder, cascaded diffusion | Learned seeds for the optimiser; only if planning_failed remains high after the world is fixed | citation graph |
| PyRoki (already used via ASPIRE) | Our current IK and default planner | repo |

**Reading for ANTS.** Our logged failures are world-model failures: the carve erased the rack, the
held-bowl spheres were in the wrong frame, and ghost points blocked goals. They are not optimiser
failures. The literature agrees: fix the **world representation** first (segmentation-based robot
removal, a persistent fused map with a dynamic layer, tracked attached objects, calibrated margins),
and only then consider learned seeds or MPPI.

## Cross-category overlap (input to the plan)

The same modules appear in all three categories. Where reuse costs quality, keep two of them:

| Module | A simulator | B live twin | C planning | Reuse or keep two |
|---|---|---|---|---|
| Capture + calibration (intrinsics, ChArUco, camera pose) | yes | yes | yes | one |
| Depth front-end (RGB-D / stereo / mono / feed-forward multi-view) | offline | online | online | one interface, several back-ends; pick per source by measured error |
| Segmentation (SAM 3, robot self-mask) | yes | yes | yes (robot removal) | one |
| Fused TSDF/ESDF (cuRoboV2 Mapper) | collision mesh | incremental map | planner world | one code path, **two map instances** (static high-res prior, dynamic decaying layer) |
| Splat / 2DGS / PGSR | visuals | visual correction (later) | optional (SPLANNING) | separate from collision geometry: splat geometry is worse (ReVeal ordering) |
| Object assets + sim-ready gate | yes | identities for tracking | attached objects | one |
| 6D pose tracking | init poses | core | attached / moved objects | one; RGB-D and RGB back-ends |
| Scene state (objects, poses, robot q, time, provenance) | export source | core | world source | one, with SIM TRUTH / PLANNER BELIEF / RECONSTRUCTED badges |
| Exporters (MJCF, USD) | yes | sim-first mirror | — | MJCF first, USD second |
| Fidelity + agreement metrics | yes | twin vs sim truth | refusal FN/FP, path contacts | one evaluation kit |

## Sources

- PolaRiS https://arxiv.org/abs/2512.16881 · YUBI-Real2Sim https://arxiv.org/abs/2610.17521 · ReVeal https://arxiv.org/pdf/2609.23910 · Practical Recipe https://arxiv.org/abs/2606.10366
- DISCOVERSE https://arxiv.org/abs/2507.21981 · NuRec https://developer.nvidia.com/blog/how-to-instantly-render-real-world-scenes-in-interactive-simulation · Isaac Sim 6.0 NuRec https://radiancefields.com/nvidia-s-isaac-sim-6.0-ships-with-nurec-gaussian-splatting
- Real-is-Sim https://arxiv.org/abs/2504.03597 · GaussTwin https://arxiv.org/abs/2603.05108 · POGS https://www.tri.global/research/persistent-object-gaussian-splat-pogs-tracking-human-and-robot-manipulation-irregularly · 6DOPE-GS https://arxiv.org/pdf/2412.01543
- cuRoboV2 https://arxiv.org/abs/2603.05493 · cuRobo depth camera https://curobo.org/get_started/2d_nvblox_demo.html · Isaac Sim cuRobo/cuMotion https://docs.isaacsim.omniverse.nvidia.com/6.0.0/manipulators/manipulators_curobo.html · ORB https://arxiv.org/pdf/2509.15600
- SPLANNING https://roahmlab.github.io/splanning · Splat-Nav https://arxiv.org/abs/2403.02751 · Robo3R https://arxiv.org/abs/2602.10101
- PhysTwin https://arxiv.org/abs/2503.17973 · Video2Sim2Real https://arxiv.org/abs/2606.08828 · SAM 3D https://learnopencv.com/sam-3d/
- Citation graph: OpenAlex API, top-200 citers per anchor (FoundationPose W4402754209, BundleSDF W4386066287, nvblox W4401417366, cuRobo W4383172031/W4387995287, ASPIRE W7167029019, PolaRiS W7116303404, MoGe, FoundationStereo, SplatSim, R2R2R, RoboGSim)
