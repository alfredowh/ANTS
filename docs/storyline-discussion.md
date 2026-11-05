# Meta hackathon story line: discussion log

Mirror of the Discussion segment in the Meta hackathon story line tab of the [ANTS To-do](https://claude.ai/artifact/C3NqC3ij7jDMMtEqfzdaFp) artifact (db collection `storyline_discussion`). Started 2026-11-02.

## d1. The program may only use what a real robot has

- Setup: "real robot executed in sim". The program localizes objects from camera, depth and joint state. Simulator state is the grader (success, collision, drop) and diagnoser evidence, never an input. Applies to System 1 and System 2.
- Why: ground truth is a perfect measurement and hides the failures real robots hit (bad mask, depth noise, calibration, occlusion). Sensed `locate` makes the lighting, camera and occlusion attacks meaningful.
- Watch-outs: keep privileged state out of `RobotAPI` (add a sandbox test); log perceived and true pose per run; decide what evidence the generator may see; say "localization from simulated RGB-D".
- Decision: adopt. Ablation: privileged vs sensed `locate`, same policies and seeds.

## d2. Experiment 04 uses an oracle scene

- Exp 04 builds the scene text from simulator state on purpose, to measure the representation and not perception ([experiment-04-scene-context.md](synthesizer/experiment-04-scene-context.md), `data/runs/exp04_scene`).
- A3 shows perception is weakest on the object that matters (wine rack: found 86 cm away; merged with the bowl mask in L2 and L3).
- The contact log used in repairs is after-the-fact sim feedback, which fits the setup.
- Decision: label exp 04 "oracle upper bound". Later: repeat runs, check L2 and L3 solvability, cleaner placebo, perceived-scene arm.

## d3. If sim = real, is perception still needed?

- Not to write the program from a measured twin. Yes at run time and to keep the twin current: the twin update step is perception.
- The adversary moves things on purpose, so a program with twin coordinates fails; and a perfect twin makes System 2 nearly pointless.
- Do not mix oracle scene in the prompt, oracle poses at run time and adversarial perturbation: perturbed poses come for free and robustness is inflated.
- Decision needed: (A) twin as development tool, program senses at run time; or (B) twin as generator-only ground truth, oracle-vs-perceived gap is the measurement.
