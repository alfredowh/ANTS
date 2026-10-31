from ants.contracts import (
    Grasp,
    GripperResult,
    MotionResult,
    ObjectEstimate,
    Pose,
    RobotAPI,
)


class FakeRobot:
    def __init__(self) -> None:
        self.phases: list[str] = []

    def phase(self, name: str) -> None:
        self.phases.append(name)

    def localize_object(self, name: str) -> ObjectEstimate:
        return ObjectEstimate(name, True, Pose((0.5, 0.0, 0.1)), 0.9)

    def generate_grasps(self, target: ObjectEstimate) -> tuple[Grasp, ...]:
        return (Grasp(target.pose, target.pose.offset(z=0.1), 1.0),)

    def select_grasp(self, grasps: tuple[Grasp, ...]) -> Grasp | None:
        return grasps[0] if grasps else None

    def move_to_pose(self, pose: Pose) -> MotionResult:
        return MotionResult(True)

    def close_gripper(self, force: float) -> GripperResult:
        return GripperResult(True, holding=True, width=0.04)

    def open_gripper(self) -> GripperResult:
        return GripperResult(True)


POLICY = """
def run(robot, params):
    robot.phase("locate")
    bowl = robot.localize_object("bowl")
    robot.phase("grasp")
    grasp = robot.select_grasp(robot.generate_grasps(bowl))
    robot.move_to_pose(grasp.pre_pose)
    robot.move_to_pose(grasp.pose)
    held = robot.close_gripper(force=params["grasp_force"]).holding
    robot.phase("place")
    robot.move_to_pose(bowl.pose.offset(x=0.2, z=params["release_height"]))
    robot.open_gripper()
    return held
"""


def test_fake_robot_satisfies_protocol():
    assert isinstance(FakeRobot(), RobotAPI)


def test_example_policy_runs_against_api():
    scope: dict = {}
    exec(POLICY, scope)
    robot = FakeRobot()
    assert scope["run"](robot, {"grasp_force": 20.0, "release_height": 0.06}) is True
    assert robot.phases == ["locate", "grasp", "place"]


def test_pose_offset_keeps_orientation():
    p = Pose((0.0, 0.0, 0.0), (0.0, 0.0, 0.7071, 0.7071))
    q = p.offset(x=0.1, z=0.2)
    assert q.position == (0.1, 0.0, 0.2) and q.orientation == p.orientation
