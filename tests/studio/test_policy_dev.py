"""The /policy-dev pipeline with every subprocess faked: no Muse call, no GPU, no simulator."""

from __future__ import annotations

import json
from pathlib import Path

from ants.studio import policy_dev as pd

SKILL = pd.load_skill()


class FakeProc:
    def __init__(self, lines: list[str], code: int) -> None:
        self.stdout, self.code = iter(lines), code

    def wait(self) -> int:
        return self.code


class FakeWorld:
    """Plays each tool: writes the files the real one writes."""

    def __init__(self, *, usable=True, passing=(1,), attempts=2, preflight=0, on_call=None):
        self.usable, self.passing, self.attempts = usable, passing, attempts
        self.preflight_code, self.on_call = preflight, on_call
        self.calls: list[list[str]] = []

    def __call__(self, cmd, **_kw):
        self.calls.append(cmd)
        if self.on_call:
            self.on_call(cmd)
        text = " ".join(cmd)
        if "preflight" in text:
            return FakeProc(["[ok  ] GPU\n"], self.preflight_code)
        if "02_extract_demos" in text:
            out = Path(cmd[cmd.index("--out") + 1])
            out.mkdir(parents=True, exist_ok=True)
            report = {
                "usable": self.usable,
                "reasons": [] if self.usable else ["no grasp detected"],
            }
            (out / "summary.json").write_text(json.dumps([report]), encoding="utf-8")
            (out / f"{Path(cmd[2]).stem}.npz").write_bytes(b"x")
            return FakeProc(["[OK  ] clip\n"], 0)
        if "hurobo_demospec" in text:
            Path(cmd[cmd.index("--out") + 1]).write_text(
                json.dumps({"summary": {"grasp": 1}}), encoding="utf-8"
            )
            return FakeProc([], 0)
        return self._generate(cmd)

    def _generate(self, cmd):
        out = Path(cmd[cmd.index("--out") + 1])
        arm = cmd[cmd.index("--arms") + 1]
        sample = out / arm / "sample0"
        sample.mkdir(parents=True)
        lines, attempts = [], []
        for n in range(self.attempts):
            ok = n in self.passing
            (sample / f"program_attempt{n}.py").write_text(f"# {n}", encoding="utf-8")
            attempts.append({"attempt": n, "trace": {"task_success": ok}})
            lines.append(f"[{arm} s0 a{n}] success={ok} reason=x\n")
        (sample / "record.json").write_text(json.dumps({"attempts": attempts}), encoding="utf-8")
        with (out / "events.jsonl").open("w", encoding="utf-8") as fh:
            for n in range(self.attempts):
                fh.write(
                    json.dumps({"kind": "program", "tokens": 40000, "from_cache": n == 0}) + "\n"
                )
        return FakeProc(lines, 0)


def _preview(task, summary, out, root):
    return {"path": str(out / "prompt_messages.json"), "chars": 10, "has_demo": summary is not None}


def _run(tmp_path, world, video=True, stop=lambda: False, jobs=()):
    events, loops = [], []
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"v")
    req = pd.Request("put the bowl on the plate", clip if video else None, tmp_path / "run")
    pd.Pipeline(
        req, SKILL, events.append,
        run_loop=lambda *a: loops.append(a), stop_requested=stop, popen=world, root=tmp_path,
        simulator_jobs=lambda: list(jobs), prompt_preview=_preview,
    ).run()  # fmt: skip
    return events, loops, req


def _stages(events):
    return [(e["stage"], e["status"]) for e in events if e["kind"] == "pipeline_stage"]


def _done(events):
    return [e for e in events if e["kind"] == "done"]


def test_full_chain_order_and_program_reaches_the_loop(tmp_path):
    events, loops, req = _run(tmp_path, FakeWorld())
    order = [s for s, st in _stages(events) if st in ("ok", "finished")]
    assert order == ["preflight", "extraction", "demospec", "prompt", "nominal", "adversary"]
    program, task, run_dir, budget = loops[0]
    assert program.name == "program_attempt1.py"
    assert (task, run_dir) == (req.task, req.run_dir)
    # one uncached attempt of 40k: 300k total - 40k - 50k headroom
    assert budget == 210_000
    assert (req.run_dir / "pipeline.jsonl").is_file()
    assert (req.run_dir / "generation.log").is_file()


def test_generation_command_is_demo_arm_stock_scene_acceptance_seed(tmp_path):
    world = FakeWorld()
    _run(tmp_path, world)
    cmd = next(c for c in world.calls if "ants.orchestrator.demo_vs_nodemo" in c)
    get = lambda f: cmd[cmd.index(f) + 1]  # noqa: E731
    assert get("--arms") == "demo"
    assert get("--temperatures") == "0.2"
    assert get("--token-budget") == "150000"
    assert get("--debug-seed") == "51"
    assert get("--eval-seeds") == ""
    assert (get("--suite"), get("--task-id")) == ("libero_goal_swap", "8")
    assert (get("--scenes"), get("--debug-scene")) == ("stock", "stock")


def test_extraction_uses_the_measured_marker_and_the_logged_setup(tmp_path):
    world = FakeWorld()
    _run(tmp_path, world)
    cmd = next(c for c in world.calls if "scripts/02_extract_demos.py" in c)
    assert cmd[cmd.index("--marker-size-m") + 1] == "0.0575"
    assert cmd[cmd.index("--intrinsics") + 1] == "data/camera_intrinsics_s10e.npz"
    assert cmd[cmd.index("--cuts") + 1] == "data/raw/e1/cuts.json"


def test_rejected_clip_stops_before_any_generation_and_says_why(tmp_path):
    world = FakeWorld(usable=False)
    events, loops, _ = _run(tmp_path, world)
    assert not loops
    assert not any("demo_vs_nodemo" in " ".join(c) for c in world.calls)
    assert _done(events)[0]["stopped"] == "extraction_rejected"
    assert any("no grasp detected" in e.get("detail", "") for e in events)
    assert any("no video" in e.get("detail", "") for e in events)


def test_last_attempt_failing_uses_the_attempt_that_passed(tmp_path):
    world = FakeWorld(passing=(0,), attempts=3)
    _, loops, _ = _run(tmp_path, world)
    assert loops[0][0].name == "program_attempt0.py"


def test_no_passing_attempt_is_never_attacked(tmp_path):
    events, loops, _ = _run(tmp_path, FakeWorld(passing=()))
    assert not loops
    assert _done(events)[0]["stopped"] == "no_working_policy"


def test_no_video_is_a_visible_no_demo_run(tmp_path):
    world = FakeWorld()
    events, loops, _ = _run(tmp_path, world, video=False)
    assert ("demospec", "skipped") in _stages(events)
    assert not any("02_extract_demos" in " ".join(c) for c in world.calls)
    cmd = next(c for c in world.calls if "ants.orchestrator.demo_vs_nodemo" in c)
    assert cmd[cmd.index("--arms") + 1] == "nodemo"
    assert loops


def test_preflight_failure_and_other_simulator_spend_nothing(tmp_path):
    world = FakeWorld(preflight=1)
    events, _, _ = _run(tmp_path, world)
    assert _done(events)[0]["stopped"] == "preflight_failed"
    assert len(world.calls) == 1
    world = FakeWorld()
    (tmp_path / "b").mkdir()
    events, _, _ = _run(tmp_path / "b", world, jobs=["pid 1: aspire_launch.py"])
    assert _done(events)[0]["stopped"] == "preflight_failed"
    assert len(world.calls) == 1


def test_stop_during_generation_is_user_stop_not_budget(tmp_path):
    flag = {"on": False}

    def on_call(cmd):
        if "demo_vs_nodemo" in " ".join(cmd):
            flag["on"] = True

    events, loops, _ = _run(tmp_path, FakeWorld(on_call=on_call), stop=lambda: flag["on"])
    assert not loops
    assert _done(events)[0]["stopped"] == "user_stop"


def test_budget_helpers():
    assert pd.loop_budget(300_000, 200_000, 50_000) == 50_000
    assert pd.loop_budget(300_000, 260_000, 50_000) < 0


def test_task_guard():
    assert pd.task_problem("put the bowl on the plate", SKILL) is None
    assert "only has the bowl-on-plate" in pd.task_problem("open the drawer", SKILL)
    assert "Type the task" in pd.task_problem("  ", SKILL)


def test_video_guard_and_upload_names(tmp_path):
    bad = tmp_path / "x.exe"
    bad.write_bytes(b"x")
    assert "allowed" in pd.video_problem(bad, SKILL)
    assert "not found" in pd.video_problem(tmp_path / "gone.mp4", SKILL)
    assert pd.video_problem(None, SKILL) is None
    ext = SKILL["video"]["extensions"]
    assert pd.safe_upload_name("../../a b.mp4", ext) == "a_b.mp4"
    assert pd.safe_upload_name("run.sh", ext) is None


class Done:
    def __init__(self, code=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


def test_pick_video_dialog_paths(tmp_path):
    ext = SKILL["video"]["extensions"]
    env = {"DISPLAY": ":0"}
    yes = lambda _: "/usr/bin/zenity"  # noqa: E731
    seen = {}

    def run(cmd, **_kw):
        seen["cmd"] = cmd
        return Done(out="/v/clip.mp4\n")

    r = pd.pick_video(tmp_path, ext, run=run, which=yes, env=env)
    assert r == {"ok": True, "path": "/v/clip.mp4", "name": "clip.mp4"}
    assert any(a.startswith(f"--filename={tmp_path}") for a in seen["cmd"])
    assert pd.pick_video(tmp_path, ext, run=lambda *a, **k: Done(1), which=yes, env=env) == {
        "ok": False,
        "cancelled": True,
    }
    assert pd.pick_video(tmp_path, ext, which=lambda _: None, env=env)["fallback"]
    assert pd.pick_video(tmp_path, ext, which=yes, env={})["fallback"]
    r = pd.pick_video(tmp_path, ext, run=lambda *a, **k: Done(out="/v/a.exe"), which=yes, env=env)
    assert not r["ok"] and "allowed" in r["error"]


def test_manager_refuses_second_run_and_bad_input_without_starting(tmp_path):
    started = []

    class Fake:
        def __init__(self, req, *a, **k):
            started.append(req)

        def run(self):
            pass

    running = {"on": False}

    def set_running(on):
        if on and running["on"]:
            return False
        running["on"] = on
        return True

    m = pd.Manager(
        lambda e: None, set_running=set_running, run_loop=lambda *a: None,
        stop_requested=lambda: False, clear_stop=lambda: None, runs_dir=lambda: tmp_path,
        skill=SKILL, pipeline=Fake,
    )  # fmt: skip
    assert not m.start("open the drawer", None)["ok"]
    assert not running["on"]
    running["on"] = True
    assert "in progress" in m.start("put the bowl on the plate", None)["error"]
    assert not started
    running["on"] = False
    assert m.start("put the bowl on the plate", None)["ok"]


def test_other_simulator_jobs_scans_proc(tmp_path):
    p = tmp_path / "123"
    p.mkdir()
    (p / "cmdline").write_bytes(b"python\0tools/aspire_launch.py\0spec.json\0")
    q = tmp_path / "124"
    q.mkdir()
    (q / "cmdline").write_bytes(b"python\0-m\0cap_harness.services.sam3\0")
    jobs = pd.other_simulator_jobs(tmp_path, own=1)
    assert len(jobs) == 1 and "123" in jobs[0]


def test_native_env_drops_snap_library_paths():
    env = pd.native_env(
        {"LD_LIBRARY_PATH": "/snap", "GTK_PATH": "/snap", "DISPLAY": ":1",
         "XDG_DATA_DIRS": "/snap", "XDG_DATA_DIRS_VSCODE_SNAP_ORIG": "/usr/share"}
    )  # fmt: skip
    assert "LD_LIBRARY_PATH" not in env and "GTK_PATH" not in env
    assert env["DISPLAY"] == ":1" and env["XDG_DATA_DIRS"] == "/usr/share"
