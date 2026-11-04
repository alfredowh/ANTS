"""A simple, interactive 3D viewer for the oracle scene System 1 reads (the S4 scene section).

Reads the same `contacts_scene.json` files `orchestrator/scene_context_exp.py` already produces
under `data/scenes/<level>/` (via `--prep`) and `levels.json` for titles, and renders one
self-contained HTML page: auto-rotating (toggle-able), drag to orbit, scroll to zoom, tabs to
switch scene level. Deliberately only the shapes, not the full robot mesh or live execution --
that is the separate, not-yet-ready realtime/cuRobo viewer.

    uv run python -m ants.studio.scene3d --levels-dir data/scenes --out data/scenes/scene3d.html
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

TEMPLATE = Path(__file__).with_name("scene3d_template.html")

# body name prefix -> (display label, category). Longest/most specific prefixes first.
BODY_CATEGORY = {
    "akita_black_bowl": ("bowl", "task"),
    "plate": ("plate", "task"),
    "cream_cheese": ("cream cheese", "other"),
    "wine_bottle": ("wine bottle", "other"),
    "wine_rack": ("wine rack", "rack"),
    "wooden_cabinet": ("wooden cabinet", "other"),
    "flat_stove": ("flat stove", "other"),
    "table": ("table", "table"),
}
# geom types this viewer can draw directly (MuJoCo geom type ids); mesh (7) has no vertex data here.
DRAWABLE_TYPES = {0: "plane", 2: "sphere", 3: "capsule", 5: "cylinder", 6: "box"}
ROBOT_PREFIXES = ("robot0_", "mount0_", "gripper0_")


def _category(body: str) -> tuple[str, str] | None:
    for prefix, (label, cat) in BODY_CATEGORY.items():
        if body.startswith(prefix):
            return label, cat
    return None


def load_scene(scene_path: Path) -> dict[str, Any]:
    """Filter one `contacts_scene.json` down to what the viewer draws."""
    raw = json.loads(scene_path.read_text(encoding="utf-8"))
    shapes: list[dict[str, Any]] = []
    for g in raw["geoms"]:
        if g["type"] not in DRAWABLE_TYPES:
            continue
        body = g["body"]
        if body == "world" or body.startswith(ROBOT_PREFIXES):
            continue  # not part of the S4 scene text: the model gets a gripper blurb, not a mesh
        cat_info = _category(body)
        if cat_info is None:
            continue
        label, cat = cat_info
        shapes.append(
            {
                "type": DRAWABLE_TYPES[g["type"]],
                "pos": g["pos"],
                "xmat": g["xmat"],
                "size": g["size"],
                "body": body,
                "label": label,
                "cat": cat,
            }
        )
    # one marker for the gripper, from the hand body's own pose (already in `bodies`)
    hand = raw["bodies"].get("gripper0_eef") or raw["bodies"].get("robot0_right_hand")
    gripper = {"pos": hand["pos"], "label": "gripper"} if hand else None

    # camera framing: centre and radius of the scene objects only (not the whole robot/table),
    # so the default view starts on the table-top layout, not wherever the robot happens to be.
    framed = [s["pos"] for s in shapes if s["cat"] in ("task", "rack", "other")]
    if framed:
        xs, ys, zs = (sorted(p[i] for p in framed) for i in range(3))
        center = [(xs[0] + xs[-1]) / 2, (ys[0] + ys[-1]) / 2, (zs[0] + zs[-1]) / 2]
        radius = max(0.3, ((xs[-1] - xs[0]) ** 2 + (ys[-1] - ys[0]) ** 2) ** 0.5 / 2 + 0.15)
    else:
        center, radius = [0.0, 0.0, 0.0], 1.0
    return {"shapes": shapes, "gripper": gripper, "center": center, "radius": radius}


def build(levels_dir: Path, out: Path, levels: tuple[str, ...] = ("L1", "L2", "L3")) -> Path:
    meta = json.loads((levels_dir / "levels.json").read_text(encoding="utf-8"))
    data = {
        "levels": [
            {
                "id": lvl,
                "title": meta.get(lvl, {}).get("title", lvl),
                "desc": meta.get(lvl, {}).get("desc", ""),
                "scene": load_scene(levels_dir / lvl / "contacts_scene.json"),
            }
            for lvl in levels
            if (levels_dir / lvl / "contacts_scene.json").exists()
        ]
    }
    page = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", json.dumps(data))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--levels-dir", type=Path, default=Path("data/scenes"))
    parser.add_argument("--out", type=Path, default=Path("data/scenes/scene3d.html"))
    parser.add_argument("--levels", default="L1,L2,L3")
    args = parser.parse_args()
    out = build(args.levels_dir, args.out, tuple(args.levels.split(",")))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
