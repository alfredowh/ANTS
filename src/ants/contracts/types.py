"""Data shapes that cross the System 1 / System 2 / orchestrator boundaries.

Everything is a frozen dataclass and round-trips through JSON (`to_dict` / `from_dict`), so every
object can be logged and replayed. Flow per cycle:

    System 1 --Policy--> System 2 --AttackReport--> orchestrator --Feedback--> System 1

Skills (code functions and guidance rules) are proposed by System 1 and admitted to the library by
the orchestrator only after a policy using them passes the gate.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum, StrEnum
from typing import Any

CONTRACTS_VERSION = "0.2"

FAILURE_SOURCES = ("model", "rules", "human")  # who produced a Failure diagnosis


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
    """Recommended vocabulary, not a closed set: `Failure.mode` is any string, so a new task can
    add modes without a contract change. PROGRAM_ERROR is the one value with special meaning."""

    MISSED_OBJECT = "missed_object"
    GRASP_SLIP = "grasp_slip"
    COLLISION = "collision"
    OBJECT_DROPPED = "object_dropped"
    TIMEOUT = "timeout"
    WRONG_PLACEMENT = "wrong_placement"
    PROGRAM_ERROR = "program_error"


def failure_signature(category: str, primitive: str, status: str) -> str:
    """The one failure-signature format: `<category>:<failing primitive>:<status>`.

    Stall counting, memory retrieval and escalation all key on it, so both systems build it here.
    Example: `size:move_to_pose:timeout`. With no failing call, pass the termination reason as
    `primitive` and `not_scored` as `status`.
    """
    parts = (category, primitive, status)
    if any(not p or ":" in p for p in parts):
        raise ValueError(f"signature parts must be non-empty and contain no ':', got {parts}")
    return ":".join(parts)


class BlameTarget(StrEnum):
    PROGRAM = "program"  # rewrite the code
    PERCEPTION = "perception"  # re-check what was extracted from the demonstration (DemoSpec)
    SKILL = "skill"  # fix a library skill; affects every policy that uses it


class SkillKind(StrEnum):
    CODE = "code"  # a verified function over RobotAPI primitives, inlined into policy code
    GUIDANCE = "guidance"  # a rule the generator reads in context


@dataclass(frozen=True)
class SkillRef:
    skill_id: str
    version: int


@dataclass(frozen=True)
class Skill:
    """One library entry. Retrieved by System 1; admitted only through the regression gate."""

    skill_id: str
    version: int
    kind: SkillKind
    name: str  # function name for CODE, short title for GUIDANCE
    when_to_apply: str
    body: str  # Python source of one function for CODE, the rule text for GUIDANCE
    evidence: tuple[str, ...] = ()  # attack ids or policy versions that passed the gate with it
    source_constraints: tuple[str, ...] = ()  # constraint ids this skill generalises
    help_count: int = 0  # times a policy using it passed the gate; drives retrieval and decay

    def __post_init__(self) -> None:
        if self.version < 0 or self.help_count < 0:
            raise ValueError("version and help_count must be >= 0")
        if not self.body.strip():
            raise ValueError(f"skill {self.skill_id} has an empty body")

    @property
    def ref(self) -> SkillRef:
        return SkillRef(self.skill_id, self.version)

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Skill:
        return cls(
            **{
                **d,
                "kind": SkillKind(d["kind"]),
                "evidence": tuple(d.get("evidence", ())),
                "source_constraints": tuple(d.get("source_constraints", ())),
            }
        )


@dataclass(frozen=True)
class Policy:
    """System 1's output: a program (see `entry_format`) plus its demo data."""

    policy_id: str  # stable across versions of one skill
    version: int
    task: str
    code: str
    params: Mapping[str, Any] = field(default_factory=dict)  # demo-derived values, JSON-able
    parent_version: int | None = None
    constraints: tuple[str, ...] = ()  # constraint ids this version claims to satisfy
    skills_used: tuple[SkillRef, ...] = ()  # library skills inlined in `code` or read as guidance
    demo_id: str | None = None
    # False = outcomes can vary run to run, so the gate must use several rollouts per case.
    deterministic: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)  # model, prompt hash, tokens, ...
    # (min, max) per key of `params` that is worth attacking; System 2 stays inside it.
    attack_ranges: Mapping[str, tuple[float, float]] = field(default_factory=dict)
    # Open string. "run_function": `def run(robot, params)`. "script": top-level code that sets
    # a top-level `result`; the backend wraps it.
    entry_format: str = "run_function"

    def __post_init__(self) -> None:
        if self.version < 0:
            raise ValueError(f"version must be >= 0, got {self.version}")
        for name, (lo, hi) in self.attack_ranges.items():
            if lo > hi:
                raise ValueError(f"attack_ranges[{name!r}] has min {lo} > max {hi}")

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Policy:
        return cls(
            **{
                **d,
                "params": dict(d.get("params", {})),
                "metadata": dict(d.get("metadata", {})),
                "attack_ranges": {
                    k: (float(r[0]), float(r[1])) for k, r in d.get("attack_ranges", {}).items()
                },
                "constraints": tuple(d.get("constraints", ())),
                "skills_used": tuple(SkillRef(**s) for s in d.get("skills_used", ())),
            }
        )


@dataclass(frozen=True)
class Perturbation:
    """One test case: a category, concrete parameter values, a severity and a seed."""

    category: str
    params: Mapping[str, float]
    severity: float  # 0 = nominal scene, 1 = edge of the allowed range
    seed: int | None = None  # None when the test case carries the seed
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


class Split(StrEnum):
    """Acceptance cases tune and gate; held-out cases only report and never reach System 1."""

    ACCEPTANCE = "acceptance"
    HELD_OUT = "held_out"


@dataclass(frozen=True)
class CaseSpec:
    """One test case: task, seed and perturbations, with its split visible in every log."""

    case_id: str
    suite: str
    task_id: int
    seed: int
    split: Split
    perturbations: tuple[Perturbation, ...] = ()

    @property
    def held_out(self) -> bool:
        return self.split is Split.HELD_OUT

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> CaseSpec:
        return cls(
            **{
                **d,
                "split": Split(d["split"]),
                "perturbations": tuple(
                    Perturbation.from_dict(p) for p in d.get("perturbations", ())
                ),
            }
        )


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
    details: Mapping[str, Any] = field(default_factory=dict)  # backend-specific trace, JSON-able

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
                "details": dict(d.get("details", {})),
            }
        )


@dataclass(frozen=True)
class Failure:
    """The diagnosis of one failed rollout."""

    mode: str  # open string; see FailureMode for the recommended vocabulary
    root_cause: str  # one causal sentence tied to the code
    confidence: float
    source: str = "rules"  # one of FAILURE_SOURCES
    target: BlameTarget = BlameTarget.PROGRAM

    def __post_init__(self) -> None:
        _check_unit("confidence", self.confidence)
        if self.source not in FAILURE_SOURCES:
            raise ValueError(f"source must be one of {FAILURE_SOURCES}, got {self.source!r}")

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Failure:
        return cls(
            **{
                **d,
                "mode": str(d["mode"]),
                "target": BlameTarget(d.get("target", BlameTarget.PROGRAM.value)),
            }
        )


@dataclass(frozen=True)
class Constraint:
    """A failure turned into one rule System 1 must satisfy from now on (ASPIRE skill entry)."""

    constraint_id: str
    failure_signature: str  # from failure_signature(): "<category>:<primitive>:<status>"
    when_to_apply: str
    rule: str  # one imperative sentence
    target: BlameTarget = BlameTarget.PROGRAM
    code_sketch: str | None = None  # a hint, never a full patch
    evidence: tuple[str, ...] = ()  # attack ids, replayable
    skill: SkillRef | None = None  # the blamed skill when target is SKILL
    check_code: str | None = None  # runnable precondition (a Python expression or function body)
    phase: str | None = None  # the policy stage it applies to; None means the whole program

    def __post_init__(self) -> None:
        if (self.target is BlameTarget.SKILL) != (self.skill is not None):
            raise ValueError("skill must be set exactly when target is SKILL")

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Constraint:
        return cls(
            **{
                **d,
                "target": BlameTarget(d.get("target", BlameTarget.PROGRAM.value)),
                "evidence": tuple(d.get("evidence", ())),
                "skill": SkillRef(**d["skill"]) if d.get("skill") else None,
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

    Held-out cases never produce Feedback. The orchestrator enforces the split; as a second line
    of defence, a Feedback built from a held-out `test_case` raises.
    """

    policy_id: str
    version: int  # the version that failed
    constraint: Constraint
    failure: Failure
    case: Perturbation
    rollout: RolloutResult
    details: Mapping[str, Any] = field(default_factory=dict)
    test_case: CaseSpec | None = None  # the suite case the failure came from, when known

    def __post_init__(self) -> None:
        if self.test_case is not None and self.test_case.held_out:
            raise ValueError(f"held-out case {self.test_case.case_id} cannot produce Feedback")

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
            details=dict(d.get("details", {})),
            test_case=CaseSpec.from_dict(d["test_case"]) if d.get("test_case") else None,
        )

    @classmethod
    def from_report(cls, report: AttackReport, test_case: CaseSpec | None = None) -> Feedback:
        if report.failure is None or report.constraint is None:
            raise ValueError(f"attack {report.attack_id} has no failure to feed back")
        return cls(
            policy_id=report.policy_id,
            version=report.version,
            constraint=report.constraint,
            failure=report.failure,
            case=report.perturbation,
            rollout=report.result,
            test_case=test_case,
        )
