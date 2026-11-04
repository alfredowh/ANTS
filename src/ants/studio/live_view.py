"""The live simulator panel: frames of the rollout in progress, read-only.

`enable()` makes every rollout started by this console tee its video frames into a temporary folder
through `tools/ants_live_hook/sitecustomize.py`; no other command gets the hook. `LiveView` answers
the panel's polling routes (short requests, no held connection, so a tab never uses up the browser's
per-site limit). A frame is only called live while the process that wrote it is alive.
"""

from __future__ import annotations

import atexit
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parents[3] / "tools" / "ants_live_hook"
_CAMERA = re.compile(r"^[A-Za-z0-9_]+$")
LABEL_STAGES = {"nominal", "generate", "attack", "rewrite", "gate"}


def _alive(pid: object) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


class LiveView:
    def __init__(self, folder: Path) -> None:
        self.dir = folder
        self.stage = ""

    def observe(self, event: dict) -> None:
        """Remember what the last started stage said it is doing: the label's only source."""
        if event.get("kind") == "pipeline_stage" and event.get("stage") in LABEL_STAGES:
            # a rollout outside any started stage (the nominal run for the Replay) gets no label
            started = event.get("status") == "started"
            self.stage = str(event.get("detail") or event["stage"]) if started else ""
        elif event.get("kind") == "done":
            self.stage = ""

    def status(self, running: bool, now: float | None = None) -> dict:
        try:
            s = json.loads((self.dir / "status.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"active": False}
        active = running and not s.get("ended") and _alive(s.get("pid"))
        if not active:
            return {"active": False}
        frame_time = s.get("frame_time")
        now = time.time() if now is None else now
        return {
            "active": True,
            "pid": s.get("pid"),
            "cameras": s.get("cameras", []),
            "frames": s.get("frames", 0),
            "step": s.get("step"),
            "age_s": round(now - frame_time, 1) if frame_time else None,
            "stage": self.stage,
            "seed": s.get("seed"),
            "program": Path(s["program"]).name if s.get("program") else None,
            "perturbation": s.get("perturbation") or {},
        }

    def frame(self, camera: str) -> bytes | None:
        if not _CAMERA.match(camera):
            return None
        try:
            return (self.dir / f"{camera}.jpg").read_bytes()
        except OSError:
            return None


def enable() -> LiveView:
    """Hand the hook to this process's future children. Called once, by the console server."""
    folder = Path(tempfile.mkdtemp(prefix="ants-live-"))
    atexit.register(shutil.rmtree, folder, ignore_errors=True)
    os.environ["ANTS_LIVE_DIR"] = str(folder)
    previous = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, [str(HOOK_DIR), previous]))
    return LiveView(folder)
