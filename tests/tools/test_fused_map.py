"""Tests for the persistent occupancy map (tools/fused_map.py)."""

import importlib.util
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

_spec = importlib.util.spec_from_file_location(
    "fused_map", Path(__file__).resolve().parents[2] / "tools" / "fused_map.py"
)
fm = importlib.util.module_from_spec(_spec)
sys.modules["fused_map"] = fm  # dataclasses resolve their module by name
_spec.loader.exec_module(fm)

K = np.array([[100.0, 0, 50], [0, 100.0, 50], [0, 0, 1]])


def camera(depth_value: float) -> "fm.Camera":
    # camera at the origin looking down +z of the base frame
    return fm.Camera(np.full((100, 100), depth_value), K, np.eye(4))


def test_ghost_is_cleared_when_a_later_view_sees_through_it():
    m = fm.FusedMap()
    ghost = np.array([[0.0, 0.0, 0.5]])
    assert len(m.update(ghost, [camera(1.0)])) == 1  # first frame: kept (conservative)
    for _ in range(3):
        out = m.update(np.zeros((0, 3)), [camera(1.0)])  # wall at 1 m seen through the ghost
    assert len(out) == 0


def test_occluded_obstacle_is_remembered():
    m = fm.FusedMap()
    m.update(np.array([[0.0, 0.0, 0.5]]), [camera(1.0)])
    for _ in range(5):  # an arm at 0.3 m now hides it: never seen through
        out = m.update(np.zeros((0, 3)), [camera(0.3)])
    assert len(out) == 1


def test_repeated_hits_accumulate_and_clamp():
    m = fm.FusedMap()
    p = np.array([[0.0, 0.0, 0.5]])
    for _ in range(10):
        m.update(p, [camera(0.505)])
    assert m.logodds.max() == pytest.approx(3.5)
