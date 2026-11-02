"""Run the closed loop on one policy and log every decision.

    uv run python -m ants.orchestrator.run --cycles 30                      # mock world, free
    uv run python -m ants.orchestrator.run --cycles 10 --backend cap_harness --aspire ../ASPIRE

Writes `<out>/loop.jsonl`, `<out>/attacks.jsonl` (System 2's history), `<out>/policies/v<N>.py`
and `<out>/summary.json`.

System 1 is the patch fixture (`--synthesizer patch`) until System 1's Muse generator is merged:
it applies hand-written patches that the MOCK world rewards, so a run with it shows that the loop,
gate and escalation work, never that a policy got more robust. Mock-world numbers are not results.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from ants.adversary import Adversary, AdversaryConfig
from ants.adversary.perturbations import CATEGORIES, Bounds
from ants.adversary.rollout import AspireConfig
from ants.contracts import Policy
from ants.orchestrator.loop import Loop, LoopConfig
from ants.orchestrator.synthesis import PatchSynthesizer

DEFAULT_POLICY = Path("examples/bowl_on_plate/policy.py")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--cycles", type=int, default=30)
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--task", default="put the bowl on the plate")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--categories", default=",".join(CATEGORIES))
    ap.add_argument("--model", default="mock", help='"mock" (rules only) or "muse-spark"')
    ap.add_argument("--backend", default="mock", choices=["mock", "cap_harness"])
    ap.add_argument("--aspire", type=Path, default=None, help="ASPIRE checkout (cap_harness)")
    ap.add_argument("--synthesizer", default="patch", choices=["patch"])
    ap.add_argument("--gate", default="strict", choices=["strict", "off"])
    ap.add_argument("--stall-window", type=int, default=3)
    ap.add_argument("--min-severity", type=float, default=0.3)
    ap.add_argument("--severity-bound", type=float, default=0.8)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    out = args.out or Path("data/runs") / f"loop_{time.strftime('%Y%m%d_%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "attacks.jsonl").unlink(missing_ok=True)
    aspire = None
    if args.backend == "cap_harness":
        root = {"root": args.aspire} if args.aspire else {}
        aspire = AspireConfig(**root, output_root=out / "aspire")
    adv = Adversary.from_config(
        AdversaryConfig(
            model=args.model,
            backend=args.backend,
            categories=tuple(c.strip() for c in args.categories.split(",") if c.strip()),
            min_severity=args.min_severity,
            bounds=Bounds(default=args.severity_bound),
            seed=args.seed,
            history_path=out / "attacks.jsonl",
            aspire=aspire,
        )
    )
    policy = Policy("bowl_on_plate", 0, args.task, args.policy.read_text(encoding="utf-8"))
    cfg = LoopConfig(
        cycles=args.cycles, gate_mode=args.gate, stall_window=args.stall_window, out=out
    )
    res = Loop(adv, PatchSynthesizer(), cfg).run(policy)
    for r in res.cycles:
        sig = r.get("signature", "")
        print(f"{r['cycle']:3d} v{r['policy_version']} {r['category']:9s} {r['outcome']:7s} "
              f"{r.get('decision', ''):10s} {sig}")  # fmt: skip
    print(f"\nstopped: {res.stopped} ({res.stage}), final v{res.incumbent.version}, "
          f"accepted {res.accepted_versions}")  # fmt: skip
    if res.escalation:
        print(f"escalation: {res.escalation['request']}")
    print(f"log: {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
