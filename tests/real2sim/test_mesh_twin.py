"""Mesh twin: profile fit, mesh and collision geometry, and the MJCF rewrite compiles in MuJoCo."""

import importlib.util
import sys
import types
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

_ROOT = Path(__file__).resolve().parents[2] / "tools"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


mt = _load("mesh_twin", _ROOT / "real2sim" / "mesh_twin.py")
sys.modules.setdefault("cap_harness", types.ModuleType("cap_harness"))
launch = _load("aspire_launch", _ROOT / "aspire_launch.py")


def bowl_points(rng, r0=0.03, r1=0.07, height=0.06, n=20000):
    """Outer surface of a conical bowl standing on z=0, centred at (0.5, 0.1)."""
    h = rng.uniform(0, height, n)
    a = rng.uniform(0, 2 * np.pi, n)
    r = r0 + (r1 - r0) * h / height
    return np.c_[0.5 + r * np.cos(a), 0.1 + r * np.sin(a), h]


def test_profile_recovers_radius_and_height():
    pts = bowl_points(np.random.default_rng(0))
    prof = mt.profile(pts, np.array([0.5, 0.1]), 0.0)
    assert prof[-1, 0] == pytest.approx(0.06, abs=0.003)
    assert prof[-1, 1] == pytest.approx(0.07, abs=0.002)
    assert np.all(np.diff(prof[:, 1]) >= 0)


def test_collision_uses_every_name_and_mass_is_shell():
    prof = np.array([[0.0, 0.03], [0.06, 0.07]])
    assert len(mt.collision(prof, "bowl")) == mt.N_GEOMS["bowl"]
    assert len(mt.collision(prof, "plate")) == mt.N_GEOMS["plate"]
    v = mt.shell_volume(prof, 0.004)
    assert 0 < v < mt.shell_volume(prof, None)


def test_mjcf_rewrite_compiles(tmp_path):
    mujoco = pytest.importorskip("mujoco")
    prof = mt.profile(bowl_points(np.random.default_rng(1)), np.array([0.5, 0.1]), 0.0)
    verts, faces = mt.revolve(prof, 0.004)
    mesh = tmp_path / "bowl.obj"
    mesh.write_text(
        "".join(f"v {x} {y} {z}\n" for x, y, z in verts)
        + "".join(f"f {a + 1} {b + 1} {c + 1}\n" for a, b, c in faces),
        encoding="utf-8",
    )
    xml = """<mujoco><asset/><worldbody><body name="bowl_main" pos="0 0 0.1"><freejoint/>
      <geom name="vis" type="box" size="0.05 0.05 0.03" contype="0" conaffinity="0"/>
      <geom name="g1" type="box" size="0.01 0.01 0.01"/>
      <geom name="g2" type="box" size="0.01 0.01 0.01"/>
      </body></worldbody></mujoco>"""
    root = ET.fromstring(xml)
    spec = {
        "bodies": {
            "bowl_main": {
                "mesh": str(mesh),
                "rgba": [0.9, 0.9, 0.9, 1],
                "mass_kg": 0.2,
                "friction": mt.FRICTION,
                "geoms": mt.collision(prof, "bowl"),
            }
        }
    }
    launch.mesh_twin_xml(root, spec)
    model = mujoco.MjModel.from_xml_string(ET.tostring(root, encoding="unicode"))
    assert model.body_mass[model.body("bowl_main").id] == pytest.approx(0.2, rel=1e-3)
    assert model.geom("vis").type == mujoco.mjtGeom.mjGEOM_MESH
    assert model.geom("g1").type == mujoco.mjtGeom.mjGEOM_CYLINDER  # floor first
