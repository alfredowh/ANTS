"""CLI entry point for the live orchestrator console.

    uv run python -m ants.studio.console                        # full loop, mock Adversary
    uv run python -m ants.studio.console --mode single --max-model-steps 6 --reasoning-effort medium
    uv run python -m ants.studio.console --cycles 6 --max-model-steps 6 --reasoning-effort medium

Opens one local page with a turns viewer in the center, Synthesizer/Adversary/orchestrator
tools on the sides, and a Run button gated by a "ready to run the policy development phase?"
confirmation.

Two modes (`--mode`):
- "loop" (default): drives the real closed loop (`ants.orchestrator.loop.Loop`) against the mock
  Adversary backend (free, offline) with Synthesizer's repair step real (`muse exec`). Each cycle is
  one attack -> rewrite -> gate verdict, streamed live from `loop.jsonl` as it is written.
- "single": one Phase A repair step only, no Adversary call -- the cheaper/faster v1 path.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ants.studio.console_server import REPO_ROOT, LoopRunConfig, serve


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--incumbent",
        type=Path,
        default=REPO_ROOT / "examples" / "bowl_on_plate" / "policy.py",
        help="program shown as the incumbent",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--mode", choices=("loop", "single"), default="loop")
    parser.add_argument("--reasoning-effort", default="high", help="Muse Code reasoning effort")
    parser.add_argument(
        "--max-model-steps",
        type=int,
        default=20,
        help="hard cap on Muse Code tool/model steps per rewrite call",
    )
    # loop-mode only -- small defaults (3 cycles, 1 nominal seed, W=2) for a cheap, fast demo
    parser.add_argument("--cycles", type=int, default=3, help="max attacks in the loop")
    parser.add_argument(
        "--categories", default=None, help="comma-separated attack categories (default: all)"
    )
    parser.add_argument(
        "--backend",
        choices=("mock", "cap_harness"),
        default="mock",
        help="Adversary rollout backend. 'mock' (default): free, instant, offline. 'cap_harness': "
        "real ASPIRE/LIBERO rollouts (~40s+ each, real GPU time) -- needs the sam3/pyroki/curobo "
        "services up (uv run python -m ants.orchestrator.preflight); rollout videos appear in the "
        "Adversary view's Replay.",
    )
    parser.add_argument("--rho", type=float, default=0.8, help="severity bound")
    parser.add_argument("--eta", type=float, default=0.2, help="selector exploration rate")
    parser.add_argument(
        "--adversary-model",
        default="mock",
        help="'mock' (free, default) or 'muse-spark' (spends tokens, unbudgeted here)",
    )
    parser.add_argument("--n-agents", type=int, default=4, help="Adversary proposer agents")
    parser.add_argument("--stop-mode", choices=("min_tests", "posterior"), default="min_tests")
    parser.add_argument("--min-tests", type=int, default=2)
    parser.add_argument("--tau", type=float, default=0.1)
    parser.add_argument("--stall-window", type=int, default=2, help="W: cycles before escalation")
    parser.add_argument(
        "--nominal-seeds",
        default="51",
        help="comma-separated acceptance seeds for the nominal cases (default: one seed)",
    )
    parser.add_argument(
        "--synth-token-budget",
        type=int,
        default=200_000,
        help="hard cap on total Muse tokens across every rewrite in the loop",
    )
    parser.add_argument(
        "--scene",
        type=Path,
        default=REPO_ROOT / "data" / "scenes" / "L1" / "contacts_scene.json",
        help="oracle scene (contacts_scene.json) shown as the 2D illustration; omit by passing a "
        "missing path -- the panel then just says no scene data",
    )
    parser.add_argument(
        "--scene-repair",
        type=Path,
        default=None,
        help="separate scene to show under the 'repair' toggle; defaults to --scene (same data, "
        "E3-style evidence over it is not wired into this console yet)",
    )
    parser.add_argument(
        "--session",
        default=None,
        help="resume an existing session folder data/console_sessions/<id> (default: start a new "
        "one). A session stores session.json, chat.jsonl, events.jsonl and runs/run-<ts>/.",
    )
    parser.add_argument(
        "--adversary-run",
        type=Path,
        default=None,
        help="run folder the Adversary view shows while this session has no run of its own, e.g. "
        "a finished ants.orchestrator.run directory (read-only)",
    )
    parser.add_argument(
        "--video-dir",
        type=Path,
        default=None,
        help="folder /policy-dev's file dialog opens at (default: the skill file's, "
        "hurobo/data/raw/e1/clips)",
    )
    parser.add_argument(
        "--pipeline-token-budget",
        type=int,
        default=None,
        help="/policy-dev: default of the dialog's Muse token cap (default: the skill file's, "
        "300000)",
    )
    args = parser.parse_args()

    loop_cfg = LoopRunConfig(
        backend=args.backend,
        cycles=args.cycles,
        categories=tuple(args.categories.split(",")) if args.categories else None,
        rho=args.rho,
        eta=args.eta,
        adversary_model=args.adversary_model,
        n_agents=args.n_agents,
        stop_mode=args.stop_mode,
        min_tests=args.min_tests,
        tau=args.tau,
        stall_window=args.stall_window,
        nominal_seeds=tuple(int(s) for s in args.nominal_seeds.split(",")),
        synth_token_budget=args.synth_token_budget,
        video_dir=args.video_dir,
        pipeline_token_budget=args.pipeline_token_budget,
        reasoning_effort=args.reasoning_effort,
        max_model_steps=args.max_model_steps,
    )
    serve(
        incumbent=args.incumbent,
        host=args.host,
        port=args.port,
        mode=args.mode,
        reasoning_effort=args.reasoning_effort,
        max_model_steps=args.max_model_steps,
        loop_cfg=loop_cfg,
        scene_generation_path=args.scene,
        scene_repair_path=args.scene_repair,
        adversary_run=args.adversary_run,
        session_id=args.session,
    )


if __name__ == "__main__":
    main()
