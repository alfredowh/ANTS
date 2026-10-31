import random
from collections import Counter

import pytest

from ants.adversary.planner.selector import (
    CategoryCounts,
    CategorySelector,
    beta_cdf,
    beta_ppf,
)

CATS = ("pose", "physics", "clutter", "camera")


@pytest.mark.parametrize("a,b", [(1, 1), (2, 5), (5, 2), (1, 30), (30, 1), (0.5, 0.5)])
def test_ppf_inverts_cdf(a, b):
    for q in (0.05, 0.5, 0.95):
        assert beta_cdf(beta_ppf(q, a, b), a, b) == pytest.approx(q, abs=1e-8)


@pytest.mark.parametrize("n", [0, 5, 27, 100])
def test_ppf_matches_closed_form(n):
    # Beta(1, n + 1): CDF 1 - (1 - x)^(n + 1), so the q-quantile is 1 - (1 - q)^(1 / (n + 1))
    expected = 1.0 - 0.05 ** (1.0 / (n + 1))
    assert beta_ppf(0.95, 1.0, n + 1.0) == pytest.approx(expected, abs=1e-8)


def test_failing_category_is_attacked_most():
    sel = CategorySelector(CATS, eta=0.2)
    counts = {"physics": CategoryCounts(failures=6, successes=1)}
    counts |= {c: CategoryCounts(successes=10) for c in ("pose", "clutter", "camera")}
    rng = random.Random(0)
    picks = Counter(sel.select(counts, rng).category for _ in range(2000))
    assert picks["physics"] / 2000 > 0.8  # Thompson picks it ~always; eta adds ~5% elsewhere


def test_untried_category_still_gets_chances():
    sel = CategorySelector(CATS, eta=0.0)  # Thompson alone, no uniform exploration
    counts = {c: CategoryCounts(failures=1, successes=4) for c in ("pose", "physics", "clutter")}
    rng = random.Random(1)
    picks = Counter(sel.select(counts, rng).category for _ in range(2000))
    assert picks["camera"] > picks["pose"]  # wide Beta(1, 1) beats a tighter ~0.29 estimate


def test_eta_one_is_uniform_baseline():
    sel = CategorySelector(CATS, eta=1.0)
    counts = {"physics": CategoryCounts(failures=50)}
    rng = random.Random(2)
    picks = Counter(sel.select(counts, rng).category for _ in range(4000))
    assert all(900 < picks[c] < 1100 for c in CATS)


def test_selection_logs_draws_and_is_reproducible():
    sel = CategorySelector(CATS)
    a = sel.select({}, random.Random(7))
    b = sel.select({}, random.Random(7))
    assert a == b and set(a.draws) == set(CATS)


def test_stop_rule_needs_28_clean_rollouts_per_category_at_defaults():
    # derived from the closed form above: 1 - 0.05^(1/(n+1)) < 0.1  <=>  n >= 28
    sel = CategorySelector(CATS)
    assert not sel.is_robust({c: CategoryCounts(successes=27) for c in CATS}, tau=0.1, q=0.95)
    assert sel.is_robust({c: CategoryCounts(successes=28) for c in CATS}, tau=0.1, q=0.95)


def test_one_failure_blocks_robustness():
    sel = CategorySelector(CATS)
    counts = {c: CategoryCounts(successes=28) for c in CATS}
    counts["camera"] = CategoryCounts(failures=1, successes=28)
    assert not sel.is_robust(counts)


def test_mean_of_empty_counts_is_prior_mean():
    assert CategorySelector(CATS).mean({}) == {c: 0.5 for c in CATS}


def test_invalid_config():
    with pytest.raises(ValueError):
        CategorySelector(())
    with pytest.raises(ValueError):
        CategorySelector(CATS, eta=1.5)
