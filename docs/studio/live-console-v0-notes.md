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

1. **v0 commit + push** — done, commit `004a852` on `observability/live-console`.
2. **Live view** — wiring proven without GPU by `tests/studio/test_console_live.py` (6 tests):
   a fake rollout writing keyframes/overlays progressively is observed by the watcher, broadcast
   over the same queue the SSE endpoint drains, and served by the real HTTP server
   (`/live/keyframe/...` returns the exact bytes; page knows `cap_harness` mode). Stale-run guard
   tested: a run finished before the watcher started is never shown as live. **Still unproven:**
   one real GPU rollout (`--backend cap_harness` with services up). That is the one remaining
   verification step; it was not run overnight because it spends real GPU time.
   Why the owner may have seen "not working": with the default mock backend there is nothing
   live to show by design, and nothing in the old UI said so at the point of clicking Run. The
   Run-confirm dialog and Perception notes now say which mode you are in.
3. **Run logging** — every Run already creates `data/console_runs/run-<timestamp>/` containing
   `loop.jsonl` (full run log), `history.jsonl`, `summary.json`, `policies/`, and
   `muse/cycleN/` (each repair's reply + token usage). Four past runs verified on disk. The
   console now also broadcasts `run_started` and shows "saving to <folder>" in the header from
   the moment a run starts, so the folder is findable even after a crash.
4. **Collapsible logs** — every card in the middle feed collapses/expands by clicking its header;
   Collapse all / Expand all buttons sit above the feed.
5. **Scene graph** — the Scene panel gained a "scene graph" toggle: objects (nodes) and spatial
   relations (edges, gap in mm) from the same scene file the prompt is built from. Confusion Q1
   stands: on disk there is `E-E0..E-E3` and `G-S0..G-S4` under `data/runs/exp04_scene/`; no
   "E4" exists. If "E4" meant `G-S4`, say so and the panel can point at that arm instead.
6. **Perception source toggle** — Auto (default: live only while a rollout runs, replay before
   and after), Live, Replay. Choice persists in localStorage. When a run ends in Auto, badges
   flip back to replay honestly instead of leaving the last live frame labelled live.

## Morning checklist for the owner

- Start (mock): `cd /home/eeschner/alfredo/workspace/ANTS && uv run python -m ants.studio.console --port 8765`, open http://127.0.0.1:8765
- Start (real robot view): preflight READY first, then add `--backend cap_harness`.
- Your runs: `data/console_runs/run-*/loop.jsonl` in the checkout you started the console from.
- Unverified: exactly one thing — a real GPU rollout end to end. Everything else above has a
  test or a disk check behind it (`uv run pytest -q`: 293 passed, 3 skipped; ruff clean).
