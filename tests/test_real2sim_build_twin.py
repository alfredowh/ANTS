import importlib.util
import struct
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "build_twin", Path(__file__).parents[1] / "tools" / "real2sim" / "build_twin.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_read_points3d_roundtrip(tmp_path):
    # one point: id, xyz, rgb(3B), error, empty track
    blob = struct.pack("<Q", 1) + struct.pack("<QdddBBBdQ", 7, 1.0, 2.0, 3.0, 9, 8, 7, 0.5, 0)
    p = tmp_path / "points3D.bin"
    p.write_bytes(blob)
    assert mod.read_points3d(p) == [(1.0, 2.0, 3.0)]
