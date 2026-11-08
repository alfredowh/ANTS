"""Serve ANTS Studio with a logged run shown as the current /policy-dev run (for demo recordings).

The run's generation events are copied into a replay folder line by line on request, so the
attempts panel fills in as it would live. Only logged files are shown; nothing is generated.
"""

from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path

from ants.studio import console_server, policy_dev

REPO = Path(__file__).resolve().parents[2]


class Replay:
    def __init__(self, source: Path, out: Path) -> None:
        self.source, self.run_dir = source, out
        gen = out / "generation"
        if out.exists():
            shutil.rmtree(out)
        gen.mkdir(parents=True)
        for arm in source.iterdir():
            if arm.is_dir():
                # a copy: the server refuses symlinks that leave the run folder
                shutil.copytree(arm, gen / arm.name)
        self.lines = (source / "events.jsonl").read_text(encoding="utf-8").splitlines()
        self.events = gen / "events.jsonl"
        self.events.write_text("", encoding="utf-8")
        self.shown = 0

    def show_through_attempt(self, attempt: int) -> None:
        """Append logged events until every event of `attempt` is shown."""
        keep = []
        for line in self.lines:
            e = json.loads(line)
            if "attempt" in e and int(e["attempt"]) > attempt:
                break
            keep.append(line)
        self.events.write_text("\n".join(keep) + "\n", encoding="utf-8")


def start(replay: Replay, port: int, task: str) -> None:
    orig = policy_dev.Manager.__init__

    def init(self, *a, **k):
        orig(self, *a, **k)
        self.current = {"task": task, "video": None, "run_dir": str(replay.run_dir), "settings": {}}

    policy_dev.Manager.__init__ = init
    t = threading.Thread(
        target=console_server.serve, kwargs={"port": port, "sessions_dir": None}, daemon=True
    )
    t.start()
