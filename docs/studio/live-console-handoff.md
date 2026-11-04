# Studio (live console): handoff — 2026-11-04, switching to Sonnet 5.5

Supersedes the earlier version of this file (everything below is current as of commit `8503b00`).
Written because the user is switching models mid-session. Read this before touching
`src/ants/studio/*` again. Branch `observability/live-console`, worktree
`/home/eeschner/alfredo/workspace/ANTS-live-console`. User's day-to-day checkout is a **separate**
directory, `/home/eeschner/alfredo/workspace/ANTS` (branch `synthesizer`) — see "Two checkouts," the
single most important thing to get right, unchanged from before.

## Correction (2026-11-04, later): the dashboard.py edit is NOT a boundary violation

An earlier version of this section claimed a subagent had edited *Daniel's* `dashboard.py`,
`dashboard_template.html` and `tests/studio/test_dashboard.py`. **That was wrong.** `git log` shows
those three files were authored solely by `alfredowh` (the user, commit `b24e4e3` "Add the offline
prompt-generator and a local dashboard"). Daniel's (`psykoss`) studio files are only `template.html`,
`build.py`, `run.py` (+ `tests/studio/test_studio.py`). The uncommitted additions in the main checkout
(+85/+10/+33 lines: streamed-output display, event timeline) are edits to the user's own tracked
files, so there is nothing to revert on ownership grounds — just decide whether to commit them
(they are uncommitted, `synthesizer` branch only).

Still worth doing: an untracked `tests/studio/test_console_live.py` (173 lines) exists in the main
checkout only; check it and move it into the worktree + commit if it's a real test.

**Daniel's files remain off-limits to edit:** `src/ants/studio/template.html`, `build.py`, `run.py`.
Importing from them (e.g. `attack_row`) is fine.

## Daniel's latest (read 2026-11-04) and the merge

His newest commits are on `origin/integration` (via PRs #14-#17, all 2026-11-04): rollout videos in
the studio Replay view (`654c74a`), a real video player synced to the call timeline (`5e1e889`), and
"the call timeline is the player" (`586e826`) — changes in `template.html`, `build.py`, `run.py`,
`tests/studio/test_studio.py`, plus a README banner and a relative `--aspire` fix. Our branch is 9
commits behind `integration`. A read-only dry run (`git merge-tree`) showed **no overlapping files
and zero conflicts**: his changes are in his files, ours are new files. Merging
`origin/integration` into `observability/live-console` is safe. His UIs, regenerated offline from
`integration` (no videos in the offline world: "No video for this attack" placeholder): see
`/tmp/ui/shot_*.png` (may be gone; regenerate with
`uv run python -m ants.studio.run --attacks 20 --out <dir>` and
`uv run python -m ants.orchestrator.run --cycles 30 --out <dir>`, open `<dir>/studio.html`).

## Two checkouts — keep them byte-identical

- **Worktree** `/home/eeschner/alfredo/workspace/ANTS-live-console`, branch `observability/live-console`.
  Every real commit lives here. `git log --oneline -20` for the full history.
- **Main checkout** `/home/eeschner/alfredo/workspace/ANTS`, branch `synthesizer`. Where the user
  actually runs the server day to day. The console files there are **untracked copies**,
  hand-`cp`'d from the worktree after every change — never committed on `synthesizer`. Confirm sync
  before trusting what's running:
  ```
  for f in src/ants/studio/console_server.py src/ants/studio/console.py src/ants/studio/static/console.css src/ants/studio/static/console.js; do
    diff -q "$f" "/path/to/ANTS-live-console/$f" || echo "OUT OF SYNC: $f"
  done
  ```
  **After any edit in the worktree, `cp` the changed files into the main checkout before the
  server will show them.** Bit this session repeatedly; still the single most common mistake.

## Current file layout (restructured this session, commit `0aee3bc`)

No longer one big `console_template.html`. Now:
```
src/ants/studio/
  console.py                CLI entry (uv run python -m ants.studio.console)
  console_server.py         stdlib HTTP server, SSE, run_live_loop, all GET/POST routes
  scene2d.py, scene3d.py    oracle-scene projections (2D SVG / 3D three.js), scene3d_template.html
  static/
    console.css             all styling (theme tokens incl. light/dark, layout, components)
    console.js               all client JS (SSE handling, chat, scene rendering, persistence)
  views/
    shell.html                page shell: header, tab bar, theme toggle, modal, assembled by
                               _assemble_shell() via marker-comment substitution
    agent_console.html        Console tab: Primitives, Scene prompt, turns feed, chat composer
    perception.html           Perception tab: Agentview/SAM3/cuRobo + Synthesizer/Adversary toggle
    synthesizer.html, synthesizer_stub.html   stub iframe onto a COPY of Daniel's dashboard_template.html
    adversary.html, adversary_stub.html       stub iframe onto a COPY of Daniel's template.html
  run.py, template.html, build.py   Daniel's (psykoss) studio files — DO NOT EDIT, import only
  dashboard.py, dashboard_template.html   the user's own (alfredowh) local dashboard — not Daniel's
```
`console_server.py` serves static files via a new `/static/<name>` route, images via
`/agentview/<name>`, `/sam3/<name>`, `/attacks/<run_name>` (new, see below), and the cuRobo page via
`/perception/planviewer` — all whitelisted, follow that pattern for anything new.

## What's built (worktree commits, oldest first; the earlier version of this file covered through
`4fedf2d` — everything from `48b0245` on is new since then)

- `48b0245` — status badges became a connected pipeline (System 2 → System 1 → Orchestrator →
  Escalation), arrows, pulse animation. Zero new state logic, same `setSys()` calls.
- `004a852`, `1b89267`, `bfb52af`, `0979e1b` — **opt-in real backend**: `--backend cap_harness` flag
  (mock stays default). A real ASPIRE/LIBERO rollout can now drive the Perception tab's layers
  instead of only archived data — needs `sam3`/`pyroki`/`curobo` services up (see below) and the GPU.
  Verified end to end once with a real rollout. (Also where the uncommitted dashboard.py additions in the main checkout most likely came from.)
- `0aee3bc` — the file-structure restructure described above.
- `08aa99f` — the chat composer: pill input, `+`/mic icons, three cases from
  `docs/studio/chat-field-design.md`, **all three verified for real**: (1) escalated→answer via the
  real `orchestrator/human_gate.py` `ask_human`/`GateAnswer` mechanism, confirmed it becomes a real
  constraint and the loop resumes; (2) idle→one-shot Muse call with incumbent+constraints as context;
  (3) active→queue, auto-fires the instant the loop goes idle. Found and fixed a real bug: `/events`
  used to close after each run's `done`, so case 3's auto-fired reply would broadcast to nobody —
  fixed by keeping the SSE connection open for the whole page session, not just one run.
- `12fc51f` — Daniel's pixel-ant logo (copied verbatim) in the header + as the favicon.
- `7eddccc` — renamed "ANTS Live Console" → **"Studio"**. Removed the `phases_summary` header line
  entirely. "mock" backend values now display as "offline (built-in)" in the UI (the underlying
  config string is still literally `"mock"` — that's `AdversaryConfig`'s vocabulary, not ours to
  rename). Mic icon: emoji → stroke SVG.
- `ccfd76d` — **merged rollout/replay into the Perception tab** (not a new 5th tab): `run_live_loop`'s
  `on_attack` now also appends one `attacks.jsonl` row per attack, in
  `ants.studio.run.attack_row()`'s *exact* shape (imported from Daniel's `run.py`, not reimplemented
  — reading his public function is fine, editing his files is not). Served via
  `GET /attacks/<run_name>`. New Synthesizer/Adversary toggle in the Perception tab: Synthesizer side
  reuses the per-cycle detail-modal data (factored into `openCycleDetailModal()` so both places share
  it); Adversary side fetches `/attacks/<run>` live. **Graceful fallback**: a run folder with no
  `attacks.jsonl` (every run before this, or before the first attack) shows a plain "missing" badge,
  not an error. Rerun.io was investigated and intentionally not built — no existing integration
  anywhere in ANTS or ASPIRE, would need its own logging pipeline first; stays a separate future
  decision if ever pursued.
- `6e9b1ef` — **centered chat when empty** (claude.ai/new pattern): `#col-center.idle` centers the
  composer with a tagline ("What do you want to work on?") when `turnCount === 0`; the moment a run
  starts or any message/turn lands, it docks to the bottom. `restoreUiState()` checks this too, so a
  restored session with history never shows the empty centered state.
- `91ea899` — **Meta blue** (`#1877F2`, contrast-checked both ways) replacing the orange accent
  everywhere, including the logo/favicon. **Light/dark theme toggle** in the header (☽/☀), persisted
  to `localStorage` (`ants-studio-theme`), applied pre-paint via an inline `<head>` script so there's
  no flash.
- `8503b00` — **Scene prompt panel simplified**: legend removed, same info now lives as `title`
  tooltips directly on the SVG shapes; generation/repair toggle removed (was cosmetic — no backend
  distinction ever existed between those two); replaced with three independent layer checkboxes —
  **Position** (off by default, newly separable), **Size** and **Relationships** (both on by default,
  matching what was always shown) — each its own SVG `<g>` group. Pan (drag) + zoom (scroll-to-cursor)
  + double-click-to-reset via raw `viewBox` manipulation. SAM3/Agentview panels removed from the
  Agent Console's left column **only** — still fully functional in the Perception tab, unaffected.
  **Real bug found and fixed**: removing those panels left two dead IIFEs in `console.js` still
  referencing the deleted element ids, throwing on load and silently halting every script after them
  — including item B's centered-chat logic. Caught via screenshot + console-log grep.

## Sessions (added 2026-11-04)

One server start = one session folder `data/console_sessions/<sess-YYYYmmdd-HHMMSS>/` (git-ignored):
`session.json` (id, started, CLI config, incumbent; no secrets), `chat.jsonl` (every chat message:
role, case, ts; the agent reply is one row when it finishes), `events.jsonl` (every SSE event
broadcast) and `runs/run-<ts>/` (the loop's per-run folders, formerly `data/console_runs/`). The
navigator has a **New session** button: `POST /session/new` (409 while a run or an escalation
answer is pending) starts a fresh folder, clears the server's queued chat, broadcasts
`session_reset`; the page clears turns, usage, reply and the saved snapshot but keeps theme, column
and panel prefs. The old folder is kept. `--session <id>` resumes a folder. `GET /session` returns
the current id; `/runs` lists this session's runs plus older `data/console_runs/` ones read-only.
The incumbent program is a fixed file and the loop never writes it, so there is no incumbent state
to reset server-side.

## Known environment issue this session: headless-Chrome screenshot hangs

Starting around the theme/scene-panel commits, `google-chrome --headless=new ...` started hanging
indefinitely (GCM/network-registration related, unrelated to the page itself) across many flag
combinations (fresh `--user-data-dir`, `--disable-background-networking`, after killing stray chrome
processes). Reproduced independently by two different subagents and by me directly. When this
happens: don't keep fighting it past 2-3 attempts. Verify instead via direct inspection — curl the
page, check balanced tags/ids, brace-count CSS/JS, careful manual logic review — and say so honestly
in the commit message, same as commits `6e9b1ef` and later did. **Never run a bare `pkill chrome` or
`pkill -9 chrome`** — the permission system denied this mid-session for being too broad (it would
kill the user's actual browser window, not just test instances); only ever target headless test
processes specifically (`pkill -9 -f "headless=new"` or match the exact `--user-data-dir` used).

## Services for the real backend (`--backend cap_harness`) — currently DOWN, were up earlier

```
uv run python -m ants.orchestrator.preflight   # from the main checkout
```
As of the last check this session: ASPIRE/cap-harness/LIBERO config all `ok`, GPU free, but
`sam3`/`pyroki`/`curobo` services are **not listening** (they were started once, then died —
probably when their background shell session ended). Restart if continuing real-backend work:
```
cd ASPIRE && CUDA_VISIBLE_DEVICES=0 TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 \
  nohup scripts/supervise_services.sh --profile a5500 --providers sam3,pyroki,curobo \
  > /tmp/supervise.log 2>&1 & disown
```
Real rollouts cost ~40s+ wall-clock and real GPU time each — verify cheaply (file/log reads) before
spending one, per the discipline every subagent was given this session.

## Known, accepted limitations (not bugs — don't "fix" without re-deciding)

- Still true from before: mock backend is the default; this console only ever repairs a fixed
  incumbent (`examples/bowl_on_plate/policy.py`) — it has **never** driven System 1's initial
  generation. That's exactly what the next queued piece (item A, see below) is for.
- Sub-cycle granularity inside one System 2 attack is still not observable and never will be without
  editing `adversary/`'s internals (Daniel's package, needs his sign-off first).
- `cached_tokens` in the repair-detail modal is prompt-level caching, not "this repair was skipped."

## What's queued next (user's own stated order)

Three big pieces were identified; built in this order **C → B → A** (confirmed by the user):
- **C** (merged rollout/replay) — done, commit `ccfd76d`.
- **B** (centered chat) — done, commit `6e9b1ef`.
- **A** (not started) — the big one: a `/policy-dev` chat command/button that opens a wizard —
  attach a human demo video (file picker), describe the task, then the "skill" asks: synthesizer-only
  or with-adversary, budget/max-retries for each, and for the adversary specifically sampling
  strategy (random/uniform vs. Thompson — this setting **already exists** as `--eta`, `eta=1.0` is
  literally the uniform baseline, default `0.2` is Thompson+exploration; the wizard just needs to
  expose it as a friendly choice, not build new backend logic). **The user explicitly confirmed they
  want REAL initial generation** (DemoSpec extraction from the video via `tools/hurobo_demospec.py`
  or similar, System 1's actual `generator.py`/Muse Wonder writing v0 from scratch) — not a
  documentation-only stand-in. This is real, new, unscoped engineering — read
  `docs/studio/chat-field-design.md` and this file's git-log section above before starting, and
  expect to need to ask the user more clarifying questions as the shape of "attach video → generate"
  becomes concrete (where uploads are stored, how DemoSpec extraction is triggered/awaited inside a
  live server request, what "budget" maps to in `LoopRunConfig`/`MuseOrchestrator` terms, etc.).

Also still open from the earlier TODO pass, lower priority (`docs/studio/dashboard-todo.md`):
Synthesizer/Adversary tabs are still just stub iframes onto copied templates, not built out with
real content (constraint history, Thompson posteriors, attack history table, etc.).

## Quick resume checklist

1. `cd /home/eeschner/alfredo/workspace/ANTS-live-console && git log --oneline -5 && git status --short`
2. `cd /home/eeschner/alfredo/workspace/ANTS && git status --short` — decide about the uncommitted
   dashboard.py/test additions (the user's own files, see Correction above).
3. Confirm sync between checkouts (loop above) before trusting what's running.
4. `uv run python -m ants.orchestrator.preflight` if continuing real-backend work — services are down,
   see restart command above.
5. `uv run ruff check . && uv run pytest -q` in the worktree before trusting anything is clean.
6. Start item A, or ask the user what's next — everything here was built turn-by-turn from live
   feedback, there is no separate plan document beyond `docs/studio/dashboard-todo.md` and
   `docs/studio/chat-field-design.md`.

## `/policy-dev`: the full pipeline

Click the `/policy-dev` chip (it fills the input and enables `+`), choose a human demo video, type the task, press Enter. No question is asked and there is no confirmation; the cap below is shown when it starts. `+` opens the server's native dialog (`POST /pick-video`, zenity, at `hurobo/data/raw/e1/clips` or `--video-dir`) and returns a path with no upload. Without zenity or a DISPLAY it says so and uses the browser picker (`POST /upload`, stored in the session's `uploads/`), which cannot open at a chosen folder.

Defaults and limits: `docs/studio/skills/policy-dev.json`. Code: `src/ants/studio/policy_dev.py`, client `static/wizard.js`, route `POST/GET /policy-dev`. Stages, all in `<session>/runs/run-<ts>/` (`pipeline.jsonl` has every stage and exact command) and streamed as `pipeline_start`, `pipeline_stage`, `pipeline_output`:

1. **Preflight** `ants.orchestrator.preflight --muse-code`, plus a scan for another simulator job (two at once give fake depth failures). Failing spends nothing.
2. **Extraction** `hurobo/scripts/02_extract_demos.py` with the measured 5.75 cm marker, s10e intrinsics and `cuts.json`, into `demo/hurobo/`. Marker setup clips only; hurobo's `usable` verdict decides. A rejected clip stops the run, says why and offers a no-demo run; it never falls back on its own.
3. **DemoSpec** `tools/hurobo_demospec.py` to `demo/demospec.json`.
4. **Prompt** saved to `prompt_messages.json` before any spend.
5. **Synthesizer** `ants.orchestrator.demo_vs_nodemo`, one sample, demo arm (nodemo without a video), T 0.2, 4 repairs, seed 51, stock scene (the same scene the Adversary attacks), in `generation/`. The program is the latest attempt whose `record.json` trace has `task_success`, not the newest file. If none passed the run ends as `no_working_policy` and nothing is attacked.
6. **Adversary** the live `Loop` in the same run folder with `backend=cap_harness`, mock proposer, eta 0.2, 5 cycles, W = 2.

**Budget.** 300k Muse tokens in total (`--pipeline-token-budget`): generation may spend 150k, rewrites get `300k - generation spent - 50k`. Both budgets are checked before each call, so one call can overshoot; the 50k keeps one observed call (about 46k) of headroom. A single call above 50k could pass the total.

**Stop.** Kills every descendant of the server and keeps doing so until the run ends, so a gate replay cannot start a new rollout. Reported as `user_stop` in the console and in `pipeline.jsonl`; `loop.jsonl` and `summary.json` still hold Loop's own `budget` label, because Loop reads a killed rewrite as a spent budget.

Removed: the question-by-question wizard (`policy_wizard.py`), `/policy-dev setup`, `/cancel`, `/wizard`.

