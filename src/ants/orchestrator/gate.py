"""The regression gate: one pure function that decides whether a rewrite replaces the incumbent.

Ported from System 1's per-case gate (`synthesizer` branch), moved from booleans to outcomes
(decision D9). Rule (`strict`): the candidate must be no worse than the incumbent on EVERY case
seen so far and better on at least one, so robustness never decreases.

- A case counts as passed only on `Outcome.SUCCESS`. An incumbent crash (`ERROR`) is not a pass,
  and a candidate crash on a case the incumbent passed is a regression.
- A case the candidate was not run on counts as not passed (a missing result never helps).
- `off` accepts every candidate; it exists only for the "ANTS without gate" ablation arm.

The mode is part of every decision, so each log line says which rule decided.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ants.contracts import Outcome, to_dict

GATE_MODES = ("strict", "off")


@dataclass(frozen=True)
class GateDecision:
    accepted: bool
    reason: str
    mode: str
    regressions: tuple[str, ...] = ()  # case ids the incumbent passed and the candidate did not
    improvements: tuple[str, ...] = ()  # case ids the candidate passes and the incumbent did not
    incumbent_passes: int = 0
    candidate_passes: int = 0
    cases: int = 0
    outcomes: Mapping[str, tuple[str, str]] = field(default_factory=dict)  # id -> (inc, cand)

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)


def _passed(outcome: Outcome | None) -> bool:
    return outcome is Outcome.SUCCESS


def gate(
    incumbent: Mapping[str, Outcome],
    candidate: Mapping[str, Outcome],
    mode: str = "strict",
) -> GateDecision:
    """Compare per-case outcomes on the incumbent's case set (acceptance cases plus F_n)."""
    if mode not in GATE_MODES:
        raise ValueError(f"gate mode must be one of {GATE_MODES}, got {mode!r}")
    cases = sorted(incumbent)
    regressions = tuple(c for c in cases if _passed(incumbent[c]) and not _passed(candidate.get(c)))
    improvements = tuple(
        c for c in cases if _passed(candidate.get(c)) and not _passed(incumbent[c])
    )
    base = {
        "mode": mode,
        "regressions": regressions,
        "improvements": improvements,
        "incumbent_passes": sum(_passed(incumbent[c]) for c in cases),
        "candidate_passes": sum(_passed(candidate.get(c)) for c in cases),
        "cases": len(cases),
        "outcomes": {
            c: (incumbent[c].value, candidate[c].value if c in candidate else "missing")
            for c in cases
        },
    }
    if mode == "off":
        return GateDecision(True, "gate off: every candidate is accepted", **base)
    if regressions:
        return GateDecision(False, f"regressed on {len(regressions)} case(s)", **base)
    if not improvements:
        return GateDecision(False, "no improvement over the incumbent", **base)
    return GateDecision(True, f"fixes {len(improvements)} case(s), no regression", **base)


def regression_gate(incumbent: Mapping[str, bool], candidate: Mapping[str, bool]) -> GateDecision:
    """System 1's boolean gate signature (`harden()` on branch `synthesizer`), on the outcome gate.

    True is a pass and False a failure; a missing candidate result still never passes. Kept so
    `harden()` and its tests run unchanged when `synthesizer` merges; new code calls `gate()`.
    """

    def to_outcomes(results: Mapping[str, bool]) -> dict[str, Outcome]:
        return {c: Outcome.SUCCESS if ok else Outcome.FAILURE for c, ok in results.items()}

    return gate(to_outcomes(incumbent), to_outcomes(candidate), "strict")
