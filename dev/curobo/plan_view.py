"""One HTML page: what cuRobo saw, which spheres collide, straight path against planned path.

    python dev/curobo/plan_view.py [--3d] out.html "failed run=plans_fail.json" "successful run=plans_ok.json"

Inputs come from `plan_data.py`. Plain Python, no dependencies.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(
    out: Path, runs: list[str], template: str = "plan_view_template.html", card: bool = True
) -> None:
    text = (Path(__file__).parent / template).read_text(encoding="utf-8")
    if not card and "<!--CARD-->" in text:
        text = text.split("<!--CARD-->")[0] + text.split("<!--/CARD-->")[1]
    data = []
    for spec in runs:
        title, path = spec.rsplit("=", 1)
        data.append({"title": title, **json.loads(Path(path).read_text(encoding="utf-8"))})
    out.write_text(text.replace("__DATA__", json.dumps(data).replace("</", "<\\/")), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    args = sys.argv[1:]
    tpl = "plan_view3d_template.html" if args[0] == "--3d" else "plan_view_template.html"
    args = args[1:] if args[0] == "--3d" else args
    main(Path(args[0]), args[1:], tpl)
