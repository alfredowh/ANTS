import json
from dataclasses import FrozenInstanceError

import pytest

from ants.contracts import (
    AttackReport,
    BlameTarget,
    Constraint,
    Event,
    Failure,
    FailureMode,
    Feedback,
    Outcome,
    Perturbation,
    Policy,
    RolloutResult,
)


def _json(obj):
    return json.loads(json.dumps(obj.to_dict()))


@pytest.fixture
def report() -> AttackReport:
    return AttackReport(
        attack_id="atk-0001",
        policy_id="bowl_on_plate",
        version=2,
        perturbation=Perturbation("pose", {"dx": -0.09, "yaw": 0.3}, 0.45, seed=7, rationale="x"),
        result=RolloutResult(
            outcome=Outcome.FAILURE,
            metrics={"dist_to_target": 0.12},
            events=(Event(3.2, "grasp_slip", "grasp", {"force": 20.0}),),
            last_phase="grasp",
            duration_s=8.5,
            keyframes=("k0.png", "k1.png"),
        ),
        selector_draws={"pose": 0.61, "physics": 0.22},
        failure=Failure(FailureMode.GRASP_SLIP, "Bowl moved after localise.", 0.8, "model"),
        constraint=Constraint(
            "c3",
            "grasp_slip | pose",
            "the target may have moved since it was localised",
            "Re-localise the bowl after a failed grasp before retrying.",
            code_sketch="bowl = robot.localize_object('bowl')",
            evidence=("atk-0001",),
        ),
    )


def test_policy_round_trip():
    p = Policy(
        "bowl_on_plate",
        1,
        "put the bowl on the plate",
        "def run(robot, params): ...",
        params={"grasp_force": 20.0},
        parent_version=0,
        constraints=("c1",),
    )
    assert Policy.from_dict(_json(p)) == p


def test_attack_report_round_trip(report):
    assert AttackReport.from_dict(_json(report)) == report


def test_success_report_has_no_failure(report):
    ok = AttackReport(
        report.attack_id,
        report.policy_id,
        report.version,
        report.perturbation,
        RolloutResult(Outcome.SUCCESS),
    )
    assert AttackReport.from_dict(_json(ok)) == ok


def test_feedback_from_report(report):
    fb = Feedback.from_report(report)
    assert fb.case == report.perturbation
    assert fb.constraint.target is BlameTarget.PROGRAM
    assert Feedback.from_dict(_json(fb)) == fb


def test_feedback_requires_failure(report):
    ok = AttackReport(
        report.attack_id,
        report.policy_id,
        report.version,
        report.perturbation,
        RolloutResult(Outcome.SUCCESS),
    )
    with pytest.raises(ValueError):
        Feedback.from_report(ok)


def test_perturbation_key_ignores_rationale_and_order():
    a = Perturbation("pose", {"dx": 0.1, "dy": 0.0}, 0.2, seed=1, rationale="a")
    b = Perturbation("pose", {"dy": 0.0, "dx": 0.1}, 0.2, seed=1, rationale="b")
    c = Perturbation("pose", {"dx": 0.1, "dy": 0.0}, 0.2, seed=2)
    assert a.key == b.key != c.key


@pytest.mark.parametrize("severity", [-0.1, 1.1])
def test_severity_bounds(severity):
    with pytest.raises(ValueError):
        Perturbation("pose", {}, severity, seed=0)


def test_confidence_bounds():
    with pytest.raises(ValueError):
        Failure(FailureMode.TIMEOUT, "x", 1.5)


def test_frozen():
    p = Perturbation("pose", {}, 0.0, seed=0)
    with pytest.raises(FrozenInstanceError):
        p.seed = 1
