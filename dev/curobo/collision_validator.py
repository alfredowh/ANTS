"""Second success validator: no forbidden collision during the run.

The task check (LIBERO's `On(bowl, plate)`) only looks at the final state, so a run that pressed
the gripper into the wine rack for 400 steps still counts. This validator reads the per-step
contact log written by `contact_launch.py` and flags every step with a forbidden contact.

Allowed contacts: robot with the target (the bowl), the target with its goal (the plate) and with
the table, and contacts between robot links. Forbidden: the robot touching anything else, and the
target touching anything other than the goal, the table or the robot.

A run is "clean" when it has no forbidden step. A run is a "clean success" when it is clean and
the task check passed.

    python dev/curobo/collision_validator.py RUN_DIR [RUN_DIR ...]
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROBOT_PREFIXES = ("robot0", "gripper0", "mount0")
TARGET = "akita_black_bowl_1_main"
GOAL = "plate_1_main"
SURFACES = ("table",)


def is_robot(body: str) -> bool:
    return body.startswith(ROBOT_PREFIXES)


def forbidden_pair(pair: str, target: str = TARGET, goal: str = GOAL) -> str | None:
    """Return a short label when a contact pair "bodyA | bodyB" is not allowed, else None."""
    a, b = (part.strip() for part in pair.split("|"))
    if is_robot(a) and is_robot(b):
        return None
    if is_robot(a) or is_robot(b):
        other = b if is_robot(a) else a
        return None if other == target else f"robot with {other}"
    if target in (a, b):
        other = b if a == target else a
        return None if other == goal or other in SURFACES else f"{target} with {other}"
    return None


def validate(rows: list[dict], target: str = TARGET, goal: str = GOAL) -> dict:
    """Summarise forbidden contacts in a contact log (a list of per-step records)."""
    steps: Counter[str] = Counter()
    first: dict[str, int] = {}
    bad_steps = set()
    for row in rows:
        for pair in row["contacts"]:
            label = forbidden_pair(pair, target, goal)
            if label is None:
                continue
            steps[label] += 1
            first.setdefault(label, row["step"])
            bad_steps.add(row["step"])
    return {
        "steps_total": len(rows),
        "collision_steps": len(bad_steps),
        "first_collision_step": min(bad_steps) if bad_steps else None,
        "clean": not bad_steps,
        "by_contact": {k: {"steps": v, "first_step": first[k]} for k, v in steps.most_common()},
    }


def load(contact_log: Path) -> list[dict]:
    lines = contact_log.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line]


def main() -> None:
    for run in sys.argv[1:]:
        result = validate(load(Path(run) / "contacts.jsonl"))
        print(run, json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
