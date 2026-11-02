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
     "pose":      {"offsets_m": {"akita_black_bowl_1_joint0": [0.03, -0.02]},
                   "body_offsets_m": {"wine_rack_1_main": [0.1, 0.0]}},
     "camera":    {"name": "agentview", "pos_offset_m": [0.0, 0.02, 0.0], "fovy_delta_deg": 2.0},
     "lighting":  {"diffuse_scale": 0.6},
     "actuation": {"noise_std": 0.01, "latency_steps": 2, "seed": 0},
     "scale":     {"bodies": {"akita_black_bowl_1_main": 1.227, "plate_1_main": 1.855}},
     "contacts":  {"path": "run/contacts.jsonl"},
     "ablate":    {"bodies": ["wine_rack"]},
     "ontop":     {"rule": "area", "min_fraction": 0.5},
     "planner":   {"mode": "curobo-sam3", "exclude_radius_m": 0.12}}

"ablate" switches off all collisions of every geom whose body name contains one of the strings
(counterfactual: would the run still stall without that object?). Diagnosis only.

"contacts" (read-only evidence, changes nothing in the simulation) appends one JSON line per
env step with every MuJoCo contact (bodies, geoms, point, normal, distance, normal force), and
writes `<path stem>_scene.json` (every body pose, geom shape and exact object gaps) once the objects
have settled (after `dump_at_step` env steps, default 6) and `_scene_reset.json` right after reset.

"ontop" {"rule": "area"} replaces the centre-distance part of "on top of" with: at least
`min_fraction` (default 0.5) of the upper object's footprint circle lies inside the support's
footprint circle (circles from the collision geoms' axis-aligned boxes). Contact and height rules
stay. Without "ontop", "scale" scales the tolerance by the SUPPORT's factor (LIBERO calls
`support.check_ontop(object)`, so the support is `self`; before 2026-11-02 the object's factor was
used by mistake).

"planner" makes every motion plan use cuRobo (`MotionStrategy(trajectory_planner="curobo")` as the
harness default) and builds the planning cloud without robot pixels. mode "curobo-sam3": the robot
mask comes from SAM 3 prompts "robot arm" and "robot gripper" (no simulator state). Mode
"curobo-sim": the mask comes from MuJoCo's segmentation render (privileged, a digital twin).
`exclude_radius_m` drops cloud points within r of the manipulated object. The cuRobo service
(`dev/curobo/service_dev.py`, carve margin ANTS_CARVE_MARGIN_M) must be running.

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


def circle_overlap_fraction(c1, r1: float, c2, r2: float) -> float:
    """Share of circle 1's area that lies inside circle 2."""
    d = float(np.hypot(c1[0] - c2[0], c1[1] - c2[1]))
    if r1 <= 0.0:
        return 0.0
    if d >= r1 + r2:
        return 0.0
    if d <= abs(r2 - r1):
        return 1.0 if r2 >= r1 else (r2 / r1) ** 2
    a1 = np.arccos((d * d + r1 * r1 - r2 * r2) / (2 * d * r1))
    a2 = np.arccos((d * d + r2 * r2 - r1 * r1) / (2 * d * r2))
    area = (
        r1 * r1 * a1 + r2 * r2 * a2
        - 0.5 * np.sqrt((-d + r1 + r2) * (d + r1 - r2) * (d - r1 + r2) * (d + r1 + r2))
    )  # fmt: skip
    return float(area / (np.pi * r1 * r1))


def footprint(env, body_id: int) -> tuple[np.ndarray, float]:
    """Centre (x, y) and radius of a body's collision footprint: its geoms' world boxes, unioned."""
    model, data = env.sim.model._model, env.sim.data._data
    lo, hi = np.full(2, np.inf), np.full(2, -np.inf)
    for g in range(model.ngeom):
        solid = model.geom_contype[g] + model.geom_conaffinity[g] > 0
        if model.geom_bodyid[g] != body_id or not solid:
            continue
        rot = data.geom_xmat[g].reshape(3, 3)
        centre = data.geom_xpos[g] + rot @ model.geom_aabb[g][:3]
        half = np.abs(rot) @ model.geom_aabb[g][3:]
        lo, hi = np.minimum(lo, centre[:2] - half[:2]), np.maximum(hi, centre[:2] + half[:2])
    return (lo + hi) / 2, float(max(hi - lo)) / 2


def scale_ontop_tolerance(factors: dict[str, float], area_fraction: float | None = None) -> None:
    """Change LIBERO's "on top of" check for a scaled scene.

    LIBERO's `ObjectState.check_ontop(other)` requires the object's centre within 0.03 m (xy) of
    the support's, a value tuned for the stock plate. `On(bowl, plate)` calls
    `plate.check_ontop(bowl)`, so `self` is the support. Default: the tolerance becomes 0.03 m x the
    support's scale factor. With `area_fraction`: pass when that share of the object's footprint
    circle lies inside the support's footprint circle. Contact and height rules are unchanged.
    `factors` maps a body name such as "plate_1_main" to its scale.
    """
    from libero.envs.object_states.base_object_states import ObjectState

    def check_ontop(self, other):
        env = self.env
        this_id, other_id = env.obj_body_id[self.object_name], env.obj_body_id[other.object_name]
        this_pos, other_pos = env.sim.data.body_xpos[this_id], env.sim.data.body_xpos[other_id]
        if this_pos[2] > other_pos[2] or not self.check_contact(other):
            return False
        if area_fraction is None:
            tolerance = 0.03 * float(factors.get(f"{self.object_name}_main", 1.0))
            return bool(np.linalg.norm(this_pos[:2] - other_pos[:2]) < tolerance)
        (c_sup, r_sup), (c_obj, r_obj) = footprint(env, this_id), footprint(env, other_id)
        return circle_overlap_fraction(c_obj, r_obj, c_sup, r_sup) >= area_fraction

    ObjectState.check_ontop = check_ontop


LIVE: dict = {}
ROBOT_PROMPTS = ("robot arm", "robot gripper")


def install_curobo_planning(cfg: dict) -> None:
    """Planning through cuRobo on the public depth cloud, with the robot's own pixels removed."""
    import mujoco
    from cap_harness.api import CapApi
    from cap_harness.contracts import MotionStrategy
    from scipy.ndimage import binary_dilation
    from scipy.spatial import cKDTree

    mode = cfg.get("mode", "curobo-sam3")
    if mode not in ("curobo-sam3", "curobo-sim"):
        raise SystemExit(f"unknown planner mode {mode!r}")
    default = MotionStrategy(trajectory_planner="curobo")
    init = CapApi.__init__

    def patched_init(self, *a, **kw):
        init(self, *a, **kw)
        self.default_motion_strategy = default

    CapApi.__init__ = patched_init
    original = CapApi._project_mask

    def sam3_pixels(api, camera_name, observation) -> np.ndarray:
        shape = observation.cameras[camera_name].depth_m.shape
        union = np.zeros(shape, dtype=bool)
        for prompt in ROBOT_PROMPTS:
            result = api._segment_text(camera_name, prompt, observation)
            if result.ok:
                for seg in result.segmentations:
                    union |= np.asarray(seg.mask, dtype=bool)
        print(f"[ants-robot-mask] sam3 {camera_name}: {int(union.sum())} px", file=sys.stderr)
        return binary_dilation(union, iterations=3)

    renderers: dict = {}

    def sim_pixels(camera_name, depth) -> np.ndarray:
        model, data = LIVE["env"].sim.model._model, LIVE["env"].sim.data._data
        h, w = depth.shape
        if (h, w) not in renderers:
            renderers[(h, w)] = mujoco.Renderer(model, h, w)
        r = renderers[(h, w)]
        r.update_scene(data, camera=camera_name)
        r.enable_depth_rendering()
        rendered = r.render().copy()
        r.disable_depth_rendering()
        ok = np.isfinite(depth) & (depth > 0) & (rendered < 10)  # LIBERO frames may be upside down
        flip = np.abs(np.flipud(rendered) - depth)[ok].mean() < np.abs(rendered - depth)[ok].mean()
        r.enable_segmentation_rendering()
        r.update_scene(data, camera=camera_name)
        seg = r.render().copy()
        r.disable_segmentation_rendering()
        seg = np.flipud(seg) if flip else seg
        names = [
            mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, int(b)) or ""
            for b in model.geom_bodyid
        ]
        robot = np.array([n.startswith(("robot0", "gripper0", "mount0")) for n in names])
        is_geom = seg[..., 1] == int(mujoco.mjtObj.mjOBJ_GEOM)
        mask = is_geom & robot[np.clip(seg[..., 0], 0, len(robot) - 1)]
        return binary_dilation(mask, iterations=2)

    def masked(self, mask, *, camera_name, target_frame, observation):
        if isinstance(mask, np.ndarray) and mask.dtype == bool and "env" in LIVE:
            if mode == "curobo-sam3":
                robot = sam3_pixels(self, camera_name, observation)
            else:
                robot = sim_pixels(camera_name, observation.cameras[camera_name].depth_m)
            mask = mask & ~robot
        return original(
            self, mask, camera_name=camera_name, target_frame=target_frame, observation=observation
        )

    CapApi._project_mask = masked
    radius = cfg.get("exclude_radius_m")
    if radius:

        def exclude_near(scene_points, target_points):
            near = cKDTree(target_points).query(scene_points, distance_upper_bound=float(radius))[0]
            kept = scene_points[~np.isfinite(near)]
            if not len(kept):
                raise ValueError("target exclusion removed the entire observed planning scene")
            return kept

        CapApi._exclude_target_from_scene = staticmethod(exclude_near)


class PerturbedEnv:
    """Wraps a LIBERO OffScreenRenderEnv; everything not overridden is delegated."""

    def __init__(self, inner, spec: dict):
        self._inner = inner
        self._spec = spec
        act = spec.get("actuation") or {}
        self._rng = np.random.default_rng(int(act.get("seed", 0)))
        self._queue: collections.deque = collections.deque()
        self._applied: dict = {}
        LIVE["env"] = self
        self._contact_path: Path | None = None
        self._contact_step = 0
        self._dump_at = 0
        if (spec.get("contacts") or {}).get("path"):
            self._contact_path = Path(spec["contacts"]["path"]).resolve()
            self._dump_at = int(spec["contacts"].get("dump_at_step", 6))
            self._contact_path.parent.mkdir(parents=True, exist_ok=True)
            self._contact_path.write_text("", encoding="utf-8")

    def __getattr__(self, name):
        return getattr(self._inner, name)

    @property
    def sim(self):
        return self._inner.sim

    def _raw(self):
        return self.sim.model._model, self.sim.data._data

    def _dump_scene(self, path: Path) -> None:
        """Pose and shape of every body and geom right after the scene is built."""
        model, data = self._raw()
        bodies = {}
        for b in range(model.nbody):
            bodies[model.body(b).name] = {
                "pos": data.xpos[b].round(5).tolist(),
                "quat_wxyz": data.xquat[b].round(5).tolist(),
                "root": model.body(int(model.body_rootid[b])).name,
                "mass": round(float(model.body_mass[b]), 5),
            }
        geoms = []
        for g in range(model.ngeom):
            geoms.append(
                {
                    "id": g,
                    "name": model.geom(g).name,
                    "body": model.body(int(model.geom_bodyid[g])).name,
                    "type": int(model.geom_type[g]),
                    "size": model.geom_size[g].round(5).tolist(),
                    "pos": data.geom_xpos[g].round(5).tolist(),
                    "xmat": data.geom_xmat[g].round(5).tolist(),
                    "contype": int(model.geom_contype[g]),
                    "conaffinity": int(model.geom_conaffinity[g]),
                    "mesh": int(model.geom_dataid[g]) if model.geom_type[g] == 7 else None,
                }
            )
        path.write_text(
            json.dumps({"bodies": bodies, "geoms": geoms, "gaps": self._gaps()}), encoding="utf-8"
        )

    def _gaps(self, max_m: float = 0.3) -> list[dict]:
        """Exact nearest distance (MuJoCo) between every pair of scene objects within `max_m`."""
        import mujoco

        model, data = self._raw()
        root = [int(model.body_rootid[model.geom_bodyid[g]]) for g in range(model.ngeom)]
        solid = [
            g
            for g in range(model.ngeom)
            if model.geom_contype[g] + model.geom_conaffinity[g] > 0 and model.geom_type[g] != 0
            and not (model.body(root[g]).name.startswith(("robot", "gripper", "mount")))
        ]  # fmt: skip
        best: dict[tuple[str, str], float] = {}
        fromto = np.zeros(6)
        for i, g1 in enumerate(solid):
            for g2 in solid[i + 1 :]:
                if root[g1] == root[g2]:
                    continue
                d = mujoco.mj_geomDistance(model, data, g1, g2, max_m, fromto)
                if d >= max_m:
                    continue
                key = tuple(sorted((model.body(root[g1]).name, model.body(root[g2]).name)))
                best[key] = min(best.get(key, max_m), d)
        return [{"a": a, "b": b, "dist": round(v, 5)} for (a, b), v in sorted(best.items())]

    def _scene_path(self, suffix: str) -> Path:
        return self._contact_path.with_name(self._contact_path.stem + suffix)

    def _log_contacts(self) -> None:
        import mujoco

        model, data = self._raw()
        force = np.zeros(6)
        rows = []
        for i in range(data.ncon):
            c = data.contact[i]
            mujoco.mj_contactForce(model, data, i, force)
            rows.append(
                {
                    "b1": model.body(int(model.geom_bodyid[c.geom1])).name,
                    "b2": model.body(int(model.geom_bodyid[c.geom2])).name,
                    "g1": model.geom(int(c.geom1)).name or int(c.geom1),
                    "g2": model.geom(int(c.geom2)).name or int(c.geom2),
                    "pos": c.pos.round(4).tolist(),
                    "n": c.frame[:3].round(3).tolist(),
                    "dist": round(float(c.dist), 5),
                    "fn": round(float(force[0]), 3),
                }
            )
        self._contact_step += 1
        if self._contact_step == self._dump_at:  # objects have settled onto the table by now
            self._dump_scene(self._scene_path("_scene.json"))
        line = {"step": self._contact_step, "t": round(float(data.time), 4), "contacts": rows}
        with self._contact_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line) + "\n")

    def reset(self):
        obs = self._inner.reset()
        scale = (self._spec.get("scale") or {}).get("bodies")
        if scale:
            obs = self._rescale(scale, obs)
            self._applied["scaled_bounding_radius_m"] = self._radii(list(scale))
        self._apply_scene()
        self._queue.clear()
        if self._contact_path is not None:
            self._contact_step = 0
            self._dump_scene(self._scene_path("_scene_reset.json"))
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
        ablate = (self._spec.get("ablate") or {}).get("bodies") or []
        if ablate:
            hit = set()
            for g in range(model.ngeom):
                name = model.body(int(model.geom_bodyid[g])).name
                if any(a in name for a in ablate):
                    model.geom_contype[g] = 0
                    model.geom_conaffinity[g] = 0
                    hit.add(name)
            self._applied["ablated_bodies"] = sorted(hit)
        for body, (dx, dy) in ((self._spec.get("pose") or {}).get("body_offsets_m") or {}).items():
            bid = model.body_name2id(body)  # fixed bodies have no joint: move the body itself
            model.body_pos[bid][0] += dx
            model.body_pos[bid][1] += dy
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
        result = self._inner.step(action)
        if self._contact_path is not None:
            self._log_contacts()
        return result


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
    ontop = spec.get("ontop") or {}
    if scale or ontop:
        scale_ontop_tolerance(
            {k: float(v) for k, v in (scale or {}).items()},
            float(ontop.get("min_fraction", 0.5)) if ontop.get("rule") == "area" else None,
        )
    if spec.get("planner"):
        install_curobo_planning(spec["planner"])
    return cli.main(harness_argv)


if __name__ == "__main__":
    raise SystemExit(main())
