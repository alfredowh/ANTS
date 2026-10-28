# ANTS: Agentic Task Synthesis

**Teach a robot a skill from one demo. Let an adversary break it. Fix it with context, not training.**

Our entry for the [Meta Global AI Developer Hackathon 2026](https://dev.meta.ai/events/global-hackathon): *ANTS, One-Shot Robot Learning via Video-to-Program Synthesis and Adversarial Refinement.*

![ANTS architecture](docs/images/architecture.png)

- **System 1, write the skill:** SAM 3.1 tracks hand, object and gripper in one demo video; Muse Wonder (via Muse Code) turns it into a policy.
- **System 2, break the skill:** Muse Spark plans perturbations on the weakest category, a LIBERO simulation runs them, and Muse Spark diagnoses each failure.
- **Closed loop:** each failure goes back to the generator as context, never as a weight update. A regression gate accepts a rewrite only if it does at least as well on every case seen so far. If stuck after N cycles, ANTS asks for one targeted demo.
- **Deliverable:** one closed loop on one pick-and-place task with a Franka arm in LIBERO.

## Results

*Coming soon.* Numbers will come from logged runs on a held-out test set.

## Repository layout

```
src/ants/
├── contracts/      shared types: Demo, Policy, Perturbation, Failure, Constraint
├── synthesizer/    System 1: SAM 3.1 tracking, Muse Wonder policy synthesis, experience memory
├── adversary/      System 2: Muse Spark planner + diagnoser, LIBERO rollouts, failure history
├── orchestrator/   closed loop, regression gate, escalation
└── evalkit/        acceptance / held-out split, metrics, logs
```

`synthesizer` and `adversary` import only `contracts`; only `orchestrator` knows both.

## Quick start

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/) (Windows, Ubuntu, macOS).

```
uv sync
uv run pytest
```

## Docs

- [Concept and evaluation](docs/concept.md)
- [System 1 discussion: stack, method, policy format](docs/synthesizer/discussion.md)
- [Instructions for AI coding agents](AGENTS.md)

## License

[Apache-2.0](LICENSE). Third-party models (SAM 3.1, Muse) and datasets keep their own licenses.
