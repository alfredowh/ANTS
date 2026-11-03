import json

from ants.studio import dashboard

EVENTS = [
    {
        "payload_type": "task.lifecycle.proposed",
        "payload": {
            "task_id": "t1",
            "event": {"kind": "proposed", "task_kind": "model.meta.response"},
        },
    },
    {
        "payload_type": "task.lifecycle.completed",
        "payload": {"task_id": "t1", "event": {"kind": "completed"}},
    },
    {"payload_type": "run.terminal.completed", "payload": {"terminal": "completed", "text": "x"}},
]


def _write_cycle(tmp_path, *, with_incumbent=True):
    cycle = tmp_path / "cycle1"
    cycle.mkdir()
    (cycle / "usage.json").write_text(
        json.dumps(
            {
                "input_tokens": 100, "output_tokens": 20, "reasoning_tokens": 10,
                "cached_tokens": 0, "spent_total": 120, "budget": 1000,
            }
        ),
        encoding="utf-8",
    )  # fmt: skip
    (cycle / "reply.md").write_text(
        "WHY: fixed the thing\n```python\nresult = {}\n```", encoding="utf-8"
    )
    (cycle / "trace.jsonl").write_text("\n".join(json.dumps(e) for e in EVENTS), encoding="utf-8")
    (cycle / "program.py").write_text("result = {}\n", encoding="utf-8")
    if with_incumbent:
        (cycle / "incumbent.py").write_text("result = None\n", encoding="utf-8")
    return cycle


def test_collect_reads_usage_tasks_and_diff(tmp_path):
    cycle = _write_cycle(tmp_path)
    data = dashboard.collect(cycle)

    assert data["agentic"]["usage"]["spent_total"] == 120
    assert data["agentic"]["why"] == "WHY: fixed the thing"
    assert data["agentic"]["tasks"] == [
        {"task_id": "t1", "kind": "model.meta.response", "status": "completed"}
    ]
    assert "-result = None" in data["agentic"]["diff"]
    assert "+result = {}" in data["agentic"]["diff"]
    assert len(data["architecture"]["nodes"]) > 0
    assert data["perception"]["viser_url"].startswith("http://")


def test_collect_handles_missing_incumbent(tmp_path):
    cycle = _write_cycle(tmp_path, with_incumbent=False)
    data = dashboard.collect(cycle)
    assert data["agentic"]["diff"] == ""


def test_build_writes_html_with_injected_data(tmp_path):
    cycle = _write_cycle(tmp_path)
    out = dashboard.build(cycle)
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "const DATA = " in html
    assert "/*__DATA__*/null" not in html
    assert "fixed the thing" in html
