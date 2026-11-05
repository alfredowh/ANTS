# Live process-flow panel

The panel above the chat feed in the Synthesizer view of ANTS Studio. It shows the policy dev pipeline as blocks, in the style of the `#dev-flow` view of the ANTS Dev artifact, but driven by real events instead of scripted playback. Code: `src/ants/studio/static/flow.js`, `flow.css`. Data: [`process-flow-blocks.json`](process-flow-blocks.json), served as `/static/flow_blocks.json`. Vocabulary: Synthesizer, Adversary, Orchestrator.

## Layout

Top row: Human video, Extract demo, DemoSpec, Build prompt, Muse writes program, Nominal check. Second row, right to left: Adversary attack, Diagnose failure, Muse rewrites, Regression gate, Save to deploy. Third row: Experience memory (planned), Ask a human. The dashed loop edge goes from the gate back to the attack and moves while the loop is active.

Block states: idle grey, running pulsing accent, running inferred (dashed), done green, failed red, skipped dim, planned dashed (never lights up). A block shows the cycle it last ran in (`c2`) and its last detail. The panel collapses to one 36 px line with a state dot per stage; the choice is remembered.

## Drill-down

A block with `▸` opens its sub-blocks, with a breadcrumb back. Clicking any block shows its description, "how we know", code and docs under the canvas.

- Extract demo: hand tracking, marker poses, grasp and release.
- Muse writes program: model call, static checks, debug rollout.
- Adversary attack: selector, proposer, sandboxed rollout, failure history.
  - Sandboxed rollout: mock world, cap_harness backend.
    - cap_harness backend: `localize_object`, `generate_grasps`, `move_to_pose`.

## What each event proves

| Event | Effect | Strength |
|---|---|---|
| `pipeline_stage` `{stage, status, detail, cycle}` | that block's state; ids `video extract demospec prompt generate nominal attack diagnose rewrite gate deploy` | live |
| `run_started` | new run. Without earlier `pipeline_stage` events the pre-loop blocks show "skipped: not in this run" | live |
| `loop_event` `start` | Nominal check running (the row is logged just before the nominal rollouts) | live |
| `attack_event` | attack done and nominal passed; failure: diagnosis done, rewrite running (fires just before the rewrite call) | live at the end of the call |
| `loop_event` `cycle` | rewrite result and gate verdict; attack and diagnose confirmed | after the fact |
| after a `cycle` row, no `end` row within 0.8 s | next attack running, dashed | **inferred** |
| `loop_event` `no_working_policy` | Nominal check failed | live |
| `loop_event` `escalate`, `awaiting_answer`, `human_answer` | Ask a human running, then done | live |
| `stop_requested`, `done` with `user_stop` | running blocks fail with "stopped by user" | live |
| `done`, `loop_event` `end` | nothing runs any more | live |
| `error` (except logging failures) | running blocks fail | live |
| `session_reset` | panel clears | live |

## Honest limits

1. `Adversary.attack()` is one synchronous call, so selector, proposer, rollout and history share one grouped state. Diagnose can only be shown once the call returned.
2. No event marks the end of the nominal check or the start of an attack. Between `start` and the first `attack_event`, Nominal check stays lit even when the first attack is already running.
3. The gate replay runs inside `Loop` with no event, so the rewrite block stays lit through it and the gate shows only its verdict.
4. In the loop, `muse exec` lifecycle events are not forwarded (only single mode has them), so a rewrite is one long running state.
5. A verdict stays visible during the next inferred attack, and clears at the next `attack_event`.
6. SSE does not replay. After a reload the panel restores its snapshot from `localStorage`; if the server is idle, running blocks are cleared. Events missed during the reload are not recovered.
7. The cap_harness sub-blocks never light up: nothing reports the primitive calls live. Which backend ran is only in `run_started`.
8. There is no production view, because no deployment runtime exists (decision D18).

## Checks

`tests/studio/test_flow.py` keeps the data truthful: every stage has a block, the hierarchy is consistent, planned blocks cannot light up, attack steps are grouped, and code and doc references exist (`hurobo/` is a submodule and is skipped). The state logic in `flow.js` has no unit test because there is no JS runner in this repo; it was checked by driving a real server's `/events` stream in headless Chrome.
