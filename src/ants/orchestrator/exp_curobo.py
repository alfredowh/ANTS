"""Experiments 06 to 08: cuRobo planning on perception, without and with scene understanding.

All three plan with cuRobo on the public depth cloud (robot masked by SAM 3 in 06 and 07, by the
simulator in 08), debug in the scaled scene (seed 51) at temperature 0.2 with the WHY repair and
4 repairs, and score "bowl on plate" with the footprint rule (half of the bowl inside the plate).
Arms: clip 233859, clip 233832 (their demonstration summary) and no demonstration, one run each.

    exp06  no scene text; repair feedback as in exp03 (WHY only)
    exp07  S4 scene text built from perception (exp05) in the first prompt and every repair, repairs
           add the E3 evidence (contact log + scene + stall readings)
    exp08  as exp07, with the S4 text from the simulator (digital twin) and the simulator robot mask

    uv run python -m ants.orchestrator.exp_curobo --exp exp06 [--token-budget 250000]

The cuRobo service (dev/curobo/service_dev.py), SAM 3 and the other ASPIRE services must be up.
Finished runs are kept; repeat the command to resume. A crashed run is retried twice.
"""

from __future__ import annotations

import argparse
import traceback
from pathlib import Path

from ants.orchestrator import demo_vs_nodemo

ARMS = {
    "clip_233859": ("demo", "data/demospecs/hurobo_233859.json"),
    "clip_233832": ("demo", "data/demospecs/hurobo_233832.json"),
    "nodemo": ("nodemo", "data/demospecs/hurobo_233859.json"),  # the demospec is not used
}
EXPERIMENTS = {
    "exp06": {"planner": "curobo-sam3", "scene": None, "evidence": "none"},
    "exp07": {
        "planner": "curobo-sam3",
        "scene": "data/runs/exp05_perceived_scene/s4_perceived.txt",
        "evidence": "e3",
    },
    "exp08": {
        "planner": "curobo-sim",
        "scene": "data/runs/exp05_perceived_scene/s4_oracle.txt",
        "evidence": "e3",
    },
}


def argv_for(exp: str, arm: str, token_budget: int, root: Path) -> list[str]:
    cfg = EXPERIMENTS[exp]
    kind, spec = ARMS[arm]
    argv = [
        "--aspire", "../ASPIRE", "--demospec", spec, "--out", str(root / exp / arm),
        "--arms", kind, "--temperatures", "0.2", "--explain", "--repairs", "4",
        "--debug-scene", "scaled", "--scenes", "scaled", "--eval-seeds", "",
        "--planner", cfg["planner"], "--ontop-area", "0.5", "--contacts",
        "--evidence", cfg["evidence"], "--token-budget", str(token_budget),
        "--doc", "docs/synthesizer/experiment-06-08-curobo.md",
    ]  # fmt: skip
    if cfg["scene"]:
        argv += ["--scene-text-file", cfg["scene"]]
    return argv


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--exp", required=True, help="comma list of exp06, exp07, exp08")
    p.add_argument("--arms", default=",".join(ARMS))
    p.add_argument("--token-budget", type=int, default=250_000, help="per run, NEW tokens")
    p.add_argument("--root", type=Path, default=Path("data/runs/curobo"))
    p.add_argument("--print", action="store_true", help="print the commands and stop")
    args = p.parse_args(argv)
    for exp in args.exp.split(","):
        for arm in args.arms.split(","):
            cmd = argv_for(exp, arm, args.token_budget, args.root)
            if args.print:
                print("uv run python -m ants.orchestrator.demo_vs_nodemo", *cmd)
                continue
            for attempt in range(3):
                try:
                    demo_vs_nodemo.main(cmd)
                    break
                except Exception:
                    print(f"[{exp} {arm}] crashed (try {attempt + 1}/3):", flush=True)
                    traceback.print_exc()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
