"""Run the v0 bowl-on-plate policy on one LIBERO-Pro seed with ASPIRE's cap-harness.

Standard library only. Usage (from the ANTS repo root, ASPIRE services running):

    uv run python examples/bowl_on_plate/policy_run.py --aspire ../ASPIRE --seed 51

Prints one JSON line: seed, task_success, termination_reason, run_dir.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITE, TASK_ID = "libero_goal_swap", "8"  # "put the bowl on the plate"


def run(aspire: Path, seed: int, out: Path, program: Path = HERE / "policy.py") -> dict:
    env = dict(
        os.environ,
        LIBERO_CONFIG_PATH=str(aspire / ".libero"),
        TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD="1",
        MUJOCO_GL="egl",
        PYOPENGL_PLATFORM="egl",
        EGL_PLATFORM="device",
    )
    cmd = [
        str(aspire / ".venv-libero" / "bin" / "cap-harness"), "run",
        "--benchmark", "libero-pro", "--suite", SUITE, "--task-id", TASK_ID,
        "--seed", str(seed), "--init-mode", "seeded",
        "--program", str(program), "--output-root", str(out),
        "--max-steps", "2000", "--camera-width", "800", "--camera-height", "512",
    ]  # fmt: skip
    proc = subprocess.run(cmd, cwd=aspire, env=env, capture_output=True, text=True, timeout=900)
    outcomes = sorted(out.rglob("outcome.json"), key=lambda p: p.stat().st_mtime)
    if not outcomes:
        return {"seed": seed, "task_success": False, "termination_reason": "harness_error",
                "error": proc.stderr[-1000:]}  # fmt: skip
    outcome = json.loads(outcomes[-1].read_text(encoding="utf-8"))
    return {
        "seed": seed,
        "task_success": bool(outcome.get("task_success")),
        "termination_reason": outcome.get("termination_reason"),
        "run_dir": str(outcomes[-1].parent),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--aspire", type=Path, required=True, help="ASPIRE checkout")
    p.add_argument("--seed", type=int, default=51)
    p.add_argument("--out", type=Path, default=Path("data/runs/policy_v0"))
    p.add_argument("--program", type=Path, default=HERE / "policy.py")
    args = p.parse_args()
    result = run(
        args.aspire.resolve(), args.seed, args.out.resolve() / f"seed{args.seed}", args.program
    )
    print(json.dumps(result))
    return 0 if result["task_success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
