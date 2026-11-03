"""Human gate: when the loop stalls, ask a person for one targeted answer and feed it back.

Ported from System 1 (branch `synthesizer`).

The request is a JSON file next to the run log (`gate_request.json`); the answer is a JSON file
the person (or the Human gate tab of the To-do page) leaves as `gate_answer.json`. A text answer
becomes a `Constraint` in the generator's context, so nothing is trained. Video and teleop answers
need extraction (perception, DemoSpec builder, robot-log reader), which is not wired yet: they are
reported and the loop still escalates.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ants.contracts import Constraint

CHANNELS = ("text", "video", "teleop")


@dataclass
class GateAnswer:
    channel: str  # text | video | teleop
    text: str = ""
    file_name: str | None = None


def write_request(run_dir: Path, escalation: dict, context: str = "development") -> Path:
    path = Path(run_dir) / "gate_request.json"
    path.write_text(json.dumps({"context": context, **escalation}, indent=1), encoding="utf-8")
    return path


def read_answer(run_dir: Path) -> GateAnswer | None:
    path = Path(run_dir) / "gate_answer.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    ans = GateAnswer(**{k: data.get(k) for k in ("channel", "text", "file_name") if k in data})
    if ans.channel not in CHANNELS:
        raise ValueError(f"unknown gate channel {ans.channel!r}")
    return ans


def answer_to_constraint(
    answer: GateAnswer, escalation: Mapping[str, Any], index: int
) -> Constraint | None:
    """A text answer becomes a rule for the failing signature; other channels are not wired."""
    if answer.channel != "text" or not answer.text.strip():
        return None
    return Constraint(
        constraint_id=f"h{index:03d}",
        failure_signature=escalation["signature"],
        when_to_apply=f"when the failure '{escalation['signature']}' appears",
        rule=answer.text.strip(),
        evidence=("human gate", json.dumps(asdict(answer))),
    )
