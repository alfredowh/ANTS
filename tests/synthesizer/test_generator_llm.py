import json

import pytest

from ants.synthesizer.generator import build_messages, demo_section, extract_code
from ants.synthesizer.llm import BudgetExceeded, ChatClient

SUMMARY = {
    "grasp": {
        "radial_offset_over_radius": 1.2,
        "height_over_object_height": 0.82,
        "aperture_at_grasp_m": 0.029,
        "approach_last_0.5s": {"drop_m": 0.05, "horizontal_m": 0.01},
    },
    "carry": {"max_height_above_table_m": 0.23, "duration_s": 3.1},
    "release": {"radial_offset_over_plate_radius": 0.67, "height_above_table_m": 0.14},
    "objects_real": {"bowl": {"diameter_m": 0.138, "height_m": 0.067}, "plate": {}},
}


def test_extract_code_takes_first_fenced_block():
    assert extract_code("text\n```python\nresult = 1\n```\nmore") == "result = 1\n"
    assert extract_code("result = 2") == "result = 2\n"


def test_rules_forbid_sandbox_blocked_builtins():
    # exp11/nodemo attempt 3 died with `NameError: name 'getattr' is not defined`;
    # attempt 4 without getattr/isinstance probing succeeded, so the rule is prompt-level.
    from ants.synthesizer.generator import RULES

    for name in ("getattr", "isinstance", "hasattr", "eval"):
        assert f"`{name}`" in RULES
    assert "try/except AttributeError" in RULES


def test_arms_differ_only_in_demo_section():
    no_demo = build_messages("API", "EX", "other task", "put the bowl on the plate")
    demo = build_messages("API", "EX", "other task", "put the bowl on the plate", SUMMARY)
    assert no_demo[0] == demo[0]
    assert demo[1]["content"].startswith(no_demo[1]["content"])
    assert "RIM" in demo_section(SUMMARY)


def _fake_reply(tokens: int) -> dict:
    return {
        "choices": [{"message": {"content": "```python\nresult = {}\n```"}}],
        "usage": {"prompt_tokens": tokens, "completion_tokens": tokens},
    }


def test_sample_index_and_corrupt_entry_is_a_miss(tmp_path, monkeypatch):
    client = ChatClient("m", tmp_path / "cache", tmp_path / "ledger.jsonl", token_budget=10_000)
    calls = []

    def fake_post(messages, temperature):
        calls.append(1)
        return _fake_reply(100), 0.1

    monkeypatch.setattr(client, "_post", fake_post)
    msgs = [{"role": "user", "content": "a"}]
    assert client.chat(msgs, sample_index=0).from_cache is False
    assert client.chat(msgs, sample_index=1).from_cache is False  # a distinct sample
    assert client.chat(msgs, sample_index=1).from_cache is True
    assert len(calls) == 2

    ledger = [json.loads(x) for x in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    cached_path = tmp_path / "cache" / f"{ledger[-1]['cache_key']}.json"
    cached_path.write_text("{corrupt", encoding="utf-8")
    assert client.chat(msgs, sample_index=1).from_cache is False
    assert len(calls) == 3
    assert list((tmp_path / "cache").glob("*.corrupt*"))


def test_legacy_cache_entry_still_hits_for_sample_zero(tmp_path, monkeypatch):
    import hashlib

    client = ChatClient("m", tmp_path / "cache", tmp_path / "ledger.jsonl", token_budget=10_000)
    monkeypatch.setattr(client, "_post", lambda m, t: (_ for _ in ()).throw(AssertionError))
    msgs = [{"role": "user", "content": "old"}]
    legacy_key = hashlib.sha256(
        json.dumps(["m", msgs, 0.2], sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / f"{legacy_key}.json").write_text(
        json.dumps(_fake_reply(10)), encoding="utf-8"
    )
    assert client.chat(msgs).from_cache is True


def test_canonical_key_hits_similar_repair_but_exact_key_does_not(tmp_path, monkeypatch):
    from ants.synthesizer.generator import repair_cache_key

    client = ChatClient("m", tmp_path / "cache", tmp_path / "ledger.jsonl", token_budget=10_000)
    calls = []
    monkeypatch.setattr(client, "_post", lambda m, t: (calls.append(1), (_fake_reply(100), 0.1))[1])
    base = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "Task: put bowl"},
        {"role": "assistant", "content": "```python\nresult = {}\n```"},
    ]
    fb_a = {
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
    }
    fb_b = {
        "termination_reason": "timeout",
        "stdout_tail": "different printed numbers",
        "failed_calls": [
            {
                "tool": "move_to_pose",
                "status": "timeout",
                "steps_executed": 641,
                "error": "timeout after 641 steps",
                "final_position_error_m": 0.031,
            }
        ],
    }
    key_a = repair_cache_key(base, fb_a)
    assert key_a == repair_cache_key(base, fb_b)
    assert key_a != repair_cache_key(base, {**fb_b, "termination_reason": "slip"})

    msgs_a = [*base, {"role": "user", "content": "repair A 823"}]
    msgs_b = [*base, {"role": "user", "content": "repair B 641"}]
    assert client.chat(msgs_a, canonical_key=key_a).from_cache is False
    similar = client.chat(msgs_b, canonical_key=key_a)
    assert similar.from_cache is True and len(calls) == 1
    ledger = [json.loads(x) for x in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert ledger[-1]["cache_kind"] == "canonical"


def test_cache_and_budget(tmp_path, monkeypatch):
    client = ChatClient("m", tmp_path / "cache", tmp_path / "ledger.jsonl", token_budget=250)
    calls = []

    def fake_post(messages, temperature):
        calls.append(1)
        return _fake_reply(100), 0.1

    monkeypatch.setattr(client, "_post", fake_post)
    msgs = [{"role": "user", "content": "a"}]
    assert client.chat(msgs).from_cache is False
    assert client.chat(msgs).from_cache is True  # same request: no second call
    assert len(calls) == 1 and client.spent() == 200
    client.chat([{"role": "user", "content": "b"}])  # 200 < 250: allowed, now 400
    with pytest.raises(BudgetExceeded):
        client.chat([{"role": "user", "content": "c"}])
    ledger = [json.loads(x) for x in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert [e["from_cache"] for e in ledger] == [False, True, False]
