"""Replay logged attempts through the launcher, with the held-bowl attach on or off.

Dev tool for the attach experiment (experiment-09-11-curobo-attach.md (dev note, not in repo)). The same
seven no-demo and demo programs run under two conditions on seed 51:

- `sparse`: no attach (the single-frame carved cloud, the exp06 to 08 setting).
- `oracle` / `oracle-attach`: the bowl and plate pixels (simulator segmentation, privileged) never
  enter the planning cloud, without or with the attach spheres. An upper bound, not a method.
- `attach`: the held bowl attached. The launcher writes the spheres to `data/runs/curobo/attach.json`,
  the file the dev cuRobo service reads (`ANTS_ATTACH_FILE`). The file is reset before every run.

Runs one at a time (the service has one global attach file). Costs no model tokens: GPU and the
simulator only. Needs the SAM 3 and cuRobo services up (`services.start`, `curobo.service`).

    ASPIRE/.venv-libero/bin/python dev/curobo/replay_attach.py --mode sparse --out data/runs/curobo/replay
    ASPIRE/.venv-libero/bin/python dev/curobo/replay_attach.py --mode attach --out data/runs/curobo/replay

Writes `<out>/<mode>/<label>/` with the spec used, the run output and `result.json`.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASPIRE_PY = ROOT / "ASPIRE" / ".venv-libero" / "bin" / "python"
LAUNCHER = ROOT / "tools" / "aspire_launch.py"
GLOBAL_ATTACH = ROOT / "data" / "runs" / "curobo" / "attach.json"
RUNS = ROOT / "data" / "runs" / "curobo"

# (label, program, base spec). Sam 3 masks for exp10, simulator masks for exp11.
SAM3_SPEC = RUNS / "verify_fix4" / "exp10_clip233859_a3" / "spec.json"
SIM_SPEC = RUNS / "verify_fix3" / "exp11_a2" / "spec.json"
PROGRAMS = [
    ("exp10_nodemo_a1", RUNS / "exp10/nodemo/nodemo/sample0/program_attempt1.py", SAM3_SPEC),
    ("exp10_nodemo_a2", RUNS / "exp10/nodemo/nodemo/sample0/program_attempt2.py", SAM3_SPEC),
    ("exp10_nodemo_a3", RUNS / "exp10/nodemo/nodemo/sample0/program_attempt3.py", SAM3_SPEC),
    ("exp10_clip233859_a3", RUNS / "exp10/clip_233859/demo/sample0/program_attempt3.py", SAM3_SPEC),
    ("exp10_clip233832_a2", RUNS / "exp10/clip_233832/demo/sample0/program_attempt2.py", SAM3_SPEC),
    ("exp10_nodemo_a1_simmask", RUNS / "exp10/nodemo/nodemo/sample0/program_attempt1.py", SIM_SPEC),
    ("exp10_nodemo_a1_sim", RUNS / "exp10/nodemo/nodemo/sample0/program_attempt1.py", SIM_SPEC),
    ("exp10_nodemo_a2_sim", RUNS / "exp10/nodemo/nodemo/sample0/program_attempt2.py", SIM_SPEC),
    ("exp11_nodemo_a0", RUNS / "exp11/nodemo/nodemo/sample0/program_attempt0.py", SIM_SPEC),
    ("exp11_nodemo_a2", RUNS / "exp11/nodemo/nodemo/sample0/program_attempt2.py", SIM_SPEC),
]


def aspire_env() -> dict:
    """The environment the LIBERO and MuJoCo runs need (same as the runbook's ASPIRE commands)."""
    env = dict(os.environ)
    env.update(
        LIBERO_CONFIG_PATH=str(ROOT / "ASPIRE" / ".libero"),
        TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD="1",
        MUJOCO_GL="egl",
        PYOPENGL_PLATFORM="egl",
        EGL_PLATFORM="device",
        CUDA_VISIBLE_DEVICES="0",
    )
    return env


def make_spec(
    base: Path,
    out: Path,
    mode: str,
    crop_m: float | None = None,
    target_m: float | None = None,
    fit: str | None = None,
    fuse: bool = False,
    perturb: dict | None = None,
) -> Path:
    spec = json.loads(base.read_text(encoding="utf-8"))
    for key, value in (perturb or {}).items():
        if key == "scale":  # multiply onto the task's own scale factors
            bodies = spec.setdefault("scale", {}).setdefault("bodies", {})
            for body, f in value["bodies"].items():
                bodies[body] = round(bodies.get(body, 1.0) * float(f), 4)
            continue
        spec[key] = value
    planner = spec["planner"]
    planner["cloud_dir"] = str(out / "clouds")
    if mode in ("sparse", "oracle"):
        planner.pop("attach", None)
    else:
        planner["attach"]["file"] = str(GLOBAL_ATTACH)
        if crop_m:
            planner["attach"]["crop_m"] = crop_m
        planner["attach"]["debug_dir"] = str(out / "attach_debug")
        if target_m:
            planner["attach"]["target_exclude_m"] = target_m
        if fit:
            planner["attach"]["fit"] = fit
    if mode.startswith("oracle"):
        planner["oracle_exclude"] = ["akita_black_bowl", "plate_1"]
    if fuse:
        planner["fuse"] = True
    planner["label_goals"] = {
        "file": str(out / "goal_labels.jsonl"),
        "body_main": "akita_black_bowl_1_main",
    }
    if "contacts" in spec:
        spec["contacts"]["path"] = str(out / "contacts.jsonl")
    path = out / "spec.json"
    path.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    return path


def summarise(out: Path) -> dict:
    outcome = next(out.rglob("outcome.json"), None)
    result = {"task_success": None, "steps": None, "failed_spans": {}}
    if outcome is not None:
        data = json.loads(outcome.read_text(encoding="utf-8"))
        result["task_success"] = data.get("task_success")
        result["steps"] = data.get("steps_executed")
    events = next(out.rglob("trace/events.jsonl"), None)
    if events is not None:
        failed: dict[str, int] = {}
        for line in events.read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            if e.get("event") == "span_end" and e.get("ok") is False:
                failed[e.get("name", "?")] = failed.get(e.get("name", "?"), 0) + 1
        result["failed_spans"] = failed
    return result


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--mode", choices=["sparse", "attach", "oracle", "oracle-attach"], required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--only", default="", help="comma-separated labels to run (default: all)")
    p.add_argument(
        "--seeds", default="51", help="comma-separated acceptance seeds, 51 to 65 (never held-out)"
    )
    p.add_argument("--timeout-s", type=int, default=900)
    p.add_argument(
        "--attach-crop-m",
        type=float,
        default=None,
        help="fit and remove the held object only from mask points within this xy radius of the hand",
    )
    p.add_argument(
        "--target-exclude-m",
        type=float,
        default=None,
        help="open gripper: drop cloud points within this distance of the last localized target",
    )
    p.add_argument(
        "--attach-fit",
        choices=["rim", "centroid"],
        default=None,
        help="held-bowl axis: rim circle fit (default) or mask centroid + table plane",
    )
    p.add_argument(
        "--fuse",
        action="store_true",
        help="plan on a persistent occupancy map fused over all planning frames",
    )
    p.add_argument(
        "--perturb",
        type=Path,
        default=None,
        help="JSON with launcher perturbation keys (pose, scale, physics, ...) merged into the spec",
    )
    args = p.parse_args()
    perturb = json.loads(args.perturb.read_text(encoding="utf-8")) if args.perturb else None
    only = {s for s in args.only.split(",") if s}
    base_out = (ROOT / args.out).resolve() if not args.out.is_absolute() else args.out
    seeds = [int(s) for s in args.seeds.split(",")]
    if any(not 51 <= s <= 65 for s in seeds):
        raise SystemExit("--seeds: debugging uses acceptance seeds 51 to 65 only")
    for label, program, base in PROGRAMS:
        if only and label not in only:
            continue
        for seed in seeds:
            out = base_out / args.mode / f"{label}_s{seed}"
            if out.exists():
                shutil.rmtree(out)
            out.mkdir(parents=True)
            spec = make_spec(
                base,
                out,
                args.mode,
                args.attach_crop_m,
                args.target_exclude_m,
                args.attach_fit,
                args.fuse,
                perturb,
            )
            GLOBAL_ATTACH.write_text(json.dumps({"spheres": []}), encoding="utf-8")
            cmd = [
                str(ASPIRE_PY), str(LAUNCHER), str(spec), "--",
                "run", "--benchmark", "libero-pro", "--suite", "libero_goal_swap", "--task-id", "8",
                "--seed", str(seed), "--init-mode", "seeded", "--program", str(program),
                "--output-root", str(out / "run"), "--max-steps", "2000",
                "--camera-width", "800", "--camera-height", "512",
            ]  # fmt: skip
            t0 = time.time()
            try:
                proc = subprocess.run(
                    cmd, cwd=ROOT / "ASPIRE", capture_output=True, text=True,
                    timeout=args.timeout_s, env=aspire_env(),
                )  # fmt: skip
                (out / "launch.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
                code = proc.returncode
            except subprocess.TimeoutExpired:
                code = "timeout"
            result = {
                "label": label,
                "seed": seed,
                "mode": args.mode,
                "exit": code,
                "wall_s": round(time.time() - t0, 1),
            }
            result.update(summarise(out / "run"))
            (out / "result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
            print(json.dumps(result), flush=True)
    GLOBAL_ATTACH.write_text(json.dumps({"spheres": []}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
