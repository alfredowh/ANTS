"""The orchestrator's view of System 1: "given the incumbent and its failures, write a candidate".

`Synthesizer` is the only thing the loop needs from System 1. System 1's Muse generator
(`synthesizer/` on branch `synthesizer`) plugs in behind it with no loop change.

`PatchSynthesizer` is an OFFLINE TEST FIXTURE, not a synthesizer: it maps a failure category to a
fixed source patch, so the loop, gate and escalation can be tested without model tokens. Nothing
it produces is a result. `MOCK_WORLD_PATCHES` are patches the mock world rewards (see
`adversary/rollout/mock_backend.py`): a lower grasp defeats the slip, wider move tolerances help
against actuation noise; camera has no patch on purpose, so that failure stalls and escalates.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from ants.contracts import Constraint, Feedback, Policy


class Synthesizer(Protocol):
    def rewrite(
        self, incumbent: Policy, feedback: Sequence[Feedback], constraints: Sequence[Constraint]
    ) -> Policy | None:
        """A candidate that should satisfy every constraint, or None when the budget is spent."""
        ...


Patch = Callable[[str], str]


def _lower_grasp(code: str) -> str:
    return code.replace("pinch_height = 0.82 * bowl_h", "pinch_height = 0.4 * bowl_h")


def _wider_tolerances(code: str) -> str:
    return re.sub(
        r"tolerance=([0-9.]+|float\(stage\[5\]\))",
        lambda m: f"tolerance=2.0 * {m.group(1)}",
        code,
    )


MOCK_WORLD_PATCHES: Mapping[str, Patch] = {
    "physics": _lower_grasp,
    "actuation": _wider_tolerances,
}


@dataclasses.dataclass
class PatchSynthesizer:
    """Test fixture: applies the patch for each failing category not patched yet."""

    patches: Mapping[str, Patch] = dataclasses.field(default_factory=lambda: MOCK_WORLD_PATCHES)
    budget: int | None = None  # number of rewrites before it reports a spent budget
    calls: int = 0

    def rewrite(
        self, incumbent: Policy, feedback: Sequence[Feedback], constraints: Sequence[Constraint]
    ) -> Policy | None:
        if self.budget is not None and self.calls >= self.budget:
            return None
        self.calls += 1
        code = incumbent.code
        for fb in feedback:
            patch = self.patches.get(fb.case.category)
            if patch is not None:
                code = patch(code)
        return dataclasses.replace(
            incumbent,
            version=incumbent.version + 1,
            code=code,
            parent_version=incumbent.version,
            constraints=tuple(c.constraint_id for c in constraints),
            metadata={**incumbent.metadata, "synthesizer": "patch-fixture"},
        )
