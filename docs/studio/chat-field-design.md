# Chat field in the Agent Console: design (draft, not built)

Written to be reviewed and corrected, not implemented yet. Covers: the visual reference, where it
sits relative to the columns we already have, and — the part that actually needs deciding — what
happens on the System 1/System 2/Orchestrator side when a new chat message arrives. Nothing here is
final; sections marked **OPEN** need an answer before building.

## Visual reference

Claude Code's own web composer (the bar at the bottom of claude.ai/code): a single rounded pill
input, a `+` icon on the left (attach), a mic icon on the right, placeholder text ("Type / for
commands"), with the model/effort picker as a separate small control to its right, outside the pill.
What we take from it is **just the input field itself** — the rounded pill, icon placement, subdued
placeholder — not the surrounding sidebar/session-switcher chrome, which doesn't apply here.

## Where it goes (left/right columns unchanged)

The console today (`console_template.html`) is three columns:

- **Left** (`#col-left`): Primitives (chips, click → popup), Scene prompt (2D illustration,
  generation/repair toggle), SAM 3 output (archived gallery), Agentview frames (archived gallery,
  "Open perception replay" link into the Perception tab). Unchanged by this.
- **Center** (`#col-center`): incumbent name, the blocking-state banner, the turns feed
  (`#turns`) — newest-first, fed by SSE (`muse_event` / `loop_event` / `attack_event` / `done` /
  `error`).
- **Right** (`#col-right`): Loop config tiles, Orchestrator/System 2 tool chips, Usage tiles,
  Reply/summary box.

The chat field is a new fixed bar **docked to the bottom of the center column**, below the turns
feed (which becomes a scrollable region above it, same way a normal chat UI keeps the composer
pinned and the transcript scrolling). It does not touch the left or right columns — a chat message's
*effects* (see below) show up as new turns in the same feed and the same status-bar pipeline
(System 2 → System 1 → Orchestrator → Escalation) already built, not as a separate UI area.

## The actual open question: what happens when a message comes in

The console already has two real, existing mechanisms a chat message could plug into. The flow
below is the proposed default — **OPEN: confirm this is what you want**, because the three cases
genuinely behave differently and picking wrong means re-plumbing later.

```
new chat message arrives
        |
        v
  is the loop currently ESCALATED
  (orchestrator badge = "blocked: escalated",
   the red banner is showing)?
        |
   yes -+-------------------------------------------+
        |                                            | no
        v                                            v
  treat the message as the human's answer     is a run currently ACTIVE
  to that escalation. Wire it through the      (System 2 attacking or
  orchestrator's real human_gate mechanism:    System 1 writing, i.e. the
  GateAnswer("text", message) ->               sysbar shows an active node)?
  answer_to_constraint() -> the stalled              |
  signature's constraint list, loop resumes.    yes -+----------------+
  This is the one case with a real, already-         |                | no
  built destination (orchestrator/human_gate.py) --  v                v
  Loop already accepts an ask_human callback,   queue the message,    run it as a one-shot
  just never wired to anything live yet.        show "queued -- will  Muse Code call, same
                                                 send once the        mechanism --mode single
                                                 current step ends"   already uses
                                                 in the composer.     (stream_muse_exec),
                                                 Don't interrupt a    streamed into the turns
                                                 blocking muse exec   feed tagged "chat" (a
                                                 or attack() call     new turn class, visually
                                                 mid-flight.          distinct from "cycle").
```

### Case 1: answering an escalation (real mechanism exists)

`Loop(adversary, synthesizer, config, ask_human=...)` already supports this — `ask_human` is a
callback of type `Callable[[Mapping], GateAnswer | None]`, called at most `max_human_asks` times
(default 1) when a signature stalls `stall_window` cycles. `run_live_loop` in `console_server.py`
never passes one today, so a real escalation just stops the loop (`stopped: "escalate"`) with no way
to answer from the UI. Wiring the chat field to this means: when escalated, the server holds the
loop thread blocked inside the `ask_human` call, waiting; the chat message's text becomes
`GateAnswer("text", <message>)`; the loop resumes, `human_answer` gets logged in `loop.jsonl`
(already a known event type the turns feed handles), and the constraint joins the permanent list.
**This is the highest-value case to build first** — it is the only one where "what should happen to
the processes" has a real, pre-existing answer, not a new design.

### Case 2: a run is active (queue, don't interrupt)

Both `Adversary.attack()` and the `muse exec` rewrite call are blocking, synchronous, real
subprocess/HTTP calls — there is no safe way to interrupt one mid-flight without corrupting state
(same reason the Run button disables itself during a run today). **OPEN**: should a queued message
just wait for the *next* cycle boundary and then do nothing automatically (sit in the input as a
draft) unless the user re-submits, or should it auto-fire as a Case-3 one-shot the moment the run
goes idle? Proposed default: auto-fire once idle, since otherwise typing while a run is active is a
dead end that looks broken.

### Case 3: idle, free-form (reuses existing mechanism)

When nothing is running and nothing is escalated, a chat message is just a one-off prompt to Muse
Code — exactly what `--mode single` already does (`stream_muse_exec`, no `Loop` involved at all).
**OPEN**: should this see the current incumbent program as context automatically (so "why does it
grasp from the left?" can be answered), or should it be truly contextless unless the user pastes
code in? Proposed default: always include the current incumbent + active constraints in the prompt
(cheap, already have the text), so questions about "the current state" work without extra typing.

## What this explicitly does not do (yet)

- Does not let a chat message change loop *configuration* (cycles, budget, categories) mid-run —
  that stays a server restart with new CLI flags, same as today.
- Does not give chat a way to abort/pause a running cycle — ties into the same "no safe interrupt"
  limit as Case 2.
- Does not persist chat history separately from the turns feed/localStorage snapshot already built
  — a chat turn is just another entry in the same feed and gets saved/restored the same way.

## Questions to answer before building

1. Confirm the three-case flow above, or correct it.
2. Case 2: queue-and-wait vs. auto-fire-when-idle?
3. Case 3: always inject incumbent+constraints as context, or not?
4. Visual: pill input pinned at the bottom of the center column only, or should it float above all
   three columns (more like the reference screenshot, which has no columns to its sides)?
