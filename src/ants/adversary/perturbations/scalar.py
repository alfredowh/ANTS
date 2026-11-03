"""Scalar-severity sampling: System 1's v0 interface (`make`, `Bounds`, `CATEGORIES`) on our space.

One severity per draw is mapped onto every parameter of the category along its harder direction
(friction drops, objects grow, the camera shifts). Pose picks a random direction in the plane.
The result still passes `PerturbationSpace.validate`, so the space's bounds and rho always win.
This is the no-model path; the proposer can choose any direction within the same space.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ants.adversary.perturbations.space import DEFAULT_SPACE, PerturbationSpace
from ants.contracts import Perturbation

CATEGORIES: tuple[str, ...] = tuple(DEFAULT_SPACE.categories)

# +1 toward the parameter's upper bound, -1 toward its lower bound
_DIRECTION = {
    "friction_scale": -1.0,
    "mass_scale": 1.0,
    "bowl_scale": 1.0,
    "plate_scale": 1.0,
    "noise_std": 1.0,
    "latency_steps": 1.0,
    "dy_m": 1.0,
    "fovy_delta_deg": 1.0,
    "diffuse_scale": -1.0,
}


@dataclass
class Bounds:
    """Largest severity the scalar sampler may use, per category (default for the rest)."""

    default: float = 0.6
    per_category: dict[str, float] = field(default_factory=dict)

    def limit(self, category: str) -> float:
        return min(1.0, max(0.0, self.per_category.get(category, self.default)))


def make(
    category: str,
    severity: float,
    rng: random.Random,
    bounds: Bounds | None = None,
    space: PerturbationSpace = DEFAULT_SPACE,
    seed: int | None = None,
) -> Perturbation:
    """One perturbation of `category` at `severity`, clamped to the bound and to the space's rho."""
    if category not in space.categories:
        raise ValueError(f"unknown category {category!r}; choose from {tuple(space.categories)}")
    s = min(max(severity, 0.0), (bounds or Bounds()).limit(category))
    direction = dict(_DIRECTION)
    if category == "pose":
        angle = rng.uniform(0.0, 2.0 * math.pi)
        direction |= {"dx_m": math.cos(angle), "dy_m": math.sin(angle)}
    raw = {p.name: p.at(direction.get(p.name, 1.0) * s) for p in space.params(category)}
    return space.validate(category, raw, seed=seed, rationale=f"scalar severity {s:.3f}")
