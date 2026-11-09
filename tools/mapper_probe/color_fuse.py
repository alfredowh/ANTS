"""Coloured fused map: run tools/fused_map.py over scan frames, colour each voxel by mean RGB.

Frames are tools/mapper_probe scan .npz files (rgb, depth_m, intrinsics, world_from_cam).
Cropped to the LIBERO table workspace. Numpy only (run with ASPIRE/.venv-libero/bin/python).
"""

import base64
import glob
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argparse
from pathlib import Path

from fused_map import Camera, FusedMap, _ijk, _keys  # noqa: E402

ap = argparse.ArgumentParser(description="Coloured fused map from mapper_probe RGB-D frames")
ap.add_argument("--frames-glob", default="data/runs/mapper_probe/frames_hires1024_h*/frame_*.npz")
ap.add_argument("--voxel", type=float, default=0.003, help="voxel size (m)")
ap.add_argument(
    "--out", type=Path, default=Path("data/runs/mapper_probe/fused_color_hires1024.npz")
)
ap.add_argument(
    "--viewer-json", type=Path, default=None, help="also write packed points for the viewer page"
)
args = ap.parse_args()
V = args.voxel
LO, HI = np.array([-0.8, -0.75, 0.885]), np.array([0.55, 0.75, 1.8])
m = FusedMap(voxel=V, margin=2 * V)
ks, cs = [], []
files = sorted(glob.glob(args.frames_glob))
t = time.time()
for f in files:
    z = np.load(f)
    D = z["depth_m"].astype(float)
    K = z["intrinsics"].astype(float)
    T = z["world_from_cam"].astype(float)
    h, w = D.shape
    v, u = np.mgrid[0:h, 0:w]
    ok = np.isfinite(D) & (D > 0.05) & (D < 3)
    x = (u[ok] - K[0, 2]) * D[ok] / K[0, 0]
    y = (v[ok] - K[1, 2]) * D[ok] / K[1, 1]
    p = (np.c_[x, y, D[ok], np.ones(ok.sum())] @ T.T)[:, :3]
    c = z["rgb"][ok].astype(float)
    inb = np.all((p >= LO) & (p <= HI), 1)
    p, c = p[inb], c[inb]
    m.update(p, [Camera(D, K, T)])
    k = _keys(np.floor(p / V))
    uk, inv = np.unique(k, return_inverse=True)
    s = np.zeros((len(uk), 4))
    np.add.at(s, inv, np.c_[c, np.ones(len(c))])
    ks.append(uk)
    cs.append(s)
print("frames", len(files), "voxels", len(m.keys), f"{time.time() - t:.0f}s")
occ = m.occupied()
ok_ = _keys(np.floor(occ / V + 1e-9))
K_ = np.concatenate(ks)
C_ = np.concatenate(cs)
uk, inv = np.unique(K_, return_inverse=True)
s = np.zeros((len(uk), 4))
np.add.at(s, inv, C_)
idx = np.searchsorted(uk, ok_)
idx = np.minimum(idx, len(uk) - 1)
good = uk[idx] == ok_
rgb = (s[idx, :3] / np.maximum(s[idx, 3:], 1)).astype(np.uint8)
occ, rgb = occ[good], rgb[good]
print("occupied coloured", len(occ), "raw voxels", len(uk))

raw = (_ijk(uk) + 0.5) * V
rawrgb = (s[:, :3] / s[:, 3:]).astype(np.uint8)
np.savez(args.out, occ=occ.astype(np.float32), rgb=rgb, raw=raw.astype(np.float32), rawrgb=rawrgb)


def pack(p, c):
    q = np.round((p - [0, 0, 0.9]) * 1000).astype(np.int16)
    return {
        "n": len(p),
        "p": base64.b64encode(q.tobytes()).decode(),
        "c": base64.b64encode(np.ascontiguousarray(c).tobytes()).decode(),
    }


if args.viewer_json:
    args.viewer_json.write_text(
        json.dumps({"fused": pack(occ, rgb), "raw": pack(raw, rawrgb)}), encoding="utf-8"
    )
