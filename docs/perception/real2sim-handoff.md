# Handoff: real2sim dev plan (start here)

Point a new session (Claude Code, Muse Code or any agent) at this file. Last update 2026-11-07.

## Read first, in order

1. `AGENTS.md` (repo rules), then this file.
2. [real2sim-plan.md](real2sim-plan.md): decisions, two projects, backbone modules M0 to M11, steps C → B → A, compute options.
3. [real2sim-literature.md](real2sim-literature.md): literature by category, overlap table, sources.
4. Evidence: [scene-reconstruction-probe.md](scene-reconstruction-probe.md), [real2sim-overnight-2026-11-04.md](real2sim-overnight-2026-11-04.md), [../studio/digital-twin-feasibility.md](../studio/digital-twin-feasibility.md), `docs/dev/curobo-notes-2026-11-05.md` (git-ignored local notes; has the C0 results), `dev/curobo/README.md`.

## The idea in five lines

- Goal: real2sim simulator (A), realtime digital twin (B), cuRobo planning shown and improved (C), built in the order C → B → A.
- One shared backbone, **`twinkit`** (https://github.com/alfredowh/twinkit, private; local `../twinkit`), robot/camera/simulator-agnostic. ANTS and the thesis keep only adapters.
- P1 = ANTS / own side project: phone RGB (S24, S10e as stereo), no robot, MuJoCo/LIBERO. P2 = thesis: dual UR5e + Robotiq, 2 wrist RGB, 1 context RGB-D (RealSense), 1 front RGB facing the robot (uncalibrated), Isaac Sim with an existing USD.
- Simulator first: LIBERO gives ground truth for every module (map, poses, planner world).
- Reuse rule: one shared module per job unless it fails the job's metric threshold; then keep a dedicated one in parallel and log which ran.

## What "planner" and "gate" mean here

- **Planner** = cuRobo, the collision-aware motion planner the robot program calls for every move ("go to this gripper pose without hitting anything"). It needs a 3D picture of obstacles; today it builds that from one depth image per move, which caused the known bugs (carve erased the wine rack, wrong held-bowl frame, ghost points).
- **Gate** = a development-time measurement, not a runtime component. Before comparing two ways of building the planner's obstacle picture (e.g. simulator depth vs phone stereo), write down the pass numbers (never plan into an obstacle; few false refusals), run both on the same acceptance seeds (51 to 65), keep what passes. The runtime system only contains the winner.

## Status

| Item | State |
|---|---|
| Literature + plan | written (this folder) |
| `twinkit` | skeleton only: uv package, `coacd`, `trimesh`, `numpy`; first commit `0930167` |
| C0 (multi-seed replay of the frame fix) | done 2026-11-07, see below |
| Heavy deps | not installed; install locally (laptop, 16 GB) when their step starts, one uv group each |
| Commits in ANTS | plan/literature/handoff not committed yet unless git log says otherwise |

### C0 result (from `data/runs/curobo/replay_seeds/`)

Frame fix holds on seed 51 for all 5 programs but **not across seeds**: attach 9/15 successes vs sparse 4/15; refused plans 29 vs 39; planned-into-collision 0 in both. All 29 attach refusals are false (goal labeler says free). Rack guard (`plan_rack.py`) reproduces the 2026-11-04 table exactly. `carve_check` original inputs are lost (needs a recorded case).

## Next step (C0b, then C1)

1. **C0b: diagnose the 29 false refusals.** Hypothesis from the notes: bowl-rim points near the fingers. Test: exclude the localized target object from the planning cloud for grasp moves (`ANTS_EXCLUDE_RADIUS_M` or a target mask in `dev/curobo/`), re-run `replay_attach.py --mode attach` on seeds 51 to 53 (later 51 to 65), then `goal_confusion.py`. No Muse tokens. Done when false refusals drop and planned-colliding stays 0.
2. Fix the C gate thresholds before the run (proposal in the plan: 0 planned-colliding, false refusals ≤ 5%, 0 forbidden-contact steps, clean success not below baseline, p95 plan time ≤ 10 s).
3. **C1: planner-world adapter** in `twinkit` (robot removed by FK-rendered mask instead of the 5 cm carve, held object as attached spheres, target excluded for grasps), used from ANTS via `tools/aspire_launch.py` / `dev/curobo/`.
4. Exp 12 rerun (~450k tokens, ~2 h) only after C0b holds across seeds; ask the user first.

## How to run things

- Services (SAM 3 8114, PyRoki 8116, dev cuRobo 8118 with `ANTS_CARVE_MARGIN_M=0.0`, `ANTS_ATTACH_FILE=$PWD/data/runs/curobo/attach.json`): `uv run python -m ants.evalkit.runbook cmd services.start` and `cmd curobo.service`. Stop them when done; they hold GPU memory.
- One simulator at a time (`ps -eo pid,args | grep -E "[r]eplay_attach|[t]ools/aspire_launch"`), and not while the user's `/policy-dev` runs (`curl -s http://127.0.0.1:58910/session`).
- Replay commands: "Resume `replay_seeds`" section of `docs/dev/curobo-notes-2026-11-05.md`.

## Rules that stay

- Acceptance seeds 51 to 65 only; held-out 1 to 50 never for tuning; `--init-mode seeded`.
- Numbers only from logged runs, with folder paths.
- Do not touch `src/ants/adversary/` or `src/ants/orchestrator/` (Daniel); do not modify ASPIRE; hurobo is read-only.
- Every new command goes into `docs/runbook/commands.json`, then `runbook check` and `build`.
- Ask before new heavy dependencies or any run above 100k Muse tokens.
