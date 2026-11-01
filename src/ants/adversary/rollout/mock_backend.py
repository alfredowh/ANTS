"""Offline mock world for bowl-on-plate: a test fixture, not a simulator.

It implements the cap_harness calls a flat policy script uses (`get_task_context`,
`get_robot_state`, `localize_object`, `move_to_pose`, `close_gripper`, `open_gripper`, `Pose`) in
a kinematic toy scene, so the full System 2 cycle runs in tests without a GPU, ASPIRE or model
tokens. Each failure mechanism below is a modelling choice of ours, picked so that a specific
coding pattern defeats it. Nothing measured here is a result about robots; report only runs on
the cap_harness backend.

Mechanisms (all deterministic given the seed and the perturbation):
- pose: the bowl and plate move; localization reports where they are.
- size: objects scale; point clouds scale with them.
- camera: localization assumes the nominal camera, so a field-of-view change scales measured
  positions about the camera (each object shifts differently) and an offset shifts them all.
- lighting: the dark bowl is not found below a light threshold, the white plate above one.
- actuation: every move ends off target by seeded Gaussian noise, worse with latency.
- physics: a heavier bowl with less friction slips out of a grasp high on the wall once lifted.
A grasp holds only if the fingers close on the bowl wall; nothing tells the program whether it
did, so a policy must check that the bowl moved with the gripper.

Some mechanisms have a coding pattern that defeats them (grasping lower on the wall stops the
slip, a re-grasp after a failed check recovers a miss); others, such as a bowl too dark to
localize, are limits no program can fix, which is what escalation is for.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import SimpleNamespace

from ants.contracts import (
    Event,
    ExecutionResult,
    LocalizationResult,
    ObjectGeometry,
    Perturbation,
    Pose,
)

BOWL_RADIUS = 0.069  # nominal diameter 0.138 m, as the demo's object constants assume
BOWL_HEIGHT = 0.067
PLATE_RADIUS = 0.09
PLATE_HEIGHT = 0.015
BOWL_XY = (0.55, -0.12)
PLATE_XY = (0.50, 0.16)
START_EE = (0.40, 0.0, 0.30)
DOWN_WXYZ = (0.0, 1.0, 0.0, 0.0)  # gripper pointing down
GRASP_WINDOW = 0.02  # the wall must lie this close to the finger centre line (open width 8 cm)
ONTOP_TOLERANCE = 0.03  # LIBERO's on-top centre tolerance, scaled with the plate
SLIP_RATIO = 3.0  # mass_scale / friction_scale above which a high grasp slips
SECURE_GRASP = 0.5  # grasps below this fraction of the bowl height never slip
DARK_LIMIT, BRIGHT_LIMIT = 0.5, 1.35
CAMERA_XY = (1.1, 0.0)  # agent-view camera, in front of the table
CAMERA_SHIFT_GAIN, CAMERA_SCALE_PER_DEG = 0.6, 0.01
LATENCY_GAIN = 0.5


def _params(p: Perturbation | None, category: str) -> Mapping[str, float]:
    return p.params if p is not None and p.category == category else {}


def _wall_radius(radius: float, height: float, z_rel: float) -> float:
    """The bowl flares from 55% of the rim radius at the base to 100% at the rim."""
    return radius * (0.55 + 0.45 * min(max(z_rel / height, 0.0), 1.0))


@dataclass(frozen=True)
class MockLocalization(LocalizationResult):
    """cap_harness localization results also carry the segmented point cloud."""

    point_cloud: SimpleNamespace | None = None


@dataclass
class MockEpisode:
    perturbation: Perturbation | None
    seed: int
    events: list[Event] = field(default_factory=list)

    def __post_init__(self) -> None:
        p = self.perturbation
        self.rng = random.Random(f"{self.seed}:{p.key if p else 'nominal'}")
        pose, size = _params(p, "pose"), _params(p, "size")
        cam, light = _params(p, "camera"), _params(p, "lighting")
        act, phys = _params(p, "actuation"), _params(p, "physics")
        self.bowl_xy = [BOWL_XY[0] + pose.get("dx_m", 0.0), BOWL_XY[1] + pose.get("dy_m", 0.0)]
        self.bowl_z = 0.0
        self.bowl_r = BOWL_RADIUS * size.get("bowl_scale", 1.0)
        self.bowl_h = BOWL_HEIGHT * size.get("bowl_scale", 1.0)
        self.plate_xy = PLATE_XY
        self.plate_r = PLATE_RADIUS * size.get("plate_scale", 1.0)
        self.plate_top = PLATE_HEIGHT * size.get("plate_scale", 1.0)
        self.ontop_tol = ONTOP_TOLERANCE * size.get("plate_scale", 1.0)
        self.cam_scale = 1.0 + CAMERA_SCALE_PER_DEG * cam.get("fovy_delta_deg", 0.0)
        self.cam_shift_y = CAMERA_SHIFT_GAIN * cam.get("dy_m", 0.0)
        self.light = light.get("diffuse_scale", 1.0)
        self.noise = act.get("noise_std", 0.0) * (
            1.0 + LATENCY_GAIN * act.get("latency_steps", 0.0)
        )
        self.slips = phys.get("mass_scale", 1.0) / phys.get("friction_scale", 1.0) > SLIP_RATIO
        self.ee = list(START_EE)
        self.ee_q = DOWN_WXYZ
        self.gripper_open = True
        self.held_offset: tuple[float, float, float] | None = None  # bowl centre minus gripper
        self.released_on_plate = False
        self.calls = 0

    # --- bookkeeping ---------------------------------------------------------------------
    def _log(self, tool: str, ok: bool, status: str, **detail: object) -> None:
        self.calls += 1
        self.events.append(
            Event(
                float(self.calls),
                "call",
                detail={"tool": tool, "ok": ok, "status": status, **detail},
            )
        )

    def _event(self, kind: str, **detail: object) -> None:
        self.events.append(Event(float(self.calls), kind, detail=detail))

    # --- the API a policy sees -----------------------------------------------------------
    def api(self) -> Mapping[str, object]:
        return {
            "Pose": Pose,
            "get_task_context": lambda: SimpleNamespace(language="put the bowl on the plate"),
            "get_robot_state": self.get_robot_state,
            "localize_object": self.localize_object,
            "move_to_pose": self.move_to_pose,
            "close_gripper": self.close_gripper,
            "open_gripper": self.open_gripper,
        }

    def get_robot_state(self) -> SimpleNamespace:
        return SimpleNamespace(
            base_frame="robot_base",
            end_effector_poses={"primary": Pose(tuple(self.ee), self.ee_q)},
            gripper_positions={"primary": 0.04 if self.gripper_open else 0.0},
        )

    def localize_object(
        self, query: str, *, camera_name: str | None = None, target_frame: str | None = None
    ) -> LocalizationResult:
        q = query.lower()
        if "bowl" in q:
            found = self.light >= DARK_LIMIT
            centre, points = self._bowl_points() if found else (None, [])
            extents = (2 * self.bowl_r, 2 * self.bowl_r, self.bowl_h)
        elif "plate" in q:
            found = self.light <= BRIGHT_LIMIT
            centre, points = self._plate_points() if found else (None, [])
            extents = (2 * self.plate_r, 2 * self.plate_r, self.plate_top)
        else:
            found, centre, points, extents = False, None, [], (0.0, 0.0, 0.0)
        self._log("localize_object", found, "success" if found else "not_found", query=query)
        if not found:
            return LocalizationResult(ok=False)
        shifted = [self._as_measured(pt) for pt in points]
        geometry = ObjectGeometry(Pose(self._as_measured(centre)), extents, len(shifted))
        return MockLocalization(
            ok=True, geometry=geometry, point_cloud=SimpleNamespace(points=shifted)
        )

    def _as_measured(self, point: tuple[float, float, float]) -> tuple[float, float, float]:
        x, y, z = point
        cx, cy = CAMERA_XY
        return (
            cx + (x - cx) * self.cam_scale,
            cy + (y - cy) * self.cam_scale + self.cam_shift_y,
            z,
        )

    def _bowl_points(self):
        cx, cy = self.bowl_xy
        pts = []
        for k in range(11):
            z_rel = self.bowl_h * k / 10
            r = _wall_radius(self.bowl_r, self.bowl_h, z_rel)
            for a in range(32):
                ang = 2 * math.pi * a / 32
                pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang), self.bowl_z + z_rel))
        return (cx, cy, self.bowl_z + self.bowl_h / 2), pts

    def _plate_points(self):
        cx, cy = self.plate_xy
        pts = [(cx, cy, self.plate_top)]
        for ring in (0.33, 0.66, 1.0):
            for a in range(24):
                ang = 2 * math.pi * a / 24
                for z in (0.0, self.plate_top):
                    pts.append(
                        (
                            cx + ring * self.plate_r * math.cos(ang),
                            cy + ring * self.plate_r * math.sin(ang),
                            z,
                        )
                    )
        return (cx, cy, self.plate_top / 2), pts

    def move_to_pose(
        self,
        target_pose: Pose,
        tolerance: float = 0.01,
        max_steps: int = 120,
        *,
        arm: str = "primary",
        strategy: object | None = None,
    ) -> ExecutionResult:
        tx, ty, tz = (float(v) for v in target_pose.position)
        err = [self.rng.gauss(0.0, self.noise) for _ in range(3)] if self.noise > 0 else [0.0] * 3
        self.ee = [tx + err[0], ty + err[1], max(tz + err[2], 0.0)]
        self.ee_q = tuple(target_pose.quaternion_wxyz)
        if self.held_offset is not None:
            if self.slips and -self.held_offset[2] > SECURE_GRASP * self.bowl_h:
                self._event("object_dropped", reason="slip")
                self.held_offset = None
                self.bowl_z = 0.0
            else:
                ox, oy, oz = self.held_offset
                self.bowl_xy = [self.ee[0] + ox, self.ee[1] + oy]
                self.bowl_z = self.ee[2] + oz
        miss = math.sqrt(sum(e * e for e in err))
        ok = miss <= tolerance
        self._log(
            "move_to_pose",
            ok,
            "success" if ok else "timeout",
            steps=max_steps if not ok else max_steps // 2,
            error_m=round(miss, 4),
        )
        return ExecutionResult(
            ok=ok,
            steps_executed=max_steps if not ok else max_steps // 2,
            status="success" if ok else "timeout",
        )

    def close_gripper(self, *, arm: str = "primary") -> ExecutionResult:
        self.gripper_open = False
        gx, gy, gz = self.ee
        d = math.hypot(gx - self.bowl_xy[0], gy - self.bowl_xy[1])
        z_rel = gz - self.bowl_z
        on_wall = abs(d - _wall_radius(self.bowl_r, self.bowl_h, z_rel)) <= GRASP_WINDOW
        if on_wall and 0.3 * self.bowl_h <= z_rel <= self.bowl_h + 0.005:
            self.held_offset = (self.bowl_xy[0] - gx, self.bowl_xy[1] - gy, self.bowl_z - gz)
        else:
            self._event(
                "grasp_miss",
                distance_from_wall=round(d - _wall_radius(self.bowl_r, self.bowl_h, z_rel), 4),
            )
        self._log("close_gripper", True, "success")
        return ExecutionResult(ok=True, steps_executed=20, status="success")

    def open_gripper(self, *, arm: str = "primary") -> ExecutionResult:
        self.gripper_open = True
        if self.held_offset is not None:
            self.held_offset = None
            off = math.hypot(self.bowl_xy[0] - self.plate_xy[0], self.bowl_xy[1] - self.plate_xy[1])
            self.released_on_plate = off <= self.ontop_tol
            self.bowl_z = self.plate_top if off <= self.plate_r else 0.0
            self._event("released", off_centre_m=round(off, 4))
        self._log("open_gripper", True, "success")
        return ExecutionResult(ok=True, steps_executed=20, status="success")

    # --- evaluation, never visible to the policy -----------------------------------------
    def success(self) -> bool:
        return self.released_on_plate and self.held_offset is None

    def metrics(self) -> Mapping[str, float]:
        return {
            "bowl_plate_xy_m": round(
                math.hypot(self.bowl_xy[0] - self.plate_xy[0], self.bowl_xy[1] - self.plate_xy[1]),
                4,
            ),
            "primitive_calls": float(self.calls),
        }


class MockBackend:
    name = "mock"

    def episode(self, perturbation: Perturbation | None, seed: int) -> MockEpisode:
        return MockEpisode(perturbation, seed)
