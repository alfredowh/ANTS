"""workflow.md is what Muse Wonder reads about the loop; it must name what loop.py does."""

import json

from ants.orchestrator.loop import DECISIONS, EVENTS, STOP_REASONS
from ants.orchestrator.workflow import load_workflow, workflow_info

from .test_loop import V0, loop


def test_the_workflow_names_every_stop_reason_decision_and_event():
    text = load_workflow()
    missing = [n for n in (*STOP_REASONS, *DECISIONS, *EVENTS) if f"`{n}`" not in text]
    assert missing == []


def test_the_workflow_states_the_enforced_rules():
    text = load_workflow()
    for rule in ("no worse on every case", "better on at least one", "W = 3", "ρ = 0.8"):
        assert rule in text


def test_the_run_log_records_which_workflow_it_followed(tmp_path):
    loop(("physics",), cycles=2, out=tmp_path).run(V0)
    start = json.loads((tmp_path / "loop.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert start["workflow"] == workflow_info()
    assert start["workflow"]["version"] == "0.1" and len(start["workflow"]["sha256"]) == 12
