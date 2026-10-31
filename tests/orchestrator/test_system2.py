import json
import random

import pytest

from ants.adversary.perturbations import CATEGORIES, Bounds, make, to_launcher_spec
from ants.adversary.planner import TestPlanner
from ants.evalkit.runlog import RunLog
from ants.orchestrator.gate import regression_gate
from ants.orchestrator.system2 import CaseResult, HardenConfig, harden

FAIL = {"failed_calls": [{"tool": "move_to_pose", "status": "timeout"}]}


def test_gate_rejects_any_regression_and_accepts_pure_improvement():
    inc = {"a": True, "b": False, "c": True}
    assert not regression_gate(inc, {"a": True, "b": True, "c": False}).accepted
    assert regression_gate(inc, {"a": True, "b": True, "c": True}).accepted
    assert not regression_gate(inc, dict(inc)).accepted  # no improvement
    assert not regression_gate(inc, {"b": True}).accepted  # missing results count as failures


def test_severity_is_clamped_to_the_bound_and_maps_to_a_launcher_spec():
    rng = random.Random(0)
    p = make("size", 1.0, rng, Bounds(default=0.4))
    assert p.severity == 0.4 and p.params["plate_scale"] == pytest.approx(1.36)
    assert to_launcher_spec([p])["scale"]["bodies"]["plate_1_main"] == pytest.approx(1.36)
    assert to_launcher_spec([]) == {}
    with pytest.raises(ValueError):
        make("gravity", 0.5, rng, Bounds())


def test_thompson_concentrates_on_the_breaking_category_and_is_deterministic():
    def run(strategy):
        planner = TestPlanner(strategy=strategy, seed=1)
        seen = []
        for _ in range(60):
            p = planner.propose()
            planner.update(p.category, failed=p.category == "size")
            seen.append(p.category)
        return seen

    assert run("thompson") == run("thompson")
    assert run("thompson").count("size") > run("uniform").count("size")
    planner = TestPlanner(seed=2, bounds=Bounds(default=0.5))
    assert all(planner.propose().severity <= 0.5 for _ in range(30))


def _world(tmp_path, programs):
    """Programs are files with 'breaks=a,b'; a case fails if its category (or nominal) is broken."""
    for name, breaks in programs.items():
        (tmp_path / f"{name}.py").write_text(f"breaks={breaks}\n", encoding="utf-8")

    def run_case(case, program):
        broken = program.read_text(encoding="utf-8").strip().split("=")[1].split(",")
        cats = [p.category for p in case.perturbations] or ["nominal"]
        ok = not any(c in broken for c in cats)
        return CaseResult(ok, {} if ok else FAIL)

    return run_case


def test_loop_accepts_a_fix_without_regression_and_ends_robust(tmp_path):
    run_case = _world(tmp_path, {"v0": "size", "v1": "none"})
    gen = lambda inc, cons, fbs: (tmp_path / "v1.py", 100)  # noqa: E731
    cfg = HardenConfig(cycles=8, tests_per_cycle=8, min_tests_robust=1)
    res = harden(tmp_path / "v0.py", cfg, run_case, gen, RunLog(tmp_path / "run"))
    assert res.stopped == "robust" and res.incumbent.name == "v1.py"
    assert res.constraints and res.constraints[0].failure_signature.startswith("size:")
    rows = [json.loads(x) for x in (tmp_path / "run/system2.jsonl").read_text().splitlines()]
    assert any(r.get("decision") == "accepted" and r["gate"]["accepted"] for r in rows)


def test_loop_rejects_a_regressing_candidate_and_escalates_when_stalled(tmp_path):
    # v1 fixes size but breaks pose, which v0 passed: the gate must reject it every time.
    run_case = _world(tmp_path, {"v0": "size", "v1": "pose"})
    gen = lambda inc, cons, fbs: (tmp_path / "v1.py", 100)  # noqa: E731
    cfg = HardenConfig(cycles=10, tests_per_cycle=10, stall_limit=2, min_tests_robust=1)
    res = harden(tmp_path / "v0.py", cfg, run_case, gen, RunLog(tmp_path / "run"))
    assert res.stopped == "escalate" and res.incumbent.name == "v0.py"
    assert res.escalation and res.escalation["signature"].startswith("size:")


def test_loop_refuses_overlapping_splits_and_a_policy_that_fails_nominal(tmp_path):
    run_case = _world(tmp_path, {"v0": "nominal"})
    cfg = HardenConfig(held_out_seeds=(51, 1))
    with pytest.raises(ValueError):
        harden(tmp_path / "v0.py", cfg, run_case, lambda *a: None, RunLog(tmp_path / "r1"))
    res = harden(
        tmp_path / "v0.py", HardenConfig(), run_case, lambda *a: None, RunLog(tmp_path / "r2")
    )
    assert res.stopped == "no_working_policy"
    assert set(CATEGORIES) >= {"pose", "size"}
