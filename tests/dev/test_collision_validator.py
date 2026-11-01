"""The collision validator allows grasping and placing and flags everything else."""

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "dev" / "curobo" / "collision_validator.py"
_spec = importlib.util.spec_from_file_location("collision_validator", _PATH)
cv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cv)


def row(step: int, *pairs: str) -> dict:
    return {"step": step, "contacts": dict.fromkeys(pairs, -0.001)}


def test_grasp_and_place_are_clean():
    rows = [
        row(1, "akita_black_bowl_1_main | table"),
        row(2, "akita_black_bowl_1_main | gripper0_leftfinger"),
        row(3, "akita_black_bowl_1_main | plate_1_main", "plate_1_main | wine_rack_1_main"),
        row(4, "gripper0_leftfinger | robot0_link7"),
    ]
    result = cv.validate(rows)
    assert result["clean"] and result["collision_steps"] == 0


def test_robot_touching_the_rack_is_flagged():
    rows = [
        row(1, "akita_black_bowl_1_main | gripper0_leftfinger"),
        row(2, "gripper0_right_gripper | wine_rack_1_main"),
    ]
    result = cv.validate(rows)
    assert not result["clean"]
    assert result["collision_steps"] == 1 and result["first_collision_step"] == 2
    assert "robot with wine_rack_1_main" in result["by_contact"]


def test_bowl_hitting_the_rack_is_flagged_and_pair_order_does_not_matter():
    for pair in (
        "akita_black_bowl_1_main | wine_rack_1_main",
        "wine_rack_1_main | akita_black_bowl_1_main",
    ):
        assert not cv.validate([row(1, pair)])["clean"]


def test_robot_touching_the_table_or_plate_is_flagged():
    assert not cv.validate([row(1, "gripper0_rightfinger | table")])["clean"]
    assert not cv.validate([row(1, "plate_1_main | gripper0_rightfinger")])["clean"]
