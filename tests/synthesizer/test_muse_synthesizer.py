from pathlib import Path

import pytest

from ants.contracts import (
    CaseSpec,
    Constraint,
    Failure,
    Feedback,
    Outcome,
    Perturbation,
    Policy,
    RolloutResult,
    Split,
)
from ants.orchestrator.workflow import load_workflow
from ants.synthesizer.llm import ChatClient
from ants.synthesizer.muse_synthesizer import MuseSynthesizer, default_synthesizer

ASPIRE_REF = Path(__file__).resolve().parents[2] / "ASPIRE" / "docs" / "api-reference.md"
ASPIRE_EXAMPLE = (
    Path(__file__).resolve().parents[2] / "ASPIRE" / "examples" / "libero" / "object_swap_seed1.py"
)
needs_aspire = pytest.mark.skipif(
    not (ASPIRE_REF.exists() and ASPIRE_EXAMPLE.exists()),
    reason="ASPIRE checkout not present",
)

INCUMBENT = Policy(policy_id="p", version=0, task="put the bowl on the plate", code="result = {}")
CASE = Perturbation(category="physics", severity=0.5, params={})
TEST_CASE = CaseSpec("acc-1", "libero_goal_swap", 8, 51, Split.ACCEPTANCE)
CONSTRAINT = Constraint(
    constraint_id="c0",
    failure_signature="physics:move_to_pose:grasp_slip",
    when_to_apply="heavy or slippery objects",
    rule="Scale grasp force with estimated mass and friction.",
)
FEEDBACK = Feedback(
    policy_id="p",
    version=0,
    constraint=CONSTRAINT,
    failure=Failure(mode="grasp_slip", root_cause="fixed grasp force", confidence=0.9),
    case=CASE,
    rollout=RolloutResult(outcome=Outcome.FAILURE),
    test_case=TEST_CASE,
)


def _fake_reply(text: str, tokens: int = 50) -> dict:
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": tokens, "completion_tokens": tokens},
    }


def test_rewrite_builds_candidate_with_constraints_and_failures(tmp_path, monkeypatch):
    client = ChatClient("m", tmp_path / "cache", tmp_path / "ledger.jsonl", token_budget=10_000)
    seen = {}

    def fake_post(messages, temperature):
        seen["messages"] = messages
        return _fake_reply("```python\nresult = {'ok': True}\n```"), 0.1

    monkeypatch.setattr(client, "_post", fake_post)
    synth = MuseSynthesizer(client, "API", "EX", "other task", INCUMBENT.task)

    candidate = synth.rewrite(INCUMBENT, [FEEDBACK], [CONSTRAINT])

    assert candidate is not None
    assert candidate.version == 1
    assert candidate.parent_version == 0
    assert candidate.constraints == ("c0",)
    assert candidate.code == "result = {'ok': True}\n"
    assert candidate.metadata["synthesizer"] == "muse"
    joined = " ".join(str(m["content"]) for m in seen["messages"])
    assert "Scale grasp force" in joined
    assert "acc-1" in joined
    assert "grasp_slip" in joined


def test_rewrite_prepends_the_workflow_to_the_system_prompt(tmp_path, monkeypatch):
    client = ChatClient("m", tmp_path / "cache", tmp_path / "ledger.jsonl", token_budget=10_000)
    seen = {}

    def fake_post(messages, temperature):
        seen["messages"] = messages
        return _fake_reply("```python\nresult = {'ok': True}\n```"), 0.1

    monkeypatch.setattr(client, "_post", fake_post)
    synth = MuseSynthesizer(client, "API", "EX", "other task", INCUMBENT.task)

    assert synth.rewrite(INCUMBENT, [FEEDBACK], [CONSTRAINT]) is not None

    system = seen["messages"][0]
    assert system["role"] == "system"
    assert system["content"].startswith(load_workflow())


@needs_aspire
def test_default_synthesizer_matches_demo_prompt_and_logs_to_run_dir(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    synth = default_synthesizer(INCUMBENT.task, token_budget=1000, run_dir=run_dir)

    assert synth.task == INCUMBENT.task
    assert synth.example_task == "pick up the alphabet soup and place it in the basket"
    assert synth.api_reference == ASPIRE_REF.read_text(encoding="utf-8")
    assert synth.example_program == ASPIRE_EXAMPLE.read_text(encoding="utf-8")
    assert synth.client.model == "muse-wonder-1.0"
    assert synth.client.token_budget == 1000

    def fake_post(messages, temperature):
        return _fake_reply("```python\nresult = {'ok': True}\n```"), 0.1

    monkeypatch.setattr(synth.client, "_post", fake_post)
    assert synth.rewrite(INCUMBENT, [FEEDBACK], [CONSTRAINT]) is not None
    assert len((run_dir / "llm_ledger.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    assert any((run_dir / "llm_cache").glob("*.json"))


@needs_aspire
def test_default_synthesizer_hard_budget_returns_none_without_network(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    synth = default_synthesizer(INCUMBENT.task, token_budget=0, run_dir=run_dir)
    monkeypatch.setattr(
        synth.client,
        "_post",
        lambda m, t: (_ for _ in ()).throw(AssertionError("no network")),
    )

    assert synth.rewrite(INCUMBENT, [FEEDBACK], [CONSTRAINT]) is None
    assert not (run_dir / "llm_ledger.jsonl").exists()


def test_rewrite_returns_none_when_budget_is_spent(tmp_path, monkeypatch):
    client = ChatClient("m", tmp_path / "cache", tmp_path / "ledger.jsonl", token_budget=0)
    monkeypatch.setattr(
        client, "_post", lambda m, t: (_ for _ in ()).throw(AssertionError("should not be called"))
    )
    synth = MuseSynthesizer(client, "API", "EX", "other task", INCUMBENT.task)

    assert synth.rewrite(INCUMBENT, [FEEDBACK], [CONSTRAINT]) is None
