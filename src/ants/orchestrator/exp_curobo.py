"""Experiments 06 to 08 and 09 to 11: cuRobo planning on perception, without and with scene text.

All three plan with cuRobo on the public depth cloud (robot masked by SAM 3 in 06 and 07, by the
simulator in 08), debug in the scaled scene (seed 51) at temperature 0.2 with the WHY repair and
4 repairs, and score "bowl on plate" with the footprint rule (half of the bowl inside the plate).
Arms: clip 233859, clip 233832 (their demonstration summary) and no demonstration, one run each.

    exp06  no scene text; repair feedback as in exp03 (WHY only)
    exp07  S4 scene text built from perception (exp05) in the first prompt and every repair, repairs
           add the E3 evidence (contact log + scene + stall readings)
    exp08  as exp07, with the S4 text from the simulator (digital twin) and the simulator robot mask

    exp09  as exp06, and the held bowl is attached to the hand (spheres of the bowl's KNOWN size)
    exp10  as exp07 (perceived S4 + E3), with the same attached bowl, known size
    exp11  as exp08 (simulator S4 + E3, simulator masks), with the same attached bowl, known size

    uv run python -m ants.orchestrator.exp_curobo --exp exp06 [--token-budget 250000]

The cuRobo service (dev/curobo/service_dev.py), SAM 3 and the other ASPIRE services must be up.
Finished runs are kept; repeat the command to resume. A crashed run is retried twice.
"""

from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path

from ants.orchestrator import demo_vs_nodemo
from ants.synthesizer.sam_api import add_sam_model_arg, normalize_sam_model

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
    "exp09": {"planner": "curobo-sam3", "scene": None, "evidence": "none", "attach": True},
    "exp10": {
        "planner": "curobo-sam3",
        "scene": "data/runs/exp05_perceived_scene/s4_perceived.txt",
        "evidence": "e3",
        "attach": True,
    },
    "exp11": {
        "planner": "curobo-sim",
        "scene": "data/runs/exp05_perceived_scene/s4_oracle.txt",
        "evidence": "e3",
        "attach": True,
    },
}
DOCS = {
    "attach": "docs/synthesizer/experiment-09-11-curobo-attach.md",
    "plain": "docs/synthesizer/experiment-06-08-curobo.md",
}


def argv_for(
    exp: str,
    arm: str,
    token_budget: int,
    root: Path,
    sam_model: str = "sam3",
) -> list[str]:
    cfg = EXPERIMENTS[exp]
    kind, spec = ARMS[arm]
    planner = cfg["planner"]
    if normalize_sam_model(sam_model) == "sam-3.1" and planner == "curobo-sam3":
        planner = "curobo-sam31"
    argv = [
        "--aspire", "ASPIRE", "--demospec", spec, "--out", str(root / exp / arm),
        "--arms", kind, "--temperatures", "0.2", "--explain", "--repairs", "4",
        "--debug-scene", "scaled", "--scenes", "scaled", "--eval-seeds", "",
        "--planner", planner, "--ontop-area", "0.5", "--contacts",
        "--evidence", cfg["evidence"], "--token-budget", str(token_budget),
        "--doc", DOCS["attach" if cfg.get("attach") else "plain"],
        "--sam-model", sam_model,
    ]  # fmt: skip
    if cfg["scene"]:
        argv += ["--scene-text-file", cfg["scene"]]
    if cfg.get("attach"):
        argv += ["--attach-known", "--save-clouds"]
    return argv


def ledger_tokens(path: Path = Path("data/llm_ledger.jsonl")) -> int:
    """New (uncached) tokens logged so far, from the model ledger."""
    total = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not row.get("from_cache"):
            total += int(row.get("prompt_tokens") or 0) + int(row.get("completion_tokens") or 0)
    return total


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--exp", required=True, help="comma list of exp06 to exp11")
    p.add_argument("--arms", default=",".join(ARMS))
    p.add_argument("--token-budget", type=int, default=250_000, help="per run, NEW tokens")
    p.add_argument(
        "--total-token-budget", type=int, default=None,
        help="stop starting new runs once this many NEW tokens were spent in this command",
    )  # fmt: skip
    p.add_argument(
        "--arm-major", action="store_true",
        help="loop arms outside, experiments inside, so a stop leaves comparable arms",
    )  # fmt: skip
    p.add_argument("--root", type=Path, default=Path("data/runs/curobo"))
    p.add_argument("--print", action="store_true", help="print the commands and stop")
    add_sam_model_arg(p)
    args = p.parse_args(argv)
    exps, arms = args.exp.split(","), args.arms.split(",")
    pairs = [(e, a) for a in arms for e in exps]
    if not args.arm_major:
        pairs = [(e, a) for e in exps for a in arms]
    start = 0 if args.print else ledger_tokens()
    for exp, arm in pairs:
        if args.total_token_budget and not args.print:
            spent = ledger_tokens() - start
            if spent >= args.total_token_budget:
                print(f"token budget used up ({spent} >= {args.total_token_budget}); stopping")
                break
        cmd = argv_for(exp, arm, args.token_budget, args.root, args.sam_model)
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
