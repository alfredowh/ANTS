"""Data shapes that cross the System 1 / System 2 / orchestrator boundaries.

Everything is a frozen dataclass and round-trips through JSON (`to_dict` / `from_dict`), so every
object can be logged and replayed. Flow per cycle:

    System 1 --Policy--> System 2 --AttackReport--> orchestrator --Feedback--> System 1
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum, StrEnum
from typing import Any

CONTRACTS_VERSION = "0.1"


def to_dict(obj: Any) -> Any:
    """JSON-ready form: dataclasses to dicts, enums to values, tuples to lists."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_dict(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Mapping):
        return {str(k): to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_dict(v) for v in obj]
    return obj


def _check_unit(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be in [0, 1], got {value}")


class Outcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"  # the task was not achieved (timeouts included)
    ERROR = "error"  # the generated code crashed; never counted as a task failure


class FailureMode(StrEnum):
    MISSED_OBJECT = "missed_object"
    GRASP_SLIP = "grasp_slip"
    COLLISION = "collision"
    OBJECT_DROPPED = "object_dropped"
    TIMEOUT = "timeout"
    WRONG_PLACEMENT = "wrong_placement"
    PROGRAM_ERROR = "program_error"


class BlameTarget(StrEnum):
    PROGRAM = "program"  # rewrite the code
    PERCEPTION = "perception"  # re-check what was extracted from the demonstration (DemoSpec)


@dataclass(frozen=True)
class Policy:
    """System 1's output: a program defining `run(robot, params)` plus its demo data."""

    policy_id: str  # stable across versions of one skill
    version: int
    task: str
    code: str
    params: Mapping[str, Any] = field(default_factory=dict)  # demo-derived values, JSON-able
    parent_version: int | None = None
    constraints: tuple[str, ...] = ()  # constraint ids this version claims to satisfy
    demo_id: str | None = None

    def __post_init__(self) -> None:
        if self.version < 0:
            raise ValueError(f"version must be >= 0, got {self.version}")

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Policy:
        return cls(
            **{
                **d,
                "params": dict(d.get("params", {})),
                "constraints": tuple(d.get("constraints", ())),
            }
        )


@dataclass(frozen=True)
class Perturbation:
    """One test case: a category, concrete parameter values, a severity and a seed."""

    category: str
    params: Mapping[str, float]
    severity: float  # 0 = nominal scene, 1 = edge of the allowed range
    seed: int
    rationale: str = ""

    def __post_init__(self) -> None:
        _check_unit("severity", self.severity)

    @property
    def key(self) -> str:
        """Content hash of what defines the scene (rationale excluded); used to dedupe cases."""
        payload = json.dumps(
            {"category": self.category, "params": dict(self.params), "seed": self.seed},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Perturbation:
        return cls(**{**d, "params": {k: float(v) for k, v in d["params"].items()}})


@dataclass(frozen=True)
class Event:
    """Something a primitive observed during a rollout, e.g. `grasp_slip` in phase `lift`."""

    t: float  # seconds since episode start
    kind: str
    phase: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Event:
        return cls(**{**d, "detail": dict(d.get("detail", {}))})


@dataclass(frozen=True)
class RolloutResult:
    outcome: Outcome
    metrics: Mapping[str, float] = field(default_factory=dict)
    events: tuple[Event, ...] = ()
    last_phase: str | None = None
    duration_s: float = 0.0
    error: str | None = None  # traceback summary when outcome is ERROR
    video_path: str | None = None
    keyframes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> RolloutResult:
        return cls(
            **{
                **d,
                "outcome": Outcome(d["outcome"]),
                "metrics": dict(d.get("metrics", {})),
                "events": tuple(Event.from_dict(e) for e in d.get("events", ())),
                "keyframes": tuple(d.get("keyframes", ())),
            }
        )


@dataclass(frozen=True)
class Failure:
    """The diagnosis of one failed rollout."""

    mode: FailureMode
    root_cause: str  # one causal sentence tied to the code
    confidence: float
    source: str = "rules"  # "model" or "rules"
    target: BlameTarget = BlameTarget.PROGRAM

    def __post_init__(self) -> None:
        _check_unit("confidence", self.confidence)

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Failure:
        return cls(
            **{
                **d,
                "mode": FailureMode(d["mode"]),
                "target": BlameTarget(d.get("target", BlameTarget.PROGRAM.value)),
            }
        )


@dataclass(frozen=True)
class Constraint:
    """A failure turned into one rule System 1 must satisfy from now on (ASPIRE skill entry)."""

    constraint_id: str
    failure_signature: str  # "<mode> | <category>": used to dedupe and to count stalls
    when_to_apply: str
    rule: str  # one imperative sentence
    target: BlameTarget = BlameTarget.PROGRAM
    code_sketch: str | None = None  # a hint, never a full patch
    evidence: tuple[str, ...] = ()  # attack ids, replayable

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Constraint:
        return cls(
            **{
                **d,
                "target": BlameTarget(d.get("target", BlameTarget.PROGRAM.value)),
                "evidence": tuple(d.get("evidence", ())),
            }
        )


@dataclass(frozen=True)
class AttackReport:
    """Everything System 2 returns to the orchestrator after one cycle."""

    attack_id: str
    policy_id: str
    version: int
    perturbation: Perturbation
    result: RolloutResult
    selector_draws: Mapping[str, float] = field(default_factory=dict)  # why this category
    failure: Failure | None = None
    constraint: Constraint | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> AttackReport:
        return cls(
            attack_id=d["attack_id"],
            policy_id=d["policy_id"],
            version=d["version"],
            perturbation=Perturbation.from_dict(d["perturbation"]),
            result=RolloutResult.from_dict(d["result"]),
            selector_draws=dict(d.get("selector_draws", {})),
            failure=Failure.from_dict(d["failure"]) if d.get("failure") else None,
            constraint=Constraint.from_dict(d["constraint"]) if d.get("constraint") else None,
        )


@dataclass(frozen=True)
class Feedback:
    """What the orchestrator forwards to System 1 after a failure on an acceptance case.

    Held-out cases never produce Feedback; that split is enforced by the orchestrator.
    """

    policy_id: str
    version: int  # the version that failed
    constraint: Constraint
    failure: Failure
    case: Perturbation
    rollout: RolloutResult

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Feedback:
        return cls(
            policy_id=d["policy_id"],
            version=d["version"],
            constraint=Constraint.from_dict(d["constraint"]),
            failure=Failure.from_dict(d["failure"]),
            case=Perturbation.from_dict(d["case"]),
            rollout=RolloutResult.from_dict(d["rollout"]),
        )

    @classmethod
    def from_report(cls, report: AttackReport) -> Feedback:
        if report.failure is None or report.constraint is None:
            raise ValueError(f"attack {report.attack_id} has no failure to feed back")
        return cls(
            policy_id=report.policy_id,
            version=report.version,
            constraint=report.constraint,
            failure=report.failure,
            case=report.perturbation,
            rollout=report.result,
        )
