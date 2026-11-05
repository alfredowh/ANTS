"""Rule-based diagnoser: a failed perturbed episode becomes one named, reusable constraint.

Ported from System 1's v0 (branch `synthesizer`). The rule text is written for the generator: it
names what to measure or check instead of a number tuned to one case. The signature comes from
`contracts.failure_signature`, so stall counting and escalation key on the same string on both
sides. This is the fallback when the model diagnoser is unavailable or below its confidence floor.

`fb` is the compact feedback dict that the cap_harness rollout reads from a run directory
(`termination_reason`, `error`, `failed_calls` with `tool` and `status`, `final_gripper`).
"""

from __future__ import annotations

from collections.abc import Mapping

from ants.contracts import Constraint, Failure, FailureMode, Perturbation, failure_signature

RULE_CONFIDENCE = 0.5  # rules see the category and the failing call, not the cause

RULES: dict[str, tuple[str, str]] = {
    "pose": (
        "the bowl is not where the nominal layout puts it",
        "Never reuse an object position from an earlier step or a nominal layout. Re-localize the "
        "bowl and the plate from the current point cloud right before each approach, and plan "
        "every move from those fresh measurements.",
    ),
    "physics": (
        "the bowl slips or is dropped (low friction or a heavier bowl)",
        "After closing the gripper, lift 2 cm and check that the bowl moved with the gripper "
        "before carrying it. If it did not, re-grasp lower on the rim with a slower close, and "
        "carry at low speed.",
    ),
    "size": (
        "the bowl or plate is larger than in the nominal scene",
        "Measure the bowl radius and height and the plate radius from the point cloud; do not "
        "hard-code sizes. Release over the plate centre estimated from the plate points, and "
        "check the released bowl lies on the plate before finishing.",
    ),
    "actuation": (
        "commands are noisy or delayed",
        "After every move_to_pose read back the reached pose; if it is off by more than the "
        "tolerance, retry up to 3 times. Use position tolerances of at least 1.5 cm, and wait "
        "for the arm to settle before closing or opening the gripper.",
    ),
    "camera": (
        "the camera is shifted or has a different field of view",
        "Express all geometry in the robot base frame from depth, never in pixel coordinates; "
        "re-localize each object and reject a localization whose depth is invalid.",
    ),
    "lighting": (
        "the scene is darker or brighter than nominal",
        "Do not rely on colour or brightness; localize from the segmentation mask and depth, "
        "reject a localization with too few points, and localize again before each approach.",
    ),
}

_GENERIC = (
    "the scene differs from the nominal one",
    "Re-localize every object right before using it and check the result of each primitive call "
    "before the next one.",
)

# failing primitive -> recommended failure mode
_MODE_BY_PRIMITIVE = {
    "localize_object": FailureMode.MISSED_OBJECT,
    "generate_grasps": FailureMode.MISSED_OBJECT,
    "select_grasp": FailureMode.MISSED_OBJECT,
}


def _part(value: object, default: str) -> str:
    text = str(value) if value else default
    return text.replace(":", "_") or default


def without_nominal(fb: Mapping, nominal_fb: Mapping | None) -> dict:
    """`fb` without the failed calls that also fail in the nominal run on the same seed.

    A call that fails in the unperturbed scene too (for example a move the program deliberately
    accepts after a timeout) happens in every run, so it cannot explain this failure. Each such
    call is removed as many times as it occurs in the nominal run; what remains are the calls
    that only fail under the perturbation. The removed ones are kept as evidence.
    """
    out = dict(fb)
    if not nominal_fb:
        return out
    budget: dict[tuple[str, str], int] = {}
    for c in nominal_fb.get("failed_calls") or []:
        key = (str(c.get("tool")), str(c.get("status")))
        budget[key] = budget.get(key, 0) + 1
    kept, expected = [], []
    for c in fb.get("failed_calls") or []:
        key = (str(c.get("tool")), str(c.get("status")))
        if budget.get(key, 0) > 0:
            budget[key] -= 1
            expected.append(c)
        else:
            kept.append(c)
    out["failed_calls"] = kept
    out["expected_failed_calls"] = expected
    return out


def signature(perturbation: Perturbation, fb: Mapping) -> str:
    """`<category>:<failing call>:<status>`, e.g. `size:move_to_pose:timeout`."""
    failed = fb.get("failed_calls") or []
    if failed:
        primitive = _part(failed[0].get("tool"), "unknown")
        status = _part(failed[0].get("status"), "failed")
    else:
        primitive, status = _part(fb.get("termination_reason"), "unknown"), "not_scored"
    return failure_signature(perturbation.category, primitive, status)


def classify(perturbation: Perturbation, fb: Mapping) -> Failure:
    """A coarse failure mode from the failing call; the model diagnoser refines it."""
    when, _ = RULES.get(perturbation.category, _GENERIC)
    failed = fb.get("failed_calls") or []
    if fb.get("error") and not failed:
        mode = FailureMode.PROGRAM_ERROR
    elif failed:
        call = failed[0]
        if "timeout" in str(call.get("status", "")):
            mode = FailureMode.TIMEOUT
        else:
            mode = _MODE_BY_PRIMITIVE.get(
                str(call.get("tool")), f"{_part(call.get('tool'), 'call')}_failed"
            )
    else:
        mode = FailureMode.WRONG_PLACEMENT  # every call succeeded but the task was not achieved
    return Failure(str(mode), f"Fails when {when}.", RULE_CONFIDENCE, source="rules")


def diagnose(perturbation: Perturbation, fb: Mapping, index: int) -> Constraint:
    """Explain one failure of the incumbent under `perturbation` as a `Constraint`."""
    when, rule = RULES.get(perturbation.category, _GENERIC)
    evidence = [f"perturbation {perturbation.category} {dict(perturbation.params)}"]
    evidence += [
        f"failed call {c.get('tool')} status={c.get('status')} "
        f"after {c.get('steps_executed')} steps"
        for c in (fb.get("failed_calls") or [])[:3]
    ]
    expected = fb.get("expected_failed_calls") or []
    if expected:
        names = ", ".join(f"{c.get('tool')} {c.get('status')}" for c in expected[:3])
        evidence.append(f"also failing in the nominal run, so not the cause: {names}")
    final = (fb.get("final_gripper") or {}).get("position_robot_base")
    if final:
        evidence.append(f"final gripper {final}")
    return Constraint(
        constraint_id=f"c{index:03d}",
        failure_signature=signature(perturbation, fb),
        when_to_apply=f"when {when}",
        rule=rule,
        evidence=tuple(evidence),
    )
