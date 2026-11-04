"""ANTS Studio server tests: sessions, deploy, the shell. No GPU, no tokens."""

from __future__ import annotations

import threading
from pathlib import Path

from ants.studio import console_server


def test_shell_has_one_switch_and_no_removed_views():
    html = console_server._assemble_shell()
    assert html.count('class="view-switch"') == 1
    assert 'id="adversary-view"' in html and "ANTS Studio" in html
    assert 'id="run-folder"' in html and 'id="scene-graph-btn"' in html
    js = console_server.STATIC_FILES["console.js"].read_text(encoding="utf-8")
    for gone in ("perc-mode", "perception", "tabbtn", "__PERCEPTION__"):
        assert gone not in html and gone not in js, gone


def test_server_broadcasts_run_started_before_loop():
    src = Path(console_server.__file__).read_text(encoding="utf-8")
    assert '"kind": "run_started"' in src
    assert src.index('"kind": "run_started"') < src.index("loop.run(policy)")


def _serve(tmp_path, state=None):
    from http.server import ThreadingHTTPServer

    incumbent = tmp_path / "policy.py"
    incumbent.write_text("# incumbent\n", encoding="utf-8")
    state = state or console_server.RunState()
    cfg = console_server.LoopRunConfig()
    handler = console_server.make_handler(
        state,
        incumbent,
        loop_cfg=cfg,
        scene_generation_path=None,
        sessions_dir=tmp_path / "sessions",
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, state, cfg, f"http://127.0.0.1:{httpd.server_address[1]}"


def _post(url: str, body: dict | None = None):
    import json
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        url,
        data=json.dumps(body or {}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_session_folder_logs_events_and_points_runs_into_it(tmp_path):
    import json

    httpd, state, cfg, _ = _serve(tmp_path)
    try:
        s = state.session
        assert s.dir.parent == tmp_path / "sessions" and s.id.startswith("sess-")
        assert cfg.out_dir == s.runs_dir and s.runs_dir.is_dir()
        info = json.loads((s.dir / "session.json").read_text(encoding="utf-8"))
        assert info["id"] == s.id and info["config"]["cycles"] == cfg.cycles
        state.broadcast({"kind": "loop_event", "row": {"event": "x"}})
        state.broadcast(
            {
                "kind": "chat_muse_event",
                "event": {"payload_type": "run.output.delta", "payload": {"text": "hi"}},
            }
        )
        state.broadcast({"kind": "chat_done"})
        events = [
            json.loads(x) for x in (s.dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert [e["kind"] for e in events] == ["loop_event", "chat_muse_event", "chat_done"]
        chat = [
            json.loads(x) for x in (s.dir / "chat.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert chat[-1]["role"] == "assistant" and chat[-1]["text"] == "hi"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_chat_message_is_logged_with_its_case(tmp_path):
    import json

    state = console_server.RunState()
    state.running = True  # a run is active -> the message is queued, no model call
    httpd, state, _, base = _serve(tmp_path, state)
    try:
        status, body = _post(base + "/chat", {"message": "hello"})
        assert status == 200 and body["case"] == "queued"
        row = json.loads(
            (state.session.dir / "chat.jsonl").read_text(encoding="utf-8").splitlines()[0]
        )
        assert (row["role"], row["case"], row["text"]) == ("user", "queued", "hello")
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_new_session_refused_while_running_then_creates_fresh_folder(tmp_path):
    httpd, state, cfg, base = _serve(tmp_path)
    try:
        old = state.session
        state.running = True
        status, body = _post(base + "/session/new")
        assert status == 409 and not body["ok"] and "in progress" in body["error"]
        assert state.session is old
        state.running = False
        state.queued_chat = "stale"
        status, body = _post(base + "/session/new")
        assert status == 200 and body["session"] != old.id
        assert state.session.id == body["session"] and state.queued_chat is None
        assert cfg.out_dir == state.session.runs_dir and old.dir.is_dir()
        kinds = (state.session.dir / "events.jsonl").read_text(encoding="utf-8")
        assert "session_reset" in kinds
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_session_resume_keeps_folder(tmp_path):
    first = console_server.Session(tmp_path, meta={"mode": "loop"})
    first.log_chat("user", "a", "oneshot")
    again = console_server.Session(tmp_path, first.id)
    assert again.dir == first.dir and again.info["started"] == first.info["started"]
    assert again.info["resumed"]


def test_deploy_latest_picks_highest_accepted_version(tmp_path):
    from ants.studio.console_server import deploy_latest

    inc = tmp_path / "policy.py"
    inc.write_text("incumbent", encoding="utf-8")
    out = tmp_path / "deploy"
    assert deploy_latest(None, inc, out)["version"] == 0
    assert (out / "latest.py").read_text(encoding="utf-8") == "incumbent"
    pol = tmp_path / "sess" / "runs" / "run-1" / "policies"
    pol.mkdir(parents=True)
    (pol / "v0.py").write_text("zero", encoding="utf-8")
    (pol / "v2.py").write_text("two", encoding="utf-8")
    info = deploy_latest(tmp_path / "sess", inc, out)
    assert info["version"] == 2
    assert (out / "latest.py").read_text(encoding="utf-8") == "two"


def test_attacks_only_runs_real_mock_attacks_and_ends_with_a_report(tmp_path):
    from ants.studio.console_server import LoopRunConfig, RunState, run_attacks_only

    state = RunState()
    events = state.subscribe()
    program = tmp_path / "main_script.py"
    program.write_text(
        (REPO_ROOT_FOR_TEST / "examples" / "bowl_on_plate" / "policy.py").read_text("utf-8"),
        encoding="utf-8",
    )
    run_attacks_only(state, program, LoopRunConfig(cycles=2), tmp_path, "put the bowl on the plate")
    rows = []
    while not events.empty():
        rows.append(events.get())
    assert rows[-1]["kind"] == "done"
    assert rows[-1]["stopped"] == "attacks_done"
    assert sum(r["kind"] == "attack_event" for r in rows) == 2
    assert len((tmp_path / "attacks.jsonl").read_text("utf-8").splitlines()) == 2


REPO_ROOT_FOR_TEST = Path(__file__).resolve().parents[2]


def test_review_fixes_stay_fixed():
    root = Path(console_server.__file__).parent
    shell = (root / "views" / "shell.html").read_text(encoding="utf-8")
    console = (root / "views" / "agent_console.html").read_text(encoding="utf-8")
    css = (root / "static" / "console.css").read_text(encoding="utf-8")
    wizard = (root / "static" / "wizard.js").read_text(encoding="utf-8")
    assert 'id="run-btn"' not in shell  # /policy-dev is the way to start a run
    for stale in ("Phase A", "not wired", "!important"):
        assert stale not in console
    # #col-center>* sets width:100%; only an id-level rule keeps the tabs at 1 cm
    assert "#col-center>.edge-tab{" in css and "width:38px" in css
    assert 'id="set-cancel"' in wizard and "session_reset" in wizard


def test_served_adversary_page_uses_ui_names_standalone_does_not():
    from ants.studio import adversary_view

    page = "<head></head><body>System 2 attacks, System 1 rewrites, a System 2 run</body>"
    served = adversary_view.inject(page)
    assert "System" not in served.split("<script>")[0].split("</style>")[-1]
    assert "an Adversary run" in served and "Synthesizer rewrites" in served


def test_old_run_route_and_single_mode_are_gone(tmp_path):
    from ants.studio import console

    httpd, _state, _cfg, base = _serve(tmp_path)
    try:
        import urllib.error
        import urllib.request

        req = urllib.request.Request(base + "/run", data=b"{}", method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            code = 200
        except urllib.error.HTTPError as e:
            code = e.code
        assert code == 404
    finally:
        httpd.shutdown()
    assert "--mode" not in Path(console.__file__).read_text(encoding="utf-8")
    assert not hasattr(console_server, "build_prompt")
    js = console_server.STATIC_FILES["console.js"].read_text(encoding="utf-8")
    assert "DATA.mode" not in js and "run-btn" not in console_server._assemble_shell()


def test_queued_chat_fires_when_a_pipeline_run_ends(tmp_path, monkeypatch):
    from ants.studio import policy_dev

    fired = threading.Event()
    monkeypatch.setattr(console_server, "run_chat_oneshot", lambda *a, **k: fired.set())
    captured = {}
    real = policy_dev.Manager

    def spy(emit, **kw):
        captured["set_running"] = kw["set_running"]
        return real(emit, **kw)

    monkeypatch.setattr(policy_dev, "Manager", spy)
    state = console_server.RunState()
    httpd, _state, _cfg, _base = _serve(tmp_path, state)
    try:
        assert captured["set_running"](True)
        state.queued_chat = "after the run"
        captured["set_running"](False)
        assert fired.wait(5)
        assert state.queued_chat is None
    finally:
        httpd.shutdown()


def test_snapshot_and_flow_state_are_tied_to_the_session():
    js = console_server.STATIC_FILES["console.js"].read_text(encoding="utf-8")
    assert "session: currentSessionId" in js and "snap.session !== d.id" in js
    flow = console_server.STATIC_FILES["flow.js"].read_text(encoding="utf-8")
    assert "ants-flow-session" in flow and "let collapsed = true" in flow


def test_scene_panel_is_labelled_with_its_real_source(tmp_path):
    js = console_server.STATIC_FILES["console.js"].read_text(encoding="utf-8")
    assert "as sent to the Synthesizer" in js and "shown for reference" in js
    from ants.studio import policy_dev

    skill = policy_dev.load_skill()
    cmd = policy_dev.generation_command("t", Path("d.json"), Path("o"), 1, 1, True, skill)
    assert cmd[cmd.index("--scenes") + 1] == "stock"
    text = cmd[cmd.index("--scene-text-file") + 1]  # the stock text, never the scaled S4_L* files
    assert Path(text).name == "stock_seed51_S4.txt"
