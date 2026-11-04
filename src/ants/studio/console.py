"""CLI entry point for the live orchestrator console.

    uv run python -m ants.studio.console [--incumbent PATH] [--port 8765]

Opens one local page with a turns viewer in the center, System 1/2/orchestrator tools on the
sides, and a Run button gated by a "ready to run the policy development phase?" confirmation. Each
run is one Phase A repair step (`muse exec`), not the full loop -- see console_server.py's module
docstring for why.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ants.studio.console_server import REPO_ROOT, serve


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--incumbent",
        type=Path,
        default=REPO_ROOT / "examples" / "bowl_on_plate" / "policy.py",
        help="program shown as the incumbent and sent to the repair step",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument(
        "--max-model-steps",
        type=int,
        default=20,
        help="hard cap on Muse Code tool/model steps for the one repair call",
    )
    args = parser.parse_args()
    serve(
        incumbent=args.incumbent,
        host=args.host,
        port=args.port,
        reasoning_effort=args.reasoning_effort,
        max_model_steps=args.max_model_steps,
    )


if __name__ == "__main__":
    main()
