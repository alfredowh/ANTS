import pytest

from ants.adversary.perturbations import Bounds
from ants.adversary.planner import TestPlanner


def _run(strategy, seed=1, n=60):
    planner = TestPlanner(strategy=strategy, seed=seed)
    seen = []
    for _ in range(n):
        p = planner.propose()
        planner.update(p.category, failed=p.category == "size")
        seen.append(p.category)
    return seen


def test_thompson_concentrates_on_the_breaking_category_and_is_deterministic():
    # ported from System 1's v0 test (branch synthesizer)
    assert _run("thompson") == _run("thompson")
    assert _run("thompson").count("size") > _run("uniform").count("size")
    planner = TestPlanner(seed=2, bounds=Bounds(default=0.5))
    assert all(planner.propose().severity <= 0.5 for _ in range(30))


def test_selection_is_logged():
    planner = TestPlanner(seed=0)
    p = planner.propose()
    assert planner.last_selection.category == p.category
    assert set(planner.last_selection.draws) == set(planner.categories)


def test_reset_forgets_the_old_incumbent():
    planner = TestPlanner(seed=0)
    planner.update("pose", failed=True)
    planner.reset()
    assert planner.failures == {} and planner.passes == {}


def test_two_stop_modes():
    planner = TestPlanner(seed=0)
    for c in planner.categories:
        for _ in range(3):
            planner.update(c, failed=False)
    assert planner.confidently_robust(min_tests=3)  # cheap demo mode
    assert not planner.posterior_robust(tau=0.1)  # needs >= 28 clean per category
    for c in planner.categories:
        for _ in range(25):
            planner.update(c, failed=False)
    assert planner.posterior_robust(tau=0.1)


def test_bad_strategy():
    with pytest.raises(ValueError):
        TestPlanner(strategy="greedy")
