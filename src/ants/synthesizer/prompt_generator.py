"""Offline prompt-generator: turn a demonstration (video + extracted DemoSpec JSON) into the
demonstration paragraph a generator prompt uses, by model call instead of hand-written code.

Today `generator.py::demo_section()` is a hand-coded f-string tied to this one task's field names
(`grasp`/`carry`/`release`, `objects_real.bowl`). This module replaces that hand-coding with one
offline Muse Spark call: it samples a few frames from the demonstration video at its keyframe
timestamps, reads the numeric summary already extracted into the DemoSpec JSON, and asks the model
to write the paragraph, following `prompts/generate_task_template.md`. The guaranteed check is that
it reproduces `demo_section()`'s bowl-on-plate paragraph given the same inputs (see
`tests/synthesizer/test_prompt_generator.py`).

This is an authoring step, not an agentic one: it runs once per demonstration, before any policy is
generated, and its output (a short paragraph of text) is cached to disk like any other prompt
asset. "Offline" here means "run ahead of time"; the same call can equally be made online, in the
middle of a run, if a task must be prepared just-in-time instead of ahead of it -- nothing about
the function changes, only when it is invoked.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ants.synthesizer.generator import image_message
from ants.synthesizer.image_gen import data_url
from ants.synthesizer.llm import ChatClient

INSTRUCTIONS_PATH = Path(__file__).parent / "prompts" / "generate_task_template.md"


def sample_keyframes(video: Path, keyframes: list[dict], out_dir: Path) -> list[tuple[str, Path]]:
    """Extract one frame per keyframe timestamp with ffmpeg; returns (caption, frame_path) pairs."""
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for kf in keyframes:
        frame_path = out_dir / f"{kf['kind']}_{kf['t_s']:.2f}s.jpg"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(kf["t_s"]),
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(frame_path),
            ],  # fmt: skip
            capture_output=True,
            check=True,
        )
        caption = (
            f"Frame at the '{kf['kind']}' moment (t={kf['t_s']:.2f}s, anchor: {kf['anchor']}):"
        )
        frames.append((caption, frame_path))
    return frames


def generate_demo_section(
    demospec: dict,
    video: Path,
    client: ChatClient,
    *,
    frames_dir: Path,
    instructions_path: Path = INSTRUCTIONS_PATH,
) -> str:
    """One offline (or just-in-time) model call: demo video + extracted summary -> prompt text."""
    frames = sample_keyframes(video, demospec["keyframes"], frames_dir)
    images = [(caption, data_url(path)) for caption, path in frames]
    instructions = instructions_path.read_text(encoding="utf-8")
    summary_json = json.dumps(demospec["summary"], indent=1)
    text = f"{instructions}\n\n## This demonstration's summary\n```json\n{summary_json}\n```"
    message = image_message(text, images)
    reply = client.chat([message], temperature=0.2, tag="prompt_generator")
    return reply.text.strip()
