import json

from ants.evalkit.report import build, collect


def _trace(success: bool) -> dict:
    return {
        "case_id": "debug-51", "policy_id": "p", "program_ok": True, "task_success": success,
        "termination_reason": "task_succeeded" if success else "program_completed",
        "calls": [{"name": "open_gripper", "ok": True, "failure_code": None, "duration_s": 0.1}],
        "error": None, "run_dir": None, "wall_s": 1.0,
    }  # fmt: skip


def test_collect_and_build_from_a_run_dir(tmp_path):
    sample = tmp_path / "demo" / "sample0"
    sample.mkdir(parents=True)
    (sample / "program_attempt0.py").write_text("x = 1\n", encoding="utf-8")
    (sample / "program_attempt1.py").write_text("x = 2\n", encoding="utf-8")
    record = {
        "arm": "demo", "sample": 0, "temperature": 0.2,
        "attempts": [
            {"attempt": 0, "tokens": 10, "from_cache": False, "trace": _trace(False)},
            {"attempt": 1, "tokens": 5, "from_cache": True, "trace": _trace(True)},
        ],
        "evaluation": [{"scene": "scaled", **_trace(True), "case_id": "eval-scaled-53"}],
    }  # fmt: skip
    (sample / "record.json").write_text(json.dumps(record), encoding="utf-8")
    data = collect(tmp_path)
    s = data["samples"][0]
    assert s["tokens_new"] == 10 and s["tokens_all"] == 15
    assert "-x = 1" in s["attempts"][1]["diff"] and "+x = 2" in s["attempts"][1]["diff"]
    assert s["attempts"][0]["role"] == "initial"
    assert s["evaluation"][0]["scene"] == "scaled" and s["evaluation"][0]["seed"] == 53
    html = build(tmp_path).read_text(encoding="utf-8")
    assert "ANTS run viewer" in html and '"demo/sample0"' in html


def test_build_returns_an_absolute_path_for_a_relative_run_dir(tmp_path, monkeypatch):
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    out = build(__import__("pathlib").Path("run"))
    assert out.is_absolute() and out.as_uri().startswith("file://")


def test_a_folder_of_runs_gives_one_report_with_a_run_choice(tmp_path):
    for name in ("run_a", "run_b"):
        sample = tmp_path / name / "demo" / "sample0"
        sample.mkdir(parents=True)
        (sample / "program_attempt0.py").write_text("x = 1\n", encoding="utf-8")
        record = {"arm": "demo", "sample": 0, "temperature": 0.2, "evaluation": [],
                  "attempts": [{"attempt": 0, "tokens": 1, "from_cache": False,
                                "trace": _trace(True)}]}  # fmt: skip
        (sample / "record.json").write_text(json.dumps(record), encoding="utf-8")
    html = build(tmp_path).read_text(encoding="utf-8")
    assert '"name": "run_a"' in html and '"name": "run_b"' in html
    assert (tmp_path / "report.html").exists()


def test_system2_tab_data_and_view_are_embedded(tmp_path):
    run = tmp_path / "s2"
    run.mkdir()
    (run / "config.json").write_text("{}", encoding="utf-8")
    row = {"cycle": 0, "tests": [], "decision": "no_failure"}
    (run / "system2.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    html = build(run).read_text(encoding="utf-8")
    assert "function system2View" in html and '"decision": "no_failure"' in html
    assert "Correction retrieval (signature cache)" in html
    assert "retrieval not used" in html and "memory_off" in html
