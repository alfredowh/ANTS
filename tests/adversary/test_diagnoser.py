import pytest

from ants.adversary.diagnoser import RULES, classify, diagnose, signature
from ants.adversary.perturbations import CATEGORIES
from ants.contracts import Constraint, Perturbation

TIMEOUT = {"failed_calls": [{"tool": "move_to_pose", "status": "timeout", "steps_executed": 120}]}
SIZE = Perturbation("size", {"bowl_scale": 1.2, "plate_scale": 1.7}, 0.8)


def test_every_category_has_a_rule():
    assert set(CATEGORIES) <= set(RULES)


def test_signature_names_category_primitive_and_status():
    assert signature(SIZE, TIMEOUT) == "size:move_to_pose:timeout"
    assert signature(SIZE, {"termination_reason": "max_steps"}) == "size:max_steps:not_scored"
    assert signature(SIZE, {}) == "size:unknown:not_scored"


def test_diagnose_returns_a_round_trippable_constraint():
    c = diagnose(SIZE, {**TIMEOUT, "final_gripper": {"position_robot_base": [0.4, 0.0, 0.2]}}, 3)
    assert c.constraint_id == "c003" and c.failure_signature == "size:move_to_pose:timeout"
    assert "point cloud" in c.rule and any("final gripper" in e for e in c.evidence)
    assert Constraint.from_dict(c.to_dict()) == c


@pytest.mark.parametrize(
    "fb,mode",
    [
        (TIMEOUT, "timeout"),
        ({"failed_calls": [{"tool": "localize_object", "status": "not_found"}]}, "missed_object"),
        ({"failed_calls": [{"tool": "close_gripper", "status": "failed"}]}, "close_gripper_failed"),
        ({"error": {"type": "NameError"}}, "program_error"),
        ({"termination_reason": "program_finished"}, "wrong_placement"),
    ],
)
def test_classify_modes(fb, mode):
    f = classify(SIZE, fb)
    assert f.mode == mode and f.source == "rules" and 0 < f.confidence < 1


def test_unknown_category_falls_back_to_a_generic_rule():
    p = Perturbation("weather", {}, 0.2)
    assert diagnose(p, {}, 0).failure_signature.startswith("weather:")
