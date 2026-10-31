"""Rule-based diagnoser: a failed perturbed episode becomes one named, reusable constraint.

The signature (category, failing call, status) is what repeats across cycles, so it also drives
the escalation rule. The rule text is written for the generator: it names what to measure or
check instead of a number tuned to one case. A model-based diagnoser (Muse Spark) can replace
`diagnose` later; the output type (`Constraint`) stays the same.
"""

from __future__ import annotations

from ants.contracts import Constraint, Perturbation

RULES = {
    "pose": (
        "the bowl is not where the nominal layout puts it",
        "Never reuse an object position from an earlier step or a nominal layout. Re-localize the "
        "bowl and the plate from the current point cloud right before each approach, and plan "
        "every move from those fresh measurements.",
    ),
    "physics": (
        "the bowl slips or is dropped (low friction)",
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
}


def signature(perturbation: Perturbation, fb: dict) -> str:
    """category:failing-call:status, e.g. 'size:move_to_pose:timeout'."""
    failed = fb.get("failed_calls") or []
    if failed:
        call = f"{failed[0].get('tool', '?')}:{failed[0].get('status', 'failed')}"
    else:
        call = f"{fb.get('termination_reason', 'unknown')}:not_scored"
    return f"{perturbation.category}:{call}"


def diagnose(perturbation: Perturbation, fb: dict, index: int) -> Constraint:
    """Explain one failure of the incumbent under `perturbation` as a `Constraint`."""
    when, rule = RULES[perturbation.category]
    sig = signature(perturbation, fb)
    evidence = [f"perturbation {perturbation.category} {perturbation.params}"]
    evidence += [
        f"failed call {c.get('tool')} status={c.get('status')} "
        f"after {c.get('steps_executed')} steps"
        for c in (fb.get("failed_calls") or [])[:3]
    ]
    if fb.get("final_gripper", {}).get("position_robot_base"):
        evidence.append(f"final gripper {fb['final_gripper']['position_robot_base']}")
    return Constraint(
        constraint_id=f"c{index:03d}",
        failure_signature=sig,
        when_to_apply=f"when {when}",
        rule=rule,
        evidence=evidence,
    )
