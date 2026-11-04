"""H1a: does adaptive category selection find more failures per attack than uniform sampling?

    uv run python -m ants.adversary.experiments.adaptive_vs_uniform                 # mock world
    uv run python -m ants.adversary.experiments.adaptive_vs_uniform --backend cap_harness \\
        --aspire ASPIRE --attacks 40 --seeds 0 1 2 3 4

One fixed policy (no rewrites, so only the test planner differs), the same attack budget and the
same seeds for both arms. The arms differ only in eta: ANTS (eta = 0.2, Thompson sampling) and the
uniform baseline (eta = 1.0), as in the paper's evaluation protocol. Seeds are paired: seed s runs
in both arms.

Severity: every attack is drawn in [--min-severity, --severity-bound], by default 0.3 to 0.8, the
same range as the closed loop (`orchestrator.run`) and the paper's rho. Both are logged.

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
import math
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
from ants.adversary.perturbations import CATEGORIES, Bounds
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


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for k successes in n trials (sensible for rare events)."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def summarize(runs: Sequence[ArmRun], backend: str, bounds: str = "") -> str:
    seeds = sorted({r.seed for r in runs})
    attacks = runs[0].attacks if runs else 0
    lines = [
        "# Adaptive vs uniform test selection (H1a)",
        "",
        f"Backend `{backend}`, {attacks} attacks per run, seeds {seeds}, one fixed policy.",
        *([f"Severity {bounds}."] if bounds else []),
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
    # Pooled over seeds with a 95% interval, and the paired per-seed difference: failures are rare,
    # so the per-seed spread alone cannot separate a real difference from noise.
    lines += [
        "",
        "| Arm | Failures / attacks (pooled) | Rate | 95% CI (Wilson) |",
        "|---|---|---|---|",
    ]
    for arm in ARMS:
        rs = [r for r in runs if r.arm == arm]
        if rs:
            k, n = sum(r.failures for r in rs), sum(r.attacks for r in rs)
            lo, hi = wilson(k, n)
            lines.append(f"| {arm} | {k} / {n} | {k / n:.3f} | {lo:.3f} to {hi:.3f} |")
    diffs = [
        a.failures - u.failures
        for a in runs
        if a.arm == "adaptive"
        for u in runs
        if u.arm == "uniform" and u.seed == a.seed
    ]
    if diffs:
        wins = sum(d > 0 for d in diffs)
        ties = sum(d == 0 for d in diffs)
        lines += [
            "",
            f"Paired by seed, adaptive minus uniform failures: {diffs} "
            f"(adaptive more in {wins}, tie in {ties}, of {len(diffs)} seeds).",
        ]
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
    bounds = f"{base.min_severity:g} to {base.bounds.default:g}"
    (out / "summary.md").write_text(summarize(runs, base.backend, bounds), encoding="utf-8")
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
    ap.add_argument(
        "--severity-bound", type=float, default=0.8, help="largest severity (rho; as the loop)"
    )
    ap.add_argument(
        "--min-severity", type=float, default=0.3, help="smallest severity (as the loop)"
    )
    args = ap.parse_args(argv)
    out = args.out or Path("data/runs") / f"adaptive_vs_uniform_{time.strftime('%Y%m%d_%H%M%S')}"
    policy = Policy(
        args.policy.stem, 0, "put the bowl on the plate", args.policy.read_text(encoding="utf-8")
    )
    root = {"root": args.aspire} if args.aspire else {}
    on_gpu = args.backend == "cap_harness"  # rollouts go into this run's own folder
    base = AdversaryConfig(
        model=args.model,
        backend=args.backend,
        categories=tuple(args.categories),
        bounds=Bounds(default=args.severity_bound),
        min_severity=args.min_severity,
        aspire=AspireConfig(**root, output_root=out / "aspire") if on_gpu else None,
    )
    runs = run(out, policy, args.attacks, args.seeds, base)
    print(summarize(runs, args.backend, f"{args.min_severity:g} to {args.severity_bound:g}"))
    print(f"logged: {(out / 'results.json').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
