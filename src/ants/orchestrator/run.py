"""Run the closed loop on one policy and log every decision.

    uv run python -m ants.orchestrator.run --cycles 30                      # mock world, free
    uv run python -m ants.orchestrator.run --cycles 10 --backend cap_harness --aspire ../ASPIRE

Writes `<out>/loop.jsonl` (every loop decision), `<out>/attacks.jsonl` (one studio row per
attack), `<out>/history.jsonl` (System 2's history), `<out>/policies/v<N>.py`, `<out>/summary.json`
and `<out>/studio.html` (Harden, Replay and Versions views).

`--synthesizer patch` (default) is an offline fixture: it applies hand-written patches that the
MOCK world rewards, so a run with it shows that the loop, gate and escalation work, never that a
policy got more robust. Mock-world numbers are not results. System 1's real repair step, both
sending `docs/orchestrator/phases.md` and both needing `--synth-token-budget N`:
- `--synthesizer muse-code`: Muse Code through the `muse` CLI (`MuseOrchestrator`, via
  `GenerateSynthesizer`).
- `--synthesizer muse-api`: Muse Wonder through the Meta API (`default_synthesizer()`); needs only
  `META_API_KEY` and the ASPIRE checkout (its API reference and example program), no `muse` CLI.
Tokens and $ per rewrite are logged in each cycle.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from ants.adversary import Adversary, AdversaryConfig
from ants.adversary.perturbations import CATEGORIES, Bounds
from ants.adversary.rollout import AspireConfig
from ants.contracts import Policy
from ants.orchestrator.heldout import report, run_held_out
from ants.orchestrator.loop import Loop, LoopConfig, LoopResult
from ants.orchestrator.synthesis import GenerateSynthesizer, PatchSynthesizer, Synthesizer
from ants.studio.build import build
from ants.studio.run import append_row, attack_row, nominal_events

DEFAULT_POLICY = Path("examples/bowl_on_plate/policy.py")


def run_loop(
    out: Path,
    adv_config: AdversaryConfig,
    loop_config: LoopConfig,
    policy: Policy,
    synthesizer: Synthesizer | None = None,
    severity_bound: float | None = None,
) -> tuple[LoopResult, Path]:
    """Run the loop with studio logging; returns the result and the studio page."""
    out.mkdir(parents=True, exist_ok=True)
    for stale in ("loop.jsonl", "attacks.jsonl", "history.jsonl", "summary.json"):
        (out / stale).unlink(missing_ok=True)  # a run always starts from empty logs
    adv = Adversary.from_config(
        AdversaryConfig(**{**vars(adv_config), "history_path": out / "history.jsonl"})
    )
    cfg = adv.config
    (out / "policy.py").write_text(policy.code, encoding="utf-8")
    meta = {
        "name": out.name,
        "kind": "loop",
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "task": policy.task,
        "policy": {"id": policy.policy_id, "version": policy.version, "path": "policy.py"},
        "backend": cfg.backend,
        "model": cfg.model,
        "attacks_planned": loop_config.cycles,
        "config": {
            "categories": list(cfg.categories),
            "eta": cfg.eta,
            "severity_bound": severity_bound if severity_bound is not None else cfg.bounds.default,
            "rho": 0.8,
            "n_agents": cfg.n_agents if adv.model else 0,
            "stop_mode": cfg.stop_mode,
            "min_tests": cfg.min_tests,
            "tau": cfg.tau,
            "seed": cfg.seed,
            "token_budget": getattr(adv.model, "token_budget", None),
            "rollout_timeout_s": cfg.rollout_timeout_s,
            "gate_mode": loop_config.gate_mode,
            "stall_window": loop_config.stall_window,
            "synthesizer": "patch fixture" if synthesizer is None else type(synthesizer).__name__,
        },
        "nominal": nominal_events(adv, policy, cfg.seed),
    }
    (out / "run.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")

    def on_attack(report, attacked):
        append_row(out / "attacks.jsonl", attack_row(adv, report, attacked))

    lcfg = LoopConfig(**{**vars(loop_config), "out": out})
    res = Loop(adv, synthesizer or PatchSynthesizer(), lcfg, on_attack=on_attack).run(policy)
    meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    meta["tokens_spent"] = getattr(adv.model, "run_spent", 0)
    (out / "run.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    add_total_cost(out / "summary.json", meta["tokens_spent"], lcfg.usd_per_million_tokens)
    return res, build(out)


def add_total_cost(summary_path: Path, adversary_tokens: int, usd_per_million: float) -> None:
    """Add System 2's Muse Spark tokens to the loop's summary: total and per-cycle $."""
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    total = summary.get("rewrite_tokens", 0) + adversary_tokens
    cycles = summary.get("cycles_run", 0)
    summary.update(
        adversary_tokens=adversary_tokens,
        adversary_cost_usd=round(adversary_tokens * usd_per_million / 1e6, 4),
        total_tokens=total,
        total_cost_usd=round(total * usd_per_million / 1e6, 4),
        cost_per_cycle_usd=round(total * usd_per_million / 1e6 / cycles, 4) if cycles else 0.0,
    )
    summary_path.write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")


def muse_code_synthesizer(out: Path, token_budget: int) -> GenerateSynthesizer:
    """System 1's Muse Code repair step behind the loop's `Synthesizer` (imported lazily)."""
    try:
        from ants.orchestrator.muse_orchestrator import MuseOrchestrator
    except ImportError as exc:  # not merged yet
        raise SystemExit(
            "muse-code needs System 1's MuseOrchestrator (branch `synthesizer`); "
            f"it is not on this branch: {exc}"
        ) from exc
    generate = MuseOrchestrator(out_dir=out / "muse", token_budget=token_budget)
    return GenerateSynthesizer(generate, out / "muse" / "incumbents", name="muse-code")


def muse_api_synthesizer(out: Path, token_budget: int, task: str) -> Synthesizer:
    """System 1's Meta-API repair step (`default_synthesizer`), imported lazily.

    Its ChatClient writes its cache and ledger under `out/muse_api/` and stops at `token_budget`
    (a spent budget makes `rewrite()` return None, which the loop logs as a budget stop).
    """
    from ants.synthesizer.muse_synthesizer import default_synthesizer

    try:
        return default_synthesizer(task, token_budget=token_budget, run_dir=out / "muse_api")
    except FileNotFoundError as exc:  # its API reference and example come from ASPIRE
        raise SystemExit(
            "muse-api reads its API reference and example program from the ASPIRE checkout: "
            f"run `git submodule update --init ASPIRE` ({exc})"
        ) from exc


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
    ap.add_argument(
        "--synthesizer",
        default="patch",
        choices=["patch", "muse-code", "muse-api"],
        help="patch: offline test fixture. muse-code: System 1's Muse Code repair step (needs the "
        "`muse` CLI). muse-api: System 1's Meta-API repair step (needs META_API_KEY and the "
        "ASPIRE checkout). Both real ones cost Muse tokens",
    )
    ap.add_argument(
        "--synth-token-budget",
        type=int,
        default=None,
        help="tokens the synthesizer may spend this run (required for muse-code and muse-api; "
        "about 43k per cycle observed)",
    )
    ap.add_argument("--gate", default="strict", choices=["strict", "off"])
    ap.add_argument("--stall-window", type=int, default=3)
    ap.add_argument("--min-severity", type=float, default=0.3)
    ap.add_argument("--severity-bound", type=float, default=0.8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument(
        "--usd-per-million-tokens",
        type=float,
        default=13.5,
        help="Muse price for the $ figures in summary.json (observed about $13.5 per million)",
    )
    ap.add_argument(
        "--eval-held-out",
        type=int,
        default=0,
        metavar="N",
        help="after the loop, evaluate v0 and the final policy on N held-out cases (max 50)",
    )
    args = ap.parse_args(argv)
    if args.backend == "cap_harness" and args.eval_held_out > 50:
        ap.error("ASPIRE has 50 held-out seeds; use --eval-held-out 50 or fewer")

    out = args.out or Path("data/runs") / f"loop_{time.strftime('%Y%m%d_%H%M%S')}"
    aspire = None
    if args.backend == "cap_harness":
        root = {"root": args.aspire} if args.aspire else {}
        aspire = AspireConfig(**root, output_root=out / "aspire")
    adv_cfg = AdversaryConfig(
        model=args.model,
        backend=args.backend,
        categories=tuple(c.strip() for c in args.categories.split(",") if c.strip()),
        min_severity=args.min_severity,
        bounds=Bounds(default=args.severity_bound),
        seed=args.seed,
        aspire=aspire,
    )
    policy = Policy("bowl_on_plate", 0, args.task, args.policy.read_text(encoding="utf-8"))
    loop_cfg = LoopConfig(
        cycles=args.cycles,
        gate_mode=args.gate,
        stall_window=args.stall_window,
        usd_per_million_tokens=args.usd_per_million_tokens,
    )
    synth = None
    if args.synthesizer != "patch" and args.synth_token_budget is None:
        ap.error(f"--synthesizer {args.synthesizer} needs an explicit --synth-token-budget")
    if args.synthesizer == "muse-code":
        synth = muse_code_synthesizer(out, args.synth_token_budget)
    elif args.synthesizer == "muse-api":
        synth = muse_api_synthesizer(out, args.synth_token_budget, args.task)
    res, page = run_loop(
        out, adv_cfg, loop_cfg, policy, synthesizer=synth, severity_bound=args.severity_bound
    )
    for r in res.cycles:
        sig = r.get("signature", "")
        print(f"{r['cycle']:3d} v{r['policy_version']} {r['category']:9s} {r['outcome']:7s} "
              f"{r.get('decision', ''):10s} {sig}")  # fmt: skip
    cost = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    print(f"cost: {cost['total_tokens']} tokens, ${cost['total_cost_usd']:.2f} total, "
          f"${cost['cost_per_cycle_usd']:.3f} per cycle")  # fmt: skip
    print(f"\nstopped: {res.stopped} ({res.stage}), final v{res.incumbent.version}, "
          f"accepted {res.accepted_versions}")  # fmt: skip
    if res.escalation:
        print(f"escalation: {res.escalation['request']}")
    if args.eval_held_out:
        held = run_held_out(
            out, adv_cfg, [policy, res.incumbent] if res.incumbent.version else [policy],
            args.eval_held_out, args.seed,
        )  # fmt: skip
        print("\n" + report(held, args.backend))
    print(f"studio: {page.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
