"""Test planner: which category to attack next (selector) and what to change in it.

Keeps System 1's v0 interface (`propose`, `update`, `reset`, `confidently_robust`, strategies
"thompson" and "uniform") so the experiment loop on branch `synthesizer` runs unchanged, on top
of `CategorySelector` (eta exploration, logged draws, posterior stop rule). The model proposer
will plug in here; until then severities are drawn by the scalar sampler.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from ants.adversary.perturbations import CATEGORIES, Bounds, make
from ants.adversary.planner.selector import CategoryCounts, CategorySelector, Selection
from ants.contracts import Perturbation


@dataclass
class TestPlanner:
    __test__ = False  # not a pytest class

    categories: tuple[str, ...] = CATEGORIES
    bounds: Bounds = field(default_factory=Bounds)
    strategy: str = "thompson"  # thompson | uniform (the evaluation baseline)
    seed: int = 0
    eta: float = 0.2  # uniform share of thompson picks; ignored by "uniform"
    min_severity: float = 0.3
    failures: dict[str, int] = field(default_factory=dict)
    passes: dict[str, int] = field(default_factory=dict)
    last_selection: Selection | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.strategy not in ("thompson", "uniform"):
            raise ValueError("strategy must be 'thompson' or 'uniform'")
        eta = 1.0 if self.strategy == "uniform" else self.eta
        self.selector = CategorySelector(self.categories, eta=eta)
        self._rng = random.Random(self.seed)

    @property
    def counts(self) -> dict[str, CategoryCounts]:
        return {
            c: CategoryCounts(self.failures.get(c, 0), self.passes.get(c, 0))
            for c in self.categories
        }

    @property
    def rng(self) -> random.Random:
        return self._rng

    def select_category(self) -> str:
        """Thompson draw (or uniform pick) over the categories; the draws are kept for the log."""
        self.last_selection = self.selector.select(self.counts, self._rng)
        return self.last_selection.category

    def propose(self) -> Perturbation:
        """One perturbation: a category from the selector, a severity in [min_severity, bound]."""
        category = self.select_category()
        limit = self.bounds.limit(category)
        severity = self._rng.uniform(min(self.min_severity, limit), limit) if limit > 0 else 0.0
        return make(category, severity, self._rng, self.bounds)

    def update(self, category: str, failed: bool) -> None:
        """Record one outcome. Program errors must not be recorded: they are not task failures."""
        book = self.failures if failed else self.passes
        book[category] = book.get(category, 0) + 1

    def reset(self) -> None:
        """Forget the history: the beliefs were about the previous incumbent policy."""
        self.failures.clear()
        self.passes.clear()

    def confidently_robust(self, min_tests: int = 3) -> bool:
        """Cheap stop mode: every category tested at least `min_tests` times with no failure."""
        return all(
            self.passes.get(c, 0) >= min_tests and self.failures.get(c, 0) == 0
            for c in self.categories
        )

    def posterior_robust(self, tau: float = 0.1, q: float = 0.95) -> bool:
        """Reported-numbers stop mode: every category's q-quantile failure rate below tau."""
        return self.selector.is_robust(self.counts, tau=tau, q=q)
