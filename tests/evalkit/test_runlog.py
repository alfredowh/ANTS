import json

from ants.evalkit.runlog import RunLog, unified_diff


def test_diff_shows_changed_line_and_is_empty_for_identical_programs():
    old = "a = 1\nb = 2\n"
    new = "a = 1\nb = 3\n"
    diff = unified_diff(old, new, "attempt0", "attempt1")
    assert "-b = 2" in diff and "+b = 3" in diff
    assert unified_diff(old, old, "x", "y") == ""


def test_runlog_appends_events_and_writes_files(tmp_path):
    log = RunLog(tmp_path / "run")
    log.event("attempt", arm="demo", n=0)
    log.event("attempt", arm="demo", n=1)
    log.write("demo/sample0/attempt0/program.py", "result = 1\n")
    log.write_json("demo/sample0/attempt0/feedback.json", {"ok": False})
    lines = (tmp_path / "run" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["n"] for x in lines] == [0, 1]
    assert (tmp_path / "run/demo/sample0/attempt0/program.py").read_text(encoding="utf-8")
