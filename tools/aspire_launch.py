"""Run ASPIRE's cap-harness with an ANTS perturbation applied to the LIBERO scene.

ASPIRE has no perturbation API, but its LIBERO adapter builds the simulator through
`cap_harness.libero.adapter._load_offscreen_render_env`. This launcher replaces that loader
with a wrapper that applies the perturbation after every `reset()` (scene changes) and on
every `step()` (actuation), then hands over to the normal CLI. ASPIRE itself is not modified,
and the program under test cannot see the perturbation (it runs in ASPIRE's sandbox).

Run it with ASPIRE's Python, from the ASPIRE checkout:

    ../ASPIRE/.venv-libero/bin/python <ANTS>/tools/aspire_launch.py perturbation.json -- \
        run --benchmark libero-pro --suite libero_goal_swap --task-id 8 --seed 51 ...

perturbation.json (every key optional):
    {"physics":   {"friction_scale": 0.5, "mass_scale": 2.0, "bodies": ["bowl"]},
     "pose":      {"offsets_m": {"akita_black_bowl_1_joint0": [0.03, -0.02]}},
     "camera":    {"name": "agentview", "pos_offset_m": [0.0, 0.02, 0.0], "fovy_delta_deg": 2.0},
     "lighting":  {"diffuse_scale": 0.6},
     "actuation": {"noise_std": 0.01, "latency_steps": 2, "seed": 0},
     "scale":     {"bodies": {"akita_black_bowl_1_main": 1.227, "plate_1_main": 1.855}}}

"bodies" in physics match by substring of the MuJoCo body name. "scale" rebuilds the scene
from its XML after every reset (experimental: object placement is not re-checked) and scales
LIBERO's 0.03 m "on top of" centre tolerance by the target's factor (`scale_ontop_tolerance`).
"""

from __future__ import annotations

import collections
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np


def _scale_floats(element: ET.Element, attr: str, factor: float) -> None:
    value = element.get(attr)
    if value is not None:
        element.set(attr, " ".join(f"{float(v) * factor:.6g}" for v in value.split()))


def scale_body_xml(root: ET.Element, body_name: str, factor: float) -> None:
    """Uniformly scale one MJCF body in place (same rules as hurobo.object_scale.scale_body_xml)."""
    body = next((b for b in root.iter("body") if b.get("name") == body_name), None)
    if body is None:
        raise ValueError(f"no body named {body_name!r}")
    meshes = {m.get("name"): m for m in root.iter("mesh")}
    done: set[str] = set()
    for el in body.iter():
        if el.tag == "geom":
            _scale_floats(el, "pos", factor)
            if el.get("type") != "mesh":
                _scale_floats(el, "size", factor)
            mesh_name = el.get("mesh")
            if mesh_name and mesh_name not in done:
                mesh = meshes[mesh_name]
                if mesh.get("scale") is None:
                    mesh.set("scale", "1 1 1")
                _scale_floats(mesh, "scale", factor)
                done.add(mesh_name)
        elif el.tag == "site":
            _scale_floats(el, "pos", factor)
            _scale_floats(el, "size", factor)
        elif el.tag == "body" and el is not body:
            _scale_floats(el, "pos", factor)
        elif el.tag == "joint" and el.get("type") != "free":
            _scale_floats(el, "pos", factor)
        elif el.tag == "inertial":
            _scale_floats(el, "pos", factor)
            _scale_floats(el, "mass", factor**3)
            _scale_floats(el, "diaginertia", factor**5)


def scale_ontop_tolerance(factors: dict[str, float]) -> None:
    """Make LIBERO's "on top of" centre tolerance grow with the target's scale.

    LIBERO's `ObjectState.check_ontop` requires the object's centre within 0.03 m (xy) of the
    target's centre, a value tuned for the stock plate. At real size the plate is larger, so the
    tolerance becomes 0.03 m x the target's scale factor. Contact and height rules are unchanged.
    `factors` maps a body name such as "plate_1_main" to its scale.
    """
    import numpy as np
    from libero.envs.object_states.base_object_states import ObjectState

    def check_ontop(self, other):
        env = self.env
        this_pos = env.sim.data.body_xpos[env.obj_body_id[self.object_name]]
        other_pos = env.sim.data.body_xpos[env.obj_body_id[other.object_name]]
        tolerance = 0.03 * float(factors.get(f"{other.object_name}_main", 1.0))
        return (
            this_pos[2] <= other_pos[2]
            and self.check_contact(other)
            and np.linalg.norm(this_pos[:2] - other_pos[:2]) < tolerance
        )

    ObjectState.check_ontop = check_ontop


class PerturbedEnv:
    """Wraps a LIBERO OffScreenRenderEnv; everything not overridden is delegated."""

    def __init__(self, inner, spec: dict):
        self._inner = inner
        self._spec = spec
        act = spec.get("actuation") or {}
        self._rng = np.random.default_rng(int(act.get("seed", 0)))
        self._queue: collections.deque = collections.deque()
        self._applied: dict = {}

    def __getattr__(self, name):
        return getattr(self._inner, name)

    @property
    def sim(self):
        return self._inner.sim

    def reset(self):
        obs = self._inner.reset()
        scale = (self._spec.get("scale") or {}).get("bodies")
        if scale:
            obs = self._rescale(scale, obs)
            self._applied["scaled_bounding_radius_m"] = self._radii(list(scale))
        self._apply_scene()
        self._queue.clear()
        return obs

    def _rescale(self, scale: dict, obs):
        """Rebuild the scene from scaled MJCF; every reset restores the stock task, so redo it.

        The joint state is saved by name and written back (as hurobo's `reload_model` does).
        """
        model = self.sim.model
        saved = {
            model.joint(j).name: self.sim.data.qpos[
                model.jnt_qposadr[j] : model.jnt_qposadr[j] + (7 if model.jnt_type[j] == 0 else 1)
            ].copy()
            for j in range(model.njnt)
        }
        root = ET.fromstring(model.get_xml())
        for body, factor in scale.items():
            scale_body_xml(root, body, float(factor))
        self._inner.env.reset_from_xml_string(ET.tostring(root, encoding="unicode"))
        names = {self.sim.model.joint(j).name for j in range(self.sim.model.njnt)}
        for name, qpos in saved.items():
            if name in names:
                self.sim.data.set_joint_qpos(name, qpos)
        self.sim.forward()
        return self._inner.env._get_observations(force_update=True)

    def _radii(self, names: list[str]) -> dict:
        """Largest geom bounding radius per body: proof that scaling reached the simulator."""
        model, out = self.sim.model, {}
        for name in names:
            bid = model.body_name2id(name)
            radii = [
                model.geom_rbound[g] for g in range(model.ngeom) if model.geom_bodyid[g] == bid
            ]
            out[name] = round(float(max(radii)), 4) if radii else None
        return out

    def _bodies(self, patterns: list[str]) -> list[int]:
        model = self.sim.model
        ids = []
        for i in range(model.nbody):
            name = model.body_id2name(i) or ""
            if not patterns or any(p in name for p in patterns):
                if not name.startswith(("robot", "gripper", "mount", "world", "table", "floor")):
                    ids.append(i)
        return ids

    def _apply_scene(self) -> None:
        sim, model = self.sim, self.sim.model
        phys = self._spec.get("physics") or {}
        if phys:
            bodies = set(self._bodies(phys.get("bodies") or []))
            if "friction_scale" in phys:
                for g in range(model.ngeom):
                    if model.geom_bodyid[g] in bodies:
                        model.geom_friction[g, 0] *= float(phys["friction_scale"])
            if "mass_scale" in phys:
                for b in bodies:
                    model.body_mass[b] *= float(phys["mass_scale"])
            self._applied["physics_bodies"] = sorted(model.body_id2name(b) for b in bodies)
        for joint, (dx, dy) in ((self._spec.get("pose") or {}).get("offsets_m") or {}).items():
            q = np.array(sim.data.get_joint_qpos(joint), dtype=float)
            q[0] += dx
            q[1] += dy
            sim.data.set_joint_qpos(joint, q)
        cam = self._spec.get("camera") or {}
        if cam:
            cid = model.camera_name2id(cam.get("name", "agentview"))
            model.cam_pos[cid] += np.asarray(cam.get("pos_offset_m", [0, 0, 0]), dtype=float)
            model.cam_fovy[cid] += float(cam.get("fovy_delta_deg", 0.0))
        light = self._spec.get("lighting") or {}
        if "diffuse_scale" in light:
            model.light_diffuse[:] *= float(light["diffuse_scale"])
        sim.forward()
        # Log what was changed so a run can prove its perturbation was applied.
        print(
            f"[ants-perturbation] {json.dumps(self._spec)} {json.dumps(self._applied)}",
            file=sys.stderr,
        )

    def step(self, action):
        act = self._spec.get("actuation") or {}
        action = np.asarray(action, dtype=float).copy()
        if act.get("noise_std"):
            action[:-1] += self._rng.normal(0.0, float(act["noise_std"]), size=action.shape[0] - 1)
        lag = int(act.get("latency_steps", 0))
        if lag > 0:
            # Actions are absolute joint targets (ASPIRE uses JOINT_POSITION), so a delayed
            # command holds the oldest queued target; it never sends zeros.
            self._queue.append(action)
            action = self._queue.popleft() if len(self._queue) > lag else self._queue[0]
        return self._inner.step(action)


def main() -> int:
    if "--" not in sys.argv:
        print(__doc__)
        return 2
    split = sys.argv.index("--")
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    harness_argv = sys.argv[split + 1 :]

    import cap_harness.libero.adapter as adapter
    from cap_harness import cli

    original = adapter._load_offscreen_render_env

    def patched_loader():
        factory = original()
        return lambda **kwargs: PerturbedEnv(factory(**kwargs), spec)

    adapter._load_offscreen_render_env = patched_loader
    scale = (spec.get("scale") or {}).get("bodies")
    if scale:
        scale_ontop_tolerance({k: float(v) for k, v in scale.items()})
    return cli.main(harness_argv)


if __name__ == "__main__":
    raise SystemExit(main())
