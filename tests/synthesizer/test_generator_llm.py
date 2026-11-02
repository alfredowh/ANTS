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
