"""Franka Panda forward kinematics and the cuRobo collision spheres, for the viewer's arm "bubbles".

Standard Panda geometry (modified Denavit-Hartenberg, the Franka documentation values). The link
frames follow the URDF used by cuRobo, so the sphere centres in `panda_spheres.json` (cuRobo's
`franka.yml`, Apache-2.0) are expressed in them. Used only for drawing; nothing here is a control
or collision-checking path. Pure Python so the viewer needs no extra dependency.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

Mat = list[list[float]]
# (a_{i-1}, d_i, alpha_{i-1}) per joint
DH = [
    (0.0, 0.333, 0.0),
    (0.0, 0.0, -math.pi / 2),
    (0.0, 0.316, math.pi / 2),
    (0.0825, 0.0, math.pi / 2),
    (-0.0825, 0.384, -math.pi / 2),
    (0.0, 0.0, math.pi / 2),
    (0.088, 0.0, math.pi / 2),
]
FLANGE_D = 0.107
_SPHERES = json.loads((Path(__file__).parent / "panda_spheres.json").read_text(encoding="utf-8"))


def _mul(a: Mat, b: Mat) -> Mat:
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _dh(a: float, d: float, alpha: float, theta: float) -> Mat:
    ca, sa, ct, st = math.cos(alpha), math.sin(alpha), math.cos(theta), math.sin(theta)
    return [
        [ct, -st, 0.0, a],
        [st * ca, ct * ca, -sa, -d * sa],
        [st * sa, ct * sa, ca, d * ca],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _rz(theta: float) -> Mat:
    c, s = math.cos(theta), math.sin(theta)
    return [[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def _tz(z: float) -> Mat:
    return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, z], [0, 0, 0, 1]]


def link_frames(q: list[float], finger_half_width: float = 0.04) -> dict[str, Mat]:
    """Frame of every link that carries spheres, in the robot base frame."""
    t: Mat = [[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]]
    frames = {"panda_link0": t}
    for i, (a, d, alpha) in enumerate(DH):
        t = _mul(t, _dh(a, d, alpha, q[i]))
        frames[f"panda_link{i + 1}"] = t
    hand = _mul(_mul(t, _tz(FLANGE_D)), _rz(-math.pi / 4))
    frames["panda_hand"] = hand
    left = _mul(hand, [[1, 0, 0, 0], [0, 1, 0, finger_half_width], [0, 0, 1, 0.0584], [0, 0, 0, 1]])
    right = _mul(
        hand, [[-1, 0, 0, 0], [0, -1, 0, -finger_half_width], [0, 0, 1, 0.0584], [0, 0, 0, 1]]
    )
    frames["panda_leftfinger"], frames["panda_rightfinger"] = left, right
    return frames


def flange_position(q: list[float]) -> tuple[float, float, float]:
    t = link_frames(q)["panda_hand"]
    return t[0][3], t[1][3], t[2][3]


def spheres(q: list[float], finger_half_width: float = 0.04) -> list[list[float | str]]:
    """The cuRobo spheres at joint angles `q`: [x, y, z, radius, link] in the base frame."""
    out: list[list[float | str]] = []
    for link, t in link_frames(q, finger_half_width).items():
        for cx, cy, cz, r in _SPHERES["links"].get(link, []):
            out.append(
                [
                    round(t[0][0] * cx + t[0][1] * cy + t[0][2] * cz + t[0][3], 4),
                    round(t[1][0] * cx + t[1][1] * cy + t[1][2] * cz + t[1][3], 4),
                    round(t[2][0] * cx + t[2][1] * cy + t[2][2] * cz + t[2][3], 4),
                    r,
                    link,
                ]
            )
    return out
