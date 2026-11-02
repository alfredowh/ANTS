"""The footprint-overlap rule used for "bowl on plate" on a scaled scene."""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("numpy")  # the launcher runs in ASPIRE's venv; skipped in the ANTS env

# the launcher imports numpy only at module level; the simulator imports happen inside functions
_PATH = Path(__file__).resolve().parents[2] / "tools" / "aspire_launch.py"
sys.modules.setdefault("cap_harness", types.ModuleType("cap_harness"))
_spec = importlib.util.spec_from_file_location("aspire_launch", _PATH)
launch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launch)


def test_bowl_inside_plate_is_fully_covered():
    assert launch.circle_overlap_fraction((0, 0), 0.07, (0.02, 0), 0.12) == pytest.approx(1.0)


def test_far_apart_is_zero():
    assert launch.circle_overlap_fraction((0, 0), 0.07, (0.5, 0), 0.12) == 0.0


def test_half_of_bowl_on_the_plate_edge():
    # bowl centre on the plate edge, bowl much smaller than plate: just under half is inside
    f = launch.circle_overlap_fraction((0.12, 0), 0.02, (0, 0), 0.12)
    assert 0.45 < f < 0.5


def test_plate_smaller_than_bowl_caps_the_share():
    assert launch.circle_overlap_fraction((0, 0), 0.1, (0, 0), 0.05) == pytest.approx(0.25)
