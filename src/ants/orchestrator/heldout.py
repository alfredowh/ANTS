"""Held-out evaluation: v0 and the final policy on cases System 1 never saw.

    uv run python -m ants.orchestrator.heldout --run data/runs/<loop run>             # mock world
    uv run python -m ants.orchestrator.heldout --run data/runs/<loop run> --n 50 \\
        --backend cap_harness --aspire ASPIRE

Or right after a loop: `uv run python -m ants.orchestrator.run ... --eval-held-out 50`.

Cases. `n` cases, categories in round robin (balanced), one perturbation each at a severity drawn
uniformly in [min_severity, bound] from a random stream of its own (`heldout-<seed>`), so the
held-out cases never coincide with what the adversary proposed during the loop. Every case is a
`Split.HELD_OUT` `CaseSpec`; held-out results are only written here, never turned into Feedback.

Seeds. On cap_harness the backend is built with `split=Split.HELD_OUT`, so case i runs on ASPIRE
held-out seed i + 1 (1-50) and can never run an acceptance seed (51-65). The mock world has no
seed split; mock numbers check the pipeline only and are not results.

Writes `heldout.json` (config, every case, every outcome per policy) and `heldout.md` to the run.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import random
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ants.adversary import Adversary, AdversaryConfig
from ants.adversary.perturbations import CATEGORIES, Bounds, make
from ants.adversary.rollout import AspireConfig
from ants.contracts import CaseSpec, Outcome, Policy, Split


def held_out_cases(
    n: int,
    categories: Sequence[str] = CATEGORIES,
    bounds: Bounds | None = None,
    min_severity: float = 0.3,
    seed: int = 0,
    suite: str = "libero_goal_swap",
    task_id: int = 8,
) -> list[CaseSpec]:
    """Deterministic, category-balanced held-out cases (case i uses held-out seed index i)."""
    bounds = bounds or Bounds()
    rng = random.Random(f"heldout-{seed}")
    cases = []
    for i in range(n):
        cat = categories[i % len(categories)]
        sev = rng.uniform(min(min_severity, bounds.limit(cat)), bounds.limit(cat))
        p = make(cat, sev, rng, bounds, seed=i)
        cases.append(CaseSpec(f"heldout-{i:03d}", suite, task_id, i, Split.HELD_OUT, (p,)))
    return cases


def evaluate(
    adv: Adversary, policies: Sequence[Policy], cases: Sequence[CaseSpec]
) -> dict[str, Any]:
    """Replay every policy on every held-out case; success rate overall and per category."""
    if any(not c.held_out for c in cases):
        raise ValueError("held-out evaluation got a case that is not Split.HELD_OUT")
    out: dict[str, Any] = {}
    for policy in policies:
        rows = []
        for case in cases:
            r = adv.replay(policy, list(case.perturbations), seed=case.seed)[0]
            rows.append(
                {
                    "case_id": case.case_id,
                    "category": case.perturbations[0].category,
                    "outcome": r.outcome.value,
                    "harness_seed": r.details.get("harness_seed"),
                }
            )
        per_cat: dict[str, list[int]] = {}
        for row in rows:
            ok = row["outcome"] == Outcome.SUCCESS.value
            per_cat.setdefault(row["category"], []).append(int(ok))
        passed = sum(row["outcome"] == Outcome.SUCCESS.value for row in rows)
        out[f"v{policy.version}"] = {
            "version": policy.version,
            "passed": passed,
            "cases": len(rows),
            "success_rate": round(passed / len(rows), 4) if rows else 0.0,
            "errors": sum(row["outcome"] == Outcome.ERROR.value for row in rows),
            "per_category": {c: round(sum(v) / len(v), 4) for c, v in per_cat.items()},
            "outcomes": rows,
        }
    return out


def held_out_adversary(config: AdversaryConfig, out: Path) -> Adversary:
    """An adversary whose backend can only run held-out seeds (cap_harness), history-free."""
    aspire = None
    if config.backend == "cap_harness":
        base = config.aspire or AspireConfig()
        aspire = dataclasses.replace(base, split=Split.HELD_OUT, output_root=out / "aspire_heldout")
    return Adversary.from_config(
        dataclasses.replace(config, model="mock", aspire=aspire, history_path=None)
    )


def report(results: dict[str, Any], backend: str) -> str:
    lines = [
        "# Held-out evaluation",
        "",
        f"Backend `{backend}`. Cases never reach System 1.",
        "",
        "| Policy | Passed | Success rate | Crashes |",
        "|---|---|---|---|",
    ]
    for name, r in results.items():
        lines.append(f"| {name} | {r['passed']}/{r['cases']} | {r['success_rate']:.0%} "
                     f"| {r['errors']} |")  # fmt: skip
    cats = sorted({c for r in results.values() for c in r["per_category"]})
    if cats:
        lines += ["", "| Category | " + " | ".join(results) + " |",
                  "|---|" + "---|" * len(results)]  # fmt: skip
        for c in cats:
            vals = [f"{r['per_category'].get(c, 0):.0%}" for r in results.values()]
            lines.append(f"| {c} | " + " | ".join(vals) + " |")
    if backend == "mock":
        lines += ["", "Mock world: checks the pipeline only. These numbers are not results."]
    return "\n".join(lines) + "\n"


def run_held_out(
    out: Path,
    config: AdversaryConfig,
    policies: Sequence[Policy],
    n: int = 50,
    seed: int = 0,
) -> dict[str, Any]:
    """Build the cases, evaluate every policy, write heldout.json and heldout.md."""
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    cases = held_out_cases(n, config.categories, config.bounds, config.min_severity, seed)
    results = evaluate(held_out_adversary(config, out), policies, cases)
    doc = {
        "experiment": "held_out",
        "started": started,
        "finished": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "backend": config.backend,
        "n": n,
        "seed": seed,
        "categories": list(config.categories),
        "min_severity": config.min_severity,
        "bounds": dataclasses.asdict(config.bounds),
        "cases": [c.to_dict() for c in cases],
        "results": results,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "heldout.json").write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
    (out / "heldout.md").write_text(report(results, config.backend), encoding="utf-8")
    return results


def load_run_policies(run: Path) -> list[Policy]:
    """v0 and the final accepted version of a logged loop run."""
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    versions = sorted({0, int(summary["final_version"])})
    return [
        Policy.from_dict(json.loads((run / "policies" / f"v{v}.json").read_text(encoding="utf-8")))
        for v in versions
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--run", type=Path, required=True, help="a loop run directory")
    ap.add_argument("--n", type=int, default=50, help="held-out cases (ASPIRE has 50 seeds)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--categories", default=",".join(CATEGORIES))
    ap.add_argument("--min-severity", type=float, default=0.3)
    ap.add_argument("--severity-bound", type=float, default=0.8)
    ap.add_argument("--backend", default="mock", choices=["mock", "cap_harness"])
    ap.add_argument("--aspire", type=Path, default=None, help="ASPIRE checkout (cap_harness)")
    args = ap.parse_args(argv)
    if args.backend == "cap_harness" and args.n > 50:
        ap.error("ASPIRE has 50 held-out seeds; use --n 50 or fewer")
    config = AdversaryConfig(
        backend=args.backend,
        categories=tuple(c.strip() for c in args.categories.split(",") if c.strip()),
        min_severity=args.min_severity,
        bounds=Bounds(default=args.severity_bound),
        aspire=AspireConfig(root=args.aspire) if args.aspire else None,
    )
    results = run_held_out(args.run, config, load_run_policies(args.run), args.n, args.seed)
    print(report(results, args.backend))
    print(f"logged: {(args.run / 'heldout.json').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
