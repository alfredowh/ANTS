"""A3: how well does ASPIRE's own perception see the scene? Compare it with the simulator.

    uv run python -m ants.orchestrator.a3_perception --aspire ../ASPIRE --out data/evidence/a3

Runs `data/scenes/perception_probe.py` once per scene level (SAM 3 text mask, depth point cloud,
`estimate_geometry`, from the agent-view camera) and compares each object's perceived centre and
extent with the simulator's collision boxes. The camera sees only the visible side of an object, so
part of the extent error is expected; the error of the CENTRE is the number that matters here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ants.adversary.collision_world import load_world
from ants.adversary.rollout import CapHarness
from ants.contracts import CaseSpec
from ants.orchestrator.scene_context_exp import load_levels, scene_for, scene_spec

KEYS = {
    "bowl": "bowl", "plate": "plate", "wine_rack": "wine rack", "wine_bottle": "wine bottle",
    "cream_cheese": "cream cheese", "wooden_cabinet": "wooden cabinet", "flat_stove": "flat stove",
}  # fmt: skip


def probe(args: argparse.Namespace, name: str, level: dict) -> dict:
    out = args.out.resolve() / name
    harness = CapHarness(
        args.aspire.resolve(),
        timeout_s=1800.0,
        launcher=Path("tools/aspire_launch.py").resolve(),
        scene=scene_spec(level, out / "contacts.jsonl"),
    )
    case = CaseSpec(f"a3-{name}", "libero_goal_swap", 8, 51, "acceptance")
    last = None
    for _ in range(3):  # a service timeout is retried
        try:
            trace = harness.run(
                case, Path("data/scenes/perception_probe.py").resolve(), out / "run", f"a3-{name}"
            )
        except Exception as err:
            last = str(err)
            continue
        if trace.run_dir:
            res = json.loads(
                (Path(trace.run_dir) / "source" / "program-result.json").read_text(encoding="utf-8")
            )["result"]
            if res:
                return res
        last = trace.error or trace.termination_reason
    raise RuntimeError(f"probe failed in {name}: {last}")


def compare(perceived: dict, name: str) -> list[dict]:
    world = load_world(scene_for(name))
    rows = []
    for key, label in KEYS.items():
        obj = world.get(label)
        a = obj.aabb
        truth_c = [(a.lo[i] + a.hi[i]) / 2 for i in range(3)]
        truth_size = [a.hi[i] - a.lo[i] for i in range(3)]
        p = perceived.get(key, {})
        if not p.get("ok"):
            rows.append({"object": label, "ok": False, "error": p.get("error")})
            continue
        lo, hi = p["p5"], p["p95"]
        c = [float(v) for v in p["center"]]
        size = [hi[i] - lo[i] for i in range(3)]
        rows.append(
            {
                "object": label, "ok": True, "points": p["n"],
                "centre_err_cm": [round((c[i] - truth_c[i]) * 100, 1) for i in range(3)],
                "centre_err_xy_cm": round(100 * ((c[0] - truth_c[0]) ** 2 + (c[1] - truth_c[1]) ** 2) ** 0.5, 1),
                "truth_size_cm": [round(v * 100, 1) for v in truth_size],
                "seen_size_cm": [round(v * 100, 1) for v in size],
                "extents_cm": [round(float(v) * 100, 1) for v in p["extents"]],
                "truth_centre": [round(v, 3) for v in truth_c], "seen_centre": [round(v, 3) for v in c],
            }
        )  # fmt: skip
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--aspire", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--levels-file", type=Path, default=Path("data/scenes/levels.json"))
    args = p.parse_args(argv)
    levels = load_levels(args.levels_file)
    result = {}
    for name, level in levels.items():
        try:
            perceived = probe(args, name, level)
            result[name] = compare(perceived, name)
            print(
                name,
                [(r["object"], r.get("centre_err_xy_cm", "fail")) for r in result[name]],
                flush=True,
            )
        except Exception as err:  # one level failing must not stop the others
            result[name] = {"error": str(err)[:300]}
            print(name, "failed:", err, flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
