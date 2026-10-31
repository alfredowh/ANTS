"""Test planner: choose which perturbation category to try next, within the severity bound.

`thompson` keeps a Beta(1 + failures, 1 + passes) belief per category that a test there breaks
the incumbent, samples it, and tests the highest draw: the budget goes to the categories most
likely to break the policy. `uniform` is the baseline that ignores history. Both are
deterministic given the seed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from ants.adversary.perturbations import CATEGORIES, Bounds, make
from ants.contracts import Perturbation


@dataclass
class TestPlanner:
    __test__ = False  # not a pytest class

    categories: tuple[str, ...] = CATEGORIES
    bounds: Bounds = field(default_factory=Bounds)
    strategy: str = "thompson"  # thompson | uniform
    seed: int = 0
    failures: dict[str, int] = field(default_factory=dict)
    passes: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.strategy not in ("thompson", "uniform"):
            raise ValueError("strategy must be 'thompson' or 'uniform'")
        self._rng = random.Random(self.seed)

    def propose(self) -> Perturbation:
        """One perturbation: a category by the strategy, a severity in (0.3, bound]."""
        if self.strategy == "uniform":
            category = self._rng.choice(self.categories)
        else:
            draws = {
                c: self._rng.betavariate(1 + self.failures.get(c, 0), 1 + self.passes.get(c, 0))
                for c in self.categories
            }
            category = max(draws, key=draws.get)
        limit = self.bounds.limit(category)
        severity = self._rng.uniform(min(0.3, limit), limit) if limit > 0 else 0.0
        return make(category, severity, self._rng, self.bounds)

    def update(self, category: str, failed: bool) -> None:
        book = self.failures if failed else self.passes
        book[category] = book.get(category, 0) + 1

    def reset(self) -> None:
        """Forget the history: the beliefs were about the previous incumbent policy."""
        self.failures.clear()
        self.passes.clear()

    def confidently_robust(self, min_tests: int = 3) -> bool:
        """True when every category was tested at least `min_tests` times with no failure."""
        return all(
            self.passes.get(c, 0) >= min_tests and self.failures.get(c, 0) == 0
            for c in self.categories
        )
