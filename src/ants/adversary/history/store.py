"""Failure history: System 2's memory of every attack.

An append-only log (JSONL when a path is given) of which policy version was attacked with which
perturbation, the outcome and the diagnosed signature. Two things are read from it:

- per-category counts for one policy version, which feed the selector (program errors count as
  neither failure nor success, so broken code never inflates the statistics);
- every perturbation that ever caused a failure, which the regression gate replays.

Counts are per policy version, so a new version starts fresh while the log keeps everything.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ants.adversary.planner.selector import CategoryCounts
from ants.contracts import Outcome, Perturbation, to_dict


def policy_key(policy_id: str, version: int) -> str:
    return f"{policy_id}@v{version}"


@dataclass(frozen=True)
class AttackRecord:
    attack_id: str
    policy: str  # policy_key(policy_id, version)
    perturbation: Perturbation
    outcome: Outcome
    failure_signature: str | None = None
    failure_mode: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> AttackRecord:
        return cls(
            **{
                **d,
                "perturbation": Perturbation.from_dict(d["perturbation"]),
                "outcome": Outcome(d["outcome"]),
            }
        )


class FailureHistory:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.records: list[AttackRecord] = []
        if path is not None and path.exists():
            with path.open(encoding="utf-8") as f:
                self.records = [
                    AttackRecord.from_dict(json.loads(line)) for line in f if line.strip()
                ]

    def append(self, record: AttackRecord) -> None:
        self.records.append(record)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")

    def counts(self, policy: str, categories: Iterable[str]) -> dict[str, CategoryCounts]:
        failures = {c: 0 for c in categories}
        successes = dict(failures)
        for r in self.records:
            if r.policy != policy or r.perturbation.category not in failures:
                continue
            if r.outcome is Outcome.FAILURE:
                failures[r.perturbation.category] += 1
            elif r.outcome is Outcome.SUCCESS:
                successes[r.perturbation.category] += 1
        return {c: CategoryCounts(failures[c], successes[c]) for c in failures}

    def discovered_failures(self) -> list[Perturbation]:
        """Every perturbation that ever made any version fail, deduplicated, in discovery order."""
        seen: dict[str, Perturbation] = {}
        for r in self.records:
            if r.outcome is Outcome.FAILURE and r.perturbation.key not in seen:
                seen[r.perturbation.key] = r.perturbation
        return list(seen.values())

    def recent(self, policy: str, category: str, n: int = 5) -> list[AttackRecord]:
        """The last `n` attacks on one version in one category (context for the proposer)."""
        hits = [
            r for r in self.records if r.policy == policy and r.perturbation.category == category
        ]
        return hits[-n:]

    def __len__(self) -> int:
        return len(self.records)
