"""Local dashboard: architecture, perception and agentic tabs over one MuseOrchestrator cycle.

    uv run python -m ants.studio.dashboard <cycle_dir>

Everything in the agentic tab comes from what `MuseOrchestrator` already writes to disk
(`program.py`, `incumbent.py`, `reply.md`, `trace.jsonl`, `usage.json`). The architecture tab reads
a hand-maintained manifest (`docs/orchestrator/architecture_manifest.json`) -- nothing generates it
from a run yet, so node status reflects what is committed, not a live pointer into this cycle.
The perception tab is a link/instructions panel for ASPIRE's own Viser+MCP page, not a rebuilt 3D
viewer: nothing here duplicates it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ants.evalkit.runlog import unified_diff

TEMPLATE = Path(__file__).with_name("dashboard_template.html")
REPO_ROOT = Path(__file__).resolve().parents[3]
ARCHITECTURE_MANIFEST = REPO_ROOT / "docs" / "orchestrator" / "architecture_manifest.json"
VISER_URL = "http://127.0.0.1:8080"
MCP_URL = "http://127.0.0.1:8222/mcp/"


def _task_rows(events: list[dict]) -> list[dict]:
    """One row per Muse Code task (a model call, a tool, a reminder agent), in first-seen order."""
    tasks: dict[str, dict] = {}
    order: list[str] = []
    for event in events:
        payload_type = event.get("payload_type", "")
        if not payload_type.startswith("task.lifecycle."):
            continue
        payload = event["payload"]
        task_id = payload.get("task_id")
        if task_id is None:
            continue
        if task_id not in tasks:
            tasks[task_id] = {"task_id": task_id, "kind": None, "status": "proposed"}
            order.append(task_id)
        inner = payload.get("event") or {}
        kind = inner.get("kind") or payload.get("kind")
        if inner.get("task_kind"):
            tasks[task_id]["kind"] = inner["task_kind"]
        if kind in ("proposed", "accepted", "started", "completed"):
            tasks[task_id]["status"] = kind
    return [tasks[t] for t in order if tasks[t]["kind"]]


def _why(reply_text: str) -> str:
    return "\n".join(ln for ln in reply_text.splitlines() if ln.strip().startswith("WHY:"))


def collect(cycle_dir: Path) -> dict[str, Any]:
    usage = json.loads((cycle_dir / "usage.json").read_text(encoding="utf-8"))
    reply = (cycle_dir / "reply.md").read_text(encoding="utf-8")
    events = [
        json.loads(line)
        for line in (cycle_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    candidate = (cycle_dir / "program.py").read_text(encoding="utf-8")
    incumbent_path = cycle_dir / "incumbent.py"
    incumbent = incumbent_path.read_text(encoding="utf-8") if incumbent_path.exists() else ""
    diff = unified_diff(incumbent, candidate, "incumbent.py", "program.py") if incumbent else ""
    architecture = json.loads(ARCHITECTURE_MANIFEST.read_text(encoding="utf-8"))
    return {
        "architecture": architecture,
        "perception": {
            "viser_url": VISER_URL,
            "mcp_url": MCP_URL,
            "start_cmd": "ASPIRE/scripts/start_system2.sh --profile <hardware-profile>",
        },
        "agentic": {
            "cycle_dir": str(cycle_dir),
            "usage": usage,
            "why": _why(reply),
            "tasks": _task_rows(events),
            "event_count": len(events),
            "candidate_program": candidate,
            "diff": diff,
        },
    }


def build(cycle_dir: Path) -> Path:
    data = json.dumps(collect(cycle_dir), default=str).replace("</", "<\\/")
    page = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", data)
    out = cycle_dir / "dashboard.html"
    out.write_text(page, encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m ants.studio.dashboard <muse_orchestrator_cycle_dir>")
        return 2
    print(build(Path(args[0])).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
