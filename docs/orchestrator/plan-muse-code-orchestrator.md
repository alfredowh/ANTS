# Plan: a Muse-Code-driven orchestrator, a two-phase architecture, and the agentic dashboard tab

Status: **all four items built**, 2026-11-03. Read `AGENTS.md`, `docs/concept.md`,
`docs/architecture.md` and `docs/adversary/spec.md` first.

## Implementation log

1. **No-demo gets only a flat task description**: already true before this plan existed
   (`demo_vs_nodemo.py:80-81`, `args.task` defaults to `"put the bowl on the plate"`, no scene
   context unless a flag is passed). No change needed.
2. **Offline prompt-generator**: built. `src/ants/synthesizer/prompt_generator.py` +
   `src/ants/synthesizer/prompts/generate_task_template.md`. Verified live against clip 233832:
   reproduces the hand-coded `demo_section()` paragraph almost exactly (14,925 prompt / 2,317
   completion tokens, ~$0.23) -- the honest caveat is that this clip is also the worked example
   embedded in the md, so it confirms the guarantee but not yet generalization to a new task; that
   needs a second demo clip, not available yet.
3. **Muse-Code orchestrator**: built (see below, unchanged from the original plan). Verified live
   with one real cycle (42,947 tokens, ~$0.58): given a constraint in plain English, correctly
   diagnosed a hard-coded grasp offset and derived a ratio-based fix independently close to the
   real demo's own numbers.
4. **Dashboard**: built as one local page, `src/ants/studio/dashboard.py` +
   `dashboard_template.html`, three tabs:
   - **Architecture**: reads `docs/orchestrator/architecture_manifest.json` (hand-maintained, not
     generated from a run -- that generator does not exist yet) and renders it as a status grid,
     not the originally-scoped animated/highlighted flow; time did not allow more.
   - **Perception**: a link/instructions panel for ASPIRE's own Viser+MCP page
     (`http://127.0.0.1:8080`, started by `ASPIRE/scripts/start_system2.sh`) -- confirmed this is
     ASPIRE's existing real-YAM/LIBERO monitoring stack (SAM3 masks, cuRobo trajectories, collision
     spheres), not rebuilt. Likely the source of the two reference screenshots given earlier in
     this session.
   - **Agentic**: fully real. Renders whatever `MuseOrchestrator` already writes to disk for one
     cycle: token usage tiles, the WHY note, the Muse Code task-lifecycle trace, and the
     incumbent-to-candidate diff.

What did not get built, honestly: a generator that produces the architecture manifest from a real
run (so the "current block" cannot actually be highlighted yet), the recovery-skill module, and the
deployment monitor -- all still exactly as scoped below, all still open.

## What changed from the first pass

The original ask had four items: (1) a harder demo-vs-no-demo experiment, (2) an offline
prompt-generator module, (3) a two-phase (policy-development / deployment) architecture with the
orchestrator itself becoming a Muse-Code agent, (4) a full local dashboard with four tabs
(architecture-flow, perception/3D, agentic, plus whatever else). Mid-planning the user cancelled
the full dashboard build (a teammate already has one; work from their state instead of duplicating),
kept the Muse-Code-orchestrator work as the immediate build target, and asked for one small,
simple dashboard tab (agentic/reasoning trace only) instead of all four.

**Build order now: item 3 (orchestrator) first, item 4 scoped down to one tab, items 1-2 after if
time allows before the deadline.**

## Why Muse Code instead of the Meta Model API

Today System 1 and System 2 both call the Meta Model API directly (`src/ants/synthesizer/llm.py`,
`src/ants/adversary/models/meta.py`): one HTTP call in, one JSON reply out. The reply's "reasoning"
is a short, explicitly prompted 3-6 line "WHY:" note (`generator.py` lines 82-86) -- never a real
chain-of-thought. That is a hard API limit, not a prompting problem.

`muse` (Muse Code, installed at `~/.local/bin/muse`, v1.4.14) is Meta's own agentic coding CLI --
structurally the same kind of tool as the one running this session. Confirmed by a live smoke test
(`muse exec --json "..."`):

- `muse exec` runs one prompt headlessly and emits a JSONL event stream on stdout: task lifecycle
  events (`task.lifecycle.proposed/accepted/started/completed`), streamed output deltas
  (`run.output.delta`), a final `run.terminal.completed` event with the full answer text, and a
  `run.usage` event with `input_tokens`, `output_tokens`, `reasoning_tokens`, `cached_tokens`. The
  reasoning token count is visible per call even when the text itself is not -- the model used is
  `muse-wonder-1.0`.
- `--workspace <PATH>` roots policy-gated workspace tools (file read/write/shell) at a directory,
  the same shape as this session's own tool sandboxing.
- `--output-schema <FILE>` can shape the final answer as JSON (meta provider only) -- useful for
  getting a structured `{code, rationale}` reply instead of parsing markdown.
- `--preset ac_orch` exists as a named built-in preset (not yet inspected in detail; likely the
  closest built-in starting point for an orchestrator-shaped agent and worth reading before writing
  one from scratch).
- A trivial 5-word test cost 28,484 input / 187 reasoning / 202 output tokens. Muse costs about
  $13.5 per million tokens (per `docs/runbook/agent-access.md`). **Every real call is non-trivial
  cost; budget this explicitly, log it per call, and do not loop this uncapped.**

This directly replaces the open "if we can't get all the reasoning from the model API" fallback:
we are not reconstructing reasoning after the fact, we are switching the backend to one that
already exposes it.

## The two phases (becomes the orchestrator's operating context)

This section is meant to be saved as its own file (`docs/orchestrator/phases.md`) and fed to the
Muse-Code orchestrator session as context on every call, the way `AGENTS.md` is fed to this session.
Restated here first so the design is visible in one place before it is split out.

### Phase A: policy development (slow loop)

Runs once per new task, scene or embodiment, offline, until a policy is strong enough to deploy or
the token budget runs out.

```
prompt (human video | task text | teleop) --> System 1 generates program v0
   --> System 1 internal repair loop (caching happens here) --> policy candidate
   --> System 2 designs a measured harder scenario (NOT uniform random sampling --
       Thompson-sampled category + bounded severity, already built: planner/selector.py,
       perturbations/space.py) --> rollout --> track why it passed or failed
   --> feedback to System 1 --> new policy candidate --> repeat
until: confidently robust, OR token/cycle budget spent, OR a stall triggers human intervention
(decided by the orchestrator against explicit constraints: token budget, max loop count).
```

The "challenge only where the policy might actually fail, not randomly" idea is **already System
2's design**, not new: the Thompson-sampling category selector (`src/ants/adversary/planner/selector.py`)
picks the perturbation category whose posterior failure rate is highest, with an eta-uniform
exploration floor. What's missing is the orchestrator-level framing that ties this explicitly to
"Phase A" and a logged number showing it beats uniform sampling at equal rollouts (already flagged
as a gap in the `s2-training-free-harden-demo` storyline review).

**Missing piece, not yet built anywhere:** a *recovery module*. Today a repair either patches the
main policy's code (more branches, more retries, as seen in the no-demo bowl-grasp program) or fails.
The alternative -- generating a small, separately-callable recovery *skill* (e.g. "if grasp slip
detected, re-approach from the opposite rim point") instead of over-engineering the main policy body
-- has no code and no contract support yet. `contracts.types.Skill`/`SkillKind` (CODE/GUIDANCE)
already exists and is the natural home for this; a `SkillKind.RECOVERY` (or a `trigger_signature`
field on existing `Skill`) is the smallest contract change that would support it. Scope this as a
stretch goal, not part of the first orchestrator.

### Phase B: deployment (fast loop)

The accepted policy runs in production. Execution is perception-only -- simulator state is never
available at runtime, matching the already-logged decision d1 in `docs/storyline-discussion.md`
("adopt sensed, camera-based `locate`, not privileged sim state"). Simulator state is only ever used
*inside Phase A's repair loop*, for grounding and validation -- exactly what experiments 09-11
already do (`docs/synthesizer/experiment-09-11-curobo-attach.md`): cuRobo-planned trajectories and
SAM3 perception ground the repair reasoning; the sim never substitutes for perception at execution
time.

```
policy running in production --> orchestrator monitors (new failure signature observed,
   or a human flags one) --> orchestrator proposes re-entering Phase A for the new case
   --> needs human approval/supervision before committing compute
   --> if approved: Phase A re-runs IN PARALLEL, in simulation; production is NOT paused
   --> human decides: keep production running despite the known new failure case,
       or stop production, once Phase A has a candidate fix
```

No monitor or re-entry trigger exists in code today (the "checkpoint monitor" is listed as optional
in `docs/HANDOFF.md`). This is new-build, scoped below as "stretch" given the deadline.

## The first orchestrator: design

Smallest useful v1, built to slot into the **existing, tested** loop rather than replace it:

`src/ants/orchestrator/system2.py::harden()` already has a `Generate` callable slot:
`Callable[[Path, list[Constraint], list[dict]], tuple[Path, int] | None]`
(incumbent program, all constraints so far, failure feedback dicts) -> (candidate program path, tokens spent) or None on budget stop.
Today this is only ever filled by `tools/system2_mock.py`'s scripted fake. **The first orchestrator
is a real implementation of this exact slot, backed by `muse exec`.**

New module: `src/ants/orchestrator/muse_cli.py`
- `run(prompt: str, *, workspace: Path | None, output_schema: Path | None, max_model_steps: int | None, reasoning_effort: str = "high") -> MuseRunResult`
- Shells out to `muse exec --json --prompt-file <tmp> [--workspace ...] [--output-schema ...] --approval-mode never --max-model-steps <N>`.
- Parses the JSONL stream into: `final_text`, `usage` (input/output/reasoning/cached tokens),
  and `events: list[dict]` (the raw lifecycle trace, kept for the dashboard -- see below). A crash,
  non-zero exit, or malformed JSONL is a `MuseCliError`, never silently swallowed (matches the
  adversary spec's "the loop never crashes on the model" rule -- same discipline applies here).
- `--approval-mode never` and no `--workspace` (or a read-only one) for v1: the orchestrator asks
  Muse Code to **write** a program as text in its reply (shaped by `--output-schema`), not to edit
  files directly on disk -- keeps the blast radius identical to today's `llm.py` calls and avoids
  needing to reason about Muse Code's own tool-approval/sandbox semantics under a deadline.

New module: `src/ants/orchestrator/muse_orchestrator.py`
- `generate(incumbent: Path, constraints: list[Constraint], feedbacks: list[dict]) -> tuple[Path, int] | None`
  -- the literal `Generate` type `harden()` expects.
- Builds one prompt: `docs/orchestrator/phases.md` (Phase A/B context) + the incumbent program text +
  each constraint's `when_to_apply`/`rule` + each feedback dict, asks for a repaired program.
- Token budget checked before every call (same `BudgetExceeded` pattern as `llm.py`); on budget
  exhaustion, returns `None` so `harden()` already knows how to stop cleanly -- **no change needed
  to `harden()` itself**.
- Writes the candidate program to disk, logs the full Muse event trace next to it (one JSONL file
  per cycle, same convention as `system2.jsonl`) so the dashboard has something to read.

**v1 test plan**: wire this into one real `harden()` cycle against the exp01 bowl-on-plate program,
with a tiny `tests_per_cycle` and a hard token cap, before trusting it for a live demo. This doubles
as the "one real cycle" de-risking step the storyline review already recommended.

## Item 4, scoped down: one dashboard tab

Not the four-tab dashboard. One local, self-contained HTML page (same style as
`ants.studio`/`evalkit.report` -- static HTML plus injected JSON, no server, no new dependency),
showing only the Muse-Code orchestrator's trace for one or more cycles:

- A timeline of `task.lifecycle.*` events (what Muse Code did, in order).
- The reasoning/output/cached token counts per call, and running total against the budget.
- The final program diff (incumbent vs. candidate) and the constraints/feedback that were in the
  prompt, reusing `unified_diff` from `evalkit/runlog.py`.
- Nothing 3D, nothing live/streaming for v1 -- reads a saved JSONL trace after the fact, same as
  every other viewer in this repo today.

Architecture-flow and perception tabs: deferred. Before building anything here, read the
teammate's existing dashboard (ask where it lives) so this stays additive, not a duplicate.

## Items 1 and 2 (after the orchestrator, if time allows)

1. **No-demo gets only a flat task string** ("stack the bowl on the plate"), no scene/demo context
   at all -- a small change to `demo_vs_nodemo.py`'s no-demo arm prompt construction.
2. **Offline prompt-generator module**: samples a few frames from the human video, reads the hurobo
   demospec JSON, and makes one Muse Spark call (not Muse Code -- this is an offline authoring step,
   not an agentic one) to produce a task-specific prompt template. Must reproduce today's hand-coded
   `generator.py::demo_section()` field shape as its correctness baseline. The Muse task instructions
   live in their own md file (e.g. `src/ants/synthesizer/prompts/generate_task_template.md`), written
   from the current bowl-on-plate template so the guarantee is checkable. Runs offline by default;
   note in the module that it can also run online (same call, no code change, just invoked at a
   different time) if a task needs to be prepared just-in-time instead of ahead of a run.

## Open questions / assumptions going into implementation

- `--preset ac_orch` has not been inspected yet -- read it before writing prompts from scratch, it
  may already shape exactly the orchestrator role being designed here.
- Whether `muse exec`'s `--output-schema` reliably returns valid code in a JSON field (vs. markdown
  prose) is unverified -- test on the first real call, fall back to markdown-code-block extraction
  (`generator.py::extract_code` already exists and is reusable) if not.
- Cost per cycle is unknown until the first real run; log it from call one so the demo's "cost per
  accepted program" question (flagged as missing in the earlier storyline review) finally has a
  number.
