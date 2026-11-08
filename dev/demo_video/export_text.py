"""Write captions (.srt) and a timed narration script (.md) for a clip, from the same shot list
Remotion renders, so text and video stay in sync.

    uv run python dev/demo_video/export_text.py repair
    -> data/demo_video/clips/<clip>/captions.srt, narration.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLIPS = HERE.parents[1] / "data" / "demo_video" / "clips"


def stamp(s: float, sep: str = ",") -> str:
    ms = round(s * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}{sep}{ms % 1000:03d}"


def main(clip: str) -> None:
    shots = json.loads((HERE / "remotion" / "src" / "shots" / f"{clip}.json").read_text("utf-8"))
    tl = json.loads((CLIPS / clip / "timeline.json").read_text("utf-8"))
    times = {e["name"]: e["t"] for e in tl["events"]}

    def at(a: dict) -> float:
        base = a["at"] if isinstance(a["at"], (int, float)) else times[a["at"]]
        return min(base + a.get("offset", 0), tl["duration"])

    srt, md = [], [f"# Narration: {clip} ({tl['duration']:.1f} s)", "",
                   f"Source run: `{tl.get('source_run', '?')}`. Generated from "
                   f"`remotion/src/shots/{clip}.json`; edit that, not this.", "",
                   "| Time | Caption | Narration | Words / s |", "|---|---|---|---|"]  # fmt: skip
    for i, c in enumerate(shots["captions"], 1):
        a, b = at(c["from"]), at(c["to"])
        srt += [str(i), f"{stamp(a)} --> {stamp(b)}", c["text"], ""]
        say = c.get("say", "")
        rate = len(say.split()) / max(b - a, 0.1)
        flag = " (too fast)" if rate > 2.8 else ""
        md.append(f"| {stamp(a, '.')[3:-2]} to {stamp(b, '.')[3:-2]} | {c['text']} | {say} | "
                  f"{rate:.1f}{flag} |")  # fmt: skip
    (CLIPS / clip / "captions.srt").write_text("\n".join(srt), encoding="utf-8")
    (CLIPS / clip / "narration.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(CLIPS / clip / "narration.md")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "repair")
