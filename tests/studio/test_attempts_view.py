"""Generation attempts read while generation is still running."""

import json

from ants.studio import attempts_view


def _run(tmp_path):
    sample = tmp_path / "generation" / "demo" / "sample0"
    frame = sample / "debug_attempt1" / "x" / "media" / "keyframes" / "0001-move"
    frame.mkdir(parents=True)
    (frame / "agentview.png").write_bytes(b"png")
    (sample / "reply_attempt1.md").write_text("WHY: it missed\n```python\nx\n```", encoding="utf-8")
    (sample / "diff_attempt1.diff").write_text("+a\n-b\n", encoding="utf-8")
    (sample / "feedback_attempt0.json").write_text('{"failed_calls": []}', encoding="utf-8")
    events = [
        {"kind": "run_start"},
        {"kind": "program", "arm": "demo", "sample": "0", "attempt": "0", "role": "initial"},
        {"kind": "rollout", "arm": "demo", "sample": "0", "attempt": "0", "success": "False"},
        {"kind": "program", "arm": "demo", "sample": "0", "attempt": "1", "role": "repair"},
    ]
    (tmp_path / "generation" / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events), encoding="utf-8"
    )
    return tmp_path


def test_attempts_without_a_record_file(tmp_path):
    rows = attempts_view.attempts(_run(tmp_path))
    assert [r["attempt"] for r in rows] == [0, 1]
    assert rows[0]["feedback"] == {"failed_calls": []}
    assert "success" not in rows[1]  # its rollout has not finished
    assert rows[1]["why"].startswith("WHY")
    assert rows[1]["diff"].startswith("+a")
    assert rows[1]["frames"][0]["label"] == "0001-move"


def test_no_generation_yet(tmp_path):
    assert attempts_view.attempts(None) == []
    assert attempts_view.attempts(tmp_path) == []


def test_media_stays_inside_the_run_and_is_an_image(tmp_path):
    run = _run(tmp_path / "run") if (tmp_path / "run").mkdir() is None else None
    rel = attempts_view.attempts(run)[1]["frames"][0]["src"]
    assert attempts_view.media_path(run, rel) is not None
    (tmp_path / "secret.png").write_bytes(b"x")
    assert attempts_view.media_path(run, "../secret.png") is None
    assert attempts_view.media_path(run, "generation/events.jsonl") is None
