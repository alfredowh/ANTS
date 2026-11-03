"""MuseOrchestrator against a monkeypatched run_muse: no real API call, no tokens spent."""

from __future__ import annotations

import json

from ants.contracts import BlameTarget, Constraint
from ants.orchestrator import muse_orchestrator as mo
from ants.orchestrator.muse_cli import MuseCliError, MuseRunResult


def _result(text="WHY: x\n```python\nresult = {}\n```", tokens=(10, 5, 3, 0)):
    i, o, r, c = tokens
    return MuseRunResult(
        text=text, input_tokens=i, output_tokens=o, reasoning_tokens=r, cached_tokens=c,
        events=[{"payload_type": "run.terminal.completed", "payload": {"terminal": "completed"}}],
    )  # fmt: skip


def test_generate_writes_candidate_and_trace(tmp_path, monkeypatch):
    monkeypatch.setattr(mo, "run_muse", lambda *a, **k: _result())
    incumbent = tmp_path / "v0.py"
    incumbent.write_text("result = {}\n", encoding="utf-8")
    orch = mo.MuseOrchestrator(out_dir=tmp_path / "runs", token_budget=1000)

    out = orch(incumbent, [], [])

    assert out is not None
    candidate, tokens = out
    assert tokens == 15
    assert candidate.read_text(encoding="utf-8").strip() == "result = {}"
    cycle_dir = tmp_path / "runs" / "cycle1"
    assert (cycle_dir / "reply.md").exists()
    assert (cycle_dir / "trace.jsonl").exists()
    usage = json.loads((cycle_dir / "usage.json").read_text(encoding="utf-8"))
    assert usage["spent_total"] == 15
    assert orch.spent() == 15


def test_generate_stops_once_budget_spent(tmp_path, monkeypatch):
    monkeypatch.setattr(mo, "run_muse", lambda *a, **k: _result(tokens=(60, 60, 0, 0)))
    incumbent = tmp_path / "v0.py"
    incumbent.write_text("result = {}\n", encoding="utf-8")
    orch = mo.MuseOrchestrator(out_dir=tmp_path / "runs", token_budget=100)

    first = orch(incumbent, [], [])
    assert first is not None
    second = orch(incumbent, [], [])
    assert second is None  # 120 spent >= 100 budget


def test_generate_returns_none_on_cli_error(tmp_path, monkeypatch):
    def _raise(*a, **k):
        raise MuseCliError("boom")

    monkeypatch.setattr(mo, "run_muse", _raise)
    incumbent = tmp_path / "v0.py"
    incumbent.write_text("result = {}\n", encoding="utf-8")
    orch = mo.MuseOrchestrator(out_dir=tmp_path / "runs", token_budget=1000)

    assert orch(incumbent, [], []) is None
    assert orch.spent() == 0


def test_prompt_includes_constraints_and_feedback(tmp_path, monkeypatch):
    captured = {}

    def _capture(prompt, **kwargs):
        captured["prompt"] = prompt
        return _result()

    monkeypatch.setattr(mo, "run_muse", _capture)
    incumbent = tmp_path / "v0.py"
    incumbent.write_text("result = {}\n", encoding="utf-8")
    orch = mo.MuseOrchestrator(out_dir=tmp_path / "runs", token_budget=1000)
    constraint = Constraint(
        constraint_id="c1", failure_signature="physics:close_gripper:failed",
        when_to_apply="grasping a light object", rule="lower the grasp force",
        target=BlameTarget.PROGRAM,
    )  # fmt: skip

    orch(incumbent, [constraint], [{"termination_reason": "timeout"}])

    assert "lower the grasp force" in captured["prompt"]
    assert "timeout" in captured["prompt"]
    assert "Phase A" in captured["prompt"]  # phases.md context is included
