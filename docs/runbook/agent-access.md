# Agent access: Claude Code today, Muse Code if the session limit hits

Goal: whichever coding agent continues the work can run the same experiments, with the same files, commands and rules. Nothing here is specific to one vendor. `AGENTS.md` stays the single source of repo rules; this page adds what an agent needs to *run* experiments.

## Start-up prompt (paste as the first message to a new agent)

> Read `AGENTS.md`, then `docs/HANDOFF.md` and `docs/runbook/agent-access.md`. Run `uv run python -m ants.evalkit.runbook list` to see every experiment and command. Do not print or commit `.env`. Ask me before any run that spends Muse tokens beyond `--token-budget 100000`.

## What the agent needs (same as Claude Code has now)

| Need | Why | How to check |
|---|---|---|
| Read and write the repo | code, docs, run dirs under `data/` | `uv run pytest -q` |
| Read `ASPIRE` and `hurobo`, run their venv pythons | simulator, services, demo extraction | `ls ASPIRE/.venv-libero/bin/python` |
| A shell that can run long commands in the background | a run takes 10 to 120 minutes | start `sleep 5 &` and read back |
| `uv`, `git`, `gh` (old `gh`: use `gh api graphql`) | env, commits, GitHub | `uv --version` |
| Network to `https://api.meta.ai/v1` | the generator (Muse) | `META_API_KEY` is in `ANTS/.env` (never print it) |
| The GPU (RTX A5500) | SAM 3, PyRoki, MuJoCo EGL | `nvidia-smi` |
| Claude-only: the Artifact tool (To-do page, Radar, run book page) | optional UI | not available elsewhere; use the fallbacks below |

## Fallbacks that work without Claude's tools

- **Run book UI:** Claude artifact https://claude.ai/artifact/AimCCqfBF2ooHEqZwiFVMS (Claude only); elsewhere open `docs/runbook.html` in a browser (static, no server). Same content: `uv run python -m ants.evalkit.runbook list | show <exp> | cmd <id>`.
- **To-do:** `docs/todo.md` (items plus the generated run book block). The interactive To-do artifact needs Claude's Artifact tool.
- **Run viewer:** `uv run python -m ants.evalkit.report data/runs --open`.
- **Skills** (`.claude/skills/*/SKILL.md`) are plain markdown procedures. Another agent can read and follow them; only the steps that write to the artifact database need the Artifact tools, so skip those or write the result into `docs/`.

## Rules that must survive an agent switch

1. Tune only on acceptance seeds (51 to 65); held-out seeds (1 to 50) are never used for tuning.
2. Always `--init-mode seeded` for LIBERO seeds.
3. Every run uses a hard `--token-budget`; ask the user before a big or paid run. Muse costs about $13.5 per million tokens (logged).
4. Repeat the same `--out` to resume a stopped run; cached model calls are free.
5. Keep evidence under `ANTS/data/` (git-ignored), never in a scratch folder.
6. Numbers in docs come from logged runs only.
7. Commit and push at meaningful milestones on the checked-out branch (AGENTS.md).

## Keeping the run book current (every agent)

When you add or change a command, experiment or flag:

1. Edit `docs/runbook/commands.json` (the only hand-edited file).
2. `uv run python -m ants.evalkit.runbook check` then `... build`. This regenerates `docs/runbook.html`, `docs/runbook/commands-full.md`, `docs/synthesizer/experiment-commands.md` and the block in `docs/todo.md`.
3. `uv run pytest tests/evalkit/test_runbook.py` must pass.
