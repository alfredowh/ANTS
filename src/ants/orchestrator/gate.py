"""Per-case regression gate: a candidate is accepted only if it never does worse than the incumbent.

`incumbent` and `candidate` map case id -> success on every case seen so far. The gate rejects
when the candidate fails any case the incumbent passes (a regression), or when it was not
evaluated on a case the incumbent was (a missing result counts as a failure).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GateDecision:
    accepted: bool
    reason: str
    regressions: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    incumbent_passes: int = 0
    candidate_passes: int = 0
    cases: int = 0


def regression_gate(incumbent: dict[str, bool], candidate: dict[str, bool]) -> GateDecision:
    regressions = [c for c, ok in incumbent.items() if ok and not candidate.get(c, False)]
    improvements = [c for c, ok in candidate.items() if ok and not incumbent.get(c, False)]
    inc, cand = sum(incumbent.values()), sum(candidate.values())
    base = {"incumbent_passes": inc, "candidate_passes": cand, "cases": len(incumbent)}
    if regressions:
        return GateDecision(False, f"regressed on {len(regressions)} case(s)", regressions, **base)
    if not improvements:
        return GateDecision(False, "no improvement over the incumbent", [], [], **base)
    return GateDecision(
        True, f"fixes {len(improvements)} case(s), no regression", [], improvements, **base
    )
