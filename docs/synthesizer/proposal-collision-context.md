# Proposal: tell the generator why the arm is stuck (collision-grounded failure context)

Status: proposal, 2026-11-01. Nothing here is built or run yet. Numbers marked **[run]** come from the logged exp03 run (`data/runs/exp03_explain`); everything else is a design estimate or a literature claim and is labelled as such.

## 1. Goal

When a generated program stalls, the repair prompt today says only `status: timeout, final_errors: {}, steps_executed: 141`. The model then guesses the cause (exp03 clip 233859: "descent stalled at z≈0.206 m", "bowl slid 56 mm"). We want the next attempt to receive:

1. **Whether** the arm was physically blocked (and not at a joint limit, an IK miss or a controller limit).
2. **Which part of the arm** (finger pad, hand, link 7 …) touched **which object, in which region** (bowl outer wall, bowl rim, plate rim, table …).
3. A **simplified collision geometry** of the other objects, small enough to fit in a prompt.

Split the problem in three, because they need different tools and should be measured separately:

| Question | Tool | Who is allowed to answer |
|---|---|---|
| (a) Was it a contact? | geometry / simulator | never the VLM (FailBench-type judges are near chance on contact tasks, see `docs/dev/reuse-from-agentic-robot.md`) |
| (b) Which body pair, which region? | geometry | never the VLM |
| (c) Why did the program cause it, what to change? | VLM (Muse Wonder) | the VLM, given (a) and (b) as evidence |

## 2. What the logs say today (first, because it changes the plan)

Checked on the exp03 clip 233859 attempts 2 and 3 **[run]**, from `episode/steps.jsonl` (joint positions vs commanded targets):

- No joint came within **0.58 rad** of its limit (attempt 3: smallest margin 0.581 rad on joint 4). So these stalls are **not** joint-limit stalls.
- Both attempts have hundreds of steps where a joint is more than 0.04 rad from its commanded target (attempt 2: 600 of 876 steps, attempt 3: 500 of 727), and the end effector sits at z ≈ 0.204 to 0.206 m in the robot base frame during the late stalls.
- The logs contain **no contact data at all**: `steps.jsonl` has only the commanded action and the robot state. So "the arm was blocked by the plate" is currently a hypothesis written by the model, not an observation.

Consequence: before building a point-cloud pipeline we must find out how many stalls are contacts at all. That is Experiment A0 below, and everything else is gated on it.

## 3. Review of the attached architecture against ANTS

The attachment is a general RGB-D scene-graph + GPT + MoveIt manipulation design. Against what ANTS already has:

**Already exists in ANTS / ASPIRE (reuse, do not rebuild)**
- Text-prompted segmentation `segment_text` (SAM 3), RGB-D → framed point cloud `mask_to_point_cloud`, `crop_point_cloud`, `estimate_geometry` (centre, orientation, extents = an oriented box), `localize_object`. These are attachment stages 1 to 2 for a single frame. Generated programs already use them (exp03 reports `bowl_point_count`, `bowl_top_radius_m`, wall radius from a point-cloud slice).
- Collision-aware planners behind the same API: `MotionStrategy(trajectory_planner="curobo")`, PyRoki IK, Contact-GraspNet (`ASPIRE/docs/api-reference.md`). The default `move_to_pose` uses PyRoki + **joint interpolation, which is not collision-aware** (api-reference: "direct servo operations rather than collision-aware plans").
- Run artifacts: per-call traces, `steps.jsonl`, keyframes, overlays, videos (`run-artifacts.md`).
- The principle "VLM does semantics, geometry stays local and deterministic" and "VLM is not the safety or success authority": already an ANTS rule.

**New (this proposal adds)**
- Object-level *collision proxies* and their text encoding for the generator.
- Contact attribution: robot link × object region, with a "blocking" filter.
- Causal evidence (counterfactual replay), which the attachment does not cover.
- Feeding all of this into the repair prompt, and later into rule-based constraints.

**Contradicts or does not fit ANTS (drop or defer)**

| Attachment idea | Why it does not fit here |
|---|---|
| Persistent world model, multi-frame fusion, tracking, geometry revisions | Our episodes are single simulated scenes with a fixed camera and one moving object. A frame at t0 (arm out of view) gives clean static clouds. Fusion would cost effort for no gain. |
| MoveIt 2 | We use PyRoki and cuRobo through ASPIRE. |
| Grounding DINO + SAM 2 | SAM 3 is already in the harness (text prompts). |
| FoundationPose, TSDF/mesh reconstruction, 1 to 3 mm voxels | Known objects, noise-free sim depth, and collision needs centimetre-level proxies. Skip. |
| GPT tool-calling loop (`get_object_geometry` …) | Pull-style tools make the generator non-deterministic and break the gate's reproducibility. Push the evidence once in the repair message. If a pull tool is ever wanted, cap it and cache by observation hash (the C3 design in `aspire-assessment.md`). |
| GPT/OpenAI Responses API | Our generator is `muse-wonder-1.0`. Whether it accepts images is **unverified**; we have only used text so far. |
| "Detect the robot arm from the point cloud" | In simulation the arm pose is known exactly from joint positions plus forward kinematics. Detecting it from pixels is noisier and unneeded. Keep it only for a real robot. |
| Images in the feedback loop | `aspire-assessment.md` records that raw images in the loop hurt and text descriptions of visual change help (CaP-X). Start text-first. |

**Where the attachment is right and we should keep it**: keep observed geometry, collision geometry and semantic description as three separate things; never present inferred surface as measured; send a compact summary, not clouds; mark unobserved regions as unknown.

## 4. The representation for the VLM ("simplified yet enough rigidity")

Principle: spend tokens where contact decisions are made. Target budget **≤ 600 tokens** for the whole block.

**Robot side: FK collision spheres, not point clouds.** Panda links as ~7 to 60 spheres from forward kinematics (cuRobo uses sphere models of the robot; PyRoki has the Panda model; the MJCF has exact link geoms). Name every sphere group by link and finger (`finger_left_pad`, `finger_right_pad`, `hand`, `link7` …) so attribution is a label, not a guess.

**Object side: compact proxies, ordered by increasing detail** (this is the "resolution ladder" of Experiment A4):

| Level | Proxy | Tokens per object | Good for | Weak for |
|---|---|---|---|---|
| P0 | oriented box (`estimate_geometry` already returns it) | ~25 | table, boxes | bowl interior, plate lip |
| P1 | **axisymmetric radius profile**: vertical axis (x,y) + radius at 5 to 8 heights | ~60 | bowl, plate, cup, any lathe-like object | handles, non-round |
| P2 | 3 to 12 convex hulls (CoACD or V-HACD, CPU) as boxes/hull summaries | ~100 to 250 | arbitrary shapes | verbose |
| P3 | coarse occupancy grid, e.g. 8×8×4 as layered text | ~250 | open/closed volumes | precision |
| P4 | orthographic top and side views with contact marks (image) | image tokens | spatial gestalt | needs image support, CaP-X caution |
| P5 | **sphere set ("bubbles", the cuRobo style)**: 8 to 32 spheres `(x, y, z, r)` covering the object's surface | ~100 to 300 | conservative margins, per-sphere clearance numbers, same vocabulary as the robot's own sphere model | many numbers for the model to read; a hollow object must be covered as a shell, or it becomes a solid blob |

P1 is the interesting default: bowls and plates are bodies of revolution, the program already measures a wall radius from a point-cloud slice, and the same profile gives named **regions** for free (outer wall, rim, inside, base; angle around the axis as a compass bearing). A 5-row table beats a 3-D box for the question "where on the bowl did the finger touch".

**G: the relation layer (a scene graph of the objects).** P says what each object looks like; G says how objects relate. Every relation is computed from the `CollisionWorld` by geometry, never written by a model. Candidate relations, with the threshold values being starting points to tune, not measured:

| Relation | How it is computed | Example |
|---|---|---|
| `on` / `supported_by` | contact or gap ≤ 2 mm with the other object below | bowl on table |
| `inside` / `contains` | shape of A within the open volume of B | spoon in bowl |
| `near(d)` and `clearance(a, b, mm)` | minimum distance between the two proxies; exact with spheres (P5) | wine rack, plate: 15 cm |
| `left_of`, `right_of`, `in_front_of`, `behind`, `above`, `below` | positions in the robot base frame; the frame must be stated | plate right_of bowl |
| `touching` | gap ≤ 2 mm at t0 | plate, wine rack |
| `occludes(a, b)` | ray from the camera to b hits a | for perception, not for collision |
| `in_corridor(obstacle, target_pose)` | obstacle inside a corridor around the approach and the hand footprint at the target pose | wine rack under the hand at the bowl pose |
| `reachable(object)` | an IK solve for the target pose, optionally collision-free through cuRobo | needs the planners |
| `blocks(arm part, object, region, force)` | from logged contacts, a time-stamped event, not a fixed edge | hand blocks on wine rack top, steps 322 to 823 |

What it cannot do: semantic or functional relations (needs captions, and a model that writes them can invent them), relations about surfaces nobody observed, and anything about time unless the events are logged. Keep it to edges that touch the task objects or the planned path, about 150 tokens. Whether the graph adds anything over a flat list is exactly the G0 vs G1 comparison in A4.

**Contact side**: a table of *blocking* contacts, not all contacts:

```
scene (robot_base, cm; table z=0)
 bowl  axisymmetric, axis (59.4, 12.5), height 5.4; radius by height: 0:4.1 1.5:5.6 3.0:7.0 4.5:8.2 5.4:8.9
 plate axisymmetric, axis (56.0, 22.0), height 1.8; radius by height: 0:12.0 1.0:13.5 1.8:14.5
call #9 move_to_pose timeout after 141 steps; target z=11.7, reached z=20.6
blocking contacts in the last 40 steps:
 finger_right_pad -> plate, outer rim, bearing 20 deg, point (55.1, 9.8, 1.6), force 12 N, 38 of 40 steps
 hand             -> bowl, rim, bearing 270 deg, ...
free of contact: link7, finger_left_pad, joints (min margin to limit 0.58 rad)
```

Why "blocking" matters: while grasping, the fingers always touch the bowl and the bowl always touches the table, so a raw contact list is mostly expected contact. Two filters, both cheap: (i) keep contacts whose normal opposes the commanded end-effector motion (force component against the motion direction), and (ii) leave-one-out replay (Experiment A0b). Without a filter the evidence would mislead the model.

## 5. Parallel work with the cuRobo effort

Define one shared artifact so the two developments meet at an interface and can be built separately:

```
CollisionWorld = list of named primitives in robot_base frame (box | axisymmetric profile | hull set)
                 + provenance: "mjcf" (oracle) | "sam3+depth" (perceived)
```

- **This proposal** builds `CollisionWorld` (oracle first, perceived second) and the text encoder + contact attribution.
- **cuRobo work** consumes `CollisionWorld` as its world model (cuboids/meshes) and can return per-sphere collision distances for a pose or trajectory. Verify the exact API in `ASPIRE/third_party/curobo` before relying on it: I did not check which cuRobo version ASPIRE pins.
- Both can be developed against the MJCF oracle world, with no dependency on each other. Per-sphere distances from cuRobo give link-level attribution for free, which is the same output as our FK-sphere attribution; agree on link names early.

## 6. Experiments

Shared testbed unless stated: task `libero_goal_swap` 8 ("put the bowl on the plate"), scaled scene, debug seed 51, model `muse-wonder-1.0`, T=0.2, the three clips of exp03 (233832, 233859, 234314), up to 5 attempts. Failing programs from exp03 are the free test material: **[run]** 14 of the 15 debug attempts failed (all but clip 233859 attempt 4); most ended `program_completed` without success, two `program_error`.

### A0. Is it a contact? Instrumented replay (no LLM cost)
- Extend `tools/aspire_launch.py` (it already wraps the env's `step`) to log per step: all MuJoCo contacts (geom pair → body, robot link, world point, normal, penetration, force from `mj_contactForce`), joint-limit margin, tracking error. Log to a file in the run directory; the program must not see it.
- Re-run the 14 failed exp03 programs. Classify each timeout: contact-blocked / joint limit / reach-IK / controller / unexplained.
- **A0b causal check (leave-one-out):** replay the recorded action sequence open-loop with one object's collision disabled (set geom `contype/conaffinity` to 0 for the bowl, then the plate, then each other object, then the table) and measure whether the stall disappears. The object whose removal clears the stall is causally responsible. This is the ground truth for "what made it stuck", and it separates incidental from blocking contact.
- Prediction to test: most late stalls are blocked by the plate or bowl. If fewer than ~30% of stalls are contacts, stop and pivot to kinematic-reach evidence (cuRobo reachability), because collision context cannot help.
- Cost: simulator time only. Caveat: replay determinism must be checked first (run the same program twice and compare end states).

### A1. Oracle evidence ladder → does it change repairs? (the headline experiment)
Arms, same prompts as exp03 except the repair message:

| Arm | Repair message adds |
|---|---|
| E0 | nothing (exp03 baseline, with `WHY:`) |
| E1 | blocking-contact table only |
| E2 | E1 + P1 object profiles (oracle, from MJCF) |
| E3 | E2 + free-of-contact summary and joint margins ("not a joint limit") |
| E4 | **placebo**: E2 evidence taken from a *different* failure |
| E5 (optional) | E2 + one image with contact marks, only if Muse Wonder accepts images |

Measures: solved within 5 attempts, attempts to solve, reasoning tokens per repair (the count we now log), and **diagnosis accuracy** of the `WHY:` note against A0 ground truth (does it name the right link, object and region? scored by keyword match, no judge model). E4 shows whether the model actually uses the evidence. With 3 clips × 1 run per arm this is anecdote, like exp02; do 3 clips × 3 seeds/temperatures (9 per arm) and report it that way.
- Cost estimate: exp03 spent 143.8k, 238.1k and 206.4k new tokens for the three clips (588k total, **[run]**). 5 arms × 9 runs × ~200k ≈ 9M tokens. Too much; see A2 as the cheaper way to get the same answer.

### A2. Diagnosis-only benchmark (recommended first LLM experiment)
- No repair loop and no API-reference prompt. Input: program + the text feedback + one evidence variant. Ask: "which robot part touched which object region, why, and what single change fixes it". One call per (failure × variant).
- 14 failures × 5 variants × 2 repeats = 140 calls. Prompts of ~8k tokens, outputs ~3k (reasoning included): ≈ 1.3M tokens. Much cheaper per bit of information than A1, and it isolates the representation from generation luck.
- Score against A0/A0b ground truth. Also record reasoning tokens per variant. Hypothesis: better evidence lowers both error and reasoning tokens.

### A3. Perceived vs oracle geometry (no LLM)
- Build `CollisionWorld` from the first frame (arm still at home) with SAM 3 `segment_text` per object + table + `mask_to_point_cloud` + `crop_point_cloud`; fit P0 to P3; arm from FK spheres.
- Compute contacts **geometrically** (sphere-vs-proxy distance along the logged joint trajectory) without any simulator contact data.
- Metrics against the MJCF world and the A0 contacts: attribution F1 on (link, object), region error in mm and degrees of bearing, proxy fidelity (Chamfer distance / IoU), per proxy level. This tells us how much of A1's gain survives without privileged state, i.e. what a real robot could use.
- Includes the scaled scene (scale factors 1.227 and 1.855) as a check that proxies follow the real size.

### A4. Representation ladder under a token budget (shape level × relation layer)
- Two factors, crossed on the A2 benchmark and fed with the perceived scene from A3: **shape** P0, P1, P2, P3, P5 (P4 only if images work) and **relations** G0 (flat object list) vs G1 (relation graph, see "G" in section 4). Match the token budget within each comparison.
- Plot diagnosis accuracy and reasoning tokens against tokens. Expectations to test: P1 is the knee for round objects; G1 helps most for objects nobody prompted for (the wine rack), because a clearance edge is the only thing that mentions them.
- A8 goes deeper on P5 (sphere count and fitting); A4 only places P5 on the same ladder as the others.

### A5. Pre-mortem: predict the collision before running
- From the program's sequence of `move_to_pose` targets (visible in `trace/calls`), check each target pose against the `CollisionWorld` and report "finger_right_pad intersects plate rim by 14 mm at call 9" **before** execution. This turns the post-hoc explanation into a constraint, in the ANTS sense. Uses the cuRobo collision check from the parallel effort.
- Only worth doing after A1 or A2 shows the evidence helps.

### A6. Planner baseline: does a collision-aware planner make the evidence unnecessary?
- Arms: baseline program, program told to use `MotionStrategy(trajectory_planner="curobo")` (an ASPIRE option), baseline + evidence. If cuRobo planning alone removes the stalls, the interesting question becomes which target poses are unreachable, which the evidence can still say. This is the natural joint experiment with the cuRobo development.

### A7. Evidence → rule-based constraints (ANTS closed loop)
- Turn blocking contacts into imperative constraints with fixed templates, no VLM ("approach the bowl from a side where the plate rim is farther than 6 cm from the finger"), and add them to the generator context as ANTS constraints. Compare with VLM-written constraints. This matches the spec's "model diagnoser + rule fallback" and gives the adversary side something deterministic.

### A8. Bubble proxies (cuRobo-style sphere sets) as the collision shape
- cuRobo represents the robot as a chain of spheres (the Panda model in the cuRobo documentation is drawn as green bubbles). Give the objects the same kind of shape: a set of spheres fitted to each object, so a clearance is a sphere-to-sphere distance and a contact is named by a pair, for example "`finger_right_pad` sphere 2 overlaps `wine_rack` sphere 9 by 6 mm".
- Fit the spheres to the t0 point cloud (or to the MJCF meshes for the oracle). Cover the **surface**, not the volume: a bowl is a shell of spheres around the wall and rim with the inside left free, otherwise it becomes a solid blob and the grasp inside the rim is lost. Try 8, 16 and 32 spheres per object.
- cuRobo may ship its own sphere-fitting for meshes and its robot sphere config for the Panda; verify in `ASPIRE/third_party/curobo` before relying on either. For objects, cuRobo's own world model normally uses boxes, meshes or a distance field, so check whether it accepts spheres for obstacles. If it does not, spheres stay a representation for the model and for our own distance computation.
- Compare P0, P1 and P5 (same token budget where possible) on the A2 benchmark and on A3.
- Measures: attribution F1 on the (robot sphere, object sphere) pair against the A0 answer key; over-approximation (volume of the sphere set divided by the true volume); spheres needed to reach a given coverage; diagnosis accuracy and reasoning tokens in A2.
- Why it is worth a separate arm: spheres give the model explicit numeric margins ("6 mm of overlap", "clearance 23 mm") that boxes and radius profiles do not, and they use the same vocabulary as the cuRobo effort, so one `CollisionWorld` can feed both.
- Risk: more numbers per object may hurt more than help. P1 is the control for that.

## 7. Recommendation

Order (each step gates the next):

1. **A0 + A0b** first. It costs no tokens, answers whether collision context can help at all, and produces the ground truth every other experiment is scored against.
2. **A2** with oracle evidence (P0/P1, contact table), then **A1 E0 vs E2 vs E4** on one or two clips if A2 is positive. Three arms are enough for a first claim: baseline, evidence, placebo.
3. **A3** next: replace the oracle with SAM 3 + depth proxies and report how much survives. This is the result that carries over to a real robot.
4. **A4, A5, A6, A7** later. A6 is the natural shared experiment with the cuRobo work.

Most informative single design choice: **P1 axisymmetric profiles + a leave-one-out-filtered blocking-contact table**, because it names the object *region* in a few dozen tokens and does not depend on images.

The hackathon MVP is due 2026-11-04. Only A0 plus A2 (oracle) is realistic by then; the rest is the research tier.

## 8. Compute and cost

- GPU: SAM 3 plus a LIBERO worker and PyRoki fit in the 8 to 10 GB estimate in `aspire-assessment.md`; the point-cloud, primitive fitting and CoACD parts run on CPU. cuRobo adds ~1 to 3 GB estimated and was marked marginal on the A5500 profile there.
- Tokens: A0 and A3 use none. A2 about 1.3M tokens. A1 at 9 runs per arm is tens of millions of tokens: avoid.
- **Budget flag:** `data/llm_ledger.jsonl` totals 2,910,413 tokens across 85 calls, about 39 USD at the configured 13.5 USD per million, while `docs/HANDOFF.md` records a **15 USD Muse cap**. Either the rate is wrong or the cap is already exceeded. Confirm the real budget before any A1/A2 run.

## 9. Open decisions for the user

1. Confirm the Muse budget (section 8) before spending on A1/A2.
2. Does `muse-wonder-1.0` accept image input? Not tested; affects E5 and P4.
3. Where the code lives: contact logging in `tools/aspire_launch.py` (simulator side); `CollisionWorld` and the evidence encoder as `adversary/` code (it is the diagnoser's evidence) with the shared type agreed in `contracts/` with Daniel. Adding a contracts type needs agreement with the other owner.
4. Whether `check_pose_collision(pose)` should ever become a primitive the program can call (changes the policy API, so deferred).

## 10. Literature (found by web search 2026-11-01; titles and one-line takeaways only, not read in full)

- Dynamic scene graph + VLM for long-horizon manipulation, with collision-failure explanation and replanning: PMC13568281.
- ProTracer, proprioception-guided failure diagnosis (finding failure onset that video alone misses): arXiv 2609.21369.
- RAFAIL, relationship-aware failure detection from point-cloud relationships: arXiv 2609.18324.
- KITE, keyframe-indexed evidence with a coarse 3D scene graph for VLM failure analysis: arXiv 2604.07034.
- Probing collision grounding in VLMs: models describe the obstacle but fail to connect it to robot body geometry and contact state: arXiv 2605.31196.
- Diagnose, correct and learn from manipulation failures via visual symbols: arXiv 2512.02787.
- Object-centric 3D tokens (arXiv 2606.29513) and LLaVA³ (arXiv 2511.16454): per-object representations for VLMs, evaluated on 3D question answering, not manipulation. ConceptGraphs (arXiv 2309.16650): open-vocabulary 3D scene graphs tested on robots.
- CoACD (SIGGRAPH 2022) vs V-HACD for convex decomposition: vendor comparison only; check the paper before quoting hull counts.

Not found: a controlled study of text scene graph vs object tokens vs images for *failure explanation* in manipulation. That gap is what A4 would fill.
