# Process-flow viewer: design spec

Builder-ready spec for a Studio view that shows the ANTS architecture and where a run currently is. Data: [`process-flow-blocks.json`](process-flow-blocks.json). Vocabulary: Synthesizer, Adversary, Orchestrator (never System 1/2).

## 1. Reference design (artifact `#dev-flow`)

- Nodes (`.nd`) on a grid (column/row), edges (`.ed`) between them, loop-back edges drawn distinct.
- Each node has sub-chips (`.dp-sub`) with `.act` (active) and `.past` (done) states.
- Playback is stepped: `scenariosDev()` defines steps, `buildCanvas()` lays out, `applyStep()` toggles states.
- Respects `prefers-reduced-motion`.
- Our version replaces scripted playback with real events, and the grid with the `layout` map in the JSON (x, y, w, h per mode).

## 2. Event to block activation

Console events: `loop_event` (rows from `loop.jsonl`: start, cycle, escalate, human_answer, no_working_policy, end), `attack_event` (fires after `Adversary.attack()` returns), Muse task events (`task_*`), `chat_*`, `done`, `error`, and `perception_*` (cap_harness only).

| Signal | Block state | Honesty |
|---|---|---|
| `start` | orchestrator active | live |
| cycle begins (previous cycle row, or start) | adversary active until `attack_event` | live at block level only |
| `attack_event` | adversary done; if failure, synthesizer (repair) active | live |
| Muse `muse_event` (payload_type task.lifecycle.started) / `muse_event` (payload_type task.lifecycle.completed) | repair active / done | live |
| `cycle` with `decision` | gate flashes accepted / rejected / no_failure / budget_stop | after the fact (the gate runs inside `Loop`) |
| `escalate`, `human_answer` | escalation active, waiting on human | live |
| `end`, `done` | report | after the fact |
| `perception_*` | perception active | live, cap_harness only |
| adversary children (selector, proposer, rollout, diagnoser) | filled in from the attack record | after the fact |
| memory, admission, all production blocks | never active | static |

Each block's `live.signal` in the JSON carries this classification; render `after_the_fact` and `static` visibly different (e.g. hatched border, "static" tag).

## 3. Drill-down

- Top level shows blocks with `parent: null`. Click a block with `children` to replace the canvas with its children (breadcrumb above: Overview > Adversary). Click a leaf to open the detail popup.
- Parent activity = any child active.
- Child layout: auto grid if the JSON `layout` has no entry for them.

## 4. Description and popup

- While a block is active, show its `summary` (at most 2 sentences) in a strip under the canvas, with a "More" button.
- "More" opens a popup: `details`, status chip (built / partial / planned), branches, code paths, and doc links.
- Docs: list `docs[]`. The server serves a whitelisted route `GET /docs/<path>` that returns only files listed in the JSON, read from the working tree (the doc may live on another branch, see section 7). Render the heading section as plain text.

## 5. Dev / Production switch

A segmented toggle in the view header selects `mode`. Production shows only the `production` layout and a banner: "Concept only, no runtime exists (D18)". It never shows live state.

## 6. Links from the main console

- A "Process flow" button in the nav (next to Perception).
- The flowline badges (Adversary, Synthesizer, Orchestrator, Escalation) become links that open the viewer drilled into that block.
- The viewer subscribes to the same `/events` SSE stream, so it needs no new data.

## 7. Honest limitations

1. `Adversary.attack()` is one synchronous call: selector, proposer, rollout and diagnoser cannot be shown live separately.
2. No production runtime exists. Production is a static concept diagram.
3. The gate, stall and stop decisions are only visible from the cycle row, after the fact.
4. Initial generation, memory and skill admission are not driven by the console.
5. Some docs and code exist only on other branches (`synthesizer`, `integration`, `feature/orchestrator`, `feature/system2`); the JSON lists the branch. Verify the paths before linking. A doc missing from the working tree must show "not on this branch".

## 8. Recommended minimal server additions (separate from the viewer)

- `GET /docs/<path>`: whitelisted from the JSON, UTF-8 text, 404 otherwise.
- `GET /process-flow/blocks.json`: serves the JSON.
- Optional: `cycle_start` SSE event emitted before `Adversary.attack()` so the adversary activates at the true start. This is a change to the loop call site, so ask Daniel first.
