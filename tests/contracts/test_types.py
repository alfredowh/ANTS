from ants.contracts import (
    CallRecord,
    CaseSpec,
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


def test_demospec_round_trips_through_json():
    spec = DemoSpec(
        source="libero_demo:libero_goal_swap/8/0",
        task_text="put the bowl on the plate",
        objects=[ObjectTrack("bowl", {0: (0.1, 0.2, 0.9)})],
        keyframes=[Keyframe(1.5, "grasp", anchor="bowl")],
        ee_path_obj={"transport": [(0.0, 0.0, 0.1), (0.0, 0.05, 0.12)]},
        aperture=[(0.0, 1.0), (1.5, 0.2)],
        steps=["grasp bowl rim", "place on plate centre"],
        quality={"track_coverage": 0.97},
    )
    back = from_json(DemoSpec, to_json(spec))
    assert back == spec
    assert back.objects[0].poses_world[0] == (0.1, 0.2, 0.9)


def test_case_and_trace_round_trip():
    case = CaseSpec(
        "c1",
        "libero_goal_swap",
        8,
        51,
        "acceptance",
        [Perturbation("physics", {"friction": 0.5}, 0.4)],
    )
    trace = EpisodeTrace(
        "c1", "p1", True, False, "max_steps", [CallRecord("close_gripper", False, "no_object")]
    )
    assert from_json(CaseSpec, to_json(case)) == case
    assert from_json(EpisodeTrace, to_json(trace)) == trace


def test_policy_and_skill_defaults():
    policy = Policy("p1", "program", "result = {}")
    assert policy.deterministic and policy.parent_id is None
    skill = Skill(
        "s1", "grasp_bowl_by_rim", "(bowl) -> Result", "bowl lifted", "bowl visible", "..."
    )
    assert from_json(Skill, to_json(skill)) == skill
    assert skill.status == "candidate"
