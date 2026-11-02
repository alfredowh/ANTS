"""Backend interface: build one perturbed episode and hand the policy its API.

Policies are flat cap_harness scripts (decision D5): the backend's API functions are put in the
script's scope as globals. Two shapes:

- `Backend` (the offline mock world): hands over an in-process episode; our runner execs the script.
- `ProgramBackend` (ASPIRE cap_harness): runs the whole program in its own process and returns the
  `RolloutResult`, because the simulator and its primitives live in another venv.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from ants.contracts import Event, Perturbation, RolloutResult


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


class ProgramBackend(Protocol):
    name: str

    def run_program(
        self, program: str, perturbation: Perturbation | None, seed: int, timeout_s: float | None
    ) -> RolloutResult:
        """Run `program` once in a fresh episode reset with `seed`, `perturbation` applied."""
        ...
