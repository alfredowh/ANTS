# Orchestrator: agent spec

## What this package is

The closed loop of ANTS: System 2 attacks the incumbent policy, each failure becomes feedback for
System 1, System 1 writes a candidate, and the regression gate keeps it only if nothing got worse.
It is the only package that knows both systems. Owner: Daniel (D3). The loop, gate and human gate
are ported from System 1's `harden()`, `regression_gate` and `human_gate` (branch `synthesizer`),
moved onto the `Adversary` facade and the shared contracts.

## Hard rules

1. **Contracts and public APIs only.** Import `ants.contracts`, `ants.adversary` (the `Adversary`
   facade and its config) and System 1 only through `Synthesizer`. Never import a system's internals.
2. **The gate is one pure function** (`gate.py`). Strict rule: no worse on every case seen so far and
   better on at least one; outcomes, not booleans (a candidate crash where the incumbent passed is a
   regression; an incumbent crash is not a pass; a missing result never passes). The mode
   (`strict` or `off`) is in every decision.
3. **Only acceptance cases reach System 1.** Every case the loop builds is `Split.ACCEPTANCE`, and
   `Feedback` refuses a held-out case. Held-out evaluation (`heldout.py`, to move to `evalkit/` if System 1 prefers) builds its own
   `Split.HELD_OUT` cases and a backend that can only run held-out seeds; its results never reach
   System 1.
4. **Everything is logged.** One JSONL line per cycle with every input of every decision (attack,
   signature, constraint, diff, gate outcomes per case, stalls), each accepted version on disk.
5. **No result from fixtures.** `PatchSynthesizer` and the mock world prove the loop logic; numbers
   in any write-up come from the real synthesizer on the cap_harness backend.

## Layout

```
orchestrator/
├── gate.py         gate(), GateDecision, GATE_MODES; regression_gate() keeps System 1's boolean form
├── synthesis.py    Synthesizer protocol; GenerateSynthesizer (System 1's Generate, e.g. MuseOrchestrator);
│                   PatchSynthesizer test fixture, MOCK_WORLD_PATCHES
├── loop.py         Loop, LoopConfig, LoopResult: one attack per cycle, gate, stall, escalation
├── human_gate.py   a person's text answer to an escalation becomes a constraint (System 1's)
├── workflow.py     load_workflow(), workflow_info(): docs/orchestrator/phases.md, version + hash logged
├── preflight.py    GPU-run readiness: ASPIRE, launcher, services, GPU, disk, key, muse CLI; --smoke
├── heldout.py      held-out evaluation of v0 and final (Split.HELD_OUT cases, ASPIRE seeds 1-50)
└── run.py          CLI + run_loop(): logs in the studio format and builds studio.html
tests/orchestrator/ test_gate.py, test_loop.py, test_workflow.py (md names match the loop's)
```

## One cycle

1. `Adversary.attack(incumbent)`; a success only updates System 2's beliefs (stop if robust).
2. A task failure becomes an acceptance `CaseSpec` (in F_n) and a `Feedback`; its constraint joins
   the context once per failure signature.
3. `Synthesizer.rewrite(incumbent, feedback, constraints)`; None means the budget is spent.
4. The candidate replays every case (nominal acceptance cases + F_n); the incumbent's stored
   outcomes are reused (exact for deterministic backends).
5. Accepted: new incumbent, stalls reset; System 2's per-version history restarts its beliefs.
   Rejected: the signature's stall count grows; at W = 3, escalate (ask a person once if
   `ask_human` is given, else stop).

Policy stages: draft → attackable (passes its nominal cases) → incumbent (accepted by the gate) →
certified (System 2's stop rule met). A draft that fails its nominal cases is never attacked
(`no_working_policy`, escalation).

## Workflow file

`docs/orchestrator/phases.md` is the one workflow file, written for the repair model: System 1's
operating context (Phase A / Phase B, program rules) plus the loop's own rules (steps, gate,
escalation, stop reasons). `MuseOrchestrator` sends it at the top of every rewrite prompt
(`load_workflow()` returns the same text). `loop.py` executes the same steps; `test_workflow.py`
fails if the file stops naming a stop reason, decision or log event the loop uses, or if it is no
longer the file `MuseOrchestrator` sends. The model reads the workflow but never runs it: the gate, the split, the severity
bound and the budget stay in code. Change the workflow by editing the file and bumping its
version; the version and hash are in every `loop.jsonl` start line.

## Observability

`uv run python -m ants.orchestrator.run --cycles 30` writes `loop.jsonl`, `attacks.jsonl` (studio
rows), `history.jsonl`, `policies/`, `summary.json` and `studio.html`. `summary.json` also has the cost: rewrite
tokens and $ (per rewrite and total, from System 1's counts), System 2's Muse Spark tokens, the
total and the $ per cycle, at `--usd-per-million-tokens` (default 13.5, the observed Muse price). The studio's Versions tab
shows the version history (motivating constraint, gate verdict, diff per accepted version), every
gate decision with the cases it fixed and broke, and escalations; each attack in Replay shows the
version it hit and, for failures, the rewrite and its verdict. Read-only: it never feeds back.

## Next

- System 1 has two real plugs, both sending `phases.md`, both selected in `run.py` with an explicit
  `--synth-token-budget N`: `--synthesizer muse-code` (`MuseOrchestrator`, Muse Code via the `muse`
  CLI, through `GenerateSynthesizer`; about 43k tokens per rewrite observed) and `--synthesizer
  muse-api` (`default_synthesizer()`, Muse Wonder via the Meta API; needs `META_API_KEY` and the
  ASPIRE checkout, no `muse` CLI). Tokens and $ per rewrite are logged either way.
- Grow `phases.md` step by step (deployment loop with human approval, recovery skills) as each
  step gets code behind it.
- Several rollouts per case for `Policy.deterministic=False`.
- Skill admission after a gate pass (cut for the hackathon).
