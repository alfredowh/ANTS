"""Speak the film's voice lines with Chatterbox in a cloned voice, one wav per scene.

Runs in the separate Chatterbox env (never the ANTS env):

    env -u VIRTUAL_ENV uv run --project ../workbench/modules/tts-chatterbox \
        python dev/demo_video/tts_lines.py --ref data/demo_video/tts/voice_ref.wav

Reads data/demo_video/film/lines.json (text, exaggeration, cfg_weight per scene; written by
film.py lines). Each sentence is generated alone (long inputs drift) and cached by its text and
settings, then joined with short pauses. Writes dev/demo_video/remotion/public/film/voice/<id>.wav
and data/demo_video/film/voice.json (file, seconds per scene).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FILM = REPO / "data" / "demo_video" / "film"
OUT = REPO / "dev" / "demo_video" / "remotion" / "public" / "film" / "voice"
GAP = 0.28  # seconds between sentences


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--only", nargs="*", help="scene ids to (re)generate")
    a = ap.parse_args()

    import torch
    import torchaudio as ta
    from chatterbox.tts import ChatterboxTTS

    lines = json.loads((FILM / "lines.json").read_text(encoding="utf-8"))
    cache = FILM / "tts_cache"
    cache.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    ref_hash = hashlib.sha256(a.ref.read_bytes()).hexdigest()[:12]
    model = None
    rows = []
    for ln in lines:
        # "[pause 1s]" in the text adds that much silence (on top of the normal gap)
        chunks = re.split(r"\[pause\s*([\d.]+)\s*s?\]", ln["text"])
        items: list[str | float] = []
        for i, chunk in enumerate(chunks):
            if i % 2:
                items.append(float(chunk))
            else:
                items += [s for s in re.split(r"(?<=[.!?])\s+", chunk.strip()) if s.strip()]
        sentences = [x for x in items if isinstance(x, str)]
        parts: list[Path | float] = []
        for s in items:
            if isinstance(s, float):
                parts.append(s)
                continue
            key = f"{s}|{ref_hash}|{ln['exaggeration']}|{ln['cfg_weight']}|{a.seed}"
            f = cache / (hashlib.sha256(key.encode()).hexdigest()[:16] + ".wav")
            if not f.is_file():
                if model is None:
                    model = ChatterboxTTS.from_pretrained(device="cuda")
                torch.manual_seed(a.seed)
                w = model.generate(
                    s,
                    audio_prompt_path=str(a.ref),
                    exaggeration=ln["exaggeration"],
                    cfg_weight=ln["cfg_weight"],
                )
                ta.save(str(f), w.cpu(), model.sr)
            parts.append(f)
        sr = ta.load(str(next(p for p in parts if not isinstance(p, float))))[1]
        gap = torch.zeros(1, int(GAP * sr))
        pieces = []
        for p in parts:
            if isinstance(p, float):
                pieces.append(torch.zeros(1, int(p * sr)))
            else:
                pieces += [ta.load(str(p))[0][:1], gap]
        joined = torch.cat(pieces[:-1] if not isinstance(parts[-1], float) else pieces, dim=1)
        dst = OUT / f"{ln['id']}.wav"
        ta.save(str(dst), joined, sr)
        sec = joined.shape[-1] / sr
        rows.append({"id": ln["id"], "file": f"film/voice/{dst.name}", "seconds": round(sec, 3)})
        print(f"{ln['id']:18s} {sec:5.1f} s  {len(sentences)} sentences")
    (FILM / "voice.json").write_text(
        json.dumps({"ref": str(a.ref), "lines": rows}, indent=1), "utf-8"
    )


if __name__ == "__main__":
    main()
