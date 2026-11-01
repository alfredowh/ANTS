import json
from pathlib import Path

from ants.studio.build import _divergence, _line, _phases, collect
from ants.studio.run import run

POLICY = Path(__file__).parents[2] / "examples" / "bowl_on_plate" / "policy.py"


def test_run_writes_logs_and_a_self_contained_page(tmp_path):
    page = run(tmp_path / "r", attacks=6, policy_path=POLICY)
    rows = (tmp_path / "r" / "attacks.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 6 and page.name == "studio.html"
    html = page.read_text(encoding="utf-8")
    assert "/*__DATA__*/" not in html and "</script>" in html
    data = collect(tmp_path / "r")
    assert len(data["attacks"]) == 6 and data["program"].startswith("import math")
    assert data["run"]["nominal"]["outcome"] == "success"
    for a in data["attacks"]:
        assert a["calls"] and set(a["draws"]) == set(data["run"]["config"]["categories"])
        if a["outcome"] == "failure":
            assert a["signature"] and a["rule"] and a["explanation_source"] == "template"


def test_page_data_cannot_close_the_script_tag(tmp_path):
    run(tmp_path / "r", attacks=1, policy_path=POLICY)
    (tmp_path / "r" / "policy.py").write_text("x = '</script><b>'\n", encoding="utf-8")
    from ants.studio.build import build

    html = build(tmp_path / "r").read_text(encoding="utf-8")
    assert html.count("</script>") == 1


def test_phases_follow_the_call_order():
    calls = [{"tool": t} for t in ("open_gripper", "localize_object", "move_to_pose",
             "close_gripper", "move_to_pose", "open_gripper", "move_to_pose")]  # fmt: skip
    assert _phases(calls) == [
        "Setup", "Locate", "Approach", "Grasp", "Transport", "Place", "Retreat"
    ]  # fmt: skip


def test_divergence_is_the_first_call_that_differs_from_nominal():
    nominal = [{"tool": "a", "ok": True}, {"tool": "b", "ok": True}]
    assert _divergence(nominal, nominal) is None
    assert _divergence([{"tool": "a", "ok": True}, {"tool": "b", "ok": False}], nominal) == 1
    assert _divergence([{"tool": "a", "ok": True}], nominal) == 1


def test_root_cause_line_is_parsed():
    assert _line("Line 229 retries only three times") == 229
    assert _line("no line mentioned") is None
    assert json.dumps(_line("see lines 12-14")) == "12"


def test_rerunning_into_the_same_folder_starts_fresh(tmp_path):
    run(tmp_path / "r", attacks=3, policy_path=POLICY)
    run(tmp_path / "r", attacks=3, policy_path=POLICY)
    ids = [a["id"] for a in collect(tmp_path / "r")["attacks"]]
    assert ids == ["atk-00000", "atk-00001", "atk-00002"]
