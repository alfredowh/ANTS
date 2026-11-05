import json

from ants.contracts import Constraint
from ants.evalkit.corrections import (
    CorrectionStore,
    make_correction,
    retrieve_corrections,
    signature_from_trace,
)

FB_A = {
    "termination_reason": "timeout",
    "failed_calls": [
        {
            "tool": "move_to_pose",
            "status": "timeout",
            "steps_executed": 823,
            "error": "timeout after 823 steps",
            "final_position_error_m": 0.043,
        }
    ],
    "stdout_tail": "run A numbers",
}
FB_B = {
    "termination_reason": "timeout",
    "failed_calls": [
        {
            "tool": "move_to_pose",
            "status": "timeout",
            "steps_executed": 641,
            "error": "different wording",
            "final_position_error_m": 0.031,
        }
    ],
    "stdout_tail": "run B numbers",
}


def _record(tmp_path):
    c = Constraint("c000", "size:move_to_pose:timeout", "when larger", "Re-localize first.")
    return make_correction(
        c,
        FB_A,
        trigger_case_id="case-1",
        parent_id="v0",
        repaired_id="v1",
        repair_diff="--- v0\n+++ v1\n+re-localize\n",
        gate={"accepted": True, "improvements": ["case-1"], "regressions": []},
        epoch=1,
    )


def test_signature_ignores_volatile_feedback_detail():
    assert signature_from_trace(FB_A) == signature_from_trace(FB_B)
    sig = signature_from_trace(FB_A)
    assert sig.key(2) == "move_to_pose|timeout"
    assert sig.key(1) == "timeout"


def test_store_retrieves_by_signature_for_a_different_program(tmp_path):
    store = CorrectionStore(tmp_path / "corrections.jsonl")
    rec = _record(tmp_path)
    store.append(rec)
    # FB_B comes from another run/program: only the signature is shared.
    chosen, candidates = retrieve_corrections(store.load(), FB_B, k=2)
    assert [r["correction_id"] for r in chosen] == [rec["correction_id"]]
    assert candidates[0]["level"] in (2, 3)
    assert chosen[0]["rule"] == "Re-localize first."
    assert "re-localize" in chosen[0]["repair_diff"]


def test_retrieval_miss_and_split_guard(tmp_path):
    store = CorrectionStore(tmp_path / "corrections.jsonl")
    rec = _record(tmp_path)
    store.append(rec)
    other = {
        "termination_reason": "slip",
        "failed_calls": [{"tool": "close_gripper", "status": "slip"}],
    }
    chosen, _ = retrieve_corrections(store.load(), other, k=2)
    assert chosen == []
    held = dict(rec, correction_id="held1", split="held_out")
    import pytest

    with pytest.raises(ValueError):
        store.append(held)  # the writer itself rejects held-out records
    # a poisoned line written by hand is still filtered at retrieval time
    with (tmp_path / "corrections.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(held) + "\n")
    chosen, _ = retrieve_corrections(store.load(), FB_B, k=5)
    assert all(r["correction_id"] != "held1" for r in chosen)
    rows = (tmp_path / "corrections.jsonl").read_text().splitlines()
    assert json.loads(rows[0])["status"] == "admitted"
