"""Perturbation categories for the bowl-on-plate task, severity bounds, and the launcher spec.

A perturbation has a category and a severity in 0..1. Severity is clamped to the configured bound
before parameters are drawn, so the adversary can never propose a case beyond the bound (the
bound is the feasibility guard: keep it where a good policy can still succeed). At severity 1 the
`size` category equals the real hurobo objects (bowl x1.25, plate x1.9, close to the measured
x1.227 and x1.855).

`to_launcher_spec` turns perturbations into the JSON that `tools/aspire_launch.py` applies.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ants.contracts import Perturbation

CATEGORIES = ("pose", "physics", "size", "actuation", "camera")

BOWL_JOINT = "akita_black_bowl_1_joint0"
BOWL_BODY = "akita_black_bowl_1_main"
PLATE_BODY = "plate_1_main"

#: Parameters at severity 1.0 (linear in severity).
FULL = {
    "pose_shift_m": 0.08,
    "friction_drop": 0.7,
    "bowl_growth": 0.25,
    "plate_growth": 0.9,
    "noise_std": 0.02,
    "latency_steps": 3,
    "camera_shift_m": 0.05,
    "camera_fovy_deg": 4.0,
}


@dataclass
class Bounds:
    """Largest severity the adversary may use, per category (default for the rest)."""

    default: float = 0.6
    per_category: dict[str, float] = field(default_factory=dict)

    def limit(self, category: str) -> float:
        return min(1.0, max(0.0, self.per_category.get(category, self.default)))


def make(category: str, severity: float, rng: random.Random, bounds: Bounds) -> Perturbation:
    """Draw one perturbation of `category`; severity is clamped to the category's bound."""
    if category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}; choose from {CATEGORIES}")
    s = min(max(severity, 0.0), bounds.limit(category))
    params: dict[str, float] = {}
    if category == "pose":
        angle = rng.uniform(0.0, 2.0 * math.pi)
        r = FULL["pose_shift_m"] * s
        params = {"dx_m": round(r * math.cos(angle), 4), "dy_m": round(r * math.sin(angle), 4)}
    elif category == "physics":
        params = {"friction_scale": round(1.0 - FULL["friction_drop"] * s, 3)}
    elif category == "size":
        params = {
            "bowl_scale": round(1.0 + FULL["bowl_growth"] * s, 3),
            "plate_scale": round(1.0 + FULL["plate_growth"] * s, 3),
        }
    elif category == "actuation":
        params = {
            "noise_std": round(FULL["noise_std"] * s, 4),
            "latency_steps": float(round(FULL["latency_steps"] * s)),
        }
    elif category == "camera":
        params = {
            "dy_m": round(FULL["camera_shift_m"] * s, 4),
            "fovy_delta_deg": round(FULL["camera_fovy_deg"] * s, 3),
        }
    return Perturbation(category=category, params=params, severity=round(s, 3))


def to_launcher_spec(perturbations: list[Perturbation]) -> dict:
    """The perturbation JSON understood by `tools/aspire_launch.py` (empty if nothing to apply)."""
    spec: dict = {}
    for p in perturbations:
        if p.category == "pose":
            spec.setdefault("pose", {"offsets_m": {}})["offsets_m"][BOWL_JOINT] = [
                p.params["dx_m"],
                p.params["dy_m"],
            ]
        elif p.category == "physics":
            spec["physics"] = {"friction_scale": p.params["friction_scale"], "bodies": ["bowl"]}
        elif p.category == "size":
            spec["scale"] = {
                "bodies": {BOWL_BODY: p.params["bowl_scale"], PLATE_BODY: p.params["plate_scale"]}
            }
        elif p.category == "actuation":
            spec["actuation"] = {
                "noise_std": p.params["noise_std"],
                "latency_steps": int(p.params["latency_steps"]),
                "seed": 0,
            }
        elif p.category == "camera":
            spec["camera"] = {
                "name": "agentview",
                "pos_offset_m": [0.0, p.params["dy_m"], 0.0],
                "fovy_delta_deg": p.params["fovy_delta_deg"],
            }
    return spec
