"""Write a synthetic System 2 run (no simulator, no model) to try the viewer's System 2 tab.

The world is fake: program v0 breaks on `size` and `physics`; v1 fixes size but breaks pose
(the gate must reject it); v2 fixes both without regressing. Output goes to
`<out>/system2.jsonl` plus a `config.json` that says the run is synthetic.

    uv run python tools/system2_mock.py data/runs/system2_mock_synthetic
    uv run python -m ants.evalkit.report data/runs --open
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ants.evalkit.runlog import RunLog
from ants.orchestrator.system2 import CaseResult, HardenConfig, harden

FAIL = {"failed_calls": [{"tool": "move_to_pose", "status": "timeout", "steps_executed": 145}]}


def main(out: Path) -> None:
    programs = {"v0": "size,physics", "v1": "pose", "v2": "none"}
    out.mkdir(parents=True, exist_ok=True)
    for name, breaks in programs.items():
        (out / f"{name}.py").write_text(f"breaks={breaks}\n", encoding="utf-8")
    versions = iter([("v1", 24_000), ("v2", 26_500)])

    def run_case(case, program):
        broken = program.read_text(encoding="utf-8").strip().split("=")[1].split(",")
        cats = [p.category for p in case.perturbations] or ["nominal"]
        ok = not any(c in broken for c in cats)
        return CaseResult(ok, {} if ok else FAIL)

    def generate(incumbent, constraints, feedbacks):
        name, tokens = next(versions)
        return out / f"{name}.py", tokens

    (out / "config.json").write_text(
        json.dumps({"note": "SYNTHETIC world: no simulator, no model calls", "usd_per_mtok": 13.5}),
        encoding="utf-8",
    )
    cfg = HardenConfig(cycles=6, tests_per_cycle=6, stall_limit=3, min_tests_robust=2, seed=3)
    res = harden(out / "v0.py", cfg, run_case, generate, RunLog(out))
    print(
        f"stopped: {res.stopped}; final: {res.incumbent.name}; constraints: {len(res.constraints)}"
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
