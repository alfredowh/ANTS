"""Sim-ready gate, stage 3: drop the collision body in MuJoCo and check it settles.

Runs under ASPIRE's .venv-libero (mujoco, numpy only). Settles the reconstructed hull and,
as a control, the ground-truth hull, from an upright and a tilted start. Mass is the true
LIBERO body mass. Merges the verdict into gate_<tag>_report.json. Standalone probe.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import mujoco
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = REPO_ROOT / "data" / "runs" / "mapper_probe"

XML = """<mujoco>
  <option timestep="0.002"/>
  <asset><mesh name="obj" file="{stl}"/></asset>
  <worldbody>
    <geom name="floor" type="plane" size="1 1 0.1" friction="1 0.005 0.0001"/>
    <body name="obj" pos="0 0 {z0}" quat="{quat}">
      <freejoint/>
      <geom type="mesh" mesh="obj" mass="{mass}" friction="1 0.005 0.0001"/>
    </body>
  </worldbody>
</mujoco>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-dir", type=Path, default=RUN_DIR / "gate")
    parser.add_argument("--tag", default="fused_hires")
    parser.add_argument("--drop-height-m", type=float, default=0.03)
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--tilt-deg", type=float, default=10.0)
    parser.add_argument("--max-rest-z-err-mm", type=float, default=2.0)
    parser.add_argument("--max-speed-mps", type=float, default=1e-3)
    parser.add_argument("--max-tilt-deg", type=float, default=5.0)
    parser.add_argument("--max-penetration-mm", type=float, default=2.0)
    return parser.parse_args()


def settle(stl: Path, mass: float, tilt_deg: float, args: argparse.Namespace) -> dict:
    half = math.radians(tilt_deg) / 2.0
    quat = f"{math.cos(half):.6f} {math.sin(half):.6f} 0 0"
    xml = XML.format(stl=stl.name, z0=args.drop_height_m, quat=quat, mass=mass)
    xml_path = stl.with_suffix(".settle.xml")
    xml_path.write_text(xml, encoding="utf-8")
    model = mujoco.MjModel.from_xml_path(str(xml_path))
    data = mujoco.MjData(model)
    geom = [g for g in range(model.ngeom) if model.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH][0]
    mid = model.geom_dataid[geom]
    adr, num = model.mesh_vertadr[mid], model.mesh_vertnum[mid]
    local = model.mesh_vert[adr : adr + num].astype(np.float64)

    quat_m = model.mesh_quat[mid]
    rq = np.zeros(9)
    mujoco.mju_quat2Mat(rq, quat_m)
    rq = rq.reshape(3, 3)

    def object_up() -> np.ndarray:
        # MuJoCo re-aligns the mesh to its inertia axes; undo that to get the STL's own z axis.
        return (data.geom_xmat[geom].reshape(3, 3) @ rq.T)[:, 2]

    mujoco.mj_forward(model, data)
    start_tilt = math.degrees(math.acos(float(np.clip(object_up()[2], -1.0, 1.0))))
    worst_pen = 0.0
    rest_pen = 0.0
    n_steps = int(args.seconds / model.opt.timestep)
    for i in range(n_steps):
        mujoco.mj_step(model, data)
        if data.ncon:
            pen = float(-data.contact.dist.min())
            worst_pen = max(worst_pen, pen)
            if i >= n_steps - int(0.5 / model.opt.timestep):
                rest_pen = max(rest_pen, pen)
    world = data.geom_xpos[geom] + local @ data.geom_xmat[geom].reshape(3, 3).T
    tilt = math.degrees(math.acos(float(np.clip(object_up()[2], -1.0, 1.0))))
    finite = bool(np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all())
    return {
        "tilt_start_deg": tilt_deg,
        "tilt_start_measured_deg": start_tilt,
        "finite": finite,
        "rest_z_err_mm": float(world[:, 2].min() * 1000.0),
        "speed_mps": float(np.linalg.norm(data.qvel[:3])),
        "angular_speed_rps": float(np.linalg.norm(data.qvel[3:])),
        "tilt_end_deg": tilt,
        "peak_penetration_mm": worst_pen * 1000.0,
        "rest_penetration_mm": rest_pen * 1000.0,
    }


def verdict(r: dict, args: argparse.Namespace) -> dict:
    checks = {
        "finite": r["finite"],
        "rest_height": abs(r["rest_z_err_mm"]) <= args.max_rest_z_err_mm,
        "at_rest": r["speed_mps"] <= args.max_speed_mps,
        "tilt": r["tilt_end_deg"] <= args.max_tilt_deg,
        "rest_penetration": r["rest_penetration_mm"] <= args.max_penetration_mm,
    }
    return {"checks": {k: bool(v) for k, v in checks.items()}, "pass": bool(all(checks.values()))}


def main() -> None:
    args = parse_args()
    truth = json.loads((args.gate_dir / "truth.json").read_text(encoding="utf-8"))
    mass = truth["mass_kg"]
    out: dict[str, dict] = {}
    for label, stl in (
        ("recon", args.gate_dir / f"recon_hull_{args.tag}.stl"),
        ("truth_control", args.gate_dir / "truth_hull.stl"),
    ):
        runs = []
        for tilt in (0.0, args.tilt_deg):
            r = settle(stl, mass, tilt, args)
            r.update(verdict(r, args))
            runs.append(r)
        out[label] = {"runs": runs, "pass": all(r["pass"] for r in runs)}

    report_path = args.gate_dir / f"gate_{args.tag}_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["settle"] = out
    report["settle_thresholds"] = {
        "rest_z_err_mm": args.max_rest_z_err_mm,
        "speed_mps": args.max_speed_mps,
        "tilt_deg": args.max_tilt_deg,
        "penetration_mm": args.max_penetration_mm,
    }
    report["sim_ready"] = bool(report["geometry_pass"] and out["recon"]["pass"])
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "settle": out,
                "geometry_pass": report["geometry_pass"],
                "sim_ready": report["sim_ready"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
