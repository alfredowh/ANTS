"""Assemble the ants demo film spec from the scene planner and the recorded takes.

    uv run python dev/demo_video/film.py lines   # -> data/demo_video/film/lines.json (voice lines + tone)
    uv run python dev/demo_video/film.py build   # -> remotion/public/film/film.json (needs voice.json)

Scene text (voice line, caption) comes from the planner export in data/demo_video/film/planner/;
how each scene is shown (take, segments, zoom targets, overlay) is SCENES below. Each scene lasts
max(its footage, its voice line + PAD). Tones: calm by default, neutral for the problem, warm for
a few key lines; no excited tone.
"""

from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FILM = REPO / "data" / "demo_video" / "film"
CLIPS = REPO / "data" / "demo_video" / "clips"
PAD = 0.8  # seconds of breathing room after each line
MAX_RATE = 2.0  # screen footage may play up to this much faster to fit its line

TONES = {  # Chatterbox exaggeration, cfg_weight (lower cfg = calmer pace)
    "calm": (0.4, 0.5),
    "neutral": (0.5, 0.5),
    "warm": (0.6, 0.45),
}

# demo panel in the console takes (video pixels); the overlay clip is laid over it
DEMO_PANEL = {"x": 1539, "y": 264, "width": 366, "height": 207}

SCENES: list[dict] = [
    {"id": "v01-logo", "kind": "card", "card": "logo", "tone": "warm", "min": 5},
    {"id": "v02-problem", "kind": "problem", "tone": "neutral", "min": 27},
    {"id": "v03-devphase", "kind": "chips", "tone": "calm", "min": 6,
     "chips": ["New task", "New robot", "New setup"], "title": "Policy development phase"},
    {"id": "v04-prompt", "kind": "screen", "clip": "prompt", "tone": "calm",
     "segs": [[3.8, 14.5], [17.0, 24.0]],
     "cam": [["wide", 1.0], ["typed_task", 1.8], ["clip_chip", 1.8], ["settings_dialog", 1.5], ["setting_5", 1.9]]},
    {"id": "v05-flow", "kind": "screen", "clip": "run", "tone": "calm", "segs": [[15.0, 28.0]],
     "cam": [["flow_start", 1.35], ["demo_extraction", 1.6]], "pip": DEMO_PANEL},
    {"id": "v06-demo", "kind": "demo", "tone": "calm", "min": 12},
    {"id": "v07-generate", "kind": "screen", "clip": "run", "tone": "calm", "segs": [[33.0, 45.0]],
     "cam": [["program_generator", 1.6]], "pip": DEMO_PANEL},
    {"id": "v08-repair", "kind": "screen", "clip": "repair_long", "tone": "calm",
     "segs": [[8.0, 30.0], [52.5, 66.0]],
     "cam": [["a0_result", 2.2], ["a1_why", 1.8], ["a1_diff_body", 1.8], ["a4_result", 2.4], ["a4_rollout", 1.9]]},
    {"id": "v09-rollout", "kind": "screen", "clip": "run", "tone": "calm", "segs": [[50.0, 64.0]],
     "cam": [["live_rollout", 1.7]], "pip": DEMO_PANEL},
    {"id": "v10-result", "kind": "image", "image": "assets/fig1_success_rates.svg", "tone": "warm", "min": 8},
    {"id": "v11-humancheck", "kind": "screen", "clip": "run", "tone": "calm", "segs": [[66.0, 78.0]],
     "cam": [["human_check", 1.8]], "clicks": ["continue_adversary"],
     "pip": {"x": 1537, "y": 580, "width": 367, "height": 206}},  # demo panel sits lower here
    {"id": "v12-adversary", "kind": "screen", "clip": "adversary", "tone": "calm",
     "segs": [[16.0, 27.0], [40.0, 53.0], [57.0, 63.0]],
     "cam": [["certification", 1.6], ["videos_0", 1.5], ["timeline_0", 1.6], ["why_attack_0", 1.7]]},
    {"id": "v13-gate", "kind": "loop", "tone": "calm", "min": 16},
    {"id": "v14-deploy", "kind": "screen", "clip": "deploy", "tone": "calm", "segs": [[3.5, 15.0]],
     "cam": [["typed_deploy", 1.8], ["deploy_reply", 1.8]], "banner": "Export the policy for deployment"},
    {"id": "v15-deployconcept", "kind": "image", "image": "assets/deployment-concept.svg", "tone": "calm",
     "min": 10, "badge": "Concept"},
    {"id": "v16-newtask", "kind": "image", "image": "assets/prompt-authoring-detail.svg", "tone": "calm",
     "min": 10, "badge": "Planned"},
    {"id": "v17-close", "kind": "card", "card": "close", "tone": "warm", "min": 5},
]  # fmt: skip


def planner() -> dict[str, dict]:
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in (FILM / "planner" / "scenes").glob("*.json")
    }


def lines() -> None:
    plan = planner()
    out = []
    for s in SCENES:
        ex, cfg = TONES[s["tone"]]
        out.append({"id": s["id"], "text": plan[s["id"]]["transcript"].strip(),
                    "exaggeration": ex, "cfg_weight": cfg})  # fmt: skip
    FILM.mkdir(parents=True, exist_ok=True)
    (FILM / "lines.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(FILM / "lines.json", len(out), "lines")


def seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def build() -> None:
    plan = planner()
    voice = {v["id"]: v for v in json.loads((FILM / "voice.json").read_text("utf-8"))["lines"]}
    scenes, t = [], 0.0
    for s in SCENES:
        footage = s.get("min", 0.0)
        if s["kind"] == "screen":
            footage = sum(b - a for a, b in s["segs"])
            s = {
                **s,
                "timeline": json.loads((CLIPS / s["clip"] / "timeline.json").read_text("utf-8")),
            }
        v = voice.get(s["id"])
        need = (v["seconds"] + PAD) if v else 0.0
        rate = 1.0
        if s["kind"] == "screen":  # footage longer than its line plays faster, at most 2x
            rate = min(MAX_RATE, max(1.0, footage / (need + 1.5)))
            footage /= rate
            s = {**s, "rate": round(rate, 3)}
        dur = max(footage, need)
        scenes.append({**s, "start": round(t, 3), "duration": round(dur, 3),
                       "caption": plan[s["id"]].get("caption", ""),
                       "voice": v["file"] if v else None})  # fmt: skip
        t += dur
    out = REPO / "dev" / "demo_video" / "remotion" / "public" / "film"
    out.mkdir(parents=True, exist_ok=True)
    film = {"fps": 30, "width": 1920, "height": 1080, "duration": round(t, 3), "scenes": scenes,
            "music": "film/music.wav"}  # fmt: skip
    (out / "film.json").write_text(json.dumps(film, indent=1), encoding="utf-8")
    print(f"{out / 'film.json'}  {t:.1f} s, {len(scenes)} scenes")
    for s in scenes:
        print(f"  {s['id']:18s} {s['start']:6.1f}  {s['duration']:5.1f} s")


if __name__ == "__main__":
    {"lines": lines, "build": build}[sys.argv[1]]()
