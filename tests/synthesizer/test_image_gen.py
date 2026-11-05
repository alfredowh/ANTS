import base64
import json

import pytest

from ants.synthesizer.generator import build_messages, repair_message
from ants.synthesizer.image_gen import ImageBudgetExceeded, ImageGenerator, data_url


def _gen(tmp_path, cap, calls):
    g = ImageGenerator(tmp_path / "c", tmp_path / "l.jsonl", max_images=cap)
    g._post = lambda prompt, source: calls.append(prompt) or b"png"
    return g


def test_cache_and_cap(tmp_path):
    calls = []
    g = _gen(tmp_path, 1, calls)
    a = g.goal_scene("stack bowl on plate")
    assert g.goal_scene("stack bowl on plate") == a and len(calls) == 1
    with pytest.raises(ImageBudgetExceeded):
        g.goal_scene("other task")
    lines = (tmp_path / "l.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["from_cache"] for x in lines] == [False, True]


def test_images_become_content_parts(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    url = data_url(img)
    assert url.endswith(base64.b64encode(b"x").decode())
    msgs = build_messages("API", "EX", "ex", "task", images=[("Goal scene:", url)])
    assert msgs[1]["content"][-1]["image_url"]["url"] == url
    assert build_messages("API", "EX", "ex", "task")[1]["content"] == "Task: task"
    assert isinstance(repair_message({"a": 1}, images=[("Goal:", url)])["content"], list)
    assert isinstance(repair_message({"a": 1})["content"], str)
