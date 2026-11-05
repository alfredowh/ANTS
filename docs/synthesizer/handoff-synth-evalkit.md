# Handoff: run the synthesizer and view its runs in evalkit

Written for a teammate who builds on System 1 and its replay (not the live console). Agent-neutral:
every step is a shell command or a file path.

## 1. Get the code

- Branch: `synthesizer` (origin). Everything here is committed there.
- Work on a branch of your own, for example `feature/replay`, cut from `origin/integration`
  (AGENTS.md, Git workflow). Do not commit to `main` or `integration`.
- Then:

```bash
git clone https://github.com/alfredowh/ANTS.git && cd ANTS
git checkout synthesizer
git submodule update --init --recursive   # ASPIRE and hurobo are git submodules
uv sync
uv run ruff check . && uv run pytest -q   # the baseline should pass before you change anything
```

## 2. Copy the data (not in git: `data/` is git-ignored)

Copy these from the owner's machine into the same paths under `data/`:

| Path | Needed for | Size |
|---|---|---|
| `data/demospecs/hurobo_233859.json` | the one-clip DemoSpec for every synthesizer run | small |
| `data/scenes/` (`levels.json`, `L1/`, `L2/`, `L3/`) | scene levels, contact scenes | small |
| `data/runs/exp03_explain/clip_233859/` | the E variants read its `demo/sample0` program | ~537 MB for exp03 |
| `data/runs/exp04_scene/` | the G/E scene-context results to view | ~493 MB |
| `data/scene_text/S4_L1.txt`, `S4_L2.txt`, `S4_L3.txt` | `--scene-text-file` for S4 | tiny |

The S4 text files can be regenerated instead of copied:

```bash
uv run python -c "from pathlib import Path; from ants.orchestrator.scene_context_exp import g_scene_text; \
Path('data/scene_text').mkdir(parents=True, exist_ok=True); \
[Path(f'data/scene_text/S4_{lv}.txt').write_text(g_scene_text('S4', lv)+'\n', encoding='utf-8') for lv in ['L1','L2','L3']]"
```

## 3. View the runs (no tokens, no services)

```bash
uv run python -m ants.evalkit.report data/runs --open     # every run; pick one in the UI
uv run python -m ants.evalkit.report data/runs/<name> --open   # one run
```

Add `--serve` if videos do not load from a file. The report reads `config.json`, `events.jsonl`,
per-sample `record.json`, programs, replies, prompts, feedback and diffs, and per-rollout
`episode/steps.jsonl`, `trace/events.jsonl`, `outcome.json` and videos. Keep `report.html` in the
folder you point at, because media is linked by relative path.

## 4. Run the synthesizer (spends Muse tokens: ask first)

The one-clip run with the E3 repair evidence, the S4 scene text, cuRobo as the planner and at most
3 repairs (4 attempts in total):

```bash
uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ASPIRE \
  --out data/runs/<new_run_name> \
  --demospec data/demospecs/hurobo_233859.json \
  --arms demo --temperatures 0.2 --explain \
  --evidence e3 --contacts \
  --scene-text-file data/scene_text/S4_L1.txt \
  --repairs 3 --planner curobo-sim \
  --debug-scene scaled --scenes stock,scaled --eval-seeds "" \
  --token-budget 250000
```

- `--planner curobo-sim` needs the dev cuRobo service running. Start it with the runbook entries
  `services.start` and `curobo.service` (`uv run python -m ants.evalkit.runbook cmd <id>` prints each).
- Ask the user before any run above 100k new tokens (`docs/runbook/agent-access.md`).
- Repeat the same `--out` to resume a stopped run; cached model calls are free.
- Then view it with step 3.

## 5. Rules that must survive a handover

1. Tune only on acceptance seeds 51 to 65. Held-out seeds 1 to 50 are never used for tuning.
2. Always `--init-mode seeded` for LIBERO seeds.
3. Every run has a hard `--token-budget`.
4. Keep evidence under `data/` (git-ignored), never in a scratch folder.
5. Numbers in docs come from logged runs only.
6. Never print `.env`. The Muse key is `META_API_KEY` there.
7. A new command or experiment goes into `docs/runbook/commands.json`, then
   `uv run python -m ants.evalkit.runbook check` and `build` (see the runbook's agent-access page).

## Where things are

- Synthesizer entry point: `src/ants/orchestrator/demo_vs_nodemo.py`
- Scene-context experiment (exp04): `src/ants/orchestrator/scene_context_exp.py`
- Run viewer: `src/ants/evalkit/report.py`
- Contact analysis used for E3 evidence: `src/ants/evalkit/contacts.py`
- Experiment notes: `docs/synthesizer/experiment-04-scene-context.md`, `experiment-commands.md`
