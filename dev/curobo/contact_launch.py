"""Same as tools/aspire_launch.py, plus a per-step contact log (dev tool, not part of ants).

Records, for every simulator step, the pairs of MuJoCo bodies in contact (with penetration
depth) and the end-effector height, to $ANTS_CONTACT_LOG (JSONL). Used to find out what blocks
the arm when a trajectory does not converge.

    ANTS_CONTACT_LOG=out.jsonl ../ASPIRE/.venv-libero/bin/python dev/curobo/contact_launch.py \
        scene.json -- run --benchmark libero-pro ...
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import aspire_launch  # noqa: E402

LIVE: dict = {}
ROBOT_PROMPTS = ("robot arm", "robot gripper")


class ContactEnv(aspire_launch.PerturbedEnv):
    def __init__(self, inner, spec: dict):
        super().__init__(inner, spec)
        LIVE["env"] = self
        self._n = 0
        self._log = Path(os.environ["ANTS_CONTACT_LOG"])
        self._log.write_text("", encoding="utf-8")

    def step(self, action):
        out = self._inner_step(action)
        self._n += 1
        model, data = self.sim.model._model, self.sim.data._data
        import mujoco

        def body(geom: int) -> str:
            return (
                mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, int(model.geom_bodyid[geom]))
                or "?"
            )

        pairs: dict[str, float] = {}
        for c in data.contact[: data.ncon]:
            a, b = sorted((body(c.geom1), body(c.geom2)))
            key = f"{a} | {b}"
            pairs[key] = min(pairs.get(key, 0.0), float(c.dist))
        base = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "robot0_base")
        rot = data.xmat[base].reshape(3, 3)
        where = {}
        for c in data.contact[: data.ncon]:
            names = {body(c.geom1), body(c.geom2)}
            if any("wine_rack" in n for n in names) and any(
                n.startswith("gripper0") for n in names
            ):
                where["gripper|rack"] = [
                    round(float(v), 4) for v in rot.T @ (c.pos - data.xpos[base])
                ]
        if self._n == 1:
            rack = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "wine_rack_1_main")
            geoms = [g for g in range(model.ngeom) if model.geom_bodyid[g] == rack]
            info = {
                int(g): {
                    "type": int(model.geom_type[g]),
                    "size": [round(float(v), 4) for v in model.geom_size[g]],
                    "pos_base": [
                        round(float(v), 4) for v in rot.T @ (data.geom_xpos[g] - data.xpos[base])
                    ],
                    "group": int(model.geom_group[g]),
                }
                for g in geoms
            }
            (self._log.parent / "rack_geoms.json").write_text(
                json.dumps(info, indent=1), encoding="utf-8"
            )
        hand = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "robot0_right_hand")
        rec = {
            "step": self._n,
            "ee": [round(float(v), 4) for v in data.xpos[hand]],
            "contacts": pairs,
            "rack_gripper_pos_base": where,
            "bowl_plate_xyz": [
                [
                    round(float(v), 4)
                    for v in data.xpos[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, n)]
                ]
                for n in ("akita_black_bowl_1_main", "plate_1_main")
            ],
        }
        with self._log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        return out

    def _inner_step(self, action):
        return super().step(action)


def install_robot_mask() -> None:
    """Drop robot pixels from the planning cloud with a segmentation render, not a distance carve.

    The cuRobo service deletes scene points near its robot spheres, which also deletes real
    obstacles next to the gripper. Here the planning cloud is built from depth pixels that are not
    robot pixels (MuJoCo's segmentation of the robot and gripper geoms, dilated by 2 px). In a real
    setup the same mask would come from a text-prompted segmenter on "robot gripper and arm".
    """
    import mujoco
    import numpy as np
    from cap_harness.api import CapApi
    from scipy.ndimage import binary_dilation

    renderers: dict = {}
    flip: dict = {}
    original = CapApi._project_mask

    def robot_pixels(camera_name: str, depth: np.ndarray) -> np.ndarray:
        env = LIVE["env"]
        model, data = env.sim.model._model, env.sim.data._data
        h, w = depth.shape
        if (h, w) not in renderers:
            renderers[(h, w)] = mujoco.Renderer(model, h, w)
        r = renderers[(h, w)]
        r.update_scene(data, camera=camera_name)
        r.enable_depth_rendering()
        rendered = r.render().copy()
        r.disable_depth_rendering()
        if (
            camera_name not in flip
        ):  # LIBERO frames may be stored upside down: pick the matching one
            ok = np.isfinite(depth) & (depth > 0) & (rendered < 10)
            err = (
                np.abs(rendered - depth)[ok].mean(),
                np.abs(np.flipud(rendered) - depth)[ok].mean(),
            )
            flip[camera_name] = bool(err[1] < err[0])
            print(
                f"[ants-robot-mask] {camera_name}: depth match {err[0]:.3f} m plain, "
                f"{err[1]:.3f} m flipped",
                file=sys.stderr,
            )
        r.enable_segmentation_rendering()
        r.update_scene(data, camera=camera_name)
        seg = r.render().copy()
        r.disable_segmentation_rendering()
        if flip[camera_name]:
            seg = np.flipud(seg)
        names = [
            mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, int(b)) or ""
            for b in model.geom_bodyid
        ]
        robot_geom = np.array([n.startswith(("robot0", "gripper0", "mount0")) for n in names])
        is_geom = seg[..., 1] == int(mujoco.mjtObj.mjOBJ_GEOM)
        mask = is_geom & robot_geom[np.clip(seg[..., 0], 0, len(robot_geom) - 1)]
        LIVE["seg_body"] = np.array(
            [
                mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, int(b)) or "?"
                for b in range(model.nbody)
            ]
        )[model.geom_bodyid[np.clip(seg[..., 0], 0, model.ngeom - 1)]]
        LIVE["seg_body"][~is_geom] = "(none)"
        return binary_dilation(mask, iterations=2)

    def sam3_pixels(api, camera_name: str, observation) -> np.ndarray:
        """Robot pixels from a text-prompted segmenter: no simulator state involved."""
        shape = observation.cameras[camera_name].depth_m.shape
        union = np.zeros(shape, dtype=bool)
        for prompt in ROBOT_PROMPTS:
            result = api._segment_text(camera_name, prompt, observation)
            if result.ok:
                for seg in result.segmentations:
                    union |= np.asarray(seg.mask, dtype=bool)
        print(
            f"[ants-robot-mask] sam3 {camera_name}: {int(union.sum())} robot pixels",
            file=sys.stderr,
        )
        return binary_dilation(union, iterations=3)

    def masked(self, mask, *, camera_name, target_frame, observation):
        if isinstance(mask, np.ndarray) and mask.dtype == bool and "env" in LIVE:
            if os.environ["ANTS_ROBOT_MASK"] == "sam3":
                robot = sam3_pixels(self, camera_name, observation)
            else:
                robot = robot_pixels(camera_name, observation.cameras[camera_name].depth_m)
            mask = mask & ~robot
            probe = os.environ.get("ANTS_PROBE_XYZ")
            if probe and camera_name == "agentview":  # which scene bodies put points near the goal?
                goal = np.array([float(v) for v in probe.split(",")])
                for body in sorted(set(LIVE["seg_body"][mask])):
                    sub = mask & (LIVE["seg_body"] == body)
                    pts = original(
                        self,
                        sub,
                        camera_name=camera_name,
                        target_frame=target_frame,
                        observation=observation,
                    ).points
                    d = np.linalg.norm(pts - goal, axis=1).min() if len(pts) else float("nan")
                    print(
                        f"[ants-probe] {body:32s} {len(pts):6d} pts, "
                        f"nearest to goal {d * 100:5.1f} cm",
                        file=sys.stderr,
                    )
        return original(
            self, mask, camera_name=camera_name, target_frame=target_frame, observation=observation
        )

    CapApi._project_mask = masked


def main() -> int:
    split = sys.argv.index("--")
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    import cap_harness.libero.adapter as adapter
    from cap_harness import cli

    original = adapter._load_offscreen_render_env

    def patched_loader():
        factory = original()
        return lambda **kwargs: ContactEnv(factory(**kwargs), spec)

    adapter._load_offscreen_render_env = patched_loader
    if os.environ.get("ANTS_ROBOT_MASK"):
        install_robot_mask()
    if os.environ.get("ANTS_EXCLUDE_RADIUS_M"):
        import numpy as np
        from cap_harness.api import CapApi

        radius = float(os.environ["ANTS_EXCLUDE_RADIUS_M"])

        def exclude_near(scene_points, target_points):
            """Drop scene points within `radius` of any target point (the stock box uses the 1-99%
            quantile bounding box, which leaves rim outliers and takes in neighbours)."""
            from scipy.spatial import cKDTree

            near = cKDTree(target_points).query(scene_points, distance_upper_bound=radius)[0]
            kept = scene_points[~np.isfinite(near)]
            if not len(kept):
                raise ValueError("target exclusion removed the entire observed planning scene")
            return kept

        CapApi._exclude_target_from_scene = staticmethod(exclude_near)
    if os.environ.get("ANTS_CLOUD_DIR"):
        import numpy as np
        from cap_harness.api import CapApi

        cloud_dir = Path(os.environ["ANTS_CLOUD_DIR"])
        cloud_dir.mkdir(parents=True, exist_ok=True)
        inner = CapApi._planning_scene
        counter = iter(range(10_000))

        def dump(self, *a, **kw):  # save every planning cloud cuRobo is given
            scene = inner(self, *a, **kw)
            np.save(cloud_dir / f"cloud_{next(counter):03d}.npy", scene.point_cloud.points)
            return scene

        CapApi._planning_scene = dump
    scale = (spec.get("scale") or {}).get("bodies")
    if scale:
        aspire_launch.scale_ontop_tolerance({k: float(v) for k, v in scale.items()})
    return cli.main(sys.argv[split + 1 :])


if __name__ == "__main__":
    raise SystemExit(main())
