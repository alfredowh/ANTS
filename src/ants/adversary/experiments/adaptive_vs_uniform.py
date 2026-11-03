"""H1a: does adaptive category selection find more failures per attack than uniform sampling?

    uv run python -m ants.adversary.experiments.adaptive_vs_uniform                 # mock world
    uv run python -m ants.adversary.experiments.adaptive_vs_uniform --backend cap_harness \\
        --aspire ASPIRE --attacks 20 --seeds 0 1 2

One fixed policy (no rewrites, so only the test planner differs), the same attack budget and the
same seeds for both arms. The arms differ only in eta: ANTS (eta = 0.2, Thompson sampling) and the
uniform baseline (eta = 1.0), as in the paper's evaluation protocol. Seeds are paired: seed s runs
in both arms.

Reported per arm: task failures found, failures per attack, distinct failure signatures (coverage:
adaptive testing can find more failures of fewer kinds) and crashes (ERROR, never counted as
failures). Writes `results.json` (config, one row per arm and seed with the cumulative failure
curve), `summary.md` and the figure (`figure.svg`, `figure.html`) to the run directory.

Mock-world numbers check the experiment pipeline only; they are not results. Reported numbers
come from the cap_harness backend.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ants.adversary.adversary import Adversary
from ants.adversary.config import AdversaryConfig
from ants.adversary.experiments.figure import write as write_figure
from ants.adversary.perturbations import CATEGORIES
from ants.adversary.rollout import AspireConfig
from ants.contracts import Outcome, Policy

ARMS = {"adaptive": 0.2, "uniform": 1.0}
DEFAULT_POLICY = Path("examples/bowl_on_plate/policy.py")


@dataclass(frozen=True)
class ArmRun:
    arm: str
    eta: float
    seed: int
    attacks: int
    failures: int
    errors: int
    signatures: tuple[str, ...]
    picked: dict[str, int]
    failed: dict[str, int]
    cumulative: tuple[int, ...]  # failures found after attack 1..n

    @property
    def failures_per_attack(self) -> float:
        return self.failures / self.attacks if self.attacks else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {**vars(self), "failures_per_attack": round(self.failures_per_attack, 4)}


def run_arm(arm: str, policy: Policy, attacks: int, base: AdversaryConfig) -> ArmRun:
    """Attack one fixed policy `attacks` times with this arm's eta."""
    eta = ARMS[arm]
    adv = Adversary.from_config(AdversaryConfig(**{**vars(base), "eta": eta}))
    picked, failed, sigs, cumulative = Counter(), Counter(), [], []
    errors = 0
    for _ in range(attacks):
        report = adv.attack(policy)
        cat = report.perturbation.category
        picked[cat] += 1
        if report.result.outcome is Outcome.FAILURE:
            failed[cat] += 1
            sig = report.constraint.failure_signature if report.constraint else cat
            if sig not in sigs:
                sigs.append(sig)
        elif report.result.outcome is Outcome.ERROR:
            errors += 1
        cumulative.append(sum(failed.values()))
    return ArmRun(
        arm, eta, base.seed, attacks, sum(failed.values()), errors, tuple(sigs),
        dict(picked), dict(failed), tuple(cumulative),
    )  # fmt: skip


def _mean_sd(xs: Sequence[float]) -> str:
    sd = statistics.stdev(xs) if len(xs) > 1 else 0.0
    return f"{statistics.mean(xs):.2f} ± {sd:.2f}"


def summarize(runs: Sequence[ArmRun], backend: str) -> str:
    seeds = sorted({r.seed for r in runs})
    attacks = runs[0].attacks if runs else 0
    lines = [
        "# Adaptive vs uniform test selection (H1a)",
        "",
        f"Backend `{backend}`, {attacks} attacks per run, seeds {seeds}, one fixed policy.",
        "Mean ± sd over seeds.",
        "",
        "| Arm | eta | Failures | Failures / attack | Distinct signatures | Crashes |",
        "|---|---|---|---|---|---|",
    ]
    for arm, eta in ARMS.items():
        rs = [r for r in runs if r.arm == arm]
        if not rs:
            continue
        lines.append(
            f"| {arm} | {eta} | {_mean_sd([r.failures for r in rs])} "
            f"| {_mean_sd([r.failures_per_attack for r in rs])} "
            f"| {_mean_sd([len(r.signatures) for r in rs])} "
            f"| {_mean_sd([r.errors for r in rs])} |"
        )
    if backend == "mock":
        lines += ["", "Mock world: checks the pipeline only. These numbers are not results."]
    return "\n".join(lines) + "\n"


def run(
    out: Path,
    policy: Policy,
    attacks: int,
    seeds: Sequence[int],
    base: AdversaryConfig,
) -> list[ArmRun]:
    out.mkdir(parents=True, exist_ok=True)
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    runs = [
        run_arm(arm, policy, attacks, AdversaryConfig(**{**vars(base), "seed": s}))
        for s in seeds
        for arm in ARMS
    ]
    config = {k: v for k, v in vars(base).items() if k not in ("aspire", "history_path", "seed")}
    results = {
        "experiment": "adaptive_vs_uniform",
        "started": started,
        "finished": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "policy": {"id": policy.policy_id, "version": policy.version},
        "attacks": attacks,
        "seeds": list(seeds),
        "arms": ARMS,
        "config": config,
        "runs": [r.to_dict() for r in runs],
    }
    (out / "results.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    (out / "summary.md").write_text(summarize(runs, base.backend), encoding="utf-8")
    write_figure(out)
    return runs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--attacks", type=int, default=20, help="attack budget per run")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2, 3, 4])
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--categories", nargs="+", default=list(CATEGORIES))
    ap.add_argument("--model", default="mock", help='"mock" (rules only) or "muse-spark"')
    ap.add_argument("--backend", default="mock", choices=["mock", "cap_harness"])
    ap.add_argument("--aspire", type=Path, default=None, help="ASPIRE checkout (cap_harness)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    out = args.out or Path("data/runs") / f"adaptive_vs_uniform_{time.strftime('%Y%m%d_%H%M%S')}"
    policy = Policy(
        args.policy.stem, 0, "put the bowl on the plate", args.policy.read_text(encoding="utf-8")
    )
    base = AdversaryConfig(
        model=args.model,
        backend=args.backend,
        categories=tuple(args.categories),
        aspire=AspireConfig(root=args.aspire) if args.aspire else None,
    )
    runs = run(out, policy, args.attacks, args.seeds, base)
    print(summarize(runs, args.backend))
    print(f"logged: {(out / 'results.json').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
