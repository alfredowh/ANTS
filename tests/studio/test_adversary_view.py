"""The Adversary side of ANTS Studio: Daniel's page served for the current run. No tokens."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from ants.studio import adversary_view, console_server
from ants.studio.adversary_view import SWITCH_MARKER
from ants.studio.build import TEMPLATE, build
from ants.studio.run import run as studio_run


@pytest.fixture(scope="module")
def fixture_run(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("runs") / "run-1"
    studio_run(out, attacks=3)
    (out / "aspire" / "x_nominal" / "media" / "videos").mkdir(parents=True)
    (out / "aspire" / "x_nominal" / "media" / "videos" / "n.mp4").write_bytes(b"0123456789")
    return out


def test_template_edit_is_one_inert_comment():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert text.count(SWITCH_MARKER) == 1
    assert SWITCH_MARKER.startswith("<!--") and SWITCH_MARKER.endswith("-->")


def test_standalone_page_has_no_switch(fixture_run):
    page = build(fixture_run).read_text(encoding="utf-8")
    assert SWITCH_MARKER in page
    assert "ants-switch" not in page and "antsSetView" not in page


def test_served_page_adds_only_the_switch(fixture_run):
    standalone = build(fixture_run).read_text(encoding="utf-8")
    served = adversary_view.inject(standalone)
    assert 'class="ants-switch"' in served and SWITCH_MARKER not in served
    assert "antsSetView" in served
    # his markup, routes and player are all still there
    for needle in ('id="tab-harden"', 'id="tab-replay"', 'id="tab-versions"', "initPlayer()"):
        assert needle in served
    assert served.index('class="ants-switch"') < served.index('id="tab-harden"')


def test_empty_page_is_honest_and_has_the_switch():
    page = adversary_view.page(None)
    assert "No Adversary run in this session yet" in page and 'class="ants-switch"' in page


def test_latest_run_needs_run_json(tmp_path):
    (tmp_path / "run-2").mkdir()
    (tmp_path / "run-1").mkdir()
    (tmp_path / "run-1" / "run.json").write_text("{}", encoding="utf-8")
    assert adversary_view.latest_run(tmp_path).name == "run-1"
    assert adversary_view.latest_run(tmp_path / "missing") is None
    assert adversary_view.latest_run(None) is None


def test_media_path_only_serves_videos_inside_the_run(fixture_run, tmp_path):
    rel = "aspire/x_nominal/media/videos/n.mp4"
    assert adversary_view.media_path(fixture_run, rel) is not None
    assert adversary_view.media_path(fixture_run, "run.json") is None
    assert adversary_view.media_path(fixture_run, "../../secret.mp4") is None
    assert adversary_view.media_path(None, rel) is None


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, (0, 9)),
        ("bytes=2-4", (2, 4)),
        ("bytes=5-", (5, 9)),
        ("bytes=-3", (7, 9)),
        ("bytes=20-", (None, 0)),
        ("junk", (None, 0)),
    ],
)
def test_byte_range(header, expected):
    assert adversary_view.byte_range(header, 10) == expected


def _server(tmp_path, adversary_run=None):
    incumbent = tmp_path / "policy.py"
    incumbent.write_text("# incumbent\n", encoding="utf-8")
    state = console_server.RunState()
    handler = console_server.make_handler(
        state,
        incumbent,
        loop_cfg=console_server.LoopRunConfig(),
        scene_generation_path=None,
        sessions_dir=tmp_path / "sessions",
        adversary_run=adversary_run,
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, state, f"http://127.0.0.1:{httpd.server_address[1]}"


def _get(url: str, headers: dict | None = None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_routes_page_video_ranges_and_refusals(fixture_run, tmp_path):
    httpd, _, base = _server(tmp_path, adversary_run=fixture_run)
    try:
        code, _, body = _get(base + "/adversary/")
        assert code == 200 and b'class="ants-switch"' in body and b'id="tab-harden"' in body
        rel = "/adversary/aspire/x_nominal/media/videos/n.mp4"
        code, headers, body = _get(base + rel)
        assert code == 200 and body == b"0123456789" and headers["Accept-Ranges"] == "bytes"
        code, headers, body = _get(base + rel, {"Range": "bytes=2-4"})
        assert code == 206 and body == b"234" and headers["Content-Range"] == "bytes 2-4/10"
        assert _get(base + rel, {"Range": "bytes=99-"})[0] == 416
        assert _get(base + "/adversary/run.json")[0] == 404
        assert _get(base + "/adversary/..%2F..%2Fx.mp4")[0] == 404
        # the removed views are gone
        for gone in ("/agentview/x", "/sam3/x", "/perception/planviewer", "/views/adversary_stub"):
            assert _get(base + gone)[0] == 404, gone
        code, _, body = _get(base + "/")
        assert code == 200 and b"ANTS Studio" in body and b"studio_switch.js" in body
        assert _get(base + "/static/studio_switch.js")[0] == 200
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_no_run_gives_the_empty_state(tmp_path):
    httpd, _, base = _server(tmp_path)
    try:
        code, _, body = _get(base + "/adversary/")
        assert code == 200 and b"No Adversary run in this session yet" in body
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_live_loop_run_renders_on_his_page(tmp_path, monkeypatch):
    """A console run writes what his page needs. The rewrite is stubbed, so no Muse call."""
    import ants.orchestrator.muse_orchestrator as mo

    class NoBudget:
        def __init__(self, **_kw):
            pass

        def __call__(self, *_a):
            return None  # budget spent: the loop stops without a model call

    monkeypatch.setattr(mo, "MuseOrchestrator", NoBudget)
    state = console_server.RunState()
    cfg = console_server.LoopRunConfig(out_dir=tmp_path / "runs", cycles=3)
    incumbent = Path("examples/bowl_on_plate/policy.py").resolve()
    console_server.run_live_loop(state, incumbent, cfg)
    run_dir = adversary_view.latest_run(tmp_path / "runs")
    assert run_dir is not None
    meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert meta["nominal"]["events"] and "finished" in meta
    assert (run_dir / "policy.py").read_text(encoding="utf-8") == incumbent.read_text(
        encoding="utf-8"
    )
    page = adversary_view.page(run_dir)
    assert 'class="ants-switch"' in page and "cannot be rendered" not in page
    assert '"attacks": [{' in page
