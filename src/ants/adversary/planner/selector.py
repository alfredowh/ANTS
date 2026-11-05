"""Category selector: which category to attack next, and when to call the policy robust.

Each category c keeps a Beta(prior + failures_c, prior + successes_c) posterior over its failure
rate for the current policy version. Each cycle draws one sample per category and attacks the
highest (Thompson sampling); with probability eta the pick is uniform instead, so no category is
ever starved. Stop rule: robust when every category's q-quantile is below tau.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryCounts:
    failures: int = 0
    successes: int = 0  # program errors count as neither


@dataclass(frozen=True)
class Selection:
    category: str
    draws: Mapping[str, float]  # posterior samples, logged so a judge can see why
    explored: bool  # True when the eta-uniform branch picked the category


class CategorySelector:
    def __init__(
        self,
        categories: Sequence[str],
        eta: float = 0.2,
        prior: tuple[float, float] = (1.0, 1.0),
    ) -> None:
        if not categories:
            raise ValueError("need at least one category")
        if not 0.0 <= eta <= 1.0:
            raise ValueError(f"eta must be in [0, 1], got {eta}")
        self.categories = tuple(categories)
        self.eta = eta
        self.prior = prior

    def posterior(self, counts: CategoryCounts) -> tuple[float, float]:
        return self.prior[0] + counts.failures, self.prior[1] + counts.successes

    def select(self, counts: Mapping[str, CategoryCounts], rng: random.Random) -> Selection:
        draws = {
            c: rng.betavariate(*self.posterior(counts.get(c, CategoryCounts())))
            for c in self.categories
        }
        if rng.random() < self.eta:
            return Selection(rng.choice(self.categories), draws, explored=True)
        return Selection(max(self.categories, key=draws.__getitem__), draws, explored=False)

    def mean(self, counts: Mapping[str, CategoryCounts]) -> dict[str, float]:
        out = {}
        for c in self.categories:
            a, b = self.posterior(counts.get(c, CategoryCounts()))
            out[c] = a / (a + b)
        return out

    def upper(self, counts: Mapping[str, CategoryCounts], q: float = 0.95) -> dict[str, float]:
        """Per-category q-quantile of the failure-rate posterior."""
        return {
            c: beta_ppf(q, *self.posterior(counts.get(c, CategoryCounts())))
            for c in self.categories
        }

    def is_robust(
        self, counts: Mapping[str, CategoryCounts], tau: float = 0.1, q: float = 0.95
    ) -> bool:
        return all(u < tau for u in self.upper(counts, q).values())


def beta_cdf(x: float, a: float, b: float) -> float:
    """Regularised incomplete beta I_x(a, b) (Numerical Recipes continued fraction)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_front = (
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(log_front) * _betacf(x, a, b) / a
    return 1.0 - math.exp(log_front) * _betacf(1.0 - x, b, a) / b


def beta_ppf(q: float, a: float, b: float, tol: float = 1e-10) -> float:
    """Inverse of beta_cdf by bisection."""
    if not 0.0 <= q <= 1.0:
        raise ValueError(f"q must be in [0, 1], got {q}")
    lo, hi = 0.0, 1.0
    while hi - lo > tol:
        mid = (lo + hi) / 2.0
        if beta_cdf(mid, a, b) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


_TINY = 1e-300


def _betacf(x: float, a: float, b: float, max_iter: int = 300, eps: float = 1e-14) -> float:
    """Continued fraction for the incomplete beta, modified Lentz method."""

    def nonzero(v: float) -> float:
        return v if abs(v) > _TINY else _TINY

    c, d = 1.0, 1.0 / nonzero(1.0 - (a + b) * x / (a + 1.0))
    h = d
    for m in range(1, max_iter + 1):
        even = m * (b - m) * x / ((a + 2 * m - 1.0) * (a + 2 * m))
        odd = -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1.0))
        for coeff in (even, odd):
            d = 1.0 / nonzero(1.0 + coeff * d)
            c = nonzero(1.0 + coeff / c)
            step = d * c
            h *= step
        if abs(step - 1.0) < eps:
            break
    return h
