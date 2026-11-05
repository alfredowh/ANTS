"""Perturbations to the JSON that `tools/aspire_launch.py` applies to the LIBERO scene.

Ported from System 1's v0 (branch `synthesizer`). The launcher wraps ASPIRE's LIBERO loader, so
the program under test never sees the perturbation. Body and joint names are those of
libero_goal_swap task 8 (bowl on plate).
"""

from __future__ import annotations

from collections.abc import Iterable

from ants.contracts import Perturbation

BOWL_JOINT = "akita_black_bowl_1_joint0"
BOWL_BODY = "akita_black_bowl_1_main"
PLATE_BODY = "plate_1_main"


def to_launcher_spec(perturbations: Iterable[Perturbation]) -> dict:
    """The launcher's perturbation spec (empty if nothing to apply). Missing values are nominal."""
    spec: dict = {}
    for p in perturbations:
        v = p.params
        if p.category == "pose":
            offsets = spec.setdefault("pose", {"offsets_m": {}})["offsets_m"]
            offsets[BOWL_JOINT] = [v.get("dx_m", 0.0), v.get("dy_m", 0.0)]
        elif p.category == "physics":
            spec["physics"] = {
                "friction_scale": v.get("friction_scale", 1.0),
                "mass_scale": v.get("mass_scale", 1.0),
                "bodies": ["bowl"],
            }
        elif p.category == "size":
            spec["scale"] = {
                "bodies": {
                    BOWL_BODY: v.get("bowl_scale", 1.0),
                    PLATE_BODY: v.get("plate_scale", 1.0),
                }
            }
        elif p.category == "actuation":
            spec["actuation"] = {
                "noise_std": v.get("noise_std", 0.0),
                "latency_steps": int(v.get("latency_steps", 0)),
                "seed": p.seed or 0,
            }
        elif p.category == "camera":
            spec["camera"] = {
                "name": "agentview",
                "pos_offset_m": [0.0, v.get("dy_m", 0.0), 0.0],
                "fovy_delta_deg": v.get("fovy_delta_deg", 0.0),
            }
        elif p.category == "lighting":
            spec["lighting"] = {"diffuse_scale": v.get("diffuse_scale", 1.0)}
        else:
            raise ValueError(f"the launcher cannot apply category {p.category!r}")
    return spec
