"""Perturbation space: per-category parameters, bounds, the severity cap, and the launcher mapping.

Also exports System 1's v0 interface (`CATEGORIES`, `Bounds`, `make`, `to_launcher_spec`) so code
written against `ants.adversary.perturbations` on branch `synthesizer` keeps working.
"""

from ants.adversary.perturbations.launcher import to_launcher_spec
from ants.adversary.perturbations.scalar import CATEGORIES, Bounds, make
from ants.adversary.perturbations.space import DEFAULT_SPACE, Param, PerturbationSpace

__all__ = [
    "CATEGORIES",
    "DEFAULT_SPACE",
    "Bounds",
    "Param",
    "PerturbationSpace",
    "make",
    "to_launcher_spec",
]
