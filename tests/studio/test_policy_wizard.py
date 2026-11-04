"""The /policy-dev wizard: state machine, defaults, validation, upload whitelist, launch stub.

No Muse call, no GPU: the launcher is a stub and `popen` is faked.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from ants.studio import policy_wizard as pw


def _wiz(tmp_path: Path, specs: list[Path] | None = None) -> pw.Wizard:
    w = pw.Wizard(pw.load_skill(), tmp_path / "w", demospecs=specs or [])
    w.start()
    return w


def _texts(msgs: list[dict]) -> str:
    return "\n".join(m["text"] for m in msgs)


def test_full_flow_synth_only(tmp_path):
    w = _wiz(tmp_path)
    w.handle("pick up the cup")
    w.handle("none")
    w.handle("synthesizer")
    w.handle("50k")
    w.handle("1")
    assert w.current["id"] == "confirm"  # adversary questions skipped for synth only
    assert w.answers == {
        "task": "pick up the cup",
        "demo": "none",
        "mode": "synth",
        "synth_budget": 50000,
        "synth_retries": 1,
    }
    w.handle("yes")
    assert w.status == "confirmed"


def test_defaults_accepted_but_confirm_is_never_skipped(tmp_path):
    w = _wiz(tmp_path)
    w.handle("go with defaults")
    assert w.current["id"] == "confirm"
    assert w.status == "active"
    assert w.answers["task"] == "put the bowl on the plate"
    assert w.answers["synth_budget"] == 100000
    w.handle("go with defaults")  # still not a launch
    assert w.status == "active"
    w.handle("no")
    assert w.status == "cancelled"


def test_adversary_questions_and_strategy_mapping(tmp_path):
    w = _wiz(tmp_path)
    w.handle("task")
    w.handle("none")
    w.handle("2")  # synthesizer + adversary
    assert w.answers["mode"] == "synth_adv"
    w.handle("defaults")
    assert w.answers["adv_cycles"] == 3 and w.answers["adv_stall"] == 2
    assert w.answers["strategy"] == "thompson"
    w2 = _wiz(tmp_path / "b")
    for a in ("task", "none", "synthesizer + adversary", "20k", "0", "5", "3", "random"):
        w2.handle(a)
    assert w2.answers["strategy"] == "uniform"


def test_validation_rejects_bad_budget_and_stays_on_step(tmp_path):
    w = _wiz(tmp_path)
    w.handle("task")
    w.handle("none")
    w.handle("synthesizer")
    assert "outside the allowed range" in _texts(w.handle("5000000"))
    assert "whole number" in _texts(w.handle("lots"))
    assert w.current["id"] == "synth_budget"


def test_summary_requires_explicit_yes_above_100k(tmp_path):
    w = _wiz(tmp_path)
    for a in ("task", "none", "synthesizer", "300k", "2"):
        w.handle(a)
    summary = w.history[-1]["text"]
    assert "above 100,000 tokens" in summary and "$4.05" in summary


def test_cancel_at_any_step_and_nothing_launches(tmp_path):
    w = _wiz(tmp_path)
    w.handle("/cancel")
    assert w.status == "cancelled"
    assert w.handle("anything") == []


def test_demospec_choice_and_video_step(tmp_path):
    spec = tmp_path / "hurobo_1.json"
    spec.write_text("{}", encoding="utf-8")
    w = _wiz(tmp_path, [spec])
    w.handle("task")
    w.handle("demospec")
    w.handle("1")
    assert w.answers["demospec"] == str(spec)
    v = _wiz(tmp_path / "v")
    v.handle("task")
    v.handle("video")
    assert v.current["id"] == "video" and v.snapshot()["awaiting_upload"]
    v.attach_video("demo.mp4")
    assert v.answers["video"] == "demo.mp4" and v.current["id"] == "mode"


def test_every_step_and_answer_is_logged(tmp_path):
    w = _wiz(tmp_path)
    w.handle("my task")
    rows = [
        json.loads(line)
        for line in (w.folder / "wizard.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    events = [r["event"] for r in rows]
    assert events[0] == "start" and "ask" in events and "answer" in events and "set" in events


def test_upload_whitelist_and_target(tmp_path):
    ext = pw.load_skill()["limits"]["video_extensions"]
    assert pw.safe_upload_name("../../etc/pass wd.mp4", ext) == "pass_wd.mp4"
    assert pw.safe_upload_name("evil.py", ext) is None
    assert pw.safe_upload_name("noext", ext) is None
    mgr = pw.WizardManager(lambda e: None, base=tmp_path)
    assert mgr.upload_target("a.mp4") is None  # no wizard yet
    mgr.start()
    mgr.message("task")
    assert mgr.upload_target("a.mp4") is None  # not at the video step
    mgr.message("video")
    target = mgr.upload_target("../x.MOV")
    assert target is not None and target.parent.name == "uploads"
    assert mgr.upload_target("x.exe") is None


def test_launch_needs_reported_for_video_and_missing_prereqs(tmp_path):
    events: list[dict] = []
    ok = pw.launch_generation(
        {"demo": "video", "video": "d.mp4", "mode": "synth", "task": "t"},
        tmp_path,
        events.append,
        root=tmp_path,
    )
    assert ok is False
    msg = events[0]["message"]
    assert "video-to-DemoSpec" in msg and "ASPIRE" in msg and "META_API_KEY" in msg


def test_launch_runs_generation_command_and_loop_with_stub(tmp_path, monkeypatch):
    (tmp_path / "ASPIRE").mkdir()
    (tmp_path / ".env").write_text("META_API_KEY=x\n", encoding="utf-8")
    answers = {
        "task": "t",
        "demo": "none",
        "mode": "synth_adv",
        "synth_budget": 20000,
        "synth_retries": 3,
    }
    seen: dict = {}

    class FakeProc:
        stdout = iter(["line one\n"])

        def wait(self) -> int:
            return 0

    def fake_popen(cmd, **kw):
        seen["cmd"] = cmd
        prog = Path(cmd[cmd.index("--out") + 1]) / "nodemo-s0" / "program_attempt0.py"
        prog.parent.mkdir(parents=True)
        prog.write_text("result = {}\n", encoding="utf-8")
        return FakeProc()

    loops: list[Path] = []
    events: list[dict] = []
    ok = pw.launch_generation(
        answers,
        tmp_path / "w",
        events.append,
        run_loop=lambda p, a: loops.append(p),
        popen=fake_popen,
        root=tmp_path,
    )
    assert ok and loops and loops[0].name == "program_attempt0.py"
    cmd = seen["cmd"]
    assert cmd[cmd.index("--arms") + 1] == "nodemo"
    assert cmd[cmd.index("--repairs") + 1] == "3"
    assert cmd[cmd.index("--token-budget") + 1] == "20000"
    kinds = [e["kind"] for e in events]
    assert kinds == ["wizard_launch", "wizard_output", "wizard_generation_done"]


def test_manager_confirm_launches_in_thread_and_holds_running_flag(tmp_path):
    done = threading.Event()
    flags: list[bool] = []

    def launcher(answers, folder, emit):
        emit({"kind": "wizard_needs", "message": "stub"})
        return False

    events: list[dict] = []

    def emit(e):
        events.append(e)
        if e["kind"] == "wizard_finished":
            done.set()

    def set_running(on: bool) -> bool:
        flags.append(on)
        return True

    mgr = pw.WizardManager(emit, base=tmp_path, launcher=launcher, set_running=set_running)
    mgr.start()
    mgr.message("go with defaults")
    state = mgr.message("yes")
    assert state["status"] == "confirmed"
    assert done.wait(5)
    assert flags == [True, False]
    assert any(e["kind"] == "wizard_needs" for e in events)
