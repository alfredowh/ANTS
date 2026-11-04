<p align="center"><img src="docs/images/banner.svg" alt="ants" width="100%"></p>

# ANTS: Agentic Task Synthesis

**Show a robot a task once. An adversary breaks it in simulation. Every failure becomes a readable fix, kept only if nothing got worse.** No model weights are trained.

Our entry for the [Meta Global AI Developer Hackathon 2026](https://dev.meta.ai/events/global-hackathon).

![ANTS architecture](docs/images/architecture.png)

- **System 1 writes the skill:** one demonstration becomes a short robot program (Muse).
- **System 2 breaks it:** Muse Spark picks where to attack, LIBERO runs the attack, Muse Spark explains the failure.
- **The gate keeps only real fixes:** a rewrite is accepted only if it is no worse on every case seen so far and better on at least one. When stuck, ANTS asks for one targeted demonstration.

## Results

*Coming soon,* from logged LIBERO runs on a held-out test set.

## Quick start

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).

```
uv sync
uv run python -m ants.orchestrator.run --cycles 30 --out data/runs/mock_loop
```

This runs the closed loop in an offline test world (no GPU, no API key) and writes `data/runs/mock_loop/studio.html`. Open it in a browser.

## Docs

[Concept](docs/concept.md) · [Architecture](docs/architecture.md) · [Context and decisions](docs/context.md) · [For coding agents](AGENTS.md)

## License

[Apache-2.0](LICENSE). Third-party models (SAM 3, Muse) and datasets keep their own licenses.
