"""Data of the Studio's 3D Live mirror: what the simulator already knows, nothing else.

`write()` is called by the live hook, from inside the rollout. It only reads the MuJoCo model and
the poses and contacts the simulator has computed for this step: it never calls `mj_forward`, steps,
renders or draws a random number.

Files (replaced atomically, in the live folder):
- `mirror_model.json`, `mirror_model.bin`: once per simulator: visible geoms, their meshes, colours
  and the cameras. Geoms of the robot use the very meshes MuJoCo renders, so no URDF is involved.
- `mirror_state.bin`: little endian, `step` u32, `ncon` u32, then `ncon` x 3 f32 contact positions,
  then for each exported geom 3 f32 position + 9 f32 rotation (row major).
"""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path

import numpy as np

ROBOT_ROOTS = ("robot", "gripper", "mount")
MAX_CONTACTS = 256


def _replace(folder: Path, name: str, data: bytes) -> None:
    tmp = folder / f".{name}.{os.getpid()}.tmp"
    tmp.write_bytes(data)
    os.replace(tmp, folder / name)


def _colour(model, g: int) -> list[float]:
    """Geom colour; a textured material becomes the texture's mean colour (no UVs in the mirror)."""
    rgba = [float(x) for x in model.geom_rgba[g]]
    mat = int(model.geom_matid[g])
    if mat < 0:
        return rgba
    rgba = [float(x) for x in model.mat_rgba[mat]]
    tex = np.atleast_1d(model.mat_texid[mat])
    tex = [int(t) for t in tex if int(t) >= 0]
    if tex:
        t = tex[0]
        start, n = int(model.tex_adr[t]), int(model.tex_nchannel[t])
        size = int(model.tex_height[t]) * int(model.tex_width[t]) * n
        mean = model.tex_data[start : start + size].reshape(-1, n)[:, :3].mean(axis=0) / 255.0
        rgba[:3] = [float(rgba[i] * mean[i]) for i in range(3)]
    return rgba


def export_model(model) -> tuple[dict, bytes, list[int]]:
    """Visible geoms and the meshes they use, as JSON plus one binary blob."""
    chunks: list[bytes] = []
    offset = 0
    meshes: dict[int, dict] = {}
    geoms: list[dict] = []
    ids: list[int] = []
    for g in range(model.ngeom):
        gtype = int(model.geom_type[g])
        rgba = _colour(model, g)
        # robosuite and LIBERO: group 1 is what the camera sees, group 0 the collision copy
        if int(model.geom_group[g]) > 1 or rgba[3] <= 0.0 or gtype == 1:  # 1: height field
            continue
        if (
            int(model.geom_group[g]) == 0
            and int(model.geom_contype[g]) + int(model.geom_conaffinity[g]) > 0
            and gtype != 0
        ):
            continue
        body = int(model.geom_bodyid[g])
        root = model.body(int(model.body_rootid[body])).name
        name = model.body(body).name
        robot = root.startswith(ROBOT_ROOTS) or name.startswith(ROBOT_ROOTS)
        row = {
            "name": model.geom(g).name,
            "body": name,
            "type": gtype,
            "size": [round(float(x), 5) for x in model.geom_size[g]],
            "rgba": [round(x, 3) for x in rgba],
            "layer": "robot" if robot else "scene",
        }
        if gtype == 7:  # mesh
            m = int(model.geom_dataid[g])
            if m not in meshes:
                va, vn = int(model.mesh_vertadr[m]), int(model.mesh_vertnum[m])
                fa, fn = int(model.mesh_faceadr[m]), int(model.mesh_facenum[m])
                verts = np.asarray(model.mesh_vert[va : va + vn], dtype="<f4").tobytes()
                faces = np.asarray(model.mesh_face[fa : fa + fn], dtype="<u4").tobytes()
                meshes[m] = {
                    "vert_at": offset,
                    "verts": vn,
                    "face_at": offset + len(verts),
                    "faces": fn,
                }
                chunks += [verts, faces]
                offset += len(verts) + len(faces)
            row["mesh"] = m
        geoms.append(row)
        ids.append(g)
    return {"geoms": geoms, "meshes": {str(k): v for k, v in meshes.items()}}, b"".join(chunks), ids


def _cameras(model, data) -> dict:
    out = {}
    for c in range(model.ncam):
        out[model.camera(c).name] = {
            "pos": [round(float(x), 5) for x in data.cam_xpos[c]],
            "xmat": [round(float(x), 6) for x in data.cam_xmat[c]],
            "fovy": float(model.cam_fovy[c]),
        }
    return out


def state_bytes(data, ids: np.ndarray, step: int) -> bytes:
    ncon = min(int(data.ncon), MAX_CONTACTS)
    empty = np.empty((0, 3), "<f4")
    contacts = np.asarray(data.contact.pos[:ncon], dtype="<f4") if ncon else empty
    pose = np.concatenate([data.geom_xpos[ids], data.geom_xmat[ids]], axis=1)
    return b"".join(
        (
            struct.pack("<II", step, ncon),
            contacts.tobytes(),
            np.asarray(pose, dtype="<f4").tobytes(),
        )
    )


def write(sim, folder: Path, step: int, memo: dict) -> None:
    """`memo` keeps per-process export state; a new simulator object triggers a new export."""
    model, data = sim.model._model, sim.data._data
    if memo.get("exported") is not sim:
        meta, blob, ids = export_model(model)
        meta["id"] = f"{os.getpid()}-{id(sim)}"
        meta["cameras"] = _cameras(model, data)
        _replace(folder, "mirror_model.bin", blob)
        _replace(folder, "mirror_model.json", json.dumps(meta).encode("utf-8"))
        memo.update(exported=sim, ids=np.asarray(ids, dtype=int), mirror_id=meta["id"])
    _replace(folder, "mirror_state.bin", state_bytes(data, memo["ids"], step))
