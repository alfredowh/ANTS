# To do (for the user)

Open items that need you: a measurement, a decision, access or a review. The interactive version is the [ANTS To-do](https://claude.ai/artifact/C3NqC3ij7jDMMtEqfzdaFp) artifact (source: `todo.html`). Started 2026-10-31.

| # | Item | Why | Status |
|---|---|---|---|
| 1 | ~~Measure the printed ArUco marker edge length~~ (hurobo E1 setup) | Measured 5.75 cm (user, 2026-10-31). Matches hurobo's `RecordingSpec.marker_length_m` default (0.0575), not the 6.0 cm used in the ANTS smoke runs. The 3.9 cm fit for `test_03` is refuted as a marker-size effect; its cause is still open | done |
| 2 | **Merge ASPIRE with SAM 3.1** | ASPIRE's SAM provider loads only SAM 3 (`sam3.pt`). Using 3.1 inside the harness needs a provider patch, and loading the 3.1 checkpoint into the image model is unverified ([aspire-assessment.md](synthesizer/aspire-assessment.md) §5) | open |
| 3 | **Review the skills definition** | Proposal in [synthesizer/skills.md](synthesizer/skills.md): what a skill is, its six parts, store operations, autonomous mode | open |
| 4 | **Set effort levels and budgets for autonomous mode** | Needed before any test-time CaP-Agent0-style search (skills.md §3) | open |
| 5 | **Confirm the hackathon rules allow reusing ASPIRE and hurobo code** | The official rules mention pre-existing work | open |
| 6 | **Agree the narrowed novelty claim with your teammate** (paper) | README and concept.md now claim the loop, not demo-to-program (RAPID) | open |
| 7 | Decide on Gemini Robotics-ER 2 (needs a Google key) | Keyframe and progress signal; not needed for the MVP | open |
| 8 | **Tell me Muse's price per token** (Meta API dashboard), or the current spend | Needed to enforce the $15 cap; the first smoke test used ~53k tokens ([smoke-2026-10-31.md](synthesizer/smoke-2026-10-31.md)) | open |
| 9 | Check `table_marker_fraction` > 1 in hurobo's extraction summary | Reads 1.07–1.08 on every E1 clip; possibly a counting bug | open |
| 10 | Re-record or review the 22 flagged E1 clips | Only 4/26 pass extraction at 6.0 cm (5 "no grasp detected", several position flags) | open |
| 11 | **Decide whether ANTS accepts in-cell teleop / VR / kinesthetic demos**, not only human video | Machenta teaches in the cell; our plan is human video plus a simulated teleop demo ([instant-learning.md](dev/instant-learning.md) §3) | open |
| 12 | Check the SynthICL repo (licence, weights) and read the Instant-Fold paper | Likeliest public basis of Machenta's model; repo not opened yet | open |
| 13 | **Licence: Instant Policy is PolyForm Noncommercial** and the full paper has a commercial layer | Offline baseline only; see [instant-learning.md](dev/instant-learning.md) §5 X3 | open |
| 14 | Re-check the paper's Machenta comparison (§II) against the 27 Oct 2026 blog | New facts: VDA, four teaching modes, six robots, $40M seed | open |
| 15 | Read the USV blog and Business Insider article that TNW quotes | "11 employees", "no near-term plans to sell", "30 minutes of extra data" are second-hand | open |
