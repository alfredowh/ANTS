"""System 1's `Generate` repair step (MuseOrchestrator's signature) behind the Synthesizer."""

import json
from pathlib import Path

import pytest

from ants.orchestrator import GenerateSynthesizer, LoopConfig, feedback_dict, regression_gate
from ants.orchestrator.loop import Loop
from ants.orchestrator.run import main as run_main
from ants.orchestrator.synthesis import MOCK_WORLD_PATCHES

from .test_loop import V0, adversary


class FakeGenerate:
    """Stands in for MuseOrchestrator: same signature, writes the candidate to disk."""

    def __init__(self, out: Path, budget_calls: int | None = None, tokens: int = 1000):
        self.out, self.budget_calls, self.tokens = out, budget_calls, tokens
        self.calls: list[tuple[str, list, list[dict]]] = []

    def __call__(self, incumbent: Path, constraints: list, feedbacks: list[dict]):
        if self.budget_calls is not None and len(self.calls) >= self.budget_calls:
            return None
        code = incumbent.read_text(encoding="utf-8")
        self.calls.append((code, constraints, feedbacks))
        for fb in feedbacks:  # a "repair" the mock world rewards
            patch = MOCK_WORLD_PATCHES.get(fb["category"])
            code = patch(code) if patch else code
        path = self.out / f"cand{len(self.calls)}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding="utf-8")
        return path, self.tokens


def run(tmp_path, gen, **cfg):
    synth = GenerateSynthesizer(gen, tmp_path / "work", name="fake")
    loop = Loop(adversary(("physics",)), synth, LoopConfig(out=tmp_path / "run", **cfg))
    return loop.run(V0), synth


def test_the_loop_accepts_a_repair_from_a_generate_callable(tmp_path):
    gen = FakeGenerate(tmp_path / "gen")
    res, synth = run(tmp_path, gen, cycles=30)
    assert res.accepted_versions == [1] and res.stopped == "robust"
    v1 = res.incumbent
    assert v1.parent_version == 0 and v1.metadata["synthesizer"] == "fake"
    assert v1.metadata["tokens"] == 1000 and synth.tokens == [1000]
    code, constraints, feedbacks = gen.calls[0]
    assert code == V0.code  # the incumbent file held the incumbent's code
    assert constraints and constraints[0].failure_signature.startswith("physics:")
    assert feedbacks[0]["category"] == "physics" and "diagnosis" in feedbacks[0]
    lines = [json.loads(x) for x in (tmp_path / "run" / "loop.jsonl").read_text().splitlines()]
    accepted = next(r for r in lines if r.get("decision") == "accepted")
    assert accepted["rewrite_tokens"] == 1000
    assert lines[-1]["event"] == "end" and lines[-1]["rewrite_tokens"] == 1000


def test_none_from_generate_is_a_budget_stop(tmp_path):
    res, _ = run(tmp_path, FakeGenerate(tmp_path / "gen", budget_calls=0), cycles=10)
    assert res.stopped == "budget" and res.incumbent.version == 0


def test_feedback_dict_carries_the_category_and_diagnosis_not_the_parameters(tmp_path):
    gen = FakeGenerate(tmp_path / "gen")
    run(tmp_path, gen, cycles=30)
    fb = gen.calls[0][2][0]
    assert {"termination_reason", "case_id", "category", "diagnosis"} <= set(fb)
    assert "params" not in fb and "severity" not in fb
    assert fb["diagnosis"]["mode"] and 0.0 <= fb["diagnosis"]["confidence"] <= 1.0
    assert feedback_dict  # exported for System 1


def test_boolean_gate_keeps_system_1s_semantics():
    inc = {"a": True, "b": True, "c": False}
    assert not regression_gate(inc, {"a": True, "b": True, "c": False}).accepted  # no improvement
    assert regression_gate(inc, {"a": True, "b": True, "c": True}).accepted
    assert not regression_gate(inc, {"a": True, "b": False, "c": True}).accepted  # regression
    assert not regression_gate(inc, {"b": True, "c": True}).accepted  # missing result never passes
    assert regression_gate(inc, {"a": True, "b": True, "c": True}).mode == "strict"


def test_cli_refuses_muse_code_without_an_explicit_budget(tmp_path):
    with pytest.raises(SystemExit):
        run_main(["--synthesizer", "muse-code", "--out", str(tmp_path)])


def test_rewrite_cost_is_logged_in_dollars(tmp_path):
    gen = FakeGenerate(tmp_path / "gen", tokens=40_000)
    run(tmp_path, gen, cycles=30, usd_per_million_tokens=13.5)
    lines = [json.loads(x) for x in (tmp_path / "run" / "loop.jsonl").read_text().splitlines()]
    accepted = next(r for r in lines if r.get("decision") == "accepted")
    assert accepted["rewrite_cost_usd"] == 0.54
    end = lines[-1]
    assert end["rewrites"] == 1 and end["rewrite_cost_usd"] == 0.54
    assert end["cost_per_rewrite_usd"] == 0.54 and end["usd_per_million_tokens"] == 13.5


def test_summary_adds_system_2_tokens_and_cost_per_cycle(tmp_path):
    from ants.orchestrator.run import add_total_cost

    path = tmp_path / "summary.json"
    path.write_text(json.dumps({"rewrite_tokens": 40_000, "cycles_run": 4}), encoding="utf-8")
    add_total_cost(path, 60_000, 13.5)
    s = json.loads(path.read_text(encoding="utf-8"))
    assert s["total_tokens"] == 100_000 and s["total_cost_usd"] == 1.35
    assert s["adversary_cost_usd"] == 0.81 and s["cost_per_cycle_usd"] == 0.3375
