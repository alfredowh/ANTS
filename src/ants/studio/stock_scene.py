"""Measure the scene `/policy-dev` really simulates, for the generator's prompt.

    uv run python -m ants.studio.stock_scene

The `data/scene_text/S4_L*.txt` files describe the SCALED scene (bowl x1.227, plate x1.855) of the
experiments, so they would be wrong for `/policy-dev`, which debugs in the stock scene. This runs
a do-nothing program once in the stock scene on the debug seed (no model, no tokens), has the
launcher dump the settled scene, and writes the same S4 ("combo") description from that dump. It
is simulator truth ("oracle") for that one seed, as in the experiments; a perturbed or other-seed
rollout differs from it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
NOOP_PROGRAM = 'for i in range(8):\n    open_gripper()\nresult = {"settle": True}\n'


def text_from_dump(dump: Path, level: str) -> str:
    from ants.adversary.collision_world import describe, load_world

    return describe(load_world(json.loads(dump.read_text(encoding="utf-8"))), level)


def prep(skill: dict, root: Path = REPO_ROOT) -> Path:
    """One no-op rollout, then the dump and text files named by the skill. Returns the text path."""
    from ants.contracts import CaseSpec, Split
    from ants.evalkit.aspire_harness import CapHarness

    scene, context = skill["scene"], skill["scene_context"]
    dump = root / context["dump"]
    dump.parent.mkdir(parents=True, exist_ok=True)
    noop = dump.parent / "noop_program.py"
    noop.write_text(NOOP_PROGRAM, encoding="utf-8")
    harness = CapHarness(
        Path(os.environ.get("ANTS_ASPIRE_ROOT", root / "ASPIRE")),
        launcher=root / "tools" / "aspire_launch.py",
        scene={"contacts": {"path": str(dump.with_name("contacts.jsonl"))}},
    )
    harness.run(
        CaseSpec(
            "dump-stock", scene["suite"], scene["task_id"], scene["debug_seed"], Split.ACCEPTANCE
        ),  # fmt: skip
        noop,
        dump.parent / "run",
        "dump",
    )
    if not dump.is_file():
        raise SystemExit(f"the rollout wrote no scene dump at {dump}")
    text = root / context["text"]
    text.parent.mkdir(parents=True, exist_ok=True)
    text.write_text(text_from_dump(dump, context["level"]) + "\n", encoding="utf-8")
    return text


def main() -> int:
    from ants.studio.policy_dev import load_skill

    print(prep(load_skill()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
