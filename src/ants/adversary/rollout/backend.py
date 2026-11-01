"""Backend interface: build one perturbed episode and hand the policy its API.

Policies are flat cap_harness scripts (decision D5): the backend's API functions are put in the
script's scope as globals. Backends: the offline mock world here, and the cap_harness runner once
System 1's contracts (`CaseSpec`, `EpisodeTrace`) land.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from ants.contracts import Event, Perturbation


class Episode(Protocol):
    events: list[Event]

    def api(self) -> Mapping[str, object]:
        """Names put in the policy's scope: primitives, `Pose`, `get_robot_state`, ..."""
        ...

    def success(self) -> bool:
        """The task predicate, evaluated after the program ends. Never visible to the policy."""
        ...

    def metrics(self) -> Mapping[str, float]: ...


class Backend(Protocol):
    name: str

    def episode(self, perturbation: Perturbation | None, seed: int) -> Episode:
        """A fresh episode reset with `seed`, with `perturbation` applied (None = nominal)."""
        ...
