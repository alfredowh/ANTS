"""Persistent occupancy map for the planner: fuse every planning frame instead of using one.

Each 1 cm voxel keeps a log-odds occupancy value (a per-voxel binary Bayes filter). Every planning
call:

1. **miss**: every mapped voxel is projected into each depth camera; a voxel the camera sees
   *through* (voxel depth < measured depth - margin) loses `miss` log-odds. Voxels hidden behind a
   nearer surface (the arm, another object) are not touched, so occluded obstacles are remembered.
2. **hit**: the frame's planning points (already without robot, held object and target) add
   `hit` log-odds to their voxels, once per voxel per frame.
3. The planning cloud is the centres of voxels with log-odds above `threshold`.

`hit` > `threshold` from zero, so a newly seen obstacle enters the planner on its first frame
(conservative); single-frame ghosts leave once a later view sees through them. Numpy only, so it
runs inside the LIBERO process. Simulator truth is never read.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

_OFF = 1 << 20  # voxel index offset so keys are non-negative
_BITS = 21


def _keys(ijk: np.ndarray) -> np.ndarray:
    v = ijk.astype(np.int64) + _OFF
    return (v[:, 0] << (2 * _BITS)) | (v[:, 1] << _BITS) | v[:, 2]


def _ijk(keys: np.ndarray) -> np.ndarray:
    mask = (1 << _BITS) - 1
    return np.c_[keys >> (2 * _BITS), (keys >> _BITS) & mask, keys & mask] - _OFF


@dataclass
class Camera:
    """One depth image with its pinhole intrinsics and camera-to-base transform."""

    depth: np.ndarray  # (H, W) metres, non-finite or <= 0 = no return
    intrinsics: np.ndarray  # (3, 3)
    cam_to_base: np.ndarray  # (4, 4)


@dataclass
class FusedMap:
    voxel: float = 0.01
    hit: float = 0.85
    miss: float = 0.4
    threshold: float = 0.0
    clamp: tuple[float, float] = (-2.0, 3.5)
    margin: float = 0.02  # depth band around the measured surface treated as "seen, not free"
    keys: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    logodds: np.ndarray = field(default_factory=lambda: np.zeros(0))

    def centres(self) -> np.ndarray:
        return (_ijk(self.keys) + 0.5) * self.voxel

    def occupied(self) -> np.ndarray:
        return self.centres()[self.logodds > self.threshold]

    def _seen_free(self, cameras: list[Camera]) -> np.ndarray:
        free = np.zeros(len(self.keys), dtype=bool)
        if not len(self.keys):
            return free
        world = np.c_[self.centres(), np.ones(len(self.keys))]
        for cam in cameras:
            pc = (world @ np.linalg.inv(cam.cam_to_base).T)[:, :3]
            z = pc[:, 2]
            front = z > 1e-3
            k = cam.intrinsics
            u = np.full(len(z), -1, dtype=np.int64)
            v = np.full(len(z), -1, dtype=np.int64)
            u[front] = np.round(pc[front, 0] * k[0, 0] / z[front] + k[0, 2]).astype(np.int64)
            v[front] = np.round(pc[front, 1] * k[1, 1] / z[front] + k[1, 2]).astype(np.int64)
            h, w = cam.depth.shape
            inside = front & (u >= 0) & (u < w) & (v >= 0) & (v < h)
            measured = np.full(len(z), np.nan)
            measured[inside] = cam.depth[v[inside], u[inside]]
            ok = inside & np.isfinite(measured) & (measured > 0)
            free |= ok & (z < measured - self.margin)
        return free

    def update(self, points: np.ndarray, cameras: list[Camera]) -> np.ndarray:
        """Fuse one frame and return the occupied voxel centres (the planning cloud)."""
        lo, hi = self.clamp
        free = self._seen_free(cameras)
        self.logodds[free] = np.maximum(self.logodds[free] - self.miss, lo)
        if len(points):
            new = np.unique(_keys(np.floor(points / self.voxel)))
            pos = np.searchsorted(self.keys, new)
            known = np.zeros(len(new), dtype=bool)
            if len(self.keys):
                known = (pos < len(self.keys)) & (
                    self.keys[np.minimum(pos, len(self.keys) - 1)] == new
                )
            idx = pos[known]
            self.logodds[idx] = np.minimum(self.logodds[idx] + self.hit, hi)
            add = new[~known]
            keys = np.concatenate([self.keys, add])
            logodds = np.concatenate([self.logodds, np.full(len(add), min(self.hit, hi))])
            order = np.argsort(keys)
            self.keys, self.logodds = keys[order], logodds[order]
        keep = self.logodds > lo  # forget voxels that are confidently free
        self.keys, self.logodds = self.keys[keep], self.logodds[keep]
        return self.occupied()
