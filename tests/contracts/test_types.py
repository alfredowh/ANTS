import json
from dataclasses import FrozenInstanceError

import pytest

from ants.contracts import (
    AttackReport,
    BlameTarget,
    CaseSpec,
    Constraint,
    Event,
    Failure,
    FailureMode,
    Feedback,
    Outcome,
    Perturbation,
    Policy,
    RolloutResult,
    Skill,
    SkillKind,
    SkillRef,
    Split,
    failure_signature,
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
            "pose:close_gripper:failed",
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


def test_policy_system1_fields_round_trip_and_defaults():
    plain = Policy("p", 0, "t", "def run(robot, params): ...")
    assert plain.deterministic is False
    assert plain.entry_format == "run_function"
    p = Policy(
        "p",
        1,
        "t",
        "result = 1",
        params={"grasp_offset": 0.02},
        deterministic=True,
        metadata={"model": "m", "tokens": 1200},
        attack_ranges={"grasp_offset": (-0.03, 0.03)},
        entry_format="script",
    )
    assert Policy.from_dict(_json(p)) == p


def test_policy_rejects_inverted_attack_range():
    with pytest.raises(ValueError):
        Policy("p", 0, "t", "x", attack_ranges={"a": (1.0, 0.0)})


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


GRASP_SKILL = Skill(
    "grasp_with_retry",
    2,
    SkillKind.CODE,
    "grasp_with_retry",
    "the target may move or slip during the grasp",
    "def grasp_with_retry(robot, name, attempts):\n    ...\n",
    evidence=("bowl_on_plate@v3",),
    source_constraints=("c3",),
    help_count=4,
)


def test_skill_round_trip():
    rule = Skill("relocalise", 1, SkillKind.GUIDANCE, "Re-localise", "after a miss", "Re-localise.")
    for s in (GRASP_SKILL, rule):
        assert Skill.from_dict(_json(s)) == s


def test_skill_rejects_empty_body():
    with pytest.raises(ValueError):
        Skill("x", 0, SkillKind.GUIDANCE, "x", "always", "  ")


def test_policy_records_skills_used():
    p = Policy("bowl", 4, "t", "def run(robot, params): ...", skills_used=(GRASP_SKILL.ref,))
    back = Policy.from_dict(_json(p))
    assert back == p and back.skills_used == (SkillRef("grasp_with_retry", 2),)


def test_constraint_can_blame_a_skill():
    c = Constraint(
        "c9",
        "physics:close_gripper:failed",
        "low friction",
        "Raise grasp force when the object is light.",
        target=BlameTarget.SKILL,
        skill=GRASP_SKILL.ref,
    )
    assert Constraint.from_dict(_json(c)) == c


def test_skill_target_and_ref_must_agree():
    with pytest.raises(ValueError):
        Constraint("c", "s", "w", "r", target=BlameTarget.SKILL)
    with pytest.raises(ValueError):
        Constraint("c", "s", "w", "r", skill=GRASP_SKILL.ref)


def test_failure_mode_is_an_open_string():
    f = Failure("spill", "Liquid left the cup during transport.", 0.6)
    assert Failure.from_dict(_json(f)) == f
    assert Failure(FailureMode.TIMEOUT, "x", 0.5).mode == "timeout"


def test_failure_signature_format():
    assert failure_signature("size", "move_to_pose", "timeout") == "size:move_to_pose:timeout"
    for bad in (("", "a", "b"), ("a:b", "c", "d")):
        with pytest.raises(ValueError):
            failure_signature(*bad)


def test_perturbation_seed_is_optional_and_part_of_the_key():
    p = Perturbation("size", {"bowl_scale": 1.1}, 0.4)
    assert p.seed is None and Perturbation.from_dict(_json(p)) == p
    assert p.key != Perturbation("size", {"bowl_scale": 1.1}, 0.4, seed=3).key


def _case(split: Split) -> CaseSpec:
    pert = Perturbation("pose", {"dx": 0.05}, 0.3)
    return CaseSpec("c-51", "libero_goal_swap", 8, 51, split, perturbations=(pert,))


@pytest.mark.parametrize("split", list(Split))
def test_case_spec_round_trip(split):
    case = _case(split)
    assert CaseSpec.from_dict(_json(case)) == case
    assert case.to_dict()["split"] == split.value


def test_feedback_from_acceptance_case(report):
    fb = Feedback.from_report(report, test_case=_case(Split.ACCEPTANCE))
    assert Feedback.from_dict(_json(fb)) == fb


def test_held_out_case_cannot_produce_feedback(report):
    with pytest.raises(ValueError, match="held-out"):
        Feedback.from_report(report, test_case=_case(Split.HELD_OUT))


def test_details_mappings_round_trip(report):
    rollout = RolloutResult(Outcome.FAILURE, details={"calls": [{"name": "move_to_pose"}]})
    assert RolloutResult.from_dict(_json(rollout)) == rollout
    fb = Feedback.from_report(report)
    fb = Feedback(**{**fb.__dict__, "details": {"trace": "t.jsonl"}})
    assert Feedback.from_dict(_json(fb)).details == {"trace": "t.jsonl"}


def test_constraint_check_code_and_phase_round_trip():
    c = Constraint(
        "c4",
        "pose:localize_object:failed",
        "the bowl may have moved",
        "Re-localise the bowl before the grasp.",
        check_code="bowl.ok",
        phase="grasp",
    )
    assert Constraint.from_dict(_json(c)) == c
    assert Constraint("c5", "a:b:c", "w", "r").phase is None


def test_failure_source_is_validated():
    assert Failure("timeout", "x", 0.5, "human").source == "human"
    with pytest.raises(ValueError, match="source"):
        Failure("timeout", "x", 0.5, "oracle")
