"""The workflow file Muse Wonder reads: one markdown description of the whole development loop.

`workflow.md` (next to this module) is the plan; `loop.py` executes it. System 1 puts the text in
Muse Wonder's context (system prompt) when it writes or rewrites a program, so the model knows the
steps, how its rewrite is judged and which rules the code enforces. The loop logs the file's
version and hash in its `start` line, so every run says which workflow it followed.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

WORKFLOW_PATH = Path(__file__).with_name("workflow.md")


def load_workflow(path: Path | None = None) -> str:
    """The workflow text, to prepend to the generator's context."""
    return (path or WORKFLOW_PATH).read_text(encoding="utf-8")


def workflow_info(path: Path | None = None) -> dict[str, str]:
    """Version (from the title, e.g. `v0.1`) and a short sha256 of the text, for the run log."""
    text = load_workflow(path)
    match = re.search(r"\(v(\d+(?:\.\d+)*)\)", text.splitlines()[0] if text else "")
    return {
        "path": (path or WORKFLOW_PATH).name,
        "version": match.group(1) if match else "unknown",
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()[:12],
    }
