"""Run the closed loop on one policy and log every decision.

    uv run python -m ants.orchestrator.run --cycles 30                      # mock world, free
    uv run python -m ants.orchestrator.run --cycles 10 --backend cap_harness --aspire ../ASPIRE

Writes `<out>/loop.jsonl` (every loop decision), `<out>/attacks.jsonl` (one studio row per
attack), `<out>/history.jsonl` (System 2's history), `<out>/policies/v<N>.py`, `<out>/summary.json`
and `<out>/studio.html` (Harden, Replay and Versions views).

`--synthesizer patch` (default) is an offline fixture: it applies hand-written patches that the
MOCK world rewards, so a run with it shows that the loop, gate and escalation work, never that a
policy got more robust. Mock-world numbers are not results. `--synthesizer muse-code
--synth-token-budget N` uses System 1's Muse Code repair step (`MuseOrchestrator`, branch
`synthesizer`) through `GenerateSynthesizer`; tokens per rewrite are logged in each cycle.
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
    return res, build(out)


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
        choices=["patch", "muse-code"],
        help="patch: offline test fixture. muse-code: System 1's MuseOrchestrator (needs the "
        "synthesizer branch merged and the `muse` CLI; costs Muse tokens)",
    )
    ap.add_argument(
        "--synth-token-budget",
        type=int,
        default=None,
        help="tokens the muse-code synthesizer may spend this run (required for muse-code; "
        "about 43k per cycle observed)",
    )
    ap.add_argument("--gate", default="strict", choices=["strict", "off"])
    ap.add_argument("--stall-window", type=int, default=3)
    ap.add_argument("--min-severity", type=float, default=0.3)
    ap.add_argument("--severity-bound", type=float, default=0.8)
    ap.add_argument("--seed", type=int, default=0)
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
    loop_cfg = LoopConfig(cycles=args.cycles, gate_mode=args.gate, stall_window=args.stall_window)
    synth = None
    if args.synthesizer == "muse-code":
        if args.synth_token_budget is None:
            ap.error("--synthesizer muse-code needs an explicit --synth-token-budget")
        synth = muse_code_synthesizer(out, args.synth_token_budget)
    res, page = run_loop(
        out, adv_cfg, loop_cfg, policy, synthesizer=synth, severity_bound=args.severity_bound
    )
    for r in res.cycles:
        sig = r.get("signature", "")
        print(f"{r['cycle']:3d} v{r['policy_version']} {r['category']:9s} {r['outcome']:7s} "
              f"{r.get('decision', ''):10s} {sig}")  # fmt: skip
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
