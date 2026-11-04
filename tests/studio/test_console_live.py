"""Live-perception wiring tests: no GPU, no ASPIRE, no tokens.

Simulates what cap_harness does during a real rollout (append one keyframe
directory + SAM3 overlay at a time, while the "subprocess" is still running)
and asserts the console's watcher observes it progressively and broadcasts the
events the Perception tab consumes. Also covers the stale-run guard: a finished
run from before the watcher started must never be reported as live.
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

import pytest

from ants.studio import console_server

_PNG = b"\x89PNG\r\n\x1a\n" + b"fake-frame"


def _drain(q, kinds: set[str], timeout: float = 5.0) -> list[dict]:
    got: list[dict] = []
    deadline = time.time() + timeout
    while time.time() < deadline and not kinds <= {e["kind"] for e in got}:
        try:
            got.append(q.get(timeout=0.2))
        except Exception:
            pass
    return got


def test_watcher_broadcasts_keyframes_and_overlays_progressively(tmp_path, monkeypatch):
    monkeypatch.setattr(console_server, "ASPIRE_LIVE_ROOT", tmp_path)
    state = console_server.RunState()
    q = state.subscribe()
    stop = threading.Event()
    t = threading.Thread(target=console_server.watch_aspire_live, args=(state, stop), daemon=True)
    t.start()
    try:
        run = tmp_path / "20260101_000000_0000_s1_test"
        kf = run / "media" / "keyframes" / "000001-before-open-gripper"
        kf.mkdir(parents=True)
        (kf / "agentview.png").write_bytes(_PNG)
        events = _drain(q, {"perception_run", "perception_keyframe"})
        kinds = [e["kind"] for e in events]
        assert "perception_run" in kinds
        frame = next(e for e in events if e["kind"] == "perception_keyframe")
        assert frame["run_id"] == run.name
        assert frame["src"] == f"/live/keyframe/{run.name}/000001-before-open-gripper"

        ov = run / "media" / "overlays"
        ov.mkdir(parents=True)
        (ov / "sam3-000001-camera-agentview.png").write_bytes(_PNG)
        events = _drain(q, {"perception_sam3"})
        assert any(e["kind"] == "perception_sam3" for e in events)
    finally:
        stop.set()
        t.join(timeout=2)


def test_watcher_ignores_runs_finished_before_it_started(tmp_path, monkeypatch):
    old = tmp_path / "old_run"
    kf = old / "media" / "keyframes" / "000001-before-open-gripper"
    kf.mkdir(parents=True)
    (kf / "agentview.png").write_bytes(_PNG)
    import os

    past = time.time() - 3600
    os.utime(old, (past, past))

    monkeypatch.setattr(console_server, "ASPIRE_LIVE_ROOT", tmp_path)
    state = console_server.RunState()
    q = state.subscribe()
    stop = threading.Event()
    t = threading.Thread(target=console_server.watch_aspire_live, args=(state, stop), daemon=True)
    t.start()
    try:
        with pytest.raises(queue.Empty):
            q.get(timeout=1.0)
    finally:
        stop.set()
        t.join(timeout=2)


def test_http_live_route_serves_frame_and_page_loads(tmp_path, monkeypatch):
    """Full path: real HTTP server, /live/keyframe serves a frame from a new run dir."""
    import urllib.request
    from http.server import ThreadingHTTPServer

    run = tmp_path / "run_http"
    kf = run / "media" / "keyframes" / "000002-after-close-gripper"
    kf.mkdir(parents=True)
    (kf / "agentview.png").write_bytes(_PNG)
    monkeypatch.setattr(console_server, "ASPIRE_LIVE_ROOT", tmp_path)

    incumbent = tmp_path / "policy.py"
    incumbent.write_text("# incumbent\n", encoding="utf-8")
    handler = console_server.make_handler(
        console_server.RunState(),
        incumbent,
        loop_cfg=console_server.LoopRunConfig(backend="cap_harness"),
        scene_generation_path=None,
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            page = r.read().decode("utf-8")
        assert "cap_harness" in page  # UI knows it is in real-backend mode
        url = f"http://127.0.0.1:{port}/live/keyframe/{run.name}/000002-after-close-gripper"
        with urllib.request.urlopen(url, timeout=5) as r:
            assert r.status == 200
            assert r.read() == _PNG
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_template_has_live_replay_toggle_and_run_folder():
    """Contract for the Perception source toggle, collapsible logs, scene graph, run folder.

    HTML markup lives in the assembled shell (views/*.html); behaviour lives in the shared
    static/console.js the shell loads via <script src> -- check both, since this is a contract on
    what the served page as a whole provides, not on which file it happens to live in.
    """
    html = console_server._assemble_shell() + console_server.STATIC_FILES["console.js"].read_text(
        encoding="utf-8"
    )
    for needle in (
        'id="perc-mode-auto"',
        'id="perc-mode-live"',
        'id="perc-mode-replay"',
        "percRolloutEnded",
        'id="run-folder"',
        'id="scene-graph-btn"',
        'id="curobo-tgl-collision"',
        'id="curobo-tgl-scan"',
        'id="curobo-tgl-paths"',
        "sceneGraphOn",
    ):
        assert needle in html, needle


def test_plan_viewer_prefers_latest_exp():
    picked = console_server._latest_plan_viewer()
    if picked is not None:  # data-dependent: only assert when cuRobo runs exist locally
        assert "exp11" in str(picked) or "exp1" in str(picked)


def test_server_broadcasts_run_started_before_loop():
    src = Path(console_server.__file__).read_text(encoding="utf-8")
    assert '"kind": "run_started"' in src
    assert src.index('"kind": "run_started"') < src.index("loop.run(policy)")


def test_live_asset_path_refuses_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(console_server, "ASPIRE_LIVE_ROOT", tmp_path)
    assert console_server._live_asset_path("..", "etc/passwd", overlay=False) is None
    assert console_server._live_asset_path("nope", "000001-x", overlay=False) is None


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
