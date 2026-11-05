# ANTS Dashboard: feature to-do

Naming: **Dashboard** is the umbrella app (`uv run python -m ants.studio.console`, despite the
module name). It currently has one tab, **Agent Console** (the turns feed + run button + status
pipeline), plus a Perception tab started but unfinished. The items below are the other windows the
dashboard should grow, in roughly the priority discussed, each noting what's already built to build
on vs. what's genuinely new. See `docs/studio/live-console-handoff.md` for exact commit history and
known limitations (mock backend, no sub-cycle granularity inside one System 2 attack, etc.) — don't
re-litigate those here, build within them unless a specific item below says otherwise.

## 1. Agent Console — mostly built, finish what's open

- [ ] **Resume the stalled real-backend wiring.** A subagent got through 3 commits
  (`1b89267`, `bfb52af`, `0979e1b`) wiring `--backend cap_harness` into the Perception tab before
  hitting the account rate limit. It found real rollouts write data to disk correctly but the SSE
  `perception_*` events aren't reaching the browser — a wiring bug, debuggable from data already on
  disk, no new GPU spend needed. Resume this first; it's the closest thing to done.
- [ ] **Chat interface.** A free-text box to send an arbitrary prompt to Muse Code and see the
  streamed reply, independent of the repair-cycle flow. Mostly reuses existing machinery: the
  original `--mode single` path already does exactly this mechanically (`stream_muse_exec`, SSE
  `muse_event` handling, turns rendering) — mainly needs a UI entry point (text box + send) and a
  server route that doesn't require the gate confirmation to be about "the policy development
  phase" specifically. Low effort, high value — good next pick.
- [ ] **Per-cycle detail modal → richer.** Already shows WHY, diff, token/cache breakdown. Could add:
  the full rendered prompt sent to Muse (not just the reply), and the raw `trace.jsonl` task
  lifecycle for that one cycle (currently only shown live during a run, not retrievable after).

## 2. Synthesizer (System 1) detail window — new

A dedicated panel/tab showing System 1's internals beyond "System 1: writing repair (muse exec)":

- [ ] Live view of the actual prompt being built right now (phases.md + incumbent + constraints +
  feedback) — the console already *has* this text (`build_prompt`/`MuseOrchestrator._build_prompt`),
  just never surfaces it before the call completes.
- [ ] Constraint history: every constraint accumulated so far this run, in order, with which
  failure signature produced it (`loop.jsonl` already logs this per cycle — needs a dedicated view,
  not buried in individual cycle turns).
- [ ] Version history: every accepted policy version with its diff from the previous one, separate
  from the live turns feed (which mixes accepted and rejected attempts in one stream).
- [ ] Token/cost running total and budget burn-down as its own small chart or bar, not just a tile
  that updates per-cycle.

## 3. Adversary (System 2) detail window — new

- [ ] Thompson selector state: current posterior (α, β) per category, visualized (even a simple bar
  per category showing failure-rate belief) — `Adversary` already tracks this internally
  (`FailureHistory`), just not exposed to the console today.
- [ ] Attack history table: every attack this run, category/severity/outcome, sortable/filterable —
  currently only visible as scattered turns in the main feed.
- [ ] Stall tracker: which failure signatures are how many cycles into their W=stall_window budget,
  so you can see an escalation coming before it happens, not just after.
- [ ] Diagnoser output detail: mode/root-cause/confidence per failure, not just the one-line summary
  currently shown in cycle turns.

## 4. Interactive architecture / dev-flow block diagram — new, bigger lift

Referenced: https://claude.ai/artifact/C3NqC3ij7jDMMtEqfzdaFp#dev-flow and `#architecture`. Already
investigated once (see `live-console-handoff.md` commit `48b0245`): that artifact's node/edge data
lives in its own artifact database, not static HTML, so there's nothing to literally port — and the
honest constraint is that this console only has 3-4 distinguishable live states (System 2 attack /
System 1 rewrite / Orchestrator gate / Escalation), not fine-grained sub-module steps, because
`Adversary.attack()` runs its 4 internal steps synchronously inside one call.

- [ ] **Decide scope before building**: a full drag/edit block-diagram editor (like the referenced
  artifact's `#architecture-editor`) is a different, much bigger thing than a *live-highlighted*
  read-only flow view. Recommend starting read-only, matching the real data this console has (the
  pipeline strip from commit `48b0245` is the v0 of this — the next step is making it richer/bigger
  as its own tab rather than a thin status bar), not a general-purpose diagram editor.
- [ ] Node detail on click: clicking "Orchestrator" shows the gate's actual rule, its last decision
  and why, not just a status word — pulls from already-logged `loop.jsonl` gate rows.
- [ ] If sub-module detail is wanted badly enough to be worth it: the only way to get real
  selector/proposer/rollout/diagnoser granularity is instrumenting inside `adversary/` itself
  (Daniel's package) to emit progress callbacks — flag this with him before attempting it, per
  `AGENTS.md`'s ownership rules. Don't fake granularity that isn't real.

## 5. Realtime 3D/2D robot / perception view — lower priority, partially started

Already has: archived agentview scrubber, SAM 3 reference gallery, embedded cuRobo plan-viewer
iframe, all with honest archived/live/missing badges (commit `4fedf2d`). Real-time wiring is exactly
item 1's stalled work — once that SSE bug is fixed, this *is* the live view, not a separate build.

- [ ] Finish the real-backend live streaming (see item 1).
- [ ] Once live frames stream in, add the layer-toggle richness already designed for the archived
  version (SAM3 overlay on top of the live frame, not just a side gallery).
- [ ] Scene understanding tied to the *specific* repair attempt in progress (S4 initial vs. E1-E3
  evidence per cycle) — proposed in `docs/synthesizer/proposal-collision-context.md`, not built
  anywhere yet, real engineering (needs the evidence pipeline wired into `aspire_backend.py`, see
  that doc's effort estimate from earlier this session).

## Suggested order

1 (resume stalled work — cheapest, closest to done) → chat interface (cheap, high value) → 2 and 3
(both reuse already-logged data, no new backend work) → 4 (scope-decide first) → 5 (gated on 1).
