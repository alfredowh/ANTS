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


def test_correction_written_then_retrieved_by_signature_in_a_new_run(tmp_path):
    run_case = _world(tmp_path, {"v0": "size", "v1": "pose", "v2": "none"})
    store = tmp_path / "corrections.jsonl"
    calls = {"n": 0}

    def gen_train(inc, cons, fbs):
        calls["n"] += 1
        return (tmp_path / ("v1.py" if calls["n"] == 1 else "v2.py"), 100)

    cfg = HardenConfig(
        cycles=8,
        tests_per_cycle=8,
        min_tests_robust=1,
        memory_mode="matched",
        memory_k=2,
        correction_store=store,
    )
    res = harden(tmp_path / "v0.py", cfg, run_case, gen_train, RunLog(tmp_path / "train"))
    assert res.incumbent.name == "v2.py"
    assert store.exists() and "Re-localize" not in store.read_text()  # rule text comes from RULES
    records = [json.loads(x) for x in store.read_text().splitlines()]
    admitted = [r for r in records if r["status"] == "admitted"]
    assert admitted and admitted[-1]["signature"]["primitive"] == "move_to_pose"

    seen = []

    def gen_test(inc, cons, fbs):
        seen.append([c.constraint_id for c in cons])
        retrieved = any(cid.startswith("mem:") for cid in seen[-1])
        return (tmp_path / ("v2.py" if retrieved else "v1.py"), 100)

    cfg2 = HardenConfig(
        cycles=8,
        tests_per_cycle=8,
        min_tests_robust=1,
        memory_mode="matched",
        memory_k=2,
        correction_store=store,
    )
    res2 = harden(tmp_path / "v0.py", cfg2, run_case, gen_test, RunLog(tmp_path / "test"))
    assert res2.incumbent.name == "v2.py" and len(seen) == 1  # fixed at the first attempt
    rows = [json.loads(x) for x in (tmp_path / "test/system2.jsonl").read_text().splitlines()]
    retrieval = next(r["retrieval"] for r in rows if r.get("retrieval"))
    assert retrieval["used"] is True and retrieval["retrieved"]
    assert retrieval["retrieved"][0]["correction_id"] == admitted[-1]["correction_id"]

    # memory off: the same store is not consulted and the bad repair comes first
    seen.clear()
    cfg3 = HardenConfig(
        cycles=8, tests_per_cycle=8, min_tests_robust=1, memory_mode="off", correction_store=store
    )
    harden(tmp_path / "v0.py", cfg3, run_case, gen_test, RunLog(tmp_path / "off"))
    rows = [json.loads(x) for x in (tmp_path / "off/system2.jsonl").read_text().splitlines()]
    assert all(r["retrieval"]["used"] is False for r in rows if r.get("retrieval"))
    assert all(not any(cid.startswith("mem:") for cid in ids) for ids in seen)


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


def test_human_text_answer_becomes_a_constraint_and_the_loop_continues(tmp_path):
    from ants.orchestrator.human_gate import GateAnswer, read_answer, write_request

    run_case = _world(tmp_path, {"v0": "size", "v1": "pose", "v2": "none"})
    seen = []

    def gen(inc, cons, fbs):
        seen.append([c.rule for c in cons])
        fixed = any(c.evidence and c.evidence[0] == "human gate" for c in cons)
        return (tmp_path / ("v2.py" if fixed else "v1.py"), 100)

    asked = []

    def ask(esc):
        asked.append(esc)
        write_request(tmp_path, esc)
        return GateAnswer("text", "Measure the plate before releasing")

    cfg = HardenConfig(cycles=12, tests_per_cycle=10, stall_limit=2, min_tests_robust=1)
    res = harden(tmp_path / "v0.py", cfg, run_case, gen, RunLog(tmp_path / "run"), ask)
    assert len(asked) == 1 and (tmp_path / "gate_request.json").exists()
    assert res.stopped == "robust" and res.incumbent.name == "v2.py"
    assert any("Measure the plate" in r for r in seen[-1])
    assert read_answer(tmp_path) is None


def test_video_answer_is_not_wired_and_still_escalates(tmp_path):
    from ants.orchestrator.human_gate import GateAnswer

    run_case = _world(tmp_path, {"v0": "size", "v1": "pose"})
    gen = lambda inc, cons, fbs: (tmp_path / "v1.py", 100)  # noqa: E731
    cfg = HardenConfig(cycles=10, tests_per_cycle=10, stall_limit=2, min_tests_robust=1)
    ask = lambda esc: GateAnswer("video", file_name="fix.mp4")  # noqa: E731
    res = harden(tmp_path / "v0.py", cfg, run_case, gen, RunLog(tmp_path / "run"), ask)
    assert res.stopped == "escalate" and res.escalation


def test_read_answer_parses_the_json_file_and_rejects_unknown_channels(tmp_path):
    import pytest

    from ants.orchestrator.human_gate import read_answer

    (tmp_path / "gate_answer.json").write_text(
        '{"channel": "text", "text": "tilt it"}', encoding="utf-8"
    )
    assert read_answer(tmp_path).text == "tilt it"
    (tmp_path / "gate_answer.json").write_text('{"channel": "smoke"}', encoding="utf-8")
    with pytest.raises(ValueError):
        read_answer(tmp_path)
