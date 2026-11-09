"""Twin builder: segment an object from a raw cloud around a localized centre."""

import importlib.util
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

_PATH = Path(__file__).resolve().parents[2] / "tools" / "real2sim" / "twin_bodies.py"
_spec = importlib.util.spec_from_file_location("twin_bodies", _PATH)
tb = importlib.util.module_from_spec(_spec)
sys.modules["twin_bodies"] = tb
_spec.loader.exec_module(tb)


def disc(centre, radius, z, n, rng):
    a, r = rng.uniform(0, 2 * np.pi, n), radius * np.sqrt(rng.uniform(0, 1, n))
    return np.c_[centre[0] + r * np.cos(a), centre[1] + r * np.sin(a), np.full(n, z)]


def test_segment_keeps_the_object_at_the_centre_and_drops_its_neighbour():
    rng = np.random.default_rng(0)
    table = np.c_[rng.uniform(0.2, 0.9, 20000), rng.uniform(-0.4, 0.4, 20000), np.zeros(20000)]
    bowl = disc((0.6, 0.1), 0.065, 0.04, 4000, rng)
    bottle = disc((0.75, 0.1), 0.03, 0.1, 2000, rng)  # 5.5 cm gap from the bowl rim
    cloud = np.vstack([table, bowl, bottle])
    z = tb.table_z(cloud, np.array([0.6, 0.1, 0.0]))
    assert abs(z) < 0.003
    pts = tb.segment(cloud, np.array([0.58, 0.1, 0.04]), 0.15, z)
    lo, hi = np.percentile(pts[:, :2], 1, 0), np.percentile(pts[:, :2], 99, 0)
    assert np.allclose((lo + hi) / 2, [0.6, 0.1], atol=0.005)
    assert np.mean(hi - lo) == pytest.approx(0.13, abs=0.01)


def test_raw_cloud_back_projects_with_the_camera_pose(tmp_path):
    k = np.array([[100.0, 0, 2], [0, 100.0, 2], [0, 0, 1]])
    pose = np.eye(4)
    pose[:3, 3] = [1.0, 2.0, 3.0]
    np.savez(
        tmp_path / "c.npz", depth_0=np.full((5, 5), 0.5, np.float32), intrinsics_0=k, pose_0=pose
    )
    pts = tb.raw_cloud(tmp_path / "c.npz")
    assert pts.shape == (25, 3)
    assert np.allclose(pts[12], [1.0, 2.0, 3.5])  # centre pixel on the optical axis
