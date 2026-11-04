"""The live panel's server side and the frame tee, with stub frames: no simulator, no tokens."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ants.studio import live_view

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "tools" / "ants_live_hook" / "sitecustomize.py"


def _hook_module(monkeypatch: pytest.MonkeyPatch, live_dir: Path | None):
    if live_dir is None:
        monkeypatch.delenv("ANTS_LIVE_DIR", raising=False)
    else:
        monkeypatch.setenv("ANTS_LIVE_DIR", str(live_dir))
    before = list(sys.meta_path)
    spec = importlib.util.spec_from_file_location("ants_live_hook_under_test", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    added = [f for f in sys.meta_path if f not in before]
    for finder in added:
        sys.meta_path.remove(finder)
    return module, added


class _Frame:
    def save(self, path, format, quality):  # noqa: A002 -- PIL's parameter name
        Path(path).write_bytes(b"\xff\xd8stub")


@pytest.fixture
def stub_pil(monkeypatch: pytest.MonkeyPatch) -> None:
    """PIL lives in ASPIRE's environment, not in this project's."""
    image = SimpleNamespace(fromarray=lambda rgb: _Frame())
    monkeypatch.setitem(sys.modules, "PIL", SimpleNamespace(Image=image))


def test_without_the_variable_the_hook_does_nothing(monkeypatch):
    _, added = _hook_module(monkeypatch, None)
    assert added == []


def test_enabled_process_children_get_the_hook(tmp_path):
    env = {
        **os.environ,
        "ANTS_LIVE_DIR": str(tmp_path),
        "PYTHONPATH": str(HOOK.parent),
    }
    code = "import sys;print(any(type(f).__name__=='_Finder' for f in sys.meta_path))"
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "True"


def test_recorder_tee_writes_frames_after_the_original_and_is_rate_limited(
    monkeypatch, tmp_path, stub_pil
):
    module, _ = _hook_module(monkeypatch, tmp_path)
    calls: list[int] = []

    class Recorder:
        def _encode_video_frame(self, observation, step):
            calls.append(step)

    module._install(SimpleNamespace(RunRecorder=Recorder))
    obs = SimpleNamespace(cameras={"agentview": SimpleNamespace(rgb=object())})
    (tmp_path / "old.jpg").write_bytes(b"old")
    for step in range(5):
        Recorder()._encode_video_frame(obs, step)
    assert calls == [0, 1, 2, 3, 4]  # the video gets every frame
    assert not (tmp_path / "old.jpg").exists()  # a previous rollout's frame never looks current
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["frames"] == 1 and status["cameras"] == ["agentview"]
    assert (tmp_path / "agentview.jpg").read_bytes()[:2] == b"\xff\xd8"


def test_a_tee_failure_never_reaches_the_rollout(monkeypatch, tmp_path, stub_pil):
    module, _ = _hook_module(monkeypatch, tmp_path / "file")
    (tmp_path / "file").write_text("not a folder", encoding="utf-8")
    calls: list[int] = []

    class Recorder:
        def _encode_video_frame(self, observation, step):
            calls.append(step)

    module._install(SimpleNamespace(RunRecorder=Recorder))
    Recorder()._encode_video_frame(SimpleNamespace(cameras={}), 0)
    Recorder()._encode_video_frame(SimpleNamespace(cameras={}), 1)
    assert calls == [0, 1]


def _status(tmp_path: Path, **fields) -> None:
    row = {"pid": os.getpid(), "ended": False, "frame_time": 100.0, "step": 7, **fields}
    (tmp_path / "status.json").write_text(json.dumps(row), encoding="utf-8")


def test_status_is_active_only_while_a_run_and_its_rollout_are_alive(tmp_path):
    view = live_view.LiveView(tmp_path)
    assert view.status(True) == {"active": False}  # no rollout yet
    _status(tmp_path, cameras=["agentview"], seed="51", program="/x/program_attempt2.py")
    s = view.status(True, now=101.0)
    assert s["active"] and s["age_s"] == 1.0 and s["program"] == "program_attempt2.py"
    assert view.status(False) == {"active": False}  # outside a run
    _status(tmp_path, ended=True)
    assert view.status(True) == {"active": False}
    _status(tmp_path, pid=2**30)  # killed without a clean exit
    assert view.status(True) == {"active": False}


def test_label_comes_from_the_last_started_stage_and_clears_at_the_end(tmp_path):
    view = live_view.LiveView(tmp_path)
    view.observe({"kind": "pipeline_stage", "stage": "nominal", "status": "started", "detail": "A"})
    view.observe({"kind": "pipeline_stage", "stage": "prompt", "status": "started", "detail": "C"})
    assert view.stage == "A"
    view.observe({"kind": "pipeline_stage", "stage": "nominal", "status": "done", "detail": "B"})
    assert view.stage == ""
    view.observe({"kind": "pipeline_stage", "stage": "gate", "status": "started", "detail": "D"})
    view.observe({"kind": "done"})
    assert view.stage == ""


@pytest.mark.parametrize("camera", ["../status", "a/b", "", "status.json"])
def test_frame_route_only_serves_camera_names(tmp_path, camera):
    assert live_view.LiveView(tmp_path).frame(camera) is None


def test_enable_keeps_an_existing_pythonpath(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/existing")
    monkeypatch.delenv("ANTS_LIVE_DIR", raising=False)
    view = live_view.enable()
    assert os.environ["ANTS_LIVE_DIR"] == str(view.dir)
    assert os.environ["PYTHONPATH"] == os.pathsep.join([str(live_view.HOOK_DIR), "/existing"])
