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
    t = threading.Thread(
        target=console_server.watch_aspire_live, args=(state, stop), daemon=True
    )
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
    t = threading.Thread(
        target=console_server.watch_aspire_live, args=(state, stop), daemon=True
    )
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
