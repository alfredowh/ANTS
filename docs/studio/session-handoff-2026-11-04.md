# Studio session handoff (2026-11-04, ends at the Stop button)

For the next agent (Opus). Covers only this session's work on the Studio console. Read `AGENTS.md`
first, then `docs/studio/live-console-handoff.md` (older, general), then this file.

## Where things live

- Worktree: `/home/eeschner/alfredo/workspace/ANTS-live-console`, branch `observability/live-console`
  (all commits are here; nothing pushed, no PR yet).
- Main checkout: `/home/eeschner/alfredo/workspace/ANTS`, branch `synthesizer`. It holds UNTRACKED
  hand-copied console files and the user's server runs from there. After every edit: `cp` the
  changed files from the worktree into the same paths in the main checkout (static files need only
  a browser hard reload; Python files and `views/*.html` need a server restart).
- Start the server (from the main checkout):
  `uv run python -m ants.studio.console --port 58910 --max-model-steps 6 --reasoning-effort medium`
  (it is currently running there, started in the background by the previous agent).
- Stop a server by pid: `kill $(ss -ltnp | grep ':58910' | grep -o 'pid=[0-9]*' | cut -d= -f2)`.
  Never `pkill -f` with a pattern that appears in your own command line: it kills your shell.
- Never edit Daniel's files: `template.html`, `build.py`, `run.py`, `orchestrator/`, `adversary/`.

## What the console does now (all committed on the worktree branch)

- Layout: claude.ai style. Navigator sidebar (tabs, session, stored runs), side columns collapsed
  to a 3 mm strip with 1 cm edge tabs, centered chat when idle, chat feed oldest-first (newest at
  the bottom), user bubbles right, agent left, turns capped at 5 lines with a per-turn
  "Show more", all fonts +2pt, Meta blue theme with light/dark toggle, UI says Synthesizer and
  Adversary (element ids still `sys1-*`/`sys2-*`).
- Chat commands (client side in `static/wizard.js`): `/policy-dev` or `/policy-dev run` starts the
  loop (no confirmation dialog any more); `/policy-dev setup` starts the guided wizard
  (`policy_wizard.py`, questions in `docs/studio/skills/policy-dev.json`); `/deploy` copies the
  highest accepted version of this session (else the incumbent) to `data/deploy/` (+ `latest.py`,
  `latest.json`); `/cancel` aborts the wizard. Chips for `/policy-dev` and `/deploy` sit under the
  chat field.
- Mic: Web Speech API button in the composer (Chromium only, audio goes to Google, needs
  localhost/https). Never tested with a real microphone.
- Session storage: `data/console_sessions/<sess-id>/` holds `session.json`, `chat.jsonl`,
  `events.jsonl`, `client_errors.jsonl` and `runs/run-<ts>/`. "New session" in the navigator
  (`POST /session/new`, refused while a run is active); `--session <id>` resumes.
- Stop: red Stop button next to the RUNNING pill (`POST /stop`): sets a stop flag, SIGTERMs all
  child processes (muse exec, ASPIRE, wizard generation; Linux `/proc` only) and unblocks a pending
  escalation. The loop ends within about a second with `stopped: "user_stop"`. Verified live once.
- Client errors: `window.onerror` posts to `/clientlog` -> `client_errors.jsonl` in the session.
  Check it first when the page "does nothing".
- One shared `/events` SSE connection per tab (two per tab exhausted Chrome's 6-per-site limit and
  made the page impossible to reload).

## Things to know / traps

- Real runs spend Muse tokens: about 46k tokens (about $0.63) per rewrite at $13.5 per million,
  capped by the dialog's token cap. `/policy-dev` runs the real backend, which needs services sam3 :8114, pyroki :8116, curobo :8118 and the
  GPU. A cuRobo replay job was running on the GPU during the session; not ours.
- A killed muse call is reported by the loop as a budget stop; `/stop` overrides the final `done`
  event to `user_stop`, but the per-cycle row still says `budget_stop` and the console may show the
  "Budget exhausted" banner. Cosmetic, not fixed.
- Headless Chrome and Firefox (snap) hang or fail on this machine, so none of the late UI work was
  seen in a browser. Layout fixes (chips, edge tabs) were made blind from the user's screenshots.
  Edge tabs use inline `!important` styles because the stylesheet width was ignored for an unknown
  reason (they rendered about 770 px wide). If you can get screenshots working, verify first.
- Stale tabs cause "nothing happens": the old JS stays loaded after a server restart. Hard reload
  (Ctrl+Shift+R) and close other tabs on the port.
- Chat feed: previously saved browser snapshots may still show the old newest-first order; "New
  session" clears them.

## Open work, in the order the user cares about

1. Done: the header run button is gone, see `docs/studio/ui-review-2026-11-04.md`.
2. Held subagents (rate limit reset was 18:50 Berlin): (a) Daniel-studio full-data run, owes
   `docs/studio/daniel-studio-merge-options.md` and `docs/studio/ask-daniel.md` (options for merging
   his dashboard into the viewer without changing his functionality, how to see it with full data,
   what to ask him); (b) old-dashboard review, owes `docs/studio/old-dashboard-review.md` (what the
   old Architecture/Perception/Agentic tabs show, keep/drop questions to the user, then merge the
   kept ones into the main UI).
3. Process-flow viewer (animated architecture, dev/production switch, click-to-drill-down, popup
   details from md files on all branches, links from the console). Design is in
   `docs/studio/process-flow-design.md` and `process-flow-blocks.json` (committed; layout
   coordinates are placeholders, event names need checking against the real SSE kinds including
   `awaiting_answer`, `run_started`, `stop_requested`, `chat_*`). Production view is static with a
   "not running" banner (decision D18: no deployment runtime).
4. Wizard launch is only partly real: an uploaded video cannot become a DemoSpec (no extractor,
   SAM 3.1 is a stretch goal); launch runs `ants.orchestrator.demo_vs_nodemo` and then the loop; the
   Adversary part uses the mock backend and mock model. `wizard.js` has never run in a browser.
5. Stored runs in the navigator are listed but cannot be loaded into the view yet.
6. Decide with the user what to do with the main checkout's uncommitted `dashboard.py`,
   `dashboard_template.html`, `tests/studio/test_dashboard.py` (the user's own; a layout agent
   overwrote two of them with committed versions once, check nothing was lost) and the untracked
   console files; then PR `observability/live-console` into `integration` (ask first; AGENTS.md git
   workflow applies, never commit to `main`/`integration` directly).

## Checks before any commit

`uv run ruff check . && uv run pytest -q` (last result: 315 passed, 3 skipped). Commit trailer:
`Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` (use the current model's name).
Experiment commands go in `docs/runbook/commands.json`, then `uv run python -m ants.evalkit.runbook
check` and `build` (never hand-edit generated files).
