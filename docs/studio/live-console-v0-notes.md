# Live console v0 — overnight notes

Started: overnight session after v0 commit. Owner away; decisions and confusion are logged here
instead of being left implicit. Each subtask capped at 15 minutes.

## Status of v0 (as committed)

- This is **v0**: it works for the mock loop and needs bug-fixing and UX polish before it is a
  proper console. Do not treat anything beyond the mock path as proven.
- **Live view of the robot working is NOT verified.** Code exists (`--backend cap_harness` +
  `watch_aspire_live()` watcher + Perception-tab live flip), but it has never been run against a
  real rollout. It may not work, or the user may simply not know how to enable it. Both are
  possible; subtask 2 below exists to find out with a test that does not burn GPU time.
- Run instructions: see `live-console-handoff.md` in this folder.

## How to use the live view (current understanding, to be verified)

1. Start services: `cd ASPIRE && scripts/supervise_services.sh ...` (see handoff), then
   `uv run python -m ants.orchestrator.preflight` must print READY.
2. Start console with `--backend cap_harness` (mock is default).
3. Press Run. The Perception tab should flip agentview/SAM3 from archived to live as keyframes
   land in `data/runs/aspire/<run>/media/keyframes/`.

## Confusion / open questions (for the owner, do not guess silently)

- Q1: "E3 or E4" for the scene graph — assumed to mean the scene sources under
  `data/runs/exp04_scene/E-E3/...` (and siblings). Confirm which experiment the console should
  show; subtask 5 wires in whatever scene-graph data actually exists on disk.
- Q2: Perception toggle semantics assumed: AUTO (live during rollout, replay when idle) /
  LIVE-only / REPLAY-only three-way toggle. Adjust if wrong.

## Subtask log

(filled in as each subtask finishes)
