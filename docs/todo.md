# To do (for the user)

Open items that need you: a measurement, a decision, access or a review. The interactive version is the [ANTS To-do](https://claude.ai/artifact/C3NqC3ij7jDMMtEqfzdaFp) artifact (source: `todo.html`). Started 2026-10-31.

| # | Item | Why | Status |
|---|---|---|---|
| 1 | **Measure the printed ArUco marker edge length** (hurobo E1 setup) | Every marker pose scales with it. 6.0 cm is used for now; 3.9 cm made `test_03` pass (hurobo design log D-010, open issues) | open |
| 2 | **Merge ASPIRE with SAM 3.1** | ASPIRE's SAM provider loads only SAM 3 (`sam3.pt`). Using 3.1 inside the harness needs a provider patch, and loading the 3.1 checkpoint into the image model is unverified ([aspire-assessment.md](synthesizer/aspire-assessment.md) §5) | open |
| 3 | **Review the skills definition** | Proposal in [synthesizer/skills.md](synthesizer/skills.md): what a skill is, its six parts, store operations, autonomous mode | open |
| 4 | **Set effort levels and budgets for autonomous mode** | Needed before any test-time CaP-Agent0-style search (skills.md §3) | open |
| 5 | **Confirm the hackathon rules allow reusing ASPIRE and hurobo code** | The official rules mention pre-existing work | open |
| 6 | **Agree the narrowed novelty claim with your teammate** (paper) | README and concept.md now claim the loop, not demo-to-program (RAPID) | open |
| 7 | Decide on Gemini Robotics-ER 2 (needs a Google key) | Keyframe and progress signal; not needed for the MVP | open |
| 8 | **Tell me Muse's price per token** (Meta API dashboard), or the current spend | Needed to enforce the $15 cap; the first smoke test used ~53k tokens ([smoke-2026-10-31.md](synthesizer/smoke-2026-10-31.md)) | open |
| 9 | Check `table_marker_fraction` > 1 in hurobo's extraction summary | Reads 1.07–1.08 on every E1 clip; possibly a counting bug | open |
| 10 | Re-record or review the 22 flagged E1 clips | Only 4/26 pass extraction at 6.0 cm (5 "no grasp detected", several position flags) | open |
