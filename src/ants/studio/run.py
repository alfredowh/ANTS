"""Run System 2 against a policy and log everything the studio shows.

    uv run python -m ants.studio.run --attacks 20                     # rules, mock world, free
    uv run python -m ants.studio.run --attacks 10 --model muse-spark  # Muse Spark, costs tokens

Writes `<out>/run.json`, `<out>/policy.py`, `<out>/attacks.jsonl` (one line per attack: the report,
why it was chosen, the diagnosis source and a plain-language explanation) and `<out>/studio.html`.
The mock world is a test fixture: its numbers are not robot results.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from ants.adversary import Adversary, AdversaryConfig
from ants.adversary.perturbations import Bounds
from ants.contracts import Policy
from ants.studio.build import build

DEFAULT_POLICY = Path("examples/bowl_on_plate/policy.py")


def run(
    out: Path,
    attacks: int,
    model: str = "mock",
    policy_path: Path = DEFAULT_POLICY,
    task: str = "put the bowl on the plate",
    seed: int = 0,
    eta: float = 0.2,
    severity_bound: float = 0.6,
    token_budget: int | None = None,
) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    for stale in ("history.jsonl", "attacks.jsonl"):
        (out / stale).unlink(missing_ok=True)  # a run always starts from an empty log
    code = policy_path.read_text(encoding="utf-8")
    shutil.copyfile(policy_path, out / "policy.py")
    policy = Policy("bowl_on_plate", 0, task, code)
    cfg = AdversaryConfig(
        model=model,
        seed=seed,
        eta=eta,
        bounds=Bounds(default=severity_bound),
        history_path=out / "history.jsonl",
    )
    adv = Adversary.from_config(cfg)
    if token_budget is not None and adv.model is not None and hasattr(adv.model, "token_budget"):
        adv.model.token_budget = token_budget
    meta = {
        "name": out.name,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "task": task,
        "policy": {"id": policy.policy_id, "version": policy.version, "path": str(policy_path)},
        "backend": cfg.backend,
        "model": model,
        "attacks_planned": attacks,
        "config": {
            "categories": list(cfg.categories),
            "eta": cfg.eta,
            "severity_bound": severity_bound,
            "rho": 0.8,
            "n_agents": cfg.n_agents if adv.model else 0,
            "stop_mode": cfg.stop_mode,
            "min_tests": cfg.min_tests,
            "tau": cfg.tau,
            "seed": seed,
            "token_budget": getattr(adv.model, "token_budget", None),
            "rollout_timeout_s": cfg.rollout_timeout_s,
        },
    }
    nominal = adv.replay(policy, [None], seed=seed)[0]
    meta["nominal"] = {
        "outcome": nominal.outcome.value,
        "events": [{"kind": e.kind, **dict(e.detail)} for e in nominal.events],
    }
    (out / "run.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    log = out / "attacks.jsonl"
    for i in range(attacks):
        report = adv.attack(policy)
        notes = adv.history.records[-1].notes
        text, source = adv.explain(report, policy) if report.failure else ("", "none")
        row = {
            "report": report.to_dict(),
            "notes": notes,
            "explanation": text,
            "explanation_source": source,
            "status_after": adv.status(policy).to_dict(),
        }
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
        outcome = report.result.outcome.value
        sig = report.constraint.failure_signature if report.constraint else ""
        print(
            f"{i + 1:3d}/{attacks} {report.perturbation.category:9s} {outcome:7s} {sig}", flush=True
        )
    meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    meta["tokens_spent"] = getattr(adv.model, "run_spent", 0)
    (out / "run.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return build(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--attacks", type=int, default=20)
    ap.add_argument("--model", default="mock", help='"mock" (rules only) or "muse-spark"')
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--eta", type=float, default=0.2, help="1.0 = uniform baseline")
    ap.add_argument("--severity-bound", type=float, default=0.6)
    ap.add_argument(
        "--token-budget",
        type=int,
        default=None,
        help="new Muse tokens this run may spend (default 100k; pass more explicitly)",
    )
    args = ap.parse_args(argv)
    out = args.out or Path("data/runs") / f"studio_{time.strftime('%Y%m%d_%H%M%S')}"
    page = run(
        out, args.attacks, args.model, args.policy, seed=args.seed, eta=args.eta,
        severity_bound=args.severity_bound, token_budget=args.token_budget,
    )  # fmt: skip
    print(f"\nstudio: {page.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
