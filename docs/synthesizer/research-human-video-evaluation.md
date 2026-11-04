# Research: how to see the performance of a human-video demonstration (beyond longer horizon)

Research done 2026-11-01 by three parallel literature passes. **Nothing here has been run in ANTS.** "Read" means the arXiv HTML was fetched and read through a page summariser, not the raw text; several numbers sit only in figures and are marked so. The plan that uses this is plan-human-video-power.md.

## 1. Bottom line

1. The papers show that a human video **works** (success rate against a baseline). Almost none show that the model **used** it. In the code-writing papers read (Demo2Code, ICAL, VLMimic, FMimic, GPT-Policy, CaP-X) no one ran a mismatched-demo, shuffled-demo or same-length-filler control. The controls come from NLP (Min et al. 2022, Yoo et al. 2022) and from one video-value paper (GVL, snippet only). Running them on a robot-code pipeline is a gap, and it is cheap.
2. Success rate hides most of what we want. The useful readouts are **between** video and success: was the video extracted correctly, did the program follow it, and when it failed, was it perception or program.
3. Most robot papers use 10 trials per cell and no confidence intervals, so our n = 3 per arm is in the same range as the field but does not prove more. A **program-level diff** is a second, much less noisy readout than rollout success.

## 2. What the literature measures (read)

| Work | How the video's value is measured | Headline numbers (setting) | Caveat |
|---|---|---|---|
| Demo2Code (2305.16744) | Same LLM, three inputs: language only, demo only, both. Also noisy demos (10% of predicates or states dropped) | Tabletop unit-test pass: 0.19 / 0.81 / 0.88. Robotouille 0.29 / 0.38 / 0.59 (gpt-3.5-turbo-16k, temp 0). Noise barely mattered: 0.59 original, 0.62 and 0.59 dropped | Language-only baseline never gets a text description of the demo; ambiguous-language tasks favour demos; first 100k of 187k characters read |
| VLMimic (2410.20927) | Success over 10 placements against diffusion policy on 100 robot demos, Demo2Code, CaP; number-of-videos sweep | RLBench 0.76 vs Demo2Code 0.49; real unseen env 0.71 vs 0.37. Sweep 1/3/5/7/9/11 videos: 0.68/0.72/0.76/0.67/0.78/0.78 | No zero-video arm; baselines not data-matched; RLBench uses robot videos; unseen-env score is 0.71 in one table and 0.77 in another |
| GPT-Policy (2609.19138) | Context ablation: none, human video, robot video, robot video plus action | Pick red towel 0/3 none vs 2/3 human video; unscrew cap 0/3, 2/3, 3/3 | n = 3 per cell, same as ours; no language-only arm, so it cannot say video beats text |
| ICAL (2406.14596) | Raw demos vs abstracted, human-corrected examples; remove images | TEACh goal-condition 49.3 vs 36.7 (hand-written examples); removing images 22.2 to 19.0; 1.9x raw demos at 50 examples | No wrong-demo control |
| OKAMI (2410.11792) | 12 real trials per task, 6 tasks; vs ORION; perception oracle; demonstrator variation | 71.7% average; ground-truth poses give 100% vs vision 82-84% (sim); worst demonstrator 16.7 points below best | Whether the "58.3%" lead over ORION is points or relative is unclear |
| Phantom (2503.00779) | Human-only vs robot-only data at equal count; co-training; new scene and embodiment | Human 0.44 vs robot 0.52 at 50 demos, 0.64 vs 0.88 at 100, human 0.84 at 300; robot-only 0.0 in a new scene, +950 human demos 0.80 | Not significant at 50 and 100 demos |
| Gen2Act (2409.16283) | Four generalisation tiers; vs language-only, goal-image and video-conditioned baselines | Average 22% (language only) / 26% / 37% / 60%; motion-type tier 0/0/0/30 | No trial counts per cell |
| MimicPlay (2302.12422) | Human play data at 0%, 50%, 100%; teleop demos 20 or 40; cost framing | Kitchen full task 0.47 (20 demos) and 0.70 (40) vs 0.07 and 0.13 best baseline; 0% human data 0.23 and 0.40; 10 min of play said to equal about 3 h of teleop (authors' figure) | Scene-specific human data |
| R+X (2407.12957) | 10 trials, 12 tasks; retrieval size 1/5/10/20 clips; continual learning | 0.70 vs 0.55 and 0.53 | Generalisation numbers only in figures |

## 3. Controls that show the video is used (ranked: cheapest first, simulation, frozen API)

| # | Control | Rules out | Cost | Source of the idea |
|---|---|---|---|---|
| 1 | **Program diff** between arms: constants, object order, waypoints, grasp point, compared across programs | Noise from rollout success at n = 3 | Free (programs already logged) | Demo2Code-style test, our own use |
| 2 | **Wrong or mismatched demo** (demo of another outcome for the same instruction) | "The model ignores the demo"; the Min et al. label-flip analogue | One extra arm, no new data if a counterfactual exists | Min et al.; none of the robot papers |
| 3 | **Same-length neutral filler** (matched tokens, no task content) | "A longer prompt helps", "the task is just harder" | One extra arm | Missing in Demo2Code and VLMimic |
| 4 | **Text-equivalent demo** (numeric spec of the same facts) | "The video information is needed" | One extra arm | Our sibling project already found it matches for strong models |
| 5 | **Counterfactual edit** of one fact in the DemoSpec (grasp point, order) and check the program changes in that place | Whether each fact is used | Cheap | Our design |
| 6 | **Shuffled frames or steps** | "Only the set of objects matters, not the order" | Cheap | GVL (snippet only) |
| 7 | **Degradation dose-response**: blur, occlusion, frame rate, viewpoint, in steps. A flat curve means the demo is not used | Binary flips that average out | Moderate (re-extract per level) | Yoo et al. (sensitivity slope, GLER); Demo2Code noise test |
| 8 | **Number-of-demos sweep that includes zero** | VLMimic's missing zero-video arm | More generation | VLMimic, R+X, ICAL |

Min et al.: random labels cost only 0 to 5% absolute (12 models, 26 datasets), so much of the benefit of a demo comes from format and label space, not the mapping. That is the strongest reason to run control 2 before claiming the video "teaches" anything.

## 4. Intermediate levels (read unless marked S = snippet only)

**Extraction quality (video to DemoSpec).**
- Hand: HaMeR PA-MPJPE 7.7 mm on HO3Dv2 and 6.0 mm on FreiHAND; WiLoR 7.5 and 5.5 mm, jitter 5.92 vs 20.43 for HaMeR on HO3D. These are studio benchmarks; HumanEgo (S) reports near-identical error for the two on phone video.
- DexYCB: two object-pose estimators with almost equal recall (57.43 vs 57.54) gave different grasp quality, so **pose accuracy alone does not predict task success**. Log grasp-level metrics, not only pose error.
- Tracking: SAM 2 J&F 90.2 with a ground-truth mask on DAVIS17, but 64.7 average with one click, which is closer to our text or click prompt.
- Step segmentation: no source read.

**Execution fidelity and progress.**
- Trajectory similarity (DTW, discrete Fréchet, Hausdorff, Chamfer): snippet only; I found no paper that validates them against task success for human-video transfer.
- GVL value-order correlation (2411.04549): shuffled-frame prompting averages 0.74 vs -0.08 single-frame (RT-1 subset); success detection 0.71 zero-shot, 0.75 one-shot. VLM progress benchmarks (S) report wide spread across models and say most are not reliable yet. Calibrate any VLM judge on rollouts of known outcome.

**Failure attribution.**
- MT3 (2511.10110): 2,200 rollouts, 78.25% seen and 68% unseen; failure shares retrieval 22.3%, segmentation 19.5%, pose 23.9% (judged by hand; the shares sum to about 94.7% and the paper does not say why).
- AHA (2410.00371): seven failure modes; 70.2 vs 50.0 binary success against zero-shot GPT-4o on its test set.
- REFLECT (2306.15724): explanation accuracy 88.4 and localisation 96.0 in simulation; the localisation metric (is the failure time inside the annotated window?) can be adopted directly.

**Demo quality and when to ask for a better one.**
- DemInf (2502.08623) needs a dataset of demos, so it does not apply to a single demo. The best verified single-demo signal is GVL's value-order correlation. No source defines an "ask for a better demo" rule; any threshold is ours, tuned on the acceptance set.

## 5. What ANTS can log today (mapped to what exists)

| Question | Readout | What we need | Status |
|---|---|---|---|
| Was the video needed? | Arms A (text), B (video), C (numeric text), filler | Runner arms | A, B run (exp. 01-02); C, filler new |
| Was it used? | Wrong-video arm, counterfactual edit, program diff, dose-response | Counterfactual videos or DemoSpecs; diff script | New |
| Was it extracted right? | Extraction error against **simulator ground truth** | `tools/libero_demospec.py` replays stored simulator states, so a DemoSpec from states is exact; render the same demo to video, extract, and compare. For phone clips, use hurobo's marker poses as the reference | Ground truth exists for LIBERO demos; the comparison script is new |
| Was it followed? | Path similarity to the demo path (normalised by its extent), per-step success, success under a tolerance sweep (1, 2, 5 cm), grasp timing and aperture match | EpisodeTrace with end-effector path and events | Partly logged (events, phases); similarity new |
| Where did it fail? | Re-run the failed program with ground-truth object poses: success means perception, failure means program or physics | Pose-oracle run mode in the harness | New; our own check, not from a paper |
| What did it cost or save? | Tokens and cycles to first gate pass, with and without the video; teaching time against teleop (MimicPlay framing) | Existing ledger | Tokens logged |
| Does it generalise? | Layout, scale, viewpoint, demonstrator variation (OKAMI), different embodiment | Sealed-shift cell from the storyline review | New |

`DemoSpec` already has a `quality` dict, `ee_path_obj`, `aperture`, `steps` and keyframes in `contracts/types.py`, which gives the fields for the first three rows.

## 6. Cheapest first run (no new videos)

Reuse the experiment 02 setup and the existing demos (hurobo clip 233832, the book DemoSpec). Add three arms per task: **wrong-demo** (the book DemoSpec for the bowl task, or the reverse), **same-length filler**, **numeric text**. Compare programs by diff first and by rollout second. Estimate: 3 arms x 3 samples x about 22k tokens x 13.5 USD per million, about 2.7 USD for single-call generations (an estimate from the logged per-call size; repairs add more). If the wrong-demo program is the same as the right-demo program, the model is ignoring the video and the headline has to change before anything else is built.

## 7. Statistics

- Pair arms by task and seed; report Wilson intervals (15 episodes with 80% observed gives about 55-93%).
- Use the program diff as the second readout.
- A dose-response sweep needs more than two points to show a trend; VLMimic's sweep dips at 7 videos, which shows how noisy single runs are.

## 8. Limits of this research

Unread: Im2Flow2Act, Vid2Robot, the second half of ICAL, CaP-X and Demo2Code, the FMimic ablation sections, ASPIRE's and Show-Harness' ablations. Snippet only: GVL's frame-shuffling claim, trajectory-metric references, HOI4D tables, process-benchmark papers, HumanEgo. The summariser may have mis-transcribed numbers; check a figure against the paper before quoting it.

## 9. Sources

Demo2Code https://arxiv.org/abs/2305.16744 · VLMimic https://arxiv.org/abs/2410.20927 · FMimic https://arxiv.org/abs/2507.20622 · GPT-Policy https://arxiv.org/abs/2609.19138 · ICAL https://arxiv.org/abs/2406.14596 · OKAMI https://arxiv.org/abs/2410.11792 · Phantom https://arxiv.org/abs/2503.00779 · Gen2Act https://arxiv.org/abs/2409.16283 · MimicPlay https://arxiv.org/abs/2302.12422 · R+X https://arxiv.org/abs/2407.12957 · NovaFlow https://arxiv.org/abs/2510.08568 · CaP-X https://arxiv.org/abs/2603.22435 · Min et al. https://arxiv.org/abs/2202.12837 · Yoo et al. https://arxiv.org/abs/2205.12685 · GVL https://arxiv.org/abs/2411.04549 · HaMeR https://arxiv.org/abs/2312.05251 · WiLoR https://arxiv.org/abs/2409.12259 · DexYCB https://arxiv.org/abs/2104.04631 · SAM 2 https://arxiv.org/abs/2408.00714 · MT3 https://arxiv.org/abs/2511.10110 · AHA https://arxiv.org/abs/2410.00371 · REFLECT https://arxiv.org/abs/2306.15724 · DemInf https://arxiv.org/abs/2502.08623
