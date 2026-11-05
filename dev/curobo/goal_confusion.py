"""Score cuRobo's plan verdicts against the simulator: is a refused goal really in collision?

Reads every `goal_labels.jsonl` written by the launcher's `planner.label_goals` (see
`replay_attach.py`) under the given folders and prints one confusion matrix per folder.

A goal is COLLIDING when, with the arm set to it, the robot penetrates anything but itself and a
held bowl, or a held bowl penetrates anything but the robot, the table or the plate, by more than
TOLERANCE_M. A refusal of a free goal is a false negative; a plan to a colliding goal is a false
positive. Only the goal state is scored, not the path.

    uv run python dev/curobo/goal_confusion.py data/runs/curobo/replay_x/attach [...]
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

TOLERANCE_M = 0.002
ROBOT = ("robot0", "gripper0", "mount0")
BOWL = "akita_black_bowl"
SUPPORT = ("plate", "table", "floor")


def is_robot(body: str) -> bool:
    return body.startswith(ROBOT)


def blocking(row: dict) -> list[str]:
    """Forbidden contact pairs of one labelled goal."""
    out = []
    for a, b, dist in row.get("pairs", []):
        if dist > -TOLERANCE_M or (is_robot(a) and is_robot(b)):
            continue
        has_bowl = a.startswith(BOWL) or b.startswith(BOWL)
        if not has_bowl and not is_robot(a) and not is_robot(b):
            continue  # objects resting on each other: nothing to do with this goal
        if has_bowl and not row.get("held") and not is_robot(a) and not is_robot(b):
            continue  # a bowl that is not held rests where it is
        other = b if a.startswith(BOWL) else a
        if row.get("held") and has_bowl and (is_robot(other) or other.startswith(SUPPORT)):
            continue
        out.append(f"{a} | {b}")
    return out


def score(rows: list[dict]) -> dict:
    cells: Counter = Counter()
    false_negative_messages: Counter = Counter()
    pairs: Counter = Counter()
    for row in rows:
        if "label_error" in row:
            cells["label_error"] += 1
            continue
        hits = blocking(row)
        key = ("plan" if row["ok"] else "refuse") + ("_colliding" if hits else "_free")
        cells[key] += 1
        pairs.update(f"{key}: {pair}" for pair in hits)
        if key == "refuse_free":
            false_negative_messages[row.get("message", "")[:90]] += 1
    return {"cells": cells, "messages": false_negative_messages, "pairs": pairs}


def main(folders: list[str]) -> int:
    for folder in folders:
        rows = []
        for path in sorted(Path(folder).rglob("goal_labels.jsonl")):
            text = path.read_text(encoding="utf-8")
            rows += [json.loads(line) for line in text.splitlines() if line.strip()]
        result = score(rows)
        cells = result["cells"]
        print(f"== {folder}: {len(rows)} plan calls")
        print(
            f"   planned: {cells['plan_free']} free, {cells['plan_colliding']} colliding (false +)"
            f" | refused: {cells['refuse_colliding']} colliding, {cells['refuse_free']} free"
            f" (false -) | label errors: {cells['label_error']}"
        )
        for key, n in result["pairs"].most_common(8):
            print(f"   {n:4d}  {key}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
