"""Contract dataclasses (see docs/synthesizer/discussion.md §7 and docs/synthesizer/skills.md)."""

from __future__ import annotations

import dataclasses
import json
import types
import typing
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

KeyframeKind = Literal["approach", "grasp", "lift", "transport", "release", "retreat"]
PolicyKind = Literal["program", "agent", "monitored_program"]
SkillStatus = Literal["candidate", "verified", "deprecated"]


@dataclass
class ObjectTrack:
    """One object seen in the demonstration.

    Attributes:
        name: role or label, e.g. "bowl".
        poses_world: per keyframe index, position (x, y, z) in metres in the world/table frame.
    """

    name: str
    poses_world: dict[int, tuple[float, float, float]] = field(default_factory=dict)


@dataclass
class Keyframe:
    """A moment of the demonstration where the interaction changes."""

    t_s: float
    kind: KeyframeKind
    anchor: str | None = None  # object the following segment is expressed relative to


@dataclass
class DemoSpec:
    """System 1 perception output: what one demonstration says, in checkable form.

    Attributes:
        source: "libero_demo:<suite>/<task>/<demo>" or "phone:<clip>".
        task_text: the instruction.
        objects: tracked objects.
        keyframes: ordered keyframes.
        ee_path_obj: per segment name, the gripper/hand path in the frame of its anchor object,
            as a list of (x, y, z) in metres.
        aperture: gripper or pinch aperture over time, normalised 0..1, as (t_s, value) pairs.
        steps: the step list, e.g. ["grasp bowl rim", "place on plate centre"].
        quality: extraction quality scores in 0..1; low values trigger escalation.
    """

    source: str
    task_text: str
    objects: list[ObjectTrack] = field(default_factory=list)
    keyframes: list[Keyframe] = field(default_factory=list)
    ee_path_obj: dict[str, list[tuple[float, float, float]]] = field(default_factory=dict)
    aperture: list[tuple[float, float]] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    quality: dict[str, float] = field(default_factory=dict)


@dataclass
class Policy:
    """One candidate or accepted policy version (System 1 output).

    ``deterministic`` tells the regression gate whether one rollout per case is enough
    (a program) or whether it needs several seeds per case (an agent in the loop).
    """

    policy_id: str
    kind: PolicyKind
    code: str
    deterministic: bool = True
    parent_id: str | None = None
    spec_ref: str | None = None
    constraints_used: list[str] = field(default_factory=list)
    skills_used: list[str] = field(default_factory=list)
    model: str = ""
    prompt_hash: str = ""
    tokens: int = 0


@dataclass
class Constraint:
    """A rule learned from a failure: the only thing System 2 sends to System 1."""

    constraint_id: str
    failure_signature: str
    when_to_apply: str
    rule: str
    check_code: str | None = None
    evidence: list[str] = field(default_factory=list)


@dataclass
class Perturbation:
    """One perturbation of a test case; ``severity`` is normalised to 0..1 and clamped in code."""

    category: str  # pose | physics | clutter | camera | lighting | occlusion | actuation
    params: dict[str, float] = field(default_factory=dict)
    severity: float = 0.0


@dataclass
class CaseSpec:
    """One test case: task, seed, perturbations; ``split`` keeps acceptance and held-out apart."""

    case_id: str
    suite: str
    task_id: int
    seed: int
    split: Literal["acceptance", "held_out"]
    perturbations: list[Perturbation] = field(default_factory=list)


@dataclass
class CallRecord:
    """One primitive call in an episode, as the harness traced it."""

    name: str
    ok: bool
    failure_code: str | None = None
    duration_s: float = 0.0


@dataclass
class EpisodeTrace:
    """What one rollout did: the same record for every kind of policy runner."""

    case_id: str
    policy_id: str
    program_ok: bool
    task_success: bool
    termination_reason: str
    calls: list[CallRecord] = field(default_factory=list)
    error: str | None = None
    run_dir: str | None = None
    model_calls: int = 0
    tokens: int = 0
    wall_s: float = 0.0


@dataclass
class Skill:
    """A reusable, verified unit of behaviour (docs/synthesizer/skills.md §1)."""

    skill_id: str
    name: str
    signature: str
    success_predicate: str
    precondition: str
    code: str
    description: str = ""
    envelope: dict[str, list[float]] = field(default_factory=dict)  # param -> [min, max] tested
    evidence: list[str] = field(default_factory=list)  # run ids
    constraints: list[str] = field(default_factory=list)
    version: int = 1
    parent_id: str | None = None
    status: SkillStatus = "candidate"
    help_count: int = 0
    last_used: str | None = None


def to_json(obj: Any) -> str:
    """Serialise a contract dataclass (or a list of them) to JSON."""
    return json.dumps(
        dataclasses.asdict(obj) if dataclasses.is_dataclass(obj) else obj, sort_keys=True
    )


T = TypeVar("T")


def _build(tp: Any, value: Any) -> Any:
    if value is None:
        return None
    origin = typing.get_origin(tp)
    if origin in (typing.Union, types.UnionType):
        inner = [a for a in typing.get_args(tp) if a is not type(None)]
        return _build(inner[0], value) if inner else value
    if dataclasses.is_dataclass(tp):
        hints = typing.get_type_hints(tp)
        return tp(**{k: _build(hints[k], v) for k, v in value.items() if k in hints})
    if origin is list:
        (arg,) = typing.get_args(tp)
        return [_build(arg, v) for v in value]
    if origin is dict:
        key_tp, val_tp = typing.get_args(tp)
        return {_build(key_tp, k): _build(val_tp, v) for k, v in value.items()}
    if origin is tuple:
        return tuple(value)
    if tp is int and isinstance(value, str):
        return int(value)  # JSON object keys are strings
    return value


def from_json(cls: type[T], text: str) -> T:
    """Rebuild a contract dataclass from :func:`to_json` output."""
    return _build(cls, json.loads(text))
