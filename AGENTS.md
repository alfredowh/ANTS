# ANTS: Agentic Task Synthesis

Instructions for any AI coding agent working in this repo (Claude Code, Copilot, Codex, Cursor, etc.).
This file is the single source of truth; tool-specific files (`CLAUDE.md`, `.github/copilot-instructions.md`) only point here.

## Role

Act as a senior agentic-AI and robotics engineer from an industrial research lab:

- Research-oriented: state hypotheses, run ablations, and report results taken from the data, never from expectation.
- Production-aware: design as if this will be deployed (reproducible, tested, observable, failure modes explicit).
- Outstanding coder, hackathon mindset: get an end-to-end demo working early, then deepen it. Prefer a thin working vertical slice over broad unfinished scaffolding.
- Communication matters: advanced work must be presented so others see its relevance. Keep results, figures and demos easy to turn into a pitch, slides, a LinkedIn post or a project page (clear one-line claim, a figure or video per result, honest limitations).

## Asking questions

Clarify before building, and keep clarifying while working:

- **At the start of a task:** if the goal, success metric, data, simulator, model choice or constraints are ambiguous, ask a few targeted questions before writing code. Group them in one message, most important first, and suggest a default for each so the user can answer "go with defaults".
- **During the task:** stop and ask when you hit a decision that changes results or is costly to undo, for example:
  - choosing a simulator, generator model or perturbation categories
  - changing the gate, severity bounds, test budget or the acceptance/held-out split
  - an unexpected result that contradicts the hypothesis
  - adding a dependency, or anything needing credentials, paid APIs or a human demonstration
- **Do not ask** about things with a conventional default or that you can verify in the repo. Pick the default, say so, and continue.
- Never invent missing facts (data, metrics, results) to avoid asking.

## Project concept

Learn a robot skill from one demonstration with a frozen generative model, then harden it with an adversarial test loop. Improve through context, not weight updates. Nothing is trained.

**Problem:** one robot, one task, one policy. Each new task, scenario or embodiment needs new data and fine-tuning, so data is the bottleneck.

**Components**
- **System 1, synthesizer:** a frozen generator turns one video demonstration (segmentation, hand/object keypoints, gripper aperture) into a policy.
- **System 2, adversary:** a test planner proposes perturbations within a bounded severity; a simulator runs them; a diagnoser explains each failure.
- **Closed loop:** every failure becomes a constraint added to the generator's context, and the generator proposes a new candidate policy.
- **Adaptive testing:** spend the test budget on the failure categories most likely to break the policy, not uniform sampling.
- **Gate:** accept a candidate only if it is no worse than the current best on every case seen so far and better on at least one, so robustness never regresses and every accepted version is a real improvement. A crash on a case the incumbent passed is a regression. A skill is admitted only when a policy that uses it passes the gate.
- **Memory (not built, D18):** store past policies, retrieve by similarity weighted by how often they helped, and fade unused ones. This is how skills would be shared.
- **Stop or escalate:** stop when every category is confidently robust. If the generator stalls, escalate and ask a person (a typed answer today; one targeted demonstration is future work).

**Evaluation rules:** tune only on an acceptance set. Report on a held-out test set that is never used for tuning. Numbers in any write-up must come from logged runs.

**Vision:** skills written from a single demonstration, hardened by an adversary, shared through memory. Every failure becomes a constraint or one more human demonstration.

**Design implications for agents**
- Never add training or fine-tuning code for the generator; improvement happens only via context (constraints, retrieved policies).
- Keep the acceptance set and the held-out test set strictly separate in code and data paths.
- Make the gate, severity bounds and test budget explicit, configurable and logged.
- Log every failure, diagnosis, constraint and gate decision so runs are reproducible and presentable.


## Documentation

- **README.md is the storefront: short and visible.** Include only the one-line pitch, the main idea, headline results, images/GIFs/video, the architecture diagram, quick start, and links to `docs/`. Aim for roughly one screen of text plus visuals; no long prose, no full API or design details.
- **Details live in `docs/`** (concept, architecture, evaluation protocol, stack decisions, experiment logs). README links to them.
- Put images and diagrams in `docs/images/` and embed the best ones in the README.
- Results in the README (tables, numbers, figures) must come from logged runs; link to the run or doc they came from. If there are no results yet, say "results coming" instead of leaving filler.
- When a change affects behavior, results or architecture, update the matching doc and, if it is headline-worthy, the README.

## Environment

- Python is managed exclusively with [uv](https://docs.astral.sh/uv/). Do not use `pip`, `venv`, `poetry` or `conda`.
- Setup (identical on Ubuntu and macOS): `uv sync`
- Run anything inside the env with `uv run ...` (never activate the venv manually, never hardcode `.venv/bin` or `.venv\Scripts`).
- Python version is pinned in `.python-version`; uv installs it automatically.

### Managing packages

Always change dependencies through uv so `pyproject.toml` and `uv.lock` stay in sync. Never `pip install`, and never edit `uv.lock` by hand.

| Task | Command |
| --- | --- |
| Add runtime package | `uv add <pkg>` (version constraint: `uv add "pkg>=1.2"`) |
| Add dev-only package (pytest, ruff, jupyter) | `uv add --dev <pkg>` |
| Add to a named group (e.g. heavy GPU or sim deps) | `uv add --group <group> <pkg>` |
| Remove a package | `uv remove <pkg>` |
| Upgrade one package | `uv lock --upgrade-package <pkg>` then `uv sync` |
| Install exactly what `uv.lock` says (CI, fresh clone, after `git pull`) | `uv sync` (add `--frozen` to forbid lockfile changes) |
| Include an optional group | `uv sync --group <group>` |
| One-off tool without adding it | `uv run --with <pkg> <cmd>` |

Rules:
- After `git pull` or switching branches, run `uv sync` before running anything.
- Commit `pyproject.toml` and `uv.lock` together, in the same commit as the code that needs the package.
- Keep heavy or conflicting dependencies (GPU models, simulators) in groups per system (`synthesizer`, `adversary`) so one person's install does not force the other's.
- Ask the user before adding a large dependency (torch, simulators, model SDKs) or anything needing credentials or a paid API.
- Prefer the standard library and existing dependencies over adding a new package for a small task.

## Commands

| Task | Command |
| --- | --- |
| Install / sync | `uv sync` |
| Tests | `uv run pytest` |
| Lint | `uv run ruff check .` |
| Format | `uv run ruff format .` |
| Run a module | `uv run python -m ants` |

Before finishing a change, run lint and tests and report the real result.

## Layout

- `docs/` detailed documentation; `docs/images/` figures and diagrams
- `docs/<module>/spec.md` per-module agent spec (rules, architecture, build order); read it before working in that module. Import new ones in `CLAUDE.md`.
- `src/ants/contracts/` shared types (the only thing both systems import)
- `src/ants/synthesizer/` System 1: policy synthesis, model client, prompts
- `src/ants/adversary/` System 2: test planner, simulator rollouts, diagnoser, failure history
- `src/ants/orchestrator/` closed loop, regression gate, escalation (the only place that knows both systems)
- `src/ants/evalkit/` acceptance / held-out split, metrics, logging
- `src/ants/studio/` ANTS Studio: console, `/policy-dev` pipeline, Adversary view (read-only on decisions)
- `tests/` pytest tests, mirroring the package structure (`tests/adversary/`, `tests/synthesizer/`); every test folder has an `__init__.py` so test files with the same name in different folders do not collide
- `pyproject.toml` single config for dependencies, ruff and pytest

## Cross-platform rules

- Use `pathlib.Path`, never hardcoded `/` or `\` separators or OS-specific paths.
- Open text files with an explicit `encoding="utf-8"`.
- Do not write bash-only or PowerShell-only scripts; put automation in Python (run via `uv run`) or `pyproject.toml` entries.
- Do not assume case-sensitive filesystems or a particular shell.

## Conventions

- Type hints on public functions; keep code consistent with surrounding style (ruff enforces formatting).
- Keep changes small and focused; add or update tests with behavior changes.
- Never commit secrets, `.env` files or `.venv/`.

## Git workflow

The user wants every significant change traceable, so agents commit and push on their own, but only at meaningful checkpoints. Protected branches only accept changes through pull requests.

**Branches**

```
main              stable: demos and milestones; PRs from integration only
└─ integration    where System 1 and System 2 meet; PRs from feature branches
   └─ feature/*, synthesizer   one branch per piece of work
```

- **Never commit or push to `main` or `integration` directly.** Work on the feature branch that is checked out. Create or switch branches only when the user asks.
- **Sync before starting work:** `git fetch && git merge origin/integration` into the feature branch, so conflicts with the other system show up early.
- **When:** commit after a complete, significant feature or fix works (a new component, a behavior change, a milestone result, a refactor that is finished). Not after every edit, and not for trivial tweaks, typo fixes or half-finished work; fold those into the next feature commit. Pushing the feature branch is fine at any commit.
- **Before committing:** run `uv run ruff check .` and `uv run pytest`. Never commit or push failing code. If something is knowingly broken, say so and ask first.
- **One feature, one commit,** with a message that says what and why (imperative subject, short body). Do not mix unrelated changes in one commit, so any feature can be reverted or bisected alone.
- **Pull requests:** when a piece of work is finished (for example one build-order step), ask the user, then open a PR into `integration` with `gh pr create --base integration`. Keep PRs small: one piece per PR. After the merge, fast-forward the feature branch: `git fetch && git merge --ff-only origin/integration`.
- **Shared code:** changes to `src/ants/contracts/` are agreed by both owners and go in their own small PR. Do not edit the other system's package or docs.
- **Milestones:** a working end-to-end demo or a reported result goes from `integration` to `main` by PR and may get a tag such as `demo-v0.1`.
- **Report:** after each commit and push, tell the user the branch, the commit hash and a one-line summary; after opening a PR, give its URL.
- **Never:** force-push, rewrite pushed history, skip hooks, commit secrets, `.env`, `.venv/`, datasets or large binaries, or `git add -A` blindly (stage only the files for this feature).
