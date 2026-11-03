"""The orchestrator's view of System 1: "given the incumbent and its failures, write a candidate".

`Synthesizer` is the only thing the loop needs from System 1. `GenerateSynthesizer` adapts System
1's repair step (its `Generate` callable, e.g. `MuseOrchestrator` on branch `synthesizer`) to it,
with no loop change.

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
from pathlib import Path
from typing import Any, Protocol

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


#: System 1's repair-step signature (`harden()`'s `Generate` slot on branch `synthesizer`, filled by
#: `MuseOrchestrator`): (incumbent program file, all constraints, failure feedback dicts) ->
#: (candidate program file, tokens spent), or None when its budget is spent or the model failed.
Generate = Callable[[Path, list[Constraint], list[dict]], "tuple[Path, int] | None"]


def feedback_dict(fb: Feedback) -> dict[str, Any]:
    """One Feedback as the dict System 1's repair prompt expects (its `aspire_harness.feedback()`).

    Starts from the backend's `details["feedback"]` (termination reason, error, stdout tail,
    program result, final gripper: the cap_harness backend writes the same keys System 1's
    rollout does), then adds the first failed primitive call and System 2's diagnosis. It carries
    the perturbation category, never its parameters, and nothing about the success predicate.
    """
    out: dict[str, Any] = dict(fb.rollout.details.get("feedback") or {})
    out.setdefault("termination_reason", fb.rollout.outcome.value)
    if fb.rollout.error and "error" not in out:
        out["error"] = fb.rollout.error
    failed = next(
        (e.detail for e in fb.rollout.events if e.kind == "call" and e.detail.get("ok") is False),
        None,
    )
    if failed is not None:
        out["failed_call"] = dict(failed)
    if fb.rollout.last_phase:
        out["last_phase"] = fb.rollout.last_phase
    out["case_id"] = fb.test_case.case_id
    out["category"] = fb.case.category
    out["diagnosis"] = {
        "mode": fb.failure.mode,
        "root_cause": fb.failure.root_cause,
        "confidence": fb.failure.confidence,
        "source": fb.failure.source,
    }
    return out


@dataclasses.dataclass
class GenerateSynthesizer:
    """Adapter: any System 1 `Generate` callable (e.g. `MuseOrchestrator`) as a `Synthesizer`.

    Writes the incumbent to `workdir/v<N>.py`, calls `generate`, reads the candidate program back
    into a `Policy` of the next version. Duck-typed on the callable, so the orchestrator never
    imports System 1's internals. Tokens per rewrite are kept in `tokens` and in the candidate's
    metadata, so the loop can log the cost of each cycle.
    """

    generate: Generate
    workdir: Path
    name: str = "generate"
    tokens: list[int] = dataclasses.field(default_factory=list)

    def rewrite(
        self, incumbent: Policy, feedback: Sequence[Feedback], constraints: Sequence[Constraint]
    ) -> Policy | None:
        self.workdir.mkdir(parents=True, exist_ok=True)
        path = self.workdir / f"v{incumbent.version}.py"
        path.write_text(incumbent.code, encoding="utf-8")
        out = self.generate(path, list(constraints), [feedback_dict(f) for f in feedback])
        if out is None:
            return None
        candidate, tokens = out
        self.tokens.append(int(tokens))
        return dataclasses.replace(
            incumbent,
            version=incumbent.version + 1,
            code=Path(candidate).read_text(encoding="utf-8"),
            parent_version=incumbent.version,
            constraints=tuple(c.constraint_id for c in constraints),
            metadata={
                **incumbent.metadata,
                "synthesizer": self.name,
                "tokens": int(tokens),
                "tokens_total": sum(self.tokens),
                "candidate_path": str(candidate),
            },
        )
