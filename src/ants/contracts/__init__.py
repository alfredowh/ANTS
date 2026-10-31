"""Shared types: the only module both System 1 (synthesizer) and System 2 (adversary) import.

Everything here is plain dataclasses that round-trip through JSON, so runs can be logged,
cached and replayed. Frames are always named explicitly (``*_obj`` = in the frame of an object,
``robot_base`` = the robot base frame).
"""

from ants.contracts.types import (
    CallRecord,
    CaseSpec,
    Constraint,
    DemoSpec,
    EpisodeTrace,
    Keyframe,
    ObjectTrack,
    Perturbation,
    Policy,
    Skill,
    from_json,
    to_json,
)

__all__ = [
    "CallRecord",
    "CaseSpec",
    "Constraint",
    "DemoSpec",
    "EpisodeTrace",
    "Keyframe",
    "ObjectTrack",
    "Perturbation",
    "Policy",
    "Skill",
    "from_json",
    "to_json",
]
