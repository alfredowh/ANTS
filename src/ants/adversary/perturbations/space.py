"""The perturbation space: which settings each category may change, and how far.

Severity is enforced here, in code, whatever a model proposed: unknown settings are dropped,
missing ones take their nominal value, values are clamped to bounds, and if the result is more
severe than rho every setting is pulled toward nominal until severity equals rho.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping
from dataclasses import dataclass

from ants.contracts import Perturbation


@dataclass(frozen=True)
class Param:
    name: str
    nominal: float
    low: float
    high: float
    integer: bool = False
    unit: str = ""

    def __post_init__(self) -> None:
        if not self.low <= self.nominal <= self.high or self.low == self.high:
            raise ValueError(f"{self.name}: need low <= nominal <= high and low < high")

    def distance(self, value: float) -> float:
        """Normalised distance from nominal: 0 at nominal, 1 at the bound on that side."""
        if value >= self.nominal:
            span = self.high - self.nominal
        else:
            span = self.nominal - self.low
        return abs(value - self.nominal) / span if span > 0 else 0.0

    def at(self, signed_distance: float) -> float:
        """Value at a signed normalised distance in [-1, 1] from nominal."""
        d = max(-1.0, min(1.0, signed_distance))
        span = (self.high - self.nominal) if d >= 0 else (self.nominal - self.low)
        return self._snap(self.nominal + d * span)

    def clamp(self, value: float) -> float:
        return self._snap(max(self.low, min(self.high, value)))

    def _snap(self, value: float) -> float:
        # integers round toward nominal, so snapping never increases severity
        if not self.integer:
            return value
        return float(math.floor(value) if value >= self.nominal else math.ceil(value))


class PerturbationSpace:
    def __init__(self, categories: Mapping[str, tuple[Param, ...]], rho: float = 0.8) -> None:
        if not 0.0 < rho <= 1.0:
            raise ValueError(f"rho must be in (0, 1], got {rho}")
        self.categories = dict(categories)
        self.rho = rho

    def params(self, category: str) -> tuple[Param, ...]:
        if category not in self.categories:
            raise KeyError(f"unknown category {category!r}")
        return self.categories[category]

    def severity(self, category: str, values: Mapping[str, float]) -> float:
        return max((p.distance(values[p.name]) for p in self.params(category)), default=0.0)

    def validate(
        self,
        category: str,
        raw: Mapping[str, object],
        seed: int,
        rationale: str = "",
    ) -> Perturbation:
        """Turn any proposal into a legal perturbation inside the bounds with severity <= rho."""
        values: dict[str, float] = {}
        for p in self.params(category):
            try:
                v = float(raw[p.name])  # type: ignore[arg-type]
                if not math.isfinite(v):
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                v = p.nominal
            values[p.name] = p.clamp(v)

        sev = self.severity(category, values)
        if sev > self.rho:
            scale = self.rho / sev
            for p in self.params(category):
                v = values[p.name]
                sign = 1.0 if v >= p.nominal else -1.0
                values[p.name] = p.at(sign * p.distance(v) * scale)
            sev = self.severity(category, values)
        return Perturbation(category, values, round(sev, 6), seed, rationale)

    def sample(self, category: str, rng: random.Random, seed: int) -> Perturbation:
        """Uniform random perturbation within rho: the fallback when the model fails."""
        raw = {p.name: p.at(rng.uniform(-self.rho, self.rho)) for p in self.params(category)}
        return self.validate(category, raw, seed, rationale="uniform fallback")

    def describe(self, category: str) -> str:
        """Bounds as text for the proposer prompt."""
        lines = [
            f"- {p.name}: nominal {p.nominal}, range [{p.low}, {p.high}]"
            + (f" {p.unit}" if p.unit else "")
            + (" (integer)" if p.integer else "")
            for p in self.params(category)
        ]
        return f"category {category}, max severity {self.rho}:\n" + "\n".join(lines)


# LIBERO bowl-and-plate scene. Bounds are design choices, not measurements: tune them on the scene
# so that nominal passes and the edge of each range is hard but physically plausible.
DEFAULT_SPACE = PerturbationSpace(
    {
        "pose": (
            Param("dx", 0.0, -0.15, 0.15, unit="m"),
            Param("dy", 0.0, -0.15, 0.15, unit="m"),
            Param("dyaw", 0.0, -math.pi / 2, math.pi / 2, unit="rad"),
        ),
        "physics": (
            Param("friction_scale", 1.0, 0.2, 2.0),
            Param("mass_scale", 1.0, 0.5, 3.0),
        ),
        "clutter": (
            Param("n_distractors", 0.0, 0.0, 5.0, integer=True),
            Param("min_gap", 0.20, 0.03, 0.20, unit="m"),  # only tighter gaps are harder
        ),
        "camera": (
            Param("yaw", 0.0, -15.0, 15.0, unit="deg"),
            Param("pitch", 0.0, -10.0, 10.0, unit="deg"),
            Param("distance_scale", 1.0, 0.85, 1.15),
        ),
        "lighting": (
            Param("intensity_scale", 1.0, 0.3, 1.5),
            Param("azimuth", 0.0, -90.0, 90.0, unit="deg"),
        ),
        "occlusion": (Param("coverage", 0.0, 0.0, 0.6),),
        "actuation": (
            Param("action_noise_std", 0.0, 0.0, 0.05),
            Param("latency_steps", 0.0, 0.0, 3.0, integer=True),
        ),
    },
    rho=0.8,
)
