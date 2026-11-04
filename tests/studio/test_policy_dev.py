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
        if "ants.studio.stock_scene" in text:
            return FakeProc([], 1)  # writes nothing
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
                row = {"kind": "program", "attempt": n, "tokens": 40000, "from_cache": n == 0}
                fh.write(json.dumps(row) + "\n")
                ok = n in self.passing
                fh.write(json.dumps({"kind": "rollout", "attempt": n, "success": ok}) + "\n")
        return FakeProc(lines, 0)


def _preview(task, summary, out, root, scene_text=None):
    SCENES.append(scene_text)
    return {"path": str(out / "prompt_messages.json"), "chars": 10, "has_demo": summary is not None,
            "has_scene": scene_text is not None}  # fmt: skip


SCENES: list = []


def _settings(**over):
    settings, error = pd.parse_settings(over, SKILL)
    assert error is None
    return settings


def _run(tmp_path, world, video=True, stop=lambda: False, jobs=(), scene=True, **over):
    events, loops, attacks = [], [], []
    if scene:
        text = tmp_path / SKILL["scene_context"]["text"]
        text.parent.mkdir(parents=True, exist_ok=True)
        text.write_text("Scene, measured\n", encoding="utf-8")
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"v")
    (tmp_path / "run").mkdir(exist_ok=True)
    req = pd.Request(
        "put the bowl on the plate", clip if video else None, tmp_path / "run", _settings(**over)
    )
    pd.Pipeline(
        req, SKILL, events.append,
        run_loop=lambda *a: loops.append(a), run_attacks=lambda *a: attacks.append(a),
        stop_requested=stop, popen=world, root=tmp_path,
        simulator_jobs=lambda: list(jobs), prompt_preview=_preview,
    ).run()  # fmt: skip
    return events, loops, req, attacks


def _stages(events):
    return [(e["stage"], e["status"]) for e in events if e["kind"] == "pipeline_stage"]


def _done(events):
    return [e for e in events if e["kind"] == "done"]


def test_full_chain_order_and_program_reaches_the_loop(tmp_path):
    events, loops, req, _ = _run(tmp_path, FakeWorld())
    stages = _stages(events)
    order = [s for s, st in stages if st == "done"]
    assert order[:4] == ["video", "extract", "demospec", "prompt"]
    assert ("generate", "started") in stages
    assert ("nominal", "failed") in stages and ("nominal", "done") in stages
    program, task, run_dir, budget, settings = loops[0]
    assert program.name == "program_attempt1.py"
    assert (task, run_dir) == (req.task, req.run_dir)
    # one uncached attempt of 40k: 300k cap - 40k - 50k headroom
    assert budget == 210_000
    assert settings["attacks"] == 2
    assert (req.run_dir / "pipeline.jsonl").is_file()
    assert (req.run_dir / "generation.log").is_file()


def test_every_stage_event_follows_the_contract(tmp_path):
    events, *_ = _run(tmp_path, FakeWorld())
    rows = [e for e in events if e["kind"] == "pipeline_stage"]
    assert rows
    for e in rows:
        assert e["stage"] in pd.STAGES
        assert e["status"] in ("started", "done", "failed", "skipped")
        assert "detail" in e and "cycle" in e


def test_settings_are_logged_in_the_run_folder(tmp_path):
    _, _, req, _ = _run(tmp_path, FakeWorld(), max_retries=3, strategy="uniform")
    logged = json.loads((req.run_dir / "settings.json").read_text(encoding="utf-8"))
    assert logged["max_retries"] == 3
    assert logged["eta"] == 1.0
    assert logged["task"] == req.task


def test_generation_command_is_demo_arm_stock_scene_acceptance_seed(tmp_path):
    world = FakeWorld()
    _run(tmp_path, world, max_retries=5)
    cmd = next(c for c in world.calls if "ants.orchestrator.demo_vs_nodemo" in c)
    get = lambda f: cmd[cmd.index(f) + 1]  # noqa: E731
    assert get("--arms") == "demo"
    assert get("--temperatures") == "0.2"
    assert get("--repairs") == "5"
    assert get("--token-budget") == "250000"  # the cap minus one call of headroom
    assert get("--debug-seed") == "51"
    assert get("--eval-seeds") == ""
    assert (get("--suite"), get("--task-id")) == ("libero_goal_swap", "8")
    assert (get("--scenes"), get("--debug-scene")) == ("stock", "stock")


def test_generation_sends_the_stock_scene_text_and_e3_evidence(tmp_path):
    world = FakeWorld()
    SCENES.clear()
    _, _, req, _ = _run(tmp_path, world)
    cmd = next(c for c in world.calls if "ants.orchestrator.demo_vs_nodemo" in c)
    text = tmp_path / SKILL["scene_context"]["text"]
    assert cmd[cmd.index("--scene-text-file") + 1] == str(text)
    assert cmd[cmd.index("--evidence") + 1] == "e3"
    assert (cmd[cmd.index("--scenes") + 1], cmd[cmd.index("--debug-scene") + 1]) == (
        "stock",
        "stock",
    )
    assert "S4_L" not in str(text)  # those describe the scaled scene
    assert SCENES == ["Scene, measured"]  # the preview gets what generation reads (stripped)
    assert json.loads((req.run_dir / "settings.json").read_text("utf-8"))["scene_text"] == str(text)
    rows = (req.run_dir / "pipeline.jsonl").read_text("utf-8")
    assert '"kind": "scene_context"' in rows and str(text) in rows


def test_scene_that_cannot_be_measured_spends_nothing(tmp_path):
    world = FakeWorld()
    events, loops, _, _ = _run(tmp_path, world, scene=False)
    assert any("ants.studio.stock_scene" in c for c in world.calls)
    assert not any("ants.orchestrator.demo_vs_nodemo" in c for c in world.calls)
    assert ("prompt", "failed") in _stages(events) and not loops
    assert _done(events)[0]["stopped"] == "no_working_policy"


def test_preview_puts_the_scene_in_the_prompt(tmp_path):
    aspire = tmp_path / "ASPIRE"
    (aspire / "docs").mkdir(parents=True)
    (aspire / "docs" / "api-reference.md").write_text("API", encoding="utf-8")
    from ants.orchestrator.demo_vs_nodemo import EXAMPLE

    (aspire / EXAMPLE).parent.mkdir(parents=True, exist_ok=True)
    (aspire / EXAMPLE).write_text("EX", encoding="utf-8")
    info = pd.build_prompt_preview("t", None, tmp_path, tmp_path, "SCENE-MARKER")
    assert info["has_scene"]
    assert "SCENE-MARKER" in (tmp_path / "prompt_messages.json").read_text("utf-8")


def test_stock_command_with_contacts_uses_the_launcher_only_then():
    src = (pd.REPO_ROOT / "src/ants/orchestrator/demo_vs_nodemo.py").read_text("utf-8")
    assert "launcher=launcher if args.contacts else None" in src


def test_extraction_uses_the_measured_marker_and_the_logged_setup(tmp_path):
    world = FakeWorld()
    _run(tmp_path, world)
    cmd = next(c for c in world.calls if "scripts/02_extract_demos.py" in c)
    assert cmd[cmd.index("--marker-size-m") + 1] == "0.0575"
    assert cmd[cmd.index("--intrinsics") + 1] == "data/camera_intrinsics_s10e.npz"
    assert cmd[cmd.index("--cuts") + 1] == "data/raw/e1/cuts.json"


def test_rejected_clip_stops_before_any_generation_and_says_why(tmp_path):
    world = FakeWorld(usable=False)
    events, loops, *_ = _run(tmp_path, world)
    assert not loops
    assert not any("demo_vs_nodemo" in " ".join(c) for c in world.calls)
    assert _done(events)[0]["stopped"] == "extraction_rejected"
    assert ("extract", "failed") in _stages(events)
    assert any("no grasp detected" in e.get("detail", "") for e in events)
    assert any("no video" in e.get("detail", "") for e in events)


def test_last_attempt_failing_uses_the_attempt_that_passed(tmp_path):
    world = FakeWorld(passing=(0,), attempts=3)
    _, loops, *_ = _run(tmp_path, world)
    assert loops[0][0].name == "program_attempt0.py"


def test_no_passing_attempt_is_never_attacked(tmp_path):
    events, loops, *_ = _run(tmp_path, FakeWorld(passing=()))
    assert not loops
    assert _done(events)[0]["stopped"] == "no_working_policy"


def test_budget_stop_during_generation_is_named_as_such(tmp_path):
    class Spent(FakeWorld):
        def _generate(self, cmd):
            proc = super()._generate(cmd)
            out = Path(cmd[cmd.index("--out") + 1])
            rec = out / cmd[cmd.index("--arms") + 1] / "sample0" / "record.json"
            data = json.loads(rec.read_text(encoding="utf-8"))
            rec.write_text(json.dumps({**data, "stopped": "budget"}), encoding="utf-8")
            return proc

    events, loops, *_ = _run(tmp_path, Spent(passing=()))
    assert not loops
    assert _done(events)[0]["stopped"] == "budget"


def test_no_video_is_a_visible_no_demo_run(tmp_path):
    world = FakeWorld()
    events, loops, *_ = _run(tmp_path, world, video=False)
    assert ("video", "skipped") in _stages(events)
    assert ("demospec", "skipped") in _stages(events)
    assert not any("02_extract_demos" in " ".join(c) for c in world.calls)
    cmd = next(c for c in world.calls if "ants.orchestrator.demo_vs_nodemo" in c)
    assert cmd[cmd.index("--arms") + 1] == "nodemo"
    assert loops


def test_adversary_off_saves_to_deploy_and_never_attacks(tmp_path):
    events, loops, _, attacks = _run(tmp_path, FakeWorld(), adversary=False)
    assert not loops and not attacks
    assert ("deploy", "done") in _stages(events)
    assert _done(events)[0]["stopped"] == "deployed"
    assert (tmp_path / "data" / "deploy" / "latest.py").read_text(encoding="utf-8") == "# 1"
    assert json.loads((tmp_path / "data" / "deploy" / "latest.json").read_text("utf-8"))


def test_synthesizer_off_attacks_the_given_script_with_no_generation(tmp_path):
    script = tmp_path / "main.py"
    script.write_text("result = 1", encoding="utf-8")
    world = FakeWorld()
    events, loops, req, attacks = _run(tmp_path, world, synthesizer=False, main_script=str(script))
    assert not loops and attacks
    assert attacks[0][0].read_text(encoding="utf-8") == "result = 1"
    assert ("generate", "skipped") in _stages(events)
    assert not any("demo_vs_nodemo" in " ".join(c) for c in world.calls)
    assert not any("--muse-code" in c for c in world.calls)


def test_settings_validation(tmp_path):
    assert (
        "nothing to run" in pd.parse_settings({"synthesizer": False, "adversary": False}, SKILL)[1]
    )
    assert "main robot script" in pd.parse_settings({"synthesizer": False}, SKILL)[1]
    bad = tmp_path / "a.txt"
    bad.write_text("x", encoding="utf-8")
    assert ".py" in pd.parse_settings({"synthesizer": False, "main_script": str(bad)}, SKILL)[1]
    assert (
        "not found"
        in pd.parse_settings(
            {"synthesizer": False, "main_script": str(tmp_path / "gone.py")}, SKILL
        )[1]
    )
    assert "Attacks" in pd.parse_settings({"attacks": 0}, SKILL)[1]
    assert "whole number" in pd.parse_settings({"attacks": "x"}, SKILL)[1]
    assert "not an option" in pd.parse_settings({"strategy": "x"}, SKILL)[1]
    assert "Acceptance seeds" in pd.parse_settings({"seeds": 16}, SKILL)[1]


def test_settings_defaults_and_seeds_stay_in_the_acceptance_range():
    s = _settings()
    assert (s["max_retries"], s["attacks"], s["seeds"], s["token_cap"]) == (5, 2, 1, 300_000)
    assert (s["synthesizer"], s["adversary"], s["strategy"], s["eta"]) == (
        True,
        True,
        "thompson",
        0.2,
    )
    assert pd.nominal_seeds(s, SKILL) == (51,)
    assert pd.nominal_seeds(_settings(seeds=15), SKILL) == tuple(range(51, 66))
    assert _settings(strategy="uniform")["eta"] == 1.0


def test_worst_case_note_is_honest_about_the_cap():
    note = pd.worst_case_note(_settings(), SKILL)
    assert "$4.05" in note and "budget stop" in note  # 8 calls x 46k > 250k
    assert "budget stop" not in pd.worst_case_note(_settings(max_retries=1, adversary=False), SKILL)


def test_preflight_failure_and_other_simulator_spend_nothing(tmp_path):
    world = FakeWorld(preflight=1)
    events, *_ = _run(tmp_path, world)
    assert _done(events)[0]["stopped"] == "preflight_failed"
    assert len(world.calls) == 1
    world = FakeWorld()
    (tmp_path / "b").mkdir()
    events, *_ = _run(tmp_path / "b", world, jobs=["pid 1: aspire_launch.py"])
    assert _done(events)[0]["stopped"] == "preflight_failed"
    assert len(world.calls) == 1


def test_stop_during_generation_is_user_stop_not_budget(tmp_path):
    flag = {"on": False}

    def on_call(cmd):
        if "demo_vs_nodemo" in " ".join(cmd):
            flag["on"] = True

    events, loops, *_ = _run(tmp_path, FakeWorld(on_call=on_call), stop=lambda: flag["on"])
    assert not loops
    assert _done(events)[0]["stopped"] == "user_stop"


def test_observed_adversary_reports_around_the_real_mock_attack(tmp_path):
    from ants.adversary import Adversary, AdversaryConfig
    from ants.contracts import Policy

    code = Path("examples/bowl_on_plate/policy.py").read_text(encoding="utf-8")
    events = []
    adv = pd.ObservedAdversary(
        Adversary.from_config(AdversaryConfig(history_path=tmp_path / "h.jsonl")), events.append
    )
    report = adv.attack(Policy("p", 0, "put the bowl on the plate", code))
    seq = [(e["stage"], e["status"]) for e in events]
    assert seq[:2] == [("attack", "started"), ("attack", "done")]
    assert (("diagnose", "done") in seq) == (report.failure is not None)
    assert all(e["cycle"] == 0 for e in events)
    assert adv.discovered_failures is not None  # everything else passes through


def test_observed_synthesizer_and_gate_verdict():
    class Adv:
        cycle = 4

    class Synth:
        result = None

        def rewrite(self, inc, fb, cons):
            return self.result

    class P:
        version = 1

    events = []
    synth = Synth()
    obs = pd.ObservedSynthesizer(synth, events.append, Adv())
    assert obs.rewrite(P, [], []) is None
    assert [(e["stage"], e["status"]) for e in events] == [
        ("rewrite", "started"),
        ("rewrite", "failed"),
    ]
    events.clear()
    synth.result = P
    assert obs.rewrite(P, [], []) is P
    assert ("gate", "started") in [(e["stage"], e["status"]) for e in events]
    assert all(e["cycle"] == 4 for e in events)
    v = pd.gate_verdict_event({"event": "cycle", "cycle": 4, "decision": "rejected"})
    assert (v["stage"], v["status"], v["detail"], v["cycle"]) == ("gate", "done", "rejected", 4)
    assert pd.gate_verdict_event({"event": "cycle", "decision": "no_failure"}) is None


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


def test_pick_file_dialog_paths(tmp_path):
    ext = SKILL["video"]["extensions"]
    env = {"DISPLAY": ":0"}
    yes = lambda _: "/usr/bin/zenity"  # noqa: E731
    seen = {}

    def run(cmd, **_kw):
        seen["cmd"] = cmd
        return Done(out="/v/clip.mp4\n")

    r = pd.pick_file(tmp_path, ext, run=run, which=yes, env=env)
    assert r == {"ok": True, "path": "/v/clip.mp4", "name": "clip.mp4"}
    assert any(a.startswith(f"--filename={tmp_path}") for a in seen["cmd"])
    assert pd.pick_file(tmp_path, ext, run=lambda *a, **k: Done(1), which=yes, env=env) == {
        "ok": False,
        "cancelled": True,
    }
    assert pd.pick_file(tmp_path, ext, which=lambda _: None, env=env)["fallback"]
    assert pd.pick_file(tmp_path, ext, which=yes, env={})["fallback"]
    r = pd.pick_file(tmp_path, ext, run=lambda *a, **k: Done(out="/v/a.exe"), which=yes, env=env)
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
        lambda e: None, set_running=set_running,
        run_loop=lambda *a: None, run_attacks=lambda *a: None,
        stop_requested=lambda: False, clear_stop=lambda: None, runs_dir=lambda: tmp_path,
        skill=SKILL, pipeline=Fake,
    )  # fmt: skip
    assert not m.start("open the drawer", None)["ok"]
    assert (
        "nothing to run"
        in m.start("put the bowl on the plate", None, {"synthesizer": False, "adversary": False})[
            "error"
        ]
    )
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


def test_other_simulator_jobs_ignores_shells_that_only_mention_a_marker(tmp_path):
    marker = pd.SIMULATOR_MARKERS[0]
    for pid, argv in {
        "11": ["/bin/bash", "-c", f"ps | grep {marker}"],
        "12": ["python", marker],
    }.items():
        (tmp_path / pid).mkdir()
        (tmp_path / pid / "cmdline").write_bytes("\0".join(argv).encode())
    found = pd.other_simulator_jobs(proc=tmp_path, own=1)
    assert len(found) == 1 and found[0].startswith("pid 12")
