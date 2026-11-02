"""Build the cuRobo plan viewer (3D with before/after toggle, and 2D) for one attempt of a run.

Needs numpy and scipy: run it with ASPIRE's Python from the ANTS root, after a run made with
`--save-clouds` (exp09 to exp11 do this):

    PYTHONPATH=src ../ASPIRE/.venv-libero/bin/python dev/curobo/make_viewer.py \
        data/runs/curobo/exp09/clip_233859 [--attempt 4]

Writes `<run>/plan_viewer/index.html` (3D) and `plans2d.html`. The run viewer
(`ants.evalkit.report`, served with --serve) shows it in the Doc tab. The before/after toggle
replays the plan with my own sphere-against-cloud check; it is not a second cuRobo run.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plan_data  # noqa: E402
import plan_view  # noqa: E402


def attempt_dirs(run: Path) -> dict[int, Path]:
    found = {}
    for d in run.glob("*/sample0/debug_attempt*"):
        if (d / "clouds").is_dir():
            found[int(d.name.removeprefix("debug_attempt"))] = d
    return found


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("run", type=Path, help="e.g. data/runs/curobo/exp09/clip_233859")
    p.add_argument("--attempt", type=int, default=None, help="default: the last attempt")
    args = p.parse_args()
    dirs = attempt_dirs(args.run)
    if not dirs:
        raise SystemExit(f"no debug_attempt*/clouds under {args.run}: run with --save-clouds")
    attempt = args.attempt if args.attempt is not None else max(dirs)
    d = dirs[attempt]
    outcome = next(d.rglob("outcome.json")).parent
    out = args.run / "plan_viewer"
    out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "plans.json"
        plan_data.main(outcome, d / "clouds", data)
        title = f"{args.run.parent.name}/{args.run.name} attempt {attempt}={data}"
        plan_view.main(out / "index.html", [title], "plan_view3d_template.html", card=False)
        plan_view.main(out / "plans2d.html", [title])
    print(f"open: uv run python -m ants.evalkit.report {args.run.parents[1]} --serve")


if __name__ == "__main__":
    main()
