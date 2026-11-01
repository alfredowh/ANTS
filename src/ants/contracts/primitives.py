"""Robot primitives: the only API a generated policy can call.

Names, parameters and result fields mirror the ASPIRE harness (`cap_harness.api.CapAPI` and
`cap_harness.contracts`, checked against the ASPIRE checkout) so the LIBERO backend is a thin
adapter. Differences from ASPIRE, on purpose:

- plain tuples instead of numpy arrays, so this module stays standard-library only; the adapter
  converts;
- only the result fields a policy or the diagnoser reads (ASPIRE also carries point clouds,
  observations and so on);
- `phase()` exists only in ANTS. It is an optional hint; nothing may depend on it.

Every primitive returns a result with `ok` and `error` instead of raising, so a policy can branch on
failure and the backend can log what happened.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Pose:
    """Position in metres and a unit quaternion (w, x, y, z) in a named frame (ASPIRE order)."""

    position: tuple[float, float, float]
    quaternion_wxyz: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0)
    frame: str = "robot_base"

    def offset(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> Pose:
        """Same orientation and frame, position shifted along the frame axes."""
        px, py, pz = self.position
        return Pose((px + x, py + y, pz + z), self.quaternion_wxyz, self.frame)


@dataclass(frozen=True)
class ApiError:
    code: str
    message: str
    details: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ObjectGeometry:
    """Where an object is and how big: `extents` are the full box sizes in metres."""

    pose: Pose
    extents: tuple[float, float, float]
    point_count: int | None = None


@dataclass(frozen=True)
class LocalizationResult:
    """`segmentation` is the backend's mask handle: pass it on to `generate_grasps` unchanged."""

    ok: bool
    geometry: ObjectGeometry | None = None
    segmentation: object | None = None
    error: ApiError | None = None
    diagnostics: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GraspCandidate:
    pose: Pose
    score: float
    width_m: float
    approach_distance_m: float = 0.0
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GraspSet:
    ok: bool
    grasps: Sequence[GraspCandidate] = ()
    error: ApiError | None = None
    diagnostics: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionResult:
    """Result of a motion or gripper command. `status` is ASPIRE's ExecutionStatus value
    ("success", "timeout", "planner_failed", ...) as a plain string."""

    ok: bool
    steps_executed: int = 0
    status: str | None = None
    terminated: bool = False
    truncated: bool = False
    error: ApiError | None = None
    diagnostics: Mapping[str, object] = field(default_factory=dict)


@runtime_checkable
class RobotAPI(Protocol):
    """What a policy receives. Backends (LIBERO via ASPIRE, mock) implement it.

    Policies get no simulator state, success predicate, imports or I/O: only these calls.
    """

    def phase(self, name: str) -> None:
        """ANTS only. Optional hint that a named step starts; never required, never trusted."""
        ...

    def localize_object(
        self,
        query: str,
        *,
        camera_name: str | None = None,
        target_frame: str | None = None,
    ) -> LocalizationResult: ...

    def generate_grasps(
        self,
        camera_name: str,
        mask: object,
        *,
        backend: str = "contact-graspnet",
        max_candidates: int = 5,
    ) -> GraspSet: ...

    def select_grasp(
        self, grasps: GraspSet, strategy: str = "top_down"
    ) -> GraspCandidate | None: ...

    def move_to_pose(
        self,
        target_pose: Pose,
        tolerance: float = 0.01,
        max_steps: int = 120,
        *,
        arm: str = "primary",
        strategy: object | None = None,
    ) -> ExecutionResult: ...

    def close_gripper(self, *, arm: str = "primary") -> ExecutionResult: ...

    def open_gripper(self, *, arm: str = "primary") -> ExecutionResult: ...
