import math
import random

import pytest

from ants.adversary.perturbations import DEFAULT_SPACE, Param, PerturbationSpace

SPACE = PerturbationSpace(
    {
        "physics": (Param("friction", 1.0, 0.2, 2.0), Param("mass", 1.0, 0.5, 3.0)),
        "clutter": (Param("n", 0.0, 0.0, 5.0, integer=True),),
    },
    rho=0.8,
)


def test_nominal_scene_has_zero_severity():
    p = SPACE.validate("physics", {}, seed=0)
    assert p.params == {"friction": 1.0, "mass": 1.0} and p.severity == 0.0


def test_unknown_dropped_missing_filled_junk_ignored():
    p = SPACE.validate("physics", {"friction": "abc", "colour": 3, "mass": float("nan")}, seed=0)
    assert p.params == {"friction": 1.0, "mass": 1.0}


def test_absurd_value_is_clamped_and_capped_at_rho():
    p = SPACE.validate("physics", {"mass": 50.0}, seed=0)  # a 50x heavier bowl
    assert p.severity == pytest.approx(0.8)
    assert p.params["mass"] == pytest.approx(1.0 + 0.8 * 2.0)


def test_rho_scales_all_params_keeping_direction():
    p = SPACE.validate("physics", {"friction": 0.2, "mass": 2.0}, seed=0)  # distances 1.0 and 0.5
    assert p.severity == pytest.approx(0.8)
    assert p.params["friction"] == pytest.approx(1.0 - 0.8 * 0.8)
    assert p.params["mass"] == pytest.approx(1.0 + 0.4 * 2.0)


def test_within_rho_is_untouched():
    p = SPACE.validate("physics", {"friction": 0.6}, seed=3, rationale="halve friction")
    assert p.params["friction"] == pytest.approx(0.6)
    assert p.severity == pytest.approx(0.5)
    assert p.seed == 3 and p.rationale == "halve friction"


def test_integer_rounds_toward_nominal_and_stays_within_rho():
    p = SPACE.validate("clutter", {"n": 5}, seed=0)
    assert p.params["n"] == 4.0 and p.severity <= 0.8


def test_unknown_category():
    with pytest.raises(KeyError):
        SPACE.validate("weather", {}, seed=0)


@pytest.mark.parametrize("category", sorted(DEFAULT_SPACE.categories))
def test_default_space_samples_respect_bounds(category):
    rng = random.Random(0)
    for i in range(200):
        p = DEFAULT_SPACE.sample(category, rng, seed=i)
        assert 0.0 <= p.severity <= DEFAULT_SPACE.rho + 1e-9
        for param in DEFAULT_SPACE.params(category):
            v = p.params[param.name]
            assert param.low <= v <= param.high and math.isfinite(v)
            if param.integer:
                assert v == int(v)


def test_sampling_is_reproducible():
    a = DEFAULT_SPACE.sample("pose", random.Random(42), seed=1)
    b = DEFAULT_SPACE.sample("pose", random.Random(42), seed=1)
    assert a == b


def test_bad_param_and_rho():
    with pytest.raises(ValueError):
        Param("x", 5.0, 0.0, 1.0)
    with pytest.raises(ValueError):
        PerturbationSpace({}, rho=0.0)


def test_describe_lists_bounds():
    text = DEFAULT_SPACE.describe("physics")
    assert "friction_scale" in text and "0.8" in text
