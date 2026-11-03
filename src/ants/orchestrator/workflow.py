"""The one workflow file the repair model reads: `docs/orchestrator/phases.md`.

It holds System 1's operating context (Phase A / Phase B, the program rules) and the loop's own
rules (steps, gate, escalation, stop reasons). `MuseOrchestrator` sends it at the top of every
rewrite prompt; `loop.py` executes the same steps, and `tests/orchestrator/test_workflow.py` fails
if the file stops naming a stop reason, decision or log event the loop uses. The loop logs the
file's version and hash in its `start` line, so every run says which workflow it followed.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

WORKFLOW_PATH = Path(__file__).resolve().parents[3] / "docs" / "orchestrator" / "phases.md"


def load_workflow(path: Path | None = None) -> str:
    """The workflow text, to put at the top of the repair model's prompt."""
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
