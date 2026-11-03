# Plan: where a human video should beat the task text (longer-horizon tasks)

Plan written 2026-11-01. **Nothing here has been run; there are no results.** Numbers below are either from logged runs (cited) or marked as estimates.

## 1. Why this plan exists

- The risk is already in our notes: a frontier coding agent solves plain LIBERO pick-and-place with **no demonstration** (ASPIRE v2: 99% on 80 LIBERO-Pro tasks with a frontier model), and our sibling project found a written text spec matched video for strong models ([discussion.md](discussion.md) §0 point 4, §3.5). Q1 asks the right question: *what does the demonstration tell the policy that the task text does not?*
- Our own runs say the same: experiment 01 (demo 1 of 2 samples solved, no demo 0 of 2) was **not reproduced** in [experiment 02](experiment-02-scaled-scene.md) (each arm 1 of 3). `docs/concept.md` already says the claim is the loop, not demo-to-program.
- So the human video must be tested where it carries information the text cannot, and the test must be able to fail. The six places a demonstration has to earn its place are in [discussion.md](discussion.md) §6: under-specified instructions, grasp choice, order and multi-step structure, path shape, cost to robust, weaker generators.

## 2. The design in one paragraph

Pick tasks with **several subgoals** (longer horizon) where the video fixes something the instruction leaves open. For each such task record **two videos that differ in exactly one factor** (order, side of placement, grasp part). Same instruction, two videos, two correct behaviours. A text-only policy can match at most one of them by luck; a policy that really uses the video must follow whichever video it is given. Add a **wrong-video control** and a **numeric-text control** so the result cannot be explained by convenience or leakage.

## 3. Tasks: a horizon ladder

Task names below are the `libero_10` and `libero_90` files in `ASPIRE/third_party/LIBERO-PRO/libero/libero/bddl_files/` (checked). Task ids inside a suite are **not** checked: read them from ASPIRE's registry (`src/cap_harness/libero/registry.py`) before running. The runner already takes `--suite --task-id --task` ([demo_vs_nodemo.py](../../src/ants/orchestrator/demo_vs_nodemo.py)).

| k | Task (suite) | What the video should carry that the text does not (hypothesis) | Counterfactual pair |
|---|---|---|---|
| 1 | bowl on plate (`libero_goal_swap`) | Rim pinch at 1.05-1.26 bowl radii, 5.5 cm high (4 hurobo clips, exp. 01) | none (done) |
| 1 | pick up the book, place under the shelf (`libero_90:89`) | Edge grasp, book tilted about 63 degrees while carried (50 LIBERO demos, `data/demospecs/libero_book_under_shelf.json`); ASPIRE reports no model found this | none |
| 2 | white mug on the plate, then chocolate pudding to the right of the plate (`libero_10`, LIVING_ROOM_SCENE6) | How far "to the right" is, pudding orientation, mug grasp (handle or rim), order | pudding on the right vs in front |
| 2 | both the alphabet soup and the cream cheese in the basket (`libero_10`, LIVING_ROOM_SCENE1; also SCENE2 pairs) | Which object goes first (second may be blocked by the first) | order A then B vs B then A |
| 2 | turn on the stove, then put the moka pot on it (`libero_10`, KITCHEN_SCENE3) | Knob turn direction and amount, and that the stove must be on first | none needed: order is forced |
| 2 | bowl in the bottom drawer, then close it (`libero_10`, KITCHEN_SCENE4; ASPIRE has an oracle for `libero_10_swap:3`) | Rim grasp, placement inside, push path to close | none |
| 2 | both moka pots on the stove (`libero_10`, KITCHEN_SCENE8) | Which burner, which pot first | burner assignment swapped |
| 3-4 | **authored** (custom BDDL from an existing scene, e.g. open drawer, put bowl in, close drawer, plate on cabinet) | Full ordering and recovery structure | order variants |

`libero_10` tops out at two goals, so k = 3-4 means authoring BDDL files (1-2 days, risk that a scene is infeasible). Treat it as the second phase.

## 4. Arms

| Arm | Input to the generator | Question it answers |
|---|---|---|
| A, task text | instruction and scene only | the baseline every reviewer asks for (M4 in discussion.md §6) |
| B, video | instruction, scene and DemoSpec from the video | the ANTS claim |
| C, numeric text | the same facts as B written by hand as numbers (offset in cm, order, grasp part) | is the video magic, or only a convenient way to get the numbers? |
| D, wrong video | the counterfactual video of the other variant | proof the program follows the video: its conformance must flip |
| E, escalation | A or B after the loop stalls twice, plus **one targeted video** for that failure signature | does one targeted video repair what the model could not (ties to the escalation block) |

## 5. Metrics

1. **Task success** (LIBERO predicate) on evaluation seeds. Report with Wilson intervals; hurobo has `stats.py` to port.
2. **Demo conformance** (new): the episode trace matches the video on every checked factor: order, side or offset within a tolerance, grasp part, orientation within a tolerance. Needs one small checker per task (`evalkit/`, about 1 day each). Task success alone cannot see these differences because the LIBERO predicate only checks that the goal holds.
3. **Tokens and cycles to the first gate pass**, with and without the video (hypothesis 5).
4. **Robustness under the same adversary** at equal rollout budget.
5. **Horizon curve**: success and conformance against k for A and B.

## 6. Predictions to write down before running

- P1, counterfactual: in B the conformance follows the video it was given; in A it is near chance on a two-way factor; in D it flips.
- P2, horizon: the gap between B and A grows with k.
- P3, convenience: C is close to B. If so, say it plainly: the video is a cheap way to obtain the numbers, and the saved annotation effort is the claim.
- Kill rule from discussion.md: if A already matches B on success **and** conformance for a task, drop the task, not the claim.
- Sample size warning: with 15 episodes per arm (3 samples x 5 seeds) an observed 80% has a Wilson 95% interval of about 55-93%. Only large effects are visible at this size.

## 7. Where the videos come from

1. **LIBERO teleop demos rendered as video** (`tools/libero_demospec.py` already turns the 50 book demos into a DemoSpec). Existing human demos for `libero_10` tasks would have to be downloaded (size not checked).
2. **Counterfactual pairs recorded by you** with keyboard teleop (hurobo `teleop.py`, or LIBERO-PRO's `scripts/libero_100_collect_demonstrations.py`). Operator time per variant is unmeasured; plan on an hour to be safe.
3. **Real phone clips** (the real human video, the actual story): a two-step task on real objects through the hurobo pipeline. Today only 4 of 26 clips pass extraction at 6.0 cm and the 5.75 cm re-extraction is pending (todo 1, 10). Do this after 1 and 2 work; it is the research tier.

## 8. Order of work and cost

Cost basis: about 20-25k tokens per Muse call (HANDOFF §6, reasoning-heavy) and the logged 13.5 USD per million tokens (experiment 02). **Longer programs will cost more per call than these figures; that is not measured.** The Muse cap is 15 USD (todo 8).

| Step | Work | Estimate |
|---|---|---|
| 0 | **Pilot, arm A only**: 6 candidate tasks x 2 samples x 1 call; keep tasks where A is below 50% | about 270k tokens, about 3.6 USD |
| 1 | Conformance checkers for the 1-2 chosen tasks | 1 day each |
| 2 | Record or extract videos, including one counterfactual pair | 0.5-1 day of operator time |
| 3 | Runner: arms C and D (`--demospec` for the second video, numeric-text input) | 0.5 day |
| 4 | Main run, one task: arms A-D x 3 samples x about 2.5 calls | about 675k tokens, about 9 USD per task |
| 5 | Arm E: needs the real harden run (`system2.harden`) from the storyline plan | 1 day plus tokens |
| 6 | Authored k = 3-4 tasks | 1-2 days, research tier |
| 7 | Real phone clip, two-step | research tier |

Steps 0 and 4 for one task already reach the 15 USD cap. Decide the budget (todo 8) before step 4; step 0 is cheap enough to start.

## 9. What to show (one figure each)

1. **Same sentence, two videos, two behaviours**: side-by-side rollouts of the counterfactual pair, with A shown beside them.
2. **Horizon curve**: success and conformance against k, with and without the video.
3. **Stuck, then one video**: the loop stalls on a failure signature, one targeted video arrives, the gate accepts the fix.

If P1 fails, the honest headline is the loop and the gate, with the video reported as the input that works but is not yet shown to be necessary.

## See also

[research-human-video-evaluation.md](research-human-video-evaluation.md): controls that show the video is used, intermediate metrics (extraction, fidelity, attribution) and a cheapest first run.
