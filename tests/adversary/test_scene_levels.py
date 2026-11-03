import math

from ants.adversary.collision_world import Box
from ants.adversary.scene_levels import apart, densify, hits_hand


def corners(cx, cy, cz, hx, hy, hz, yaw=0.0):
    c, s = math.cos(yaw), math.sin(yaw)
    out = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                x, y = sx * hx, sy * hy
                out.append((cx + c * x - s * y, cy + s * x + c * y, cz + sz * hz))
    return tuple(out)


def oriented(cx, cy, cz, hx, hy, hz, yaw=0.0):
    pts = corners(cx, cy, cz, hx, hy, hz, yaw)
    lo = tuple(min(p[i] for p in pts) for i in range(3))
    hi = tuple(max(p[i] for p in pts) for i in range(3))
    return Box(lo, hi, pts)


def test_separated_boxes_respect_the_margin():
    a = oriented(0, 0, 0, 0.1, 0.1, 0.1)
    b = oriented(0.25, 0, 0, 0.1, 0.1, 0.1)  # 5 cm gap
    assert apart(a, b, 0.0) and apart(a, b, 0.04) and not apart(a, b, 0.06)


def test_rotated_box_bounding_box_overlaps_but_the_box_does_not():
    thin = oriented(0, 0, 0, 0.2, 0.01, 0.05, yaw=math.pi / 4)  # a diagonal bar
    corner = oriented(0.17, -0.17, 0, 0.03, 0.03, 0.05)  # sits inside the bar's bounding box
    assert thin.gap(corner) == 0.0  # axis-aligned bounds overlap
    assert apart(thin, corner, 0.0)  # the real shapes do not


def test_hand_keep_out_follows_the_tcp():
    rail = Box((0.4, -0.2, 0.22), (0.5, -0.17, 0.24))
    assert hits_hand(rail, (0.45, -0.1, 0.13))  # hand body spans z 0.16 to 0.23 above this TCP
    assert not hits_hand(rail, (0.45, -0.1, 0.30))  # hand passes above
    assert not hits_hand(rail, (0.45, 0.2, 0.13))  # hand is beside it


def test_densify_keeps_the_ends():
    path = [(0.0, 0.0, 0.0), (0.1, 0.0, 0.0)]
    pts = densify(path, 0.03)
    assert pts[0] == path[0] and pts[-1] == path[-1] and len(pts) >= 4
