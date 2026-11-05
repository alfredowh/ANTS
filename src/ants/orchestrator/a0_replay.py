"""A0: replay every exp03 program with the simulator contact log, and say what blocked each stall.

    uv run python -m ants.orchestrator.a0_replay --aspire ASPIRE --out data/evidence/a0

Each program runs once in the scaled L1 scene (seed 51) through `tools/aspire_launch.py` with the
contact log on. The answer key for a stall is the blocking contact (a robot part that pressed on an
object other than the grasped bowl); a stall with no blocking contact has another cause.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ants.contracts import CaseSpec, Split
from ants.evalkit.aspire_harness import CapHarness
from ants.evalkit.contacts import analyse
from ants.orchestrator.scene_context_exp import scene_spec


def replay(args: argparse.Namespace, clip: str, attempt: int) -> dict:
    """One program, retried when the harness or a local service times out or fails."""
    last: dict = {}
    for _ in range(args.retries + 1):
        try:
            last = _replay_once(args, clip, attempt)
        except Exception as err:  # a timeout or crash must not stop the batch
            last = {"clip": clip, "attempt": attempt, "error": f"{type(err).__name__}: {err}"[:300]}
        if not last.get("error"):
            return last
        print(clip, attempt, "retry after", last["error"][:120], flush=True)
    return last


def _replay_once(args: argparse.Namespace, clip: str, attempt: int) -> dict:
    out = args.out.resolve() / f"{clip}_a{attempt}"
    program = Path(args.runs) / f"clip_{clip}" / "demo" / "sample0" / f"program_attempt{attempt}.py"
    if not program.exists():
        return {"clip": clip, "attempt": attempt, "skipped": "no program"}
    done = out / "analysis.json"
    if done.exists():
        return json.loads(done.read_text(encoding="utf-8"))
    harness = CapHarness(
        args.aspire.resolve(),
        timeout_s=args.timeout_s,
        launcher=Path("tools/aspire_launch.py").resolve(),
        scene=scene_spec({}, out / "contacts.jsonl"),
    )
    case = CaseSpec("debug-51", "libero_goal_swap", 8, 51, Split.ACCEPTANCE)
    trace = harness.run(case, program.resolve(), out / "run", f"a0-{clip}-a{attempt}")
    if not trace.run_dir or not (out / "contacts_scene.json").exists():
        res = {"clip": clip, "attempt": attempt, "error": trace.error or trace.termination_reason}
    else:
        scene = json.loads((out / "contacts_scene.json").read_text(encoding="utf-8"))
        a = analyse(
            out / "contacts.jsonl",
            Path(trace.run_dir),
            scene,
            tuple(scene["bodies"]["robot0_base"]["pos"]),
        )
        a.pop("overlay")
        res = {"clip": clip, "attempt": attempt, **a}
    done.parent.mkdir(parents=True, exist_ok=True)
    done.write_text(json.dumps(res), encoding="utf-8")
    print(
        clip,
        attempt,
        "success" if res.get("success") else "failed",
        "stalls",
        len(res.get("failed_calls", [])),
        "blocking",
        [(e["part"], e["object"], e["n_steps"]) for e in res.get("blocking", [])],
        flush=True,
    )
    return res


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--aspire", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--runs", default="data/runs/exp03_explain")
    p.add_argument("--clips", default="233832,233859,234314")
    p.add_argument("--attempts", default="0,1,2,3,4")
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--retries", type=int, default=2)
    p.add_argument(
        "--timeout-s", type=float, default=1800.0, help="per program, generous on purpose"
    )
    args = p.parse_args(argv)
    jobs = [(c, int(a)) for c in args.clips.split(",") for a in args.attempts.split(",")]
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(lambda j: replay(args, *j), jobs))
    (args.out / "summary.json").write_text(json.dumps(results), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
