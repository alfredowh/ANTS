import random

import pytest

from ants.adversary.perturbations import (
    CATEGORIES,
    DEFAULT_SPACE,
    Bounds,
    make,
    to_launcher_spec,
)
from ants.contracts import Perturbation


def test_severity_is_clamped_to_the_bound_and_maps_to_a_launcher_spec():
    # ported from System 1's v0 test (branch synthesizer)
    rng = random.Random(0)
    p = make("size", 1.0, rng, Bounds(default=0.4))
    assert p.severity == pytest.approx(0.4) and p.params["plate_scale"] == pytest.approx(1.36)
    assert to_launcher_spec([p])["scale"]["bodies"]["plate_1_main"] == pytest.approx(1.36)
    assert to_launcher_spec([]) == {}
    with pytest.raises(ValueError):
        make("gravity", 0.5, rng, Bounds())


def test_scalar_severity_moves_each_param_toward_harder():
    rng = random.Random(1)
    p = make("physics", 0.5, rng, Bounds(default=1.0))
    assert p.params["friction_scale"] == pytest.approx(1.0 - 0.5 * 0.7)
    assert p.params["mass_scale"] == pytest.approx(1.0 + 0.5 * 2.0)
    assert make("lighting", 0.5, rng, Bounds(default=1.0)).params["diffuse_scale"] < 1.0


def test_rho_caps_even_an_unbounded_scalar_draw():
    p = make("size", 1.0, random.Random(2), Bounds(default=1.0))
    assert p.severity == pytest.approx(DEFAULT_SPACE.rho)


def test_pose_shift_stays_within_radius_and_is_reproducible():
    a = make("pose", 0.5, random.Random(3), Bounds(default=1.0))
    b = make("pose", 0.5, random.Random(3), Bounds(default=1.0))
    assert a == b
    assert (a.params["dx_m"] ** 2 + a.params["dy_m"] ** 2) ** 0.5 == pytest.approx(0.04)


@pytest.mark.parametrize("category", CATEGORIES)
def test_every_category_in_the_space_maps_to_the_launcher(category):
    p = make(category, 0.6, random.Random(0), Bounds(default=1.0), seed=5)
    spec = to_launcher_spec([p])
    assert spec, f"{category} produced an empty launcher spec"


def test_launcher_spec_contents():
    spec = to_launcher_spec(
        [
            Perturbation("pose", {"dx_m": 0.03, "dy_m": -0.02}, 0.4),
            Perturbation("actuation", {"noise_std": 0.01, "latency_steps": 2.0}, 0.7, seed=9),
            Perturbation("camera", {"dy_m": 0.02, "fovy_delta_deg": 2.0}, 0.5),
        ]
    )
    assert spec["pose"] == {"offsets_m": {"akita_black_bowl_1_joint0": [0.03, -0.02]}}
    assert spec["actuation"] == {"noise_std": 0.01, "latency_steps": 2, "seed": 9}
    assert spec["camera"]["pos_offset_m"] == [0.0, 0.02, 0.0]


def test_unwired_category_is_refused():
    with pytest.raises(ValueError):
        to_launcher_spec([Perturbation("clutter", {"n": 2.0}, 0.4)])
