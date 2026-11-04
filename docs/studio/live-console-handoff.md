# Live orchestrator console: handoff

Written because the session that built this is about to hit its limit. Read this before touching
`src/ants/studio/console*.py` or `console_template.html` again. Branch `observability/live-console`,
worktree `/home/eeschner/alfredo/workspace/ANTS-live-console`. The user's day-to-day checkout is a
**separate** directory, `/home/eeschner/alfredo/workspace/ANTS` (branch `synthesizer`) — see
"Two checkouts" below, this is the single most important thing to get right.

## What this is

A local, stdlib-only HTTP server + one self-contained HTML page: a live, in-browser console over
one real `Loop.run()` cycle (`ants.orchestrator.loop.Loop`), built incrementally over one session on
top of the already-merged `integration` branch (PR #13). Not part of any committed plan — built
live, feature by feature, from the user's running commentary while they used it. Nothing here has
been reviewed by Daniel (owns `orchestrator/`, `adversary/`) or merged past `observability/live-console`.

Run it: `uv run python -m ants.studio.console --port <free port>` from either checkout (once synced,
see below). Defaults: `--mode loop`, `--cycles 3`, mock System 2 backend, 1 nominal seed, `--scene
data/scenes/L1/contacts_scene.json`.

## Two checkouts — keep them byte-identical

- **Worktree** `/home/eeschner/alfredo/workspace/ANTS-live-console`, branch `observability/live-console`.
  This is where every commit below actually lives. `git log --oneline -15` here for the real history.
- **Main checkout** `/home/eeschner/alfredo/workspace/ANTS`, branch `synthesizer`. This is where the
  user actually runs the server day to day (they don't `cd` into the worktree). The console files
  there are **untracked copies**, manually `cp`'d over from the worktree each time something changed
  — `synthesizer` has never had these files committed. Confirm with:
  ```
  cd /home/eeschner/alfredo/workspace/ANTS && git status --short | grep -E "console|scene[23]d"
  ```
  If that shows `??` (untracked) for `console.py`, `console_server.py`, `console_template.html`,
  `scene2d.py`, `scene3d.py`, `scene3d_template.html` — that's expected, not a mistake.
  **After any edit in the worktree, `cp` the changed files into the main checkout before the user's
  server will show them.** This bit every round of work this session; don't skip it.

## What's built (worktree commits, oldest first)

1. `48ea1c0` — the server itself: stdlib `ThreadingHTTPServer`, SSE `/events`, `/run` POST with a
   confirm-gate ("ready to run the policy development phase?") before spending any tokens. Started as
   one Phase A repair step only (`--mode single`).
2. `4c5e4e7` — `--mode loop` (now default): drives the real `Loop` against the mock System 2 backend,
   System 1 real via `MuseOrchestrator`/`muse exec`. `on_attack` callback gives the only sub-cycle
   granularity `Loop` exposes (attack result, before the blocking rewrite call) — **this is a hard
   ceiling**, not a missing feature: `Adversary.attack()` runs selector→proposer→rollout→diagnoser
   *synchronously inside one call*, so there is no live signal for those 4 sub-steps individually.
   Every "live" feature built since respects this; don't build something that fakes finer granularity.
3. `b8fdde6` — shrank defaults (3 cycles, 1 seed, W=2) so a demo run is cheap/fast.
4. `ed30395`, `59ac77b` — `scene3d.py`/`scene2d.py`: standalone + embedded 3D/2D viewers of the
   oracle scene (`data/scenes/L1/contacts_scene.json`, from `orchestrator/scene_context_exp.py
   --prep`). The "Scene prompt" panel. One real bug found and fixed in `scene2d.py`: `gaps` entries
   reference parent bodies that own zero geoms directly (only children do) — categorizing by geom
   ownership silently dropped several relations; fixed by categorizing the gap's body name directly.
5. `ee94f69` — System 1/System 2/Orchestrator status badges (from `on_attack` + `loop.jsonl` tailing),
   a red "needs human intervention" banner on escalate/no_working_policy/budget_stop.
6. `a87c5ab` — `localStorage` persistence (`saveUiState`/`restoreUiState`): reopening the page shows
   the last session's result instead of blank, with a "restored from ..." timestamp note.
7. `a149893` — primitives became name-only chips (click → popup with role/desc) instead of permanent
   description cards; **SAM 3 archive panel** (archived segmentation overlays, real
   `exp04_scene/E-E3/sample0` data, served via a whitelisted `/sam3/<name>` route); per-cycle "View
   details" modal (WHY reasoning parsed from `reply.md`, token/cache breakdown including
   `cached_tokens`, full diff) — wired by having the `tail()` thread in `run_live_loop` read
   `run_dir/muse/cycleN/{reply.md,usage.json}` right when it sees a matching `loop.jsonl` row.
8. `629baed` — archived "perception replay" **modal**: scrubbable agentview keyframe timeline (56
   real frames), SAM 3 gallery, link to the existing cuRobo plan-viewer HTML
   (`data/runs/curobo/exp10/*/plan_viewer/index_compare_*.html`, reused via a new
   `/perception/planviewer` route, not rebuilt).
9. `48b0245` — status badges reordered into actual pipeline order (System 2 → System 1 →
   Orchestrator → Escalation) with arrows, loop-back glyph, pulse animation on the active node. Zero
   new state logic — same `setSys()` calls, just connected visually.
10. `4fedf2d` — the modal from (8) promoted into a real top-level **Perception tab** (Console /
    Perception tab bar), 3 independently-togglable panels (Agentview / SAM 3 / cuRobo, state in
    localStorage), each with its own `live` / `archived` / `missing` badge — currently all `archived`
    since nothing in this console's loop is live yet, but the server payload already carries a `live`
    flag per layer so wiring a real source is meant to be "flip the flag," not a rearchitecture.

Read `git show <hash>` on any of these for the full reasoning and what was actually verified — every
commit message documents real verification (headless-Chrome screenshots against the **running
server**, never a `file://`-wrapped copy — relative routes like `/agentview/...` silently break under
`file://` and give false negatives; bit this session twice before the convention was fixed).

## In progress when the session ended — may be incomplete or uncommitted

A background subagent was mid-task, wiring the real thing commit (10) only scaffolded: an opt-in
`--backend cap_harness` flag (**mock stays the default** — explicit user decision, don't flip it) so
a real ASPIRE rollout can drive the Perception tab's live layers instead of always showing archived
data. Its brief, in full, for whoever picks this up:

- Figure out whether `cap_harness`'s real rollout (`src/ants/adversary/rollout/aspire_backend.py`,
  currently blocks inside one `subprocess.run()`) writes keyframe/trace directories progressively
  *during* execution (matching the archived `media/keyframes/000NNN-*/` structure) or only once the
  subprocess exits. If progressive: tail the live run directory the same way `run_live_loop`'s
  existing `tail()` polls `loop.jsonl`, broadcast new frames as they appear. If not progressive: be
  honest about it — "live" then means "refreshed the instant the rollout finishes," not frame-by-
  frame, and the UI copy should say that, not imply more than is true.
- Same honesty question for SAM 3 (does a real rollout produce overlay data in a readable form?) and
  cuRobo (the archived plan-viewer came from a **separate offline experiment script**,
  `data/runs/curobo/exp10/`, not from a single live rollout path — there may be no cheap live
  equivalent; if so, say so and leave that layer on its archived fallback rather than forcing it).
- **Real GPU/compute cost**: services (`sam3` :8114, `curobo` :8118, `pyroki` :8116) were started this
  session via `cd ASPIRE && CUDA_VISIBLE_DEVICES=0 TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1
  scripts/supervise_services.sh --profile a5500 --providers sam3,curobo` (background, `nohup`). Check
  they're still up before assuming they are: `uv run python -m ants.orchestrator.preflight` from the
  main checkout should print `READY`. A real rollout costs ~40s+ wall-clock and real GPU time — the
  brief was explicit: verify cheaply (file/log reads) first, spend only one real rollout to confirm
  wiring, don't loop retries burning GPU time chasing a cosmetic bug.

**Check `git log --oneline -3` in the worktree and `git status --short` in both checkouts before
doing anything else** — the subagent may have finished and committed, partially finished and left
uncommitted changes, or not gotten far. If there's uncommitted work in the worktree that looks
sane (lint/tests passing), finish and commit it rather than discarding it.

## Known, accepted limitations (not bugs — don't "fix" these without re-deciding)

- Mock System 2 backend only, by default — no simulator, no camera, no real SAM3/cuRobo during a
  normal run. Every "archived, not live" badge in the UI is honest about this on purpose.
- This console only ever does **repairs** against a fixed incumbent (`examples/bowl_on_plate/policy.py`)
  — it never drives System 1's *initial* generation (S4 scene-text, `generator.py`). Explicitly out
  of scope, decided early in the session.
- Sub-cycle granularity inside one System 2 attack (selector/proposer/rollout/diagnoser) is not
  observable from this console and never will be without editing `adversary/`'s internals (Daniel's
  package) — don't build UI that implies otherwise.
- `cached_tokens` shown in the repair-detail modal is prompt-level caching (some input tokens served
  from cache), **not** "this whole repair was skipped" — labelled as such on purpose, there is no
  real response-level cache/reuse in this pipeline.

## Quick resume checklist

1. `cd /home/eeschner/alfredo/workspace/ANTS-live-console && git log --oneline -5 && git status --short`
2. `cd /home/eeschner/alfredo/workspace/ANTS && git status --short | grep -E "console|scene[23]d"` —
   confirm what's synced vs. stale.
3. `uv run python -m ants.orchestrator.preflight` (main checkout) — check services are still up if
   continuing the real-backend work.
4. `uv run ruff check . && uv run pytest -q` in the worktree before trusting anything is clean.
5. Pick up the in-progress real-backend work above, or ask the user what's next — this was all built
   turn-by-turn from their live feedback, there is no separate plan document to consult.
