"""Franka Panda doing bowl-on-plate in a MuJoCo scene built from the real scan (no LIBERO assets).

Input is `scan_objects.py` output: the bowl and plate shapes fitted to the real video.
The world is that frame, with the tabletop at z = 0.

- Bowl: outer radius per height from the fit, made a thin shell (silhouettes cannot see the inside).
  Collision is a ring of convex wall segments and a floor.
- Plate: footprint r(angle) from the fit, a shallow dish with a raised rim (dish depth is a prior).
- Physics priors, labelled in the output: wall thickness, ceramic density, friction. Mass is shell
  volume x density. None of these are measured.

The Panda and its gripper are robosuite's models, mounted on the table's near edge. A scripted
controller (damped least-squares IK, joint PD with gravity compensation) pinches the bowl's rim,
carries it above the plate and releases it. The controller is given the scanned poses only; it
reads the simulator state just for logging and for the success check.

    MUJOCO_GL=egl ASPIRE/.venv-libero/bin/python tools/real2sim/scan_sim.py \\
        data/runs/real2sim_scan/setup_01 --out data/runs/real2sim_scan/setup_01/sim

Writes `task.json`, `scene.xml` and, unless `--no-video`, `front.mp4` and `side.mp4`.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from scipy.spatial import ConvexHull

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mesh_twin import revolve  # noqa: E402

DENSITY_KG_M3 = 2400.0  # prior: glazed ceramic
FRICTION = [0.8, 0.02, 0.001]  # prior: ceramic on rubber pads
WALL_M = 0.005  # prior
PLATE_SHELL_M = 0.006  # prior
DISH_FRACTION = 0.7  # prior: the flat centre of the plate, as a fraction of the footprint radius
TABLE_THICK = 0.03
N_WALL = 32
N_BANDS = 4


def write_obj(path: Path, verts: np.ndarray, faces: np.ndarray) -> None:
    lines = [f"v {x:.6f} {y:.6f} {z:.6f}\n" for x, y, z in verts]
    lines += [f"f {a + 1} {b + 1} {c + 1}\n" for a, b, c in faces]
    path.write_text("".join(lines), encoding="utf-8")


def convex_obj(path: Path, pts: np.ndarray) -> None:
    """Closed convex mesh with outward faces."""
    hull = ConvexHull(pts)
    centre = pts[hull.vertices].mean(0)
    faces = []
    for s in hull.simplices:
        n = np.cross(pts[s[1]] - pts[s[0]], pts[s[2]] - pts[s[0]])
        faces.append(s if np.dot(n, pts[s[0]] - centre) > 0 else s[[0, 2, 1]])
    write_obj(path, pts, np.array(faces))


def bowl_profile(params: list[float]) -> np.ndarray:
    """[[h, r]] from the table up, from the shape fitted to the masks."""
    _, _, r0, r1, height, power = params
    s = np.linspace(0.0, 1.0, 17)
    return np.c_[s * height, abs(r0) + (r1 - abs(r0)) * s ** max(power, 0.2)]


def shell_volume(prof: np.ndarray, wall: float) -> float:
    h, r = prof[:, 0], prof[:, 1]
    side = np.sum(2 * np.pi * (r[1:] + r[:-1]) / 2 * np.hypot(np.diff(r), np.diff(h))) * wall
    return float(side + np.pi * r[0] ** 2 * wall)


def bowl_parts(prof: np.ndarray, out: Path) -> tuple[list[dict], np.ndarray]:
    """Wall segments and floor as convex meshes in the body frame; returns shell sample points."""
    hs = np.linspace(0.0, prof[-1, 0], N_BANDS + 1)
    rs = np.interp(hs, prof[:, 0], prof[:, 1])
    parts, samples = [], []
    th = np.linspace(0, 2 * np.pi, N_WALL + 1)
    for b in range(N_BANDS):
        for a in range(N_WALL):
            pts = []
            for t in (th[a], th[a + 1]):
                for z, r in ((hs[b], rs[b]), (hs[b + 1], rs[b + 1])):
                    for rad in (r, r - WALL_M):
                        pts.append([rad * math.cos(t), rad * math.sin(t), z])
            pts = np.array(pts)
            name = f"bowl_w{b}_{a}"
            convex_obj(out / f"{name}.obj", pts)
            parts.append({"name": name})
            samples.append(pts.mean(0))
    ring = [[rs[0] * math.cos(t), rs[0] * math.sin(t), z] for t in th[:-1] for z in (0.0, WALL_M)]
    convex_obj(out / "bowl_floor.obj", np.array(ring))
    parts.append({"name": "bowl_floor"})
    samples.append(np.array([0, 0, WALL_M / 2]))
    return parts, np.array(samples)


def plate_footprint(params: list[float], n: int = 72) -> np.ndarray:
    """Outer radius per angle of the fitted rounded square."""
    _, _, a, b, yaw, e, _, _ = params
    th = (np.arange(n) + 0.5) * 2 * np.pi / n - yaw
    return (np.abs(np.cos(th) / a) ** e + np.abs(np.sin(th) / b) ** e) ** (-1 / e)


def plate_mesh(foot: np.ndarray, height: float) -> tuple[np.ndarray, np.ndarray]:
    """Closed dish: bottom centre, underside out to the rim, top surface back to the centre."""
    t = PLATE_SHELL_M
    rings = [
        (0.0, 0.0),
        (DISH_FRACTION, 0.0),
        (1.0, height - t),
        (1.0, height),
        (DISH_FRACTION, t),
        (0.0, t),
    ]
    n = len(foot)
    th = (np.arange(n) + 0.5) * 2 * np.pi / n
    verts = np.array(
        [
            [s * foot[j] * math.cos(th[j]), s * foot[j] * math.sin(th[j]), z]
            for s, z in rings
            for j in range(n)
        ]
    )
    faces = []
    for i in range(len(rings) - 1):
        for j in range(n):
            a, b = i * n + j, i * n + (j + 1) % n
            c, d = a + n, b + n
            faces += [[a, b, d], [a, d, c]]
    return verts, np.array(faces)


def plate_parts(foot: np.ndarray, height: float, out: Path) -> tuple[list[dict], float]:
    n = len(foot)
    th = (np.arange(n) + 0.5) * 2 * np.pi / n
    t = PLATE_SHELL_M
    at = lambda s, z, j: [  # noqa: E731
        s * foot[j % n] * math.cos(th[j % n]),
        s * foot[j % n] * math.sin(th[j % n]),
        z,
    ]
    centre = np.array([at(DISH_FRACTION, z, j) for j in range(n) for z in (0.0, t)])
    convex_obj(out / "plate_centre.obj", centre)
    parts, area = [{"name": "plate_centre"}], 0.0
    step = 3
    for k, j in enumerate(range(0, n, step)):
        pts = []
        for jj in (j, j + step):
            pts += [at(DISH_FRACTION, 0.0, jj), at(DISH_FRACTION, t, jj)]
            pts += [at(1.0, height - t, jj), at(1.0, height, jj)]
        name = f"plate_r{k}"
        convex_obj(out / f"{name}.obj", np.array(pts))
        parts.append({"name": name})
    for j in range(n):
        area += 0.5 * foot[j] * foot[(j + 1) % n] * math.sin(2 * np.pi / n)
    return parts, area * t * 1.15  # 15 %: the rim's slope adds surface


def inertia_of(samples: np.ndarray, mass: float) -> tuple[np.ndarray, np.ndarray]:
    com = samples.mean(0)
    d = samples - com
    m = mass / len(samples)
    return com, m * np.array(
        [
            np.sum(d[:, 1] ** 2 + d[:, 2] ** 2),
            np.sum(d[:, 0] ** 2 + d[:, 2] ** 2),
            np.sum(d[:, 0] ** 2 + d[:, 1] ** 2),
        ]
    )


def object_xml(name: str, pos, mass: float, com, inertia, parts, rgba) -> str:
    fr = " ".join(str(v) for v in FRICTION)
    geoms = "".join(
        f'<geom name="{p["name"]}" type="mesh" mesh="{p["name"]}" friction="{fr}" condim="6" '
        f'mass="0" group="3" rgba="1 0 0 0"/>'
        for p in parts
    )
    rgb = " ".join(f"{v:.3f}" for v in rgba)
    c, i = " ".join(f"{v:.5f}" for v in com), " ".join(f"{max(v, 1e-6):.7f}" for v in inertia)
    return (
        f'<body name="{name}" pos="{pos[0]:.4f} {pos[1]:.4f} {pos[2]:.4f}">'
        f'<freejoint name="{name}_joint"/><inertial pos="{c}" mass="{mass:.4f}" diaginertia="{i}"/>'
        f'<geom name="{name}_vis" type="mesh" mesh="{name}_vis" contype="0" conaffinity="0" '
        f'mass="0" rgba="{rgb} 1"/>{geoms}</body>'
    )


def build_scene(scan: Path, out: Path, setup_yaml: dict | None = None) -> tuple[str, dict]:
    from robosuite.models.grippers import PandaGripper
    from robosuite.models.robots import Panda
    from robosuite.models.world import MujocoWorldBase

    report = json.loads((scan / "scan.json").read_text(encoding="utf-8"))
    bowl_fit = report["objects"]["bowl"]["fit"]["params"]
    plate_fit = report["objects"]["plate"]["fit"]["params"]
    bowl_c = np.asarray(report["objects"]["bowl"]["centre_xy"])
    plate_c = np.asarray(report["objects"]["plate"]["centre_xy"])
    meshes = out / "meshes"
    meshes.mkdir(parents=True, exist_ok=True)

    prof = bowl_profile(bowl_fit)
    verts, faces = revolve(prof, WALL_M)
    write_obj(meshes / "bowl_vis.obj", verts, faces)
    bowl_parts_, samples = bowl_parts(prof, meshes)
    bowl_mass = shell_volume(prof, WALL_M) * DENSITY_KG_M3

    foot = plate_footprint(plate_fit)
    plate_h = float(plate_fit[6])
    verts, faces = plate_mesh(foot, plate_h)
    write_obj(meshes / "plate_vis.obj", verts, faces)
    plate_parts_, plate_vol = plate_parts(foot, plate_h, meshes)
    plate_mass = plate_vol * DENSITY_KG_M3
    rs = np.linspace(0.05, 0.14, 8)
    plate_samples = np.array(
        [[r * math.cos(a), r * math.sin(a), 0.006] for r in rs for a in np.arange(0, 6.28, 0.5)]
    )

    # Table from the object layout: near edge in front of the robot, real table in x.
    span = np.array([bowl_c, plate_c])
    mid = span.mean(0)
    base_xy = np.array([mid[0], max(span[:, 1].min() - 0.42, mid[1] - 0.5)])

    world = MujocoWorldBase()
    robot = Panda(idn=0)
    robot.add_gripper(PandaGripper(idn=0))
    robot.set_base_xpos([float(base_xy[0]), float(base_xy[1]), 0.0])
    robot.set_base_ori([0.0, 0.0, np.pi / 2])  # robot x axis along table +y
    world.merge(robot)
    root = ET.fromstring(world.get_xml())
    asset, body = root.find("asset"), root.find("worldbody")
    for p in bowl_parts_ + plate_parts_:
        ET.SubElement(
            asset, "mesh", name=p["name"], file=str((meshes / f"{p['name']}.obj").resolve())
        )
    for n in ("bowl_vis", "plate_vis"):
        ET.SubElement(asset, "mesh", name=n, file=str((meshes / f"{n}.obj").resolve()))
    ET.SubElement(
        asset,
        "texture",
        type="skybox",
        builtin="gradient",
        rgb1="0.82 0.84 0.82",
        rgb2="0.5 0.53 0.52",
        width="64",
        height="64",
    )

    lo = np.array([min(span[:, 0].min(), base_xy[0]) - 0.45, base_xy[1] - 0.2])
    hi = np.array([max(span[:, 0].max(), base_xy[0]) + 0.45, span[:, 1].max() + 0.3])
    tc, ts = (lo + hi) / 2, (hi - lo) / 2
    for el in (
        '<geom name="floor" type="plane" size="4 4 0.1" pos="0 0 -0.75" rgba="0.62 0.5 0.36 1"/>',
        f'<geom name="table" type="box" size="{ts[0]:.3f} {ts[1]:.3f} {TABLE_THICK / 2}" '
        f'pos="{tc[0]:.3f} {tc[1]:.3f} {-TABLE_THICK / 2}" rgba="0.74 0.58 0.38 1" friction="0.6 0.005 0.0001"/>',  # noqa: E501
        '<light pos="0.7 -0.2 2.2" dir="0 0.1 -1" diffuse="0.8 0.8 0.8" specular="0.2 0.2 0.2" castshadow="true"/>',  # noqa: E501
        '<light pos="-0.5 0.5 1.5" dir="0.4 -0.2 -1" diffuse="0.35 0.35 0.35" specular="0 0 0" castshadow="false"/>',  # noqa: E501
        f'<camera name="front" pos="{mid[0]:.3f} {mid[1] + 1.15:.3f} 0.75" xyaxes="-1 0 0 0 -0.55 0.83"/>',  # noqa: E501
        f'<camera name="side" pos="{mid[0] + 1.05:.3f} {mid[1] - 0.05:.3f} 0.55" xyaxes="0 1 0 -0.45 0 0.89"/>',  # noqa: E501
        object_xml(
            "plate",
            (*plate_c, 0.001),
            plate_mass,
            *inertia_of(plate_samples, plate_mass),
            plate_parts_,
            np.array(report["objects"]["plate"]["rgb"]) / 255,
        ),
        object_xml(
            "bowl",
            (*bowl_c, 0.001),
            bowl_mass,
            *inertia_of(samples, bowl_mass),
            bowl_parts_,
            np.array(report["objects"]["bowl"]["rgb"]) / 255,
        ),
    ):
        body.append(ET.fromstring(el))
    # Pinch force: a position actuator's force is gain x error, so close past the finger range.
    for act in root.iter("position"):
        if "gripper" in act.get("name", ""):
            act.attrib.pop("ctrllimited", None)
            act.set("ctrlrange", "-0.06 0.06")
            act.set("forcerange", "-40 40")
    xml = ET.tostring(root, encoding="unicode")
    (out / "scene.xml").write_text(xml, encoding="utf-8")
    return xml, {
        "bowl_xy": bowl_c.tolist(),
        "plate_xy": plate_c.tolist(),
        "base_xy": base_xy.round(4).tolist(),
        "bowl_profile": prof.round(4).tolist(),
        "bowl_rim_radius_m": round(float(prof[-1, 1]), 4),
        "bowl_height_m": round(float(prof[-1, 0]), 4),
        "bowl_mass_kg_prior": round(bowl_mass, 4),
        "plate_mass_kg_prior": round(plate_mass, 4),
        "plate_height_m": round(plate_h, 4),
        "plate_radius_range_m": [round(float(foot.min()), 4), round(float(foot.max()), 4)],
        "priors": {
            "density_kg_m3": DENSITY_KG_M3,
            "friction": FRICTION,
            "bowl_wall_m": WALL_M,
            "plate_shell_m": PLATE_SHELL_M,
            "dish_fraction": DISH_FRACTION,
        },
    }


class Controller:
    """Cartesian waypoints through damped least-squares IK, joint PD plus gravity compensation."""

    KP = np.array([500, 500, 500, 500, 250, 150, 80.0])
    KD = np.array([60, 60, 60, 50, 25, 15, 8.0])

    def __init__(self, mujoco, model, data, on_step):
        self.mj, self.m, self.d, self.on_step = mujoco, model, data, on_step
        self.site = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, "gripper0_grip_site")
        self.grip = 0.05  # finger ctrl: open
        self.q_des = data.qpos[:7].copy()

    def pose(self):
        return self.d.site_xpos[self.site].copy(), self.d.site_xmat[self.site].reshape(3, 3).copy()

    def step(self):
        d, m = self.d, self.m
        err = self.q_des - d.qpos[:7]
        d.ctrl[:7] = self.KP * err - self.KD * d.qvel[:7] + d.qfrc_bias[:7]
        d.ctrl[7:9] = [self.grip, -self.grip]
        self.mj.mj_step(m, d)
        self.on_step()

    def ik(self, pos, rot, dt):
        jp, jr = np.zeros((3, self.m.nv)), np.zeros((3, self.m.nv))
        self.mj.mj_forward(self.m, self.d)
        self.mj.mj_jacSite(self.m, self.d, jp, jr, self.site)
        j = np.vstack([jp[:, :7], jr[:, :7]])
        cur_p, cur_r = self.pose()
        err_r = 0.5 * sum(np.cross(cur_r[:, i], rot[:, i]) for i in range(3))
        e = np.r_[np.clip(pos - cur_p, -0.05, 0.05), err_r]
        dq = j.T @ np.linalg.solve(j @ j.T + 1e-3 * np.eye(6), e * 8.0)
        self.q_des = np.clip(self.q_des + dq * dt, self.m.jnt_range[:7, 0], self.m.jnt_range[:7, 1])

    def move(self, pos, rot, seconds):
        start, _ = self.pose()
        n = int(seconds / self.m.opt.timestep)
        for i in range(n):
            s = (i + 1) / n
            s = s * s * (3 - 2 * s)
            self.ik(start + (pos - start) * s, rot, self.m.opt.timestep)
            self.step()

    def hold(self, seconds):
        for _ in range(int(seconds / self.m.opt.timestep)):
            self.step()


def run_task(xml: str, meta: dict, out: Path, video: bool, seconds_scale: float) -> dict:
    import mujoco

    model = mujoco.MjModel.from_xml_string(xml)
    model.opt.timestep = 0.002
    model.vis.global_.offwidth = model.vis.global_.offheight = 720
    model.opt.cone = mujoco.mjtCone.mjCONE_ELLIPTIC
    data = mujoco.MjData(model)
    home = np.array([0.0, 0.19634954, 0.0, -2.2, 0.0, 2.4, 0.78539816])
    data.qpos[:7] = home
    data.qpos[7:9] = [0.04, -0.04]
    mujoco.mj_forward(model, data)

    bid = {n: mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, n) for n in ("bowl", "plate")}
    renderers, writers = {}, {}
    if video:
        import imageio.v2 as imageio

        for cam in ("front", "side"):
            renderers[cam] = mujoco.Renderer(model, 720, 720)
            writers[cam] = imageio.get_writer(
                out / f"{cam}.mp4", fps=25, macro_block_size=1, quality=7
            )
    trace, count = [], [0]

    def on_step():
        count[0] += 1
        if count[0] % 20 == 0:  # 25 Hz
            trace.append(
                {
                    "t": round(float(data.time), 3),
                    "phase": phase[0],
                    "bowl": data.xpos[bid["bowl"]].round(4).tolist(),
                    "plate": data.xpos[bid["plate"]].round(4).tolist(),
                    "aperture": round(float(data.qpos[7] - data.qpos[8]), 4),
                }
            )
            for cam, r in renderers.items():
                r.update_scene(data, camera=cam)
                writers[cam].append_data(r.render())

    phase = ["settle"]
    ctl = Controller(mujoco, model, data, on_step)
    ctl.hold(1.0)
    start_bowl = data.xpos[bid["bowl"]].copy()
    start_plate = data.xpos[bid["plate"]].copy()

    # Only the scanned poses and shape drive the plan.
    bowl = np.array([*meta["bowl_xy"], 0.0])
    plate = np.array([*meta["plate_xy"], 0.0])
    base = np.array([*meta["base_xy"], 0.0])
    rim_r = meta["bowl_rim_radius_m"] - WALL_M / 2
    rim_h = meta["bowl_height_m"]
    radial = (base - bowl)[:2]
    radial = radial / np.linalg.norm(radial)
    angle_toward_robot = math.atan2(radial[1], radial[0])
    grasp_xy = bowl[:2] + radial * rim_r

    _, rot0 = ctl.pose()
    # Turn about world z so the line between the finger pads is radial (measured, not assumed).
    pads = [
        data.geom_xpos[
            mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, f"gripper0_finger{i}_pad_collision")
        ]
        for i in (1, 2)
    ]
    finger_axis = pads[1] - pads[0]
    yaw = angle_toward_robot - math.atan2(finger_axis[1], finger_axis[0])
    c, s = math.cos(yaw), math.sin(yaw)
    rot = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]]) @ rot0

    scale = seconds_scale
    grip_z = rim_h - 0.012
    above = 0.12
    phase[0] = "approach"
    ctl.move(np.array([*grasp_xy, rim_h + above]), rot, 3.0 * scale)
    phase[0] = "descend"
    ctl.move(np.array([*grasp_xy, grip_z]), rot, 2.0 * scale)
    ctl.hold(0.4)
    phase[0] = "close"
    ctl.grip = -0.03
    ctl.hold(1.0)
    phase[0] = "lift"
    ctl.move(np.array([*grasp_xy, rim_h + above]), rot, 2.5 * scale)
    lifted = float(data.xpos[bid["bowl"]][2] - start_bowl[2])
    ctl.hold(0.3)
    offset = grasp_xy - bowl[:2]
    place_xy = plate[:2] + offset
    drop_clear = meta["plate_height_m"] + 0.012  # bowl bottom above the plate's rim height
    phase[0] = "carry"
    ctl.move(np.array([*place_xy, rim_h + above]), rot, 3.5 * scale)
    phase[0] = "lower"
    ctl.move(np.array([*place_xy, grip_z + drop_clear]), rot, 3.0 * scale)
    ctl.hold(0.4)
    phase[0] = "release"
    ctl.grip = 0.05
    ctl.hold(1.2)
    phase[0] = "retreat"
    ctl.move(np.array([*place_xy, rim_h + above + 0.05]), rot, 2.5 * scale)
    phase[0] = "settle_end"
    ctl.hold(1.0)

    for w in writers.values():
        w.close()
    for r in renderers.values():
        r.close()

    end_bowl = data.xpos[bid["bowl"]].copy()
    end_plate = data.xpos[bid["plate"]].copy()
    ids_plate = {i for i in range(model.ngeom) if model.geom_bodyid[i] == bid["plate"]}
    ids_bowl = {i for i in range(model.ngeom) if model.geom_bodyid[i] == bid["bowl"]}
    contact = sum(
        1
        for c in data.contact[: data.ncon]
        if (c.geom1 in ids_plate and c.geom2 in ids_bowl)
        or (c.geom2 in ids_plate and c.geom1 in ids_bowl)
    )
    table_contact = sum(
        1
        for c in data.contact[: data.ncon]
        if "table" in (model.geom(c.geom1).name, model.geom(c.geom2).name)
        and (c.geom1 in ids_bowl or c.geom2 in ids_bowl)
    )
    offset_xy = float(np.linalg.norm(end_bowl[:2] - end_plate[:2]))
    success = contact > 0 and table_contact == 0 and offset_xy < 0.08 and lifted > 0.05
    result = {
        "success": bool(success),
        "lifted_m": round(lifted, 4),
        "bowl_plate_offset_m": round(offset_xy, 4),
        "bowl_plate_contacts": contact,
        "bowl_table_contacts": table_contact,
        "start": {"bowl": start_bowl.round(4).tolist(), "plate": start_plate.round(4).tolist()},
        "end": {"bowl": end_bowl.round(4).tolist(), "plate": end_plate.round(4).tolist()},
        "plate_moved_m": round(float(np.linalg.norm(end_plate[:2] - start_plate[:2])), 4),
    }
    (out / "trace.json").write_text(json.dumps(trace), encoding="utf-8")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("scan", type=Path, help="scan_objects.py output folder")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--no-video", action="store_true")
    ap.add_argument("--seconds-scale", type=float, default=1.0, help="stretch the motion timing")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    xml, meta = build_scene(args.scan, args.out)
    result = run_task(xml, meta, args.out, not args.no_video, args.seconds_scale)
    (args.out / "task.json").write_text(
        json.dumps({"scene": meta, "result": result}, indent=1), encoding="utf-8"
    )
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
