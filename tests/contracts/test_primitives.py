import inspect

from ants.contracts import (
    ApiError,
    ExecutionResult,
    GraspCandidate,
    GraspSet,
    LocalizationResult,
    ObjectGeometry,
    PointCloud,
    Pose,
    RobotAPI,
    RobotState,
    TaskContext,
)


class FakeRobot:
    def __init__(self) -> None:
        self.phases: list[str] = []

    def phase(self, name: str) -> None:
        self.phases.append(name)

    def get_task_context(self) -> TaskContext:
        return TaskContext("libero", 0, "bowl_on_plate", "put the bowl on the plate", "pick_place")

    def get_robot_state(self) -> RobotState:
        pose = Pose((0.4, 0.0, 0.3))
        return RobotState(
            joint_positions={"primary": (0.0,) * 7},
            joint_velocities={"primary": (0.0,) * 7},
            end_effector_poses={"primary": pose},
            gripper_positions={"primary": 1.0},
        )

    def localize_object(
        self, query: str, *, camera_name: str | None = None, target_frame: str | None = None
    ) -> LocalizationResult:
        geometry = ObjectGeometry(Pose((0.5, 0.0, 0.1)), (0.14, 0.14, 0.07))
        cloud = PointCloud(((0.45, -0.05, 0.05), (0.55, 0.05, 0.12)))
        return LocalizationResult(True, geometry, segmentation=f"mask:{query}", point_cloud=cloud)

    def generate_grasps(
        self,
        camera_name: str,
        mask: object,
        *,
        backend: str = "contact-graspnet",
        max_candidates: int = 5,
    ) -> GraspSet:
        return GraspSet(True, (GraspCandidate(Pose((0.5, 0.0, 0.14)), 0.9, 0.04, 0.1),))

    def select_grasp(self, grasps: GraspSet, strategy: str = "top_down") -> GraspCandidate | None:
        return grasps.grasps[0] if grasps.ok and grasps.grasps else None

    def move_to_pose(
        self,
        target_pose: Pose,
        tolerance: float = 0.01,
        max_steps: int = 120,
        *,
        arm: str = "primary",
        strategy: object | None = None,
    ) -> ExecutionResult:
        return ExecutionResult(True, 10, "success")

    def close_gripper(self, *, arm: str = "primary") -> ExecutionResult:
        return ExecutionResult(True, 5, "success")

    def open_gripper(self, *, arm: str = "primary") -> ExecutionResult:
        return ExecutionResult(True, 5, "success")


# The same shape of program the generator writes today, wrapped as run(robot, params).
POLICY = """
def run(robot, params):
    robot.phase("locate")
    bowl = robot.localize_object("bowl")
    if not bowl.ok:
        return False
    robot.phase("grasp")
    grasp = robot.select_grasp(robot.generate_grasps("agentview", bowl.segmentation))
    if grasp is None:
        return False
    robot.move_to_pose(grasp.pose.offset(z=grasp.approach_distance_m))
    robot.move_to_pose(grasp.pose)
    held = robot.close_gripper().ok
    robot.phase("place")
    robot.move_to_pose(bowl.geometry.pose.offset(x=0.2, z=params["release_height"]))
    robot.open_gripper()
    return held
"""


def test_fake_robot_satisfies_protocol():
    assert isinstance(FakeRobot(), RobotAPI)


def test_example_policy_runs_against_api():
    scope: dict = {}
    exec(POLICY, scope)
    robot = FakeRobot()
    assert scope["run"](robot, {"release_height": 0.06}) is True
    assert robot.phases == ["locate", "grasp", "place"]


def test_pose_offset_keeps_orientation_and_frame():
    p = Pose((0.0, 0.0, 0.0), (0.7071, 0.0, 0.0, 0.7071), frame="world")
    q = p.offset(x=0.1, z=0.2)
    assert q.position == (0.1, 0.0, 0.2)
    assert q.quaternion_wxyz == p.quaternion_wxyz and q.frame == "world"


def test_signatures_match_aspire_cap_api():
    """Parameter names and kinds of the ASPIRE primitives we mirror (api.py, checked by hand)."""
    expected = {
        "localize_object": ["query", "camera_name", "target_frame"],
        "generate_grasps": ["camera_name", "mask", "backend", "max_candidates"],
        "select_grasp": ["grasps", "strategy"],
        "move_to_pose": ["target_pose", "tolerance", "max_steps", "arm", "strategy"],
        "close_gripper": ["arm"],
        "open_gripper": ["arm"],
    }
    for name, params in expected.items():
        sig = inspect.signature(getattr(RobotAPI, name))
        assert [p for p in sig.parameters if p != "self"] == params, name
    assert "force" not in inspect.signature(RobotAPI.close_gripper).parameters


def test_failed_results_carry_an_error():
    err = ApiError("point_cloud_failed", "no points", {"query": "bowl"})
    assert not LocalizationResult(False, error=err).ok
    assert not GraspSet(False, error=err).grasps


def test_observe_primitives_and_point_cloud():
    robot = FakeRobot()
    assert isinstance(robot, RobotAPI)
    assert robot.get_task_context().language == "put the bowl on the plate"
    state = robot.get_robot_state()
    assert state.end_effector_poses["primary"].position == (0.4, 0.0, 0.3)
    assert state.gripper_positions["primary"] == 1.0
    points = robot.localize_object("bowl").point_cloud.points
    assert [p[2] for p in points] == [0.05, 0.12]
