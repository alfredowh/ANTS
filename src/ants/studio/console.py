"""CLI entry point for ANTS Studio.

    uv run python -m ants.studio.console --port 58910 --max-model-steps 6 --reasoning-effort medium

Opens one local page: an Adversary | Synthesizer switch over Daniel's Harden/Replay/Versions page
and the agent console. `/policy-dev` in the chat starts the pipeline after its settings dialog;
backend, attacks, seeds, strategy and budgets are chosen there, not here.
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
    parser.add_argument("--reasoning-effort", default="high", help="Muse Code reasoning effort")
    parser.add_argument(
        "--max-model-steps",
        type=int,
        default=20,
        help="hard cap on Muse Code tool/model steps per rewrite call",
    )
    parser.add_argument(
        "--categories", default=None, help="comma-separated attack categories (default: all)"
    )
    parser.add_argument("--rho", type=float, default=0.8, help="severity bound")
    parser.add_argument("--n-agents", type=int, default=4, help="Adversary proposer agents")
    parser.add_argument("--stop-mode", choices=("min_tests", "posterior"), default="min_tests")
    parser.add_argument("--min-tests", type=int, default=2)
    parser.add_argument("--tau", type=float, default=0.1)
    parser.add_argument(
        "--scene",
        type=Path,
        default=None,
        help="scene file (contacts_scene.json) to show in the scene panel, labelled with its path "
        "(default: the stock scene /policy-dev sends in its prompt)",
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
        categories=tuple(args.categories.split(",")) if args.categories else None,
        rho=args.rho,
        n_agents=args.n_agents,
        stop_mode=args.stop_mode,
        min_tests=args.min_tests,
        tau=args.tau,
        video_dir=args.video_dir,
        pipeline_token_budget=args.pipeline_token_budget,
        reasoning_effort=args.reasoning_effort,
        max_model_steps=args.max_model_steps,
    )
    serve(
        incumbent=args.incumbent,
        host=args.host,
        port=args.port,
        reasoning_effort=args.reasoning_effort,
        max_model_steps=args.max_model_steps,
        loop_cfg=loop_cfg,
        scene_generation_path=args.scene,
        adversary_run=args.adversary_run,
        session_id=args.session,
    )


if __name__ == "__main__":
    main()
