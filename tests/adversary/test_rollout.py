import random
from pathlib import Path

import pytest

from ants.adversary.diagnoser import classify, diagnose
from ants.adversary.perturbations import Bounds, make
from ants.adversary.rollout import MockBackend, run_policy, to_feedback
from ants.contracts import Outcome

V0 = (Path(__file__).parents[2] / "examples" / "bowl_on_plate" / "policy.py").read_text(
    encoding="utf-8"
)
BACKEND = MockBackend()


def attack(category, severity, seed=0, program=V0):
    p = make(category, severity, random.Random(seed), Bounds(default=1.0), seed=seed)
    return p, run_policy(program, BACKEND, p, seed)


@pytest.mark.parametrize("seed", range(5))
def test_system1_v0_policy_succeeds_in_the_nominal_mock_scene(seed):
    r = run_policy(V0, BACKEND, None, seed)
    assert r.outcome is Outcome.SUCCESS and r.error is None


def test_rollouts_are_deterministic():
    assert attack("actuation", 0.4, seed=3)[1].events == attack("actuation", 0.4, seed=3)[1].events


def test_v0_survives_pose_and_size_because_it_measures_objects():
    for category in ("pose", "size"):
        assert attack(category, 0.8)[1].outcome is Outcome.SUCCESS


def test_slip_breaks_v0_and_a_lower_grasp_defeats_it():
    p, r = attack("physics", 0.6)
    assert r.outcome is Outcome.FAILURE
    assert any(e.kind == "object_dropped" for e in r.events)
    lower = V0.replace("pinch_height = 0.82 * bowl_h", "pinch_height = 0.4 * bowl_h")
    assert lower != V0
    assert run_policy(lower, BACKEND, p, 0).outcome is Outcome.SUCCESS


def test_dark_scene_is_a_missed_object_with_a_shared_signature():
    p, r = attack("lighting", 0.8)
    fb = to_feedback(r)
    assert r.outcome is Outcome.FAILURE
    assert fb["failed_calls"][0]["tool"] == "localize_object"
    assert diagnose(p, fb, 0).failure_signature == "lighting:localize_object:not_found"
    assert classify(p, fb).mode == "missed_object"


def test_a_crash_is_an_error_not_a_failure():
    r = run_policy("x = 1 / 0\n", BACKEND, None, 0)
    assert r.outcome is Outcome.ERROR and "ZeroDivisionError" in r.error


def test_imports_other_than_math_are_refused():
    assert run_policy("import math\nresult = math.pi\n", BACKEND, None, 0).error is None
    r = run_policy("import os\n", BACKEND, None, 0)
    assert r.outcome is Outcome.ERROR and "not allowed" in r.error


def test_no_file_or_eval_access():
    for prog in ("open('x')\n", "eval('1')\n", "__import__('os')\n"):
        assert run_policy(prog, BACKEND, None, 0).outcome is Outcome.ERROR


def test_runaway_program_is_a_timeout_failure():
    r = run_policy("while True:\n    pass\n", BACKEND, None, 0, line_budget=1000)
    assert r.outcome is Outcome.FAILURE
    assert to_feedback(r)["termination_reason"] == "timeout"


def test_wall_clock_timeout_is_an_error_not_a_failure():
    """Elapsed time depends on the machine, so it must never feed a constraint to System 1."""
    r = run_policy("while True:\n    pass\n", BACKEND, None, 0, line_budget=10**12, timeout_s=0.05)
    assert r.outcome is Outcome.ERROR
    assert "WallClockExceeded" in r.error
    assert to_feedback(r)["termination_reason"] == "wall_clock_timeout"


def test_slow_primitive_trips_the_wall_clock_once_it_returns():
    class SlowEpisode:
        events: list = []

        def api(self):
            import time

            return {"slow_call": lambda: time.sleep(0.1)}

        def success(self):
            return True

        def metrics(self):
            return {}

    class SlowBackend:
        def episode(self, perturbation, seed):
            return SlowEpisode()

    r = run_policy("slow_call()\nx = 1\n", SlowBackend(), None, 0, timeout_s=0.05)
    assert r.outcome is Outcome.ERROR
    assert to_feedback(r)["termination_reason"] == "wall_clock_timeout"
