# bowl_on_plate v0: where this policy comes from

`policy.py` is a robot program written by a frozen generator from one demonstration. Nothing was trained and nobody edited it by hand: it is byte-identical to the logged program below.

- **Task:** LIBERO-Pro `libero_goal_swap`, task 8, "put the bowl on the plate", Franka arm, ASPIRE `cap-harness`, seeded init mode.
- **Generator:** `muse-wonder-1.0` (Meta API), temperature 0.2, sample 0 of the `demo` arm.
- **Demonstration:** hurobo real clip `20261016_233832`, reduced to a demo spec (rim pinch, approach from above, carry height, release over the plate, all relative to object size). Spec sha256 prefix `0de44e5b947fe6a0`.
- **How it was made:** attempt 0 failed on debug seed 51 (`program_completed`, task not done); one repair from text feedback (attempt 1) solved it. This file is attempt 1.
- **File sha256 prefix:** `5ac3b80d432fa321`.
- **Source run:** ANTS repo, branch `synthesizer`, `data/runs/exp01b/demo/sample0/program_attempt1.py` (git-ignored; the same file is in `data/runs/demo_vs_nodemo_01/`). Prompts and replies are in the same sample directory.

## Measured behaviour (logged, `exp01b/demo/sample0/record.json`)

| Scene | Seeds | Success |
|---|---|---|
| stock objects | 51-55 | 5/5 |
| bowl x1.227, plate x1.855 (real size) | 51-55 | 2/5 (51, 52 pass; 53-55 end `program_completed` without success) |

Re-checked with `policy_run.py` on 2026-11-01: seed 52, stock scene, success.

## Limits

- One task, one seed range; seeds 51-55 are acceptance seeds, not held-out.
- It uses ASPIRE's flat-script convention (primitives as globals, no `run(robot, params)` entry point) and ASPIRE's primitive names. It is not yet written against `contracts/v0` and has no `params`.
- It has not been attacked by System 2; there is no robustness claim beyond the table above.
- Generated code is untrusted: run it only inside the harness.
