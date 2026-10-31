"""Append-only log of one experiment run: events, texts and program changes.

Everything that happens is written to the run directory the moment it happens, so a crashed or
budget-stopped run still leaves a complete record:

    <run>/events.jsonl                one JSON line per event (time, kind, data)
    <run>/<arm>/sample<N>/attempt<K>/ program.py, diff_vs_previous.diff, reply.md,
                                      messages.json, feedback.json (the feedback that led to K+1)
"""

from __future__ import annotations

import difflib
import json
import time
from pathlib import Path


def unified_diff(old: str, new: str, old_name: str, new_name: str) -> str:
    """Unified diff of two program texts (empty string if they are identical)."""
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=old_name,
            tofile=new_name,
        )
    )


class RunLog:
    """Writes events and artefacts under one run directory."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def event(self, kind: str, **data: object) -> None:
        line = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind, **data}
        with (self.root / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, default=str) + "\n")

    def write(self, relpath: str, text: str) -> Path:
        path = self.root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_json(self, relpath: str, obj: object) -> Path:
        return self.write(relpath, json.dumps(obj, indent=1, default=str))

    def append_json(self, relpath: str, obj: object) -> None:
        """Append one JSON object as a line (e.g. one System 2 cycle per line)."""
        path = self.root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, default=str) + "\n")
