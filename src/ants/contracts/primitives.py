"""Robot primitives: the only API a generated policy can call.

Primitive names follow the ASPIRE harness (localize_object, generate_grasps, select_grasp,
move_to_pose, close_gripper). Signatures and result types are ours (v0) and still under review.
Every primitive returns a typed result with a status instead of raising, so a policy can branch on
failure and the backend can log what happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Pose:
    """Position in metres (world frame) and orientation as a unit quaternion (x, y, z, w)."""

    position: tuple[float, float, float]
    orientation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)

    def offset(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> Pose:
        """Same orientation, position shifted in the world frame."""
        px, py, pz = self.position
        return Pose((px + x, py + y, pz + z), self.orientation)


@dataclass(frozen=True)
class ObjectEstimate:
    name: str
    ok: bool
    pose: Pose | None = None
    confidence: float = 0.0


@dataclass(frozen=True)
class Grasp:
    pose: Pose
    pre_pose: Pose
    score: float = 0.0


@dataclass(frozen=True)
class MotionResult:
    ok: bool
    reason: str = ""


@dataclass(frozen=True)
class GripperResult:
    ok: bool
    holding: bool = False
    width: float = 0.0


@runtime_checkable
class RobotAPI(Protocol):
    """What a policy's `run(robot, params)` receives. Backends (LIBERO, mock) implement it.

    Policies get no simulator state, success predicate, imports or I/O: only these calls.
    """

    def phase(self, name: str) -> None:
        """Mark the start of a named step; the last phase reached is reported on failure."""
        ...

    def localize_object(self, name: str) -> ObjectEstimate: ...

    def generate_grasps(self, target: ObjectEstimate) -> tuple[Grasp, ...]: ...

    def select_grasp(self, grasps: tuple[Grasp, ...]) -> Grasp | None: ...

    def move_to_pose(self, pose: Pose) -> MotionResult: ...

    def close_gripper(self, force: float) -> GripperResult: ...

    def open_gripper(self) -> GripperResult: ...
