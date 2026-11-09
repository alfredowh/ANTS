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


PROFILE = [(0.0, 0.0279), (0.0124, 0.0562), (0.0372, 0.0667), (0.062, 0.0658)]
SPHERE_R = 0.015


def test_bowl_spheres_cover_the_known_profile():
    import numpy as np

    # the exp09-11 attach spec: 42 spheres of 1.5 cm, as logged in data/runs/curobo/attach.log
    spheres = launch.bowl_spheres(PROFILE, (0.45, 0.03), 0.19, SPHERE_R)
    assert len(spheres) == 42
    # every point of the wall profile is within a sphere radius (+1 voxel) of a sphere
    worst = 0.0
    for h, radius in PROFILE:
        ring = np.array(
            [
                [0.45 + radius * np.cos(a), 0.03 + radius * np.sin(a), 0.19 + max(h, SPHERE_R)]
                for a in np.linspace(0, 2 * np.pi, 36, endpoint=False)
            ]
        )
        d = np.linalg.norm(ring[:, None, :] - spheres[None, :, :], axis=-1).min(axis=1)
        worst = max(worst, float(d.max()))
    assert worst <= SPHERE_R + 0.01


def test_sphere_frames_round_trip():
    import numpy as np

    rng = np.random.default_rng(0)
    world = rng.random((10, 3))
    t = np.array([0.45, 0.03, 0.26])
    rot = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])  # 90 deg about z
    local = launch.spheres_to_local(world, t, rot)
    assert np.allclose(launch.spheres_to_world(local, t, rot), world)


def test_latch_stays_shut_on_a_flickering_mask():
    # first held frame attaches; a later frame with a missed mask must not detach
    assert launch.latch_action(False, True, True) == "keep"  # attach
    assert launch.latch_action(True, True, False) == "keep"  # flicker: the exp11 fix
    assert launch.latch_action(True, True, True) == "keep"
    assert launch.latch_action(True, False, False) == "release"  # gripper opened
    assert launch.latch_action(False, False, False) == "release"
    assert launch.latch_action(False, True, False) == "wait"  # never attached


def test_removal_mask_cuts_around_predicted_spheres_without_bowl_points():
    import numpy as np

    # no observed bowl points at all (missed mask): the predicted spheres still cut
    points = np.array([[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]])
    pred = np.array([[0.0, 0.0, 0.0]])
    cut = launch.removal_mask(points, np.zeros((0, 3)), 0.02, pred, 0.015 + 0.02)
    assert cut.tolist() == [True, False]
    # empty scene cuts nothing
    assert launch.removal_mask(np.zeros((0, 3)), np.zeros((0, 3)), 0.02, pred, 0.035).size == 0


def test_removal_mask_cuts_around_observed_bowl_points():
    scipy = pytest.importorskip("scipy")
    import numpy as np

    del scipy  # the import is the skip gate; removal_mask imports it lazily itself
    points = np.array([[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]])
    bowl = np.array([[0.0, 0.0, 0.005]])
    cut = launch.removal_mask(points, bowl, 0.02, np.zeros((0, 3)), 0.035)
    assert cut.tolist() == [True, False]


def test_held_points_drop_other_objects_matched_by_the_query():
    import numpy as np

    # C0 seed 52: bowl rim at the hand, wine bottle top 25 cm away and higher
    hand = np.array([0.612, 0.184, 0.04])
    bowl = np.array([[0.62, 0.15, 0.06], [0.58, 0.12, 0.06]])
    bottle = np.array([[0.702, -0.018, 0.25]])
    kept = launch.held_points(np.vstack([bowl, bottle]), hand, 0.15)
    assert np.allclose(kept, bowl)
    assert launch.held_points(np.zeros((0, 3)), hand, 0.15).shape == (0, 3)


def test_fit_centroid_ignores_finger_points_above_the_rim():
    import numpy as np

    rng = np.random.default_rng(0)
    ang = rng.uniform(0, 2 * np.pi, 400)
    bowl = np.c_[0.6 + 0.07 * np.cos(ang), 0.1 + 0.07 * np.sin(ang), rng.uniform(0.0, 0.05, 400)]
    fingers = np.c_[np.full(80, 0.67), np.full(80, 0.1), rng.uniform(0.05, 0.1, 80)]
    table = np.c_[rng.uniform(0.45, 0.75, 500), rng.uniform(-0.05, 0.25, 500), np.full(500, -0.011)]
    centre, z_bottom = launch.fit_centroid(np.vstack([bowl, fingers]), table)
    assert np.linalg.norm(centre - [0.6, 0.1]) < 0.02
    assert abs(z_bottom + 0.011) < 1e-6
    # no table in view: fall back to the mask's low percentile
    _, fallback = launch.fit_centroid(bowl, np.zeros((0, 3)))
    assert 0.0 <= fallback < 0.005


def test_attached_spheres_are_written_in_the_panda_hand_frame():
    """A point at the logged gripper site must land on panda_hand + the offset, by FK."""
    import numpy as np

    from ants.evalkit.panda import link_frames

    # exp10 no-demo attempt 1, first plan with the gripper closed on the bowl (replay_clean/attach)
    q = [0.2104, 0.7393, 0.0947, -1.8031, -0.1134, 2.5401, 1.1592]
    logged_site = np.array([0.6178, 0.1925, 0.0385])
    hand = np.asarray(link_frames(q)["panda_hand"], dtype=float)
    site_in_hand = launch.ee_local_to_hand(np.zeros((1, 3)))
    site_in_base = site_in_hand @ hand[:3, :3].T + hand[:3, 3]
    assert site_in_base[0] == pytest.approx(logged_site, abs=0.002)
