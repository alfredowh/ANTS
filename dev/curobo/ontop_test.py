"""Does LIBERO's "on top of" check ever pass for a bowl resting on the plate?

Drops the bowl onto the plate at its centre, lets it settle with the robot held in place, and
records what the check looks at: the z of each body's origin, the bowl-plate contact height and
the horizontal distance. Used by `contact_launch.py` when ANTS_ONTOP_TEST=<out.json> is set.
"""

from __future__ import annotations

import json
from pathlib import Path

import mujoco
import numpy as np


def run(env, out: Path, factors: dict[str, float]) -> None:
    model, data = env.sim.model._model, env.sim.data._data

    def body(name: str) -> int:
        return mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, name)

    bowl, plate = body("akita_black_bowl_1_main"), body("plate_1_main")
    for b in range(model.nbody):  # keep the arm where it is while the bowl settles
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, b) or ""
        if name.startswith(("robot0", "gripper0", "mount0")):
            model.body_gravcomp[b] = 1.0
    qadr = model.jnt_qposadr[model.body_jntadr[bowl]]
    data.qpos[qadr : qadr + 3] = [*data.xpos[plate][:2], data.xpos[plate][2] + 0.20]
    data.qpos[qadr + 3 : qadr + 7] = [1.0, 0.0, 0.0, 0.0]
    data.qvel[:] = 0.0
    mujoco.mj_forward(model, data)
    for _ in range(800):
        mujoco.mj_step(model, data)

    pairs = [
        c
        for c in data.contact[: data.ncon]
        if {
            mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, int(model.geom_bodyid[c.geom1])),
            mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, int(model.geom_bodyid[c.geom2])),
        }
        == {"akita_black_bowl_1_main", "plate_1_main"}
    ]
    bowl_z, plate_z = float(data.xpos[bowl][2]), float(data.xpos[plate][2])
    xy = float(np.linalg.norm(data.xpos[bowl][:2] - data.xpos[plate][:2]))
    tol = 0.03 * float(factors.get("plate_1_main", 1.0))
    contact_z = [float(c.pos[2]) for c in pairs]
    out.write_text(
        json.dumps(
            {
                "scales": factors,
                "bowl_origin_z": round(bowl_z, 4),
                "plate_origin_z": round(plate_z, 4),
                "bowl_minus_plate_z": round(bowl_z - plate_z, 4),
                "contact_height_z": round(float(np.mean(contact_z)), 4) if contact_z else None,
                "bowl_origin_above_contact": round(bowl_z - np.mean(contact_z), 4)
                if contact_z
                else None,
                "plate_origin_above_contact": round(plate_z - np.mean(contact_z), 4)
                if contact_z
                else None,
                "n_contacts": len(pairs),
                "xy_distance": round(xy, 4),
                "xy_tolerance": round(tol, 4),
                "rule_contact": bool(pairs),
                "rule_xy": bool(xy < tol),
                "rule_z": bool(bowl_z <= plate_z),
                "passes": bool(pairs and xy < tol and bowl_z <= plate_z),
            },
            indent=1,
        ),
        encoding="utf-8",
    )
