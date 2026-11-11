"""Live twin: a second MuJoCo scene that follows a running LIBERO task from sensors only.

The launcher (`"live_twin"` spec key, `tools/aspire_launch.py`) starts this file as a child process
and streams, every other control step, what a real robot would provide: joint and finger positions
and RGB-D from the cameras in the spec. The twin process

- sets its robot directly from the joint readings;
- renders itself from the same cameras, with segmentation, to know which observed pixels should be
  the bowl, the plate or the robot. Pixels on its own robot are thrown away;
- moves each object by the robust translation that aligns its rendered surface with the observed
  depth points (render and compare, three nearest-neighbour iterations).

Limits: objects are tracked in position only (their orientation stays as initialised), and the twin
uses the same object geometry as the running scene. Initial xy comes from a perception-built
`twin.json`. Simulator truth is written by the launcher to `truth.jsonl`, used only when scoring
(`score` subcommand); the twin process never reads it.

    ASPIRE/.venv-libero/bin/python tools/real2sim/live_twin.py score data/runs/real2sim_live/run
"""

from __future__ import annotations

import json
import pickle
import subprocess
import sys
from pathlib import Path

import numpy as np

OBJECTS = ["akita_black_bowl_1_main", "plate_1_main"]
ROBOT_JOINTS = [f"robot0_joint{i}" for i in range(1, 8)]
FINGERS = ["gripper0_finger_joint1", "gripper0_finger_joint2"]
SIZE = 320
EVERY = 2


class Sender:
    """Launcher side: streams sensor readings to the twin process, logs truth to a separate file."""

    def __init__(self, sim, spec: dict):
        self.sim, self.tick = sim, 0
        self.dir = Path(spec["dir"])
        self.dir.mkdir(parents=True, exist_ok=True)
        self.cams = list(spec.get("cameras", ["agentview", "frontview"]))
        self.proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "twin", str(self.dir)],
            stdin=subprocess.PIPE,
            stdout=(self.dir / "twin.log").open("w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
        )
        self.truth = (self.dir / "truth.jsonl").open("w", encoding="utf-8")
        self._send(
            {
                "xml": sim.model.get_xml(),
                "cams": self.cams,
                "init_bodies": json.loads(Path(spec["init"]).read_text(encoding="utf-8"))["bodies"],
            }
        )

    def _send(self, msg) -> None:
        pickle.dump(msg, self.proc.stdin, protocol=4)
        self.proc.stdin.flush()

    def _qpos(self, names):
        m, d = self.sim.model, self.sim.data
        return [float(d.qpos[m.get_joint_qpos_addr(n)]) for n in names]

    def step(self, t: float) -> None:
        self.tick += 1
        if self.tick % EVERY:
            return
        from robosuite.utils.camera_utils import get_real_depth_map

        frames = {}
        for cam in self.cams:
            rgb, depth = self.sim.render(height=SIZE, width=SIZE, camera_name=cam, depth=True)
            frames[cam] = (rgb[::-1].copy(), get_real_depth_map(self.sim, depth)[::-1].copy())
        arm, fingers = self._qpos(ROBOT_JOINTS), self._qpos(FINGERS)
        self._send({"tick": self.tick, "t": t, "arm": arm, "fingers": fingers, "frames": frames})
        m, d = self.sim.model, self.sim.data
        row = {
            "tick": self.tick,
            "t": t,
            "arm": arm,
            "fingers": fingers,
            "objects": {n: d.body_xpos[m.body_name2id(n)].tolist() for n in OBJECTS},
        }
        self.truth.write(json.dumps(row) + "\n")
        self.truth.flush()

    def close(self) -> None:
        self.truth.close()
        self.proc.stdin.close()
        self.proc.wait(timeout=120)


def backproject(depth, ids, fovy, pos, mat, h, w):
    f = 0.5 * h / np.tan(np.deg2rad(fovy) / 2)
    v, u = ids
    z = depth[v, u]
    cam = np.c_[(u + 0.5 - w / 2) * z / f, -(v + 0.5 - h / 2) * z / f, -z]
    return cam @ mat.T + pos


def twin_main(out: Path) -> None:
    import imageio.v2 as imageio
    import mujoco
    from scipy import ndimage
    from scipy.spatial import cKDTree

    stream = sys.stdin.buffer
    head = pickle.load(stream)
    model = mujoco.MjModel.from_xml_string(head["xml"])
    data = mujoco.MjData(model)
    cams = head["cams"]
    jid = {
        n: mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, n) for n in ROBOT_JOINTS + FINGERS
    }
    adr = {n: int(model.jnt_qposadr[jid[n]]) for n in jid}
    body = {n: mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, n) for n in OBJECTS}
    free = {n: int(model.jnt_qposadr[model.body_jntadr[body[n]]]) for n in OBJECTS}
    robot_geoms = np.array(
        [
            mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, int(b)).startswith(
                ("robot0", "gripper0")
            )
            for b in model.geom_bodyid
        ]
    )
    base = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "robot0_base")
    table = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "table_collision")
    mujoco.mj_forward(model, data)
    table_z = float(data.geom_xpos[table][2] + model.geom_size[table][2])
    for n in OBJECTS:
        xy = np.asarray(head["init_bodies"][n]["xy_base"]) + data.xpos[base][:2]
        data.qpos[free[n] : free[n] + 2] = xy
        data.qpos[free[n] + 2] = table_z + 0.03
        data.qpos[free[n] + 3 : free[n] + 7] = [1, 0, 0, 0]
    rend = mujoco.Renderer(model, SIZE, SIZE)
    cam_ids = {c: mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, c) for c in cams}
    video = imageio.get_writer(out / "live.mp4", fps=10, macro_block_size=1, quality=7)
    log = (out / "twin_est.jsonl").open("w", encoding="utf-8")

    def render(cam):
        rend.update_scene(data, camera=cam_ids[cam])
        rend.disable_depth_rendering()
        rend.disable_segmentation_rendering()
        rgb = rend.render().copy()
        rend.enable_depth_rendering()
        depth = rend.render().copy()
        rend.disable_depth_rendering()
        rend.enable_segmentation_rendering()
        seg = rend.render().copy()
        rend.disable_segmentation_rendering()
        return rgb, depth, seg

    while True:
        try:
            msg = pickle.load(stream)
        except EOFError:
            break
        for n, q in zip(ROBOT_JOINTS + FINGERS, msg["arm"] + msg["fingers"], strict=True):
            data.qpos[adr[n]] = q
        mujoco.mj_forward(model, data)
        inliers = {}
        for _ in range(2):  # re-render once so the object masks follow the corrected pose
            obs, ref = {n: [] for n in OBJECTS}, {n: [] for n in OBJECTS}
            for cam in cams:
                _, depth_t, seg = render(cam)
                _, depth_o = msg["frames"][cam]
                geom = seg[..., 0]
                is_geom = seg[..., 1] == mujoco.mjtObj.mjOBJ_GEOM
                robot = np.zeros_like(geom, bool)
                robot[is_geom & (geom >= 0)] = robot_geoms[geom[is_geom & (geom >= 0)]]
                robot = ndimage.binary_dilation(robot, iterations=4)
                cid = cam_ids[cam]
                fovy, pos, mat = (
                    model.cam_fovy[cid],
                    data.cam_xpos[cid],
                    data.cam_xmat[cid].reshape(3, 3),
                )
                for n in OBJECTS:
                    mine = np.zeros_like(geom, bool)
                    mine[is_geom & (geom >= 0)] = (
                        model.geom_bodyid[geom[is_geom & (geom >= 0)]] == body[n]
                    )
                    if not mine.any():
                        continue
                    ref[n].append(
                        backproject(depth_t, np.nonzero(mine), fovy, pos, mat, SIZE, SIZE)
                    )
                    near = ndimage.binary_dilation(mine, iterations=12) & ~robot
                    # Depth on anything else the twin renders above the table (furniture, the
                    # other object) is not this object: without this the fit creeps toward it.
                    ids = np.nonzero(near & ~mine)
                    world = backproject(depth_t, ids, fovy, pos, mat, SIZE, SIZE)
                    near[
                        ids[0][world[:, 2] > table_z + 0.006], ids[1][world[:, 2] > table_z + 0.006]
                    ] = False
                    p = backproject(depth_o, np.nonzero(near), fovy, pos, mat, SIZE, SIZE)
                    obs[n].append(p[p[:, 2] > table_z + 0.006])
            for n in OBJECTS:
                if not obs[n] or not ref[n]:
                    continue
                o, r = np.concatenate(obs[n]), np.concatenate(ref[n])
                if len(o) < 40 or len(r) < 40:
                    continue
                o, r = o[:: max(1, len(o) // 1500)], r[:: max(1, len(r) // 1500)]
                shift = np.zeros(3)
                for _ in range(3):
                    dist, idx = cKDTree(o).query(r + shift)
                    keep = dist < max(0.02, np.percentile(dist, 70))
                    if keep.sum() < 20:
                        break
                    shift += np.median(o[idx[keep]] - (r[keep] + shift), axis=0)
                shift = np.clip(shift, -0.03, 0.03)
                data.qpos[free[n] : free[n] + 3] += shift
                inliers[n] = int(len(o))
            mujoco.mj_forward(model, data)
        rgb_t, _, _ = render(cams[0])
        video.append_data(np.hstack([msg["frames"][cams[0]][0], rgb_t]))
        row = {
            "tick": msg["tick"],
            "t": msg["t"],
            "objects": {n: data.xpos[body[n]].tolist() for n in OBJECTS},
            "points": inliers,
        }
        log.write(json.dumps(row) + "\n")
        log.flush()
    video.close()
    log.close()


def score(run: Path) -> dict:
    def rows(name):
        return {
            r["tick"]: r
            for r in map(json.loads, (run / name).read_text(encoding="utf-8").splitlines())
        }

    est, truth = rows("twin_est.jsonl"), rows("truth.jsonl")
    ticks = sorted(set(est) & set(truth))
    series = {
        n: [
            1000 * float(np.linalg.norm(np.subtract(est[t]["objects"][n], truth[t]["objects"][n])))
            for t in ticks
        ]
        for n in OBJECTS
    }
    summary = {
        n: {
            "median_mm": round(float(np.median(v)), 1),
            "p95_mm": round(float(np.percentile(v, 95)), 1),
            "max_mm": round(float(np.max(v)), 1),
        }
        for n, v in series.items()
    }
    out = {
        "ticks": len(ticks),
        "summary": summary,
        "times_s": [round(est[t]["t"], 2) for t in ticks],
        "error_mm": {n: [round(x, 1) for x in v] for n, v in series.items()},
        "true_z": {n: [round(truth[t]["objects"][n][2], 4) for t in ticks] for n in OBJECTS},
    }
    (run / "score.json").write_text(json.dumps(out), encoding="utf-8")
    print(json.dumps({"ticks": out["ticks"], "summary": summary}))
    return out


if __name__ == "__main__":
    if sys.argv[1] == "twin":
        twin_main(Path(sys.argv[2]))
    else:
        score(Path(sys.argv[2]))
