import json
import shutil

import pytest

from ants.synthesizer import prompt_generator as pg
from ants.synthesizer.llm import ChatClient

SUMMARY = {
    "grasp": {
        "radial_offset_over_radius": 1.24,
        "height_over_object_height": 0.82,
        "aperture_at_grasp_m": 0.029,
        "approach_last_0.5s": {"horizontal_m": 0.041, "drop_m": -0.027},
    },
    "carry": {"max_height_above_table_m": 0.233, "duration_s": 3.1},
    "release": {"radial_offset_over_plate_radius": 0.67, "height_above_table_m": 0.142},
    "objects_real": {
        "bowl": {"diameter_m": 0.138, "height_m": 0.067},
        "plate": {"diameter_m": 0.255, "height_m": 0.028},
    },
}
KEYFRAMES = [
    {"t_s": 0.0, "kind": "approach", "anchor": "bowl"},
    {"t_s": 0.2, "kind": "grasp", "anchor": "bowl"},
]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_sample_keyframes_extracts_one_frame_per_keyframe(tmp_path):
    import subprocess

    video = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=64x64:rate=10",
            str(video),
        ],  # fmt: skip
        capture_output=True,
        check=True,
    )
    frames = pg.sample_keyframes(video, KEYFRAMES, tmp_path / "frames")
    assert len(frames) == 2
    for caption, path in frames:
        assert path.exists() and path.stat().st_size > 0
        assert "moment" in caption


def test_generate_demo_section_calls_model_with_instructions_and_summary(tmp_path, monkeypatch):
    frame_paths = []
    for kf in KEYFRAMES:
        p = tmp_path / f"{kf['kind']}.jpg"
        p.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-bytes")
        frame_paths.append((f"Frame at {kf['kind']}", p))
    monkeypatch.setattr(pg, "sample_keyframes", lambda *a, **k: frame_paths)

    captured = {}

    def fake_post(messages, temperature):
        captured["messages"] = messages
        reply = {
            "choices": [{"message": {"content": "A human showed this task once..."}}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 50},
        }
        return reply, 0.1

    client = ChatClient("m", tmp_path / "cache", tmp_path / "ledger.jsonl", token_budget=100_000)
    monkeypatch.setattr(client, "_post", fake_post)

    demospec = {"keyframes": KEYFRAMES, "summary": SUMMARY}
    result = pg.generate_demo_section(
        demospec, tmp_path / "unused.mp4", client, frames_dir=tmp_path / "frames"
    )

    assert result == "A human showed this task once..."
    content = captured["messages"][0]["content"]
    text_part = content[0]["text"] if isinstance(content, list) else content
    assert "object-relative" in text_part
    assert json.dumps(SUMMARY["grasp"]["radial_offset_over_radius"]) in text_part
    if isinstance(content, list):
        image_parts = [p for p in content if p.get("type") == "image_url"]
        assert len(image_parts) == 2
