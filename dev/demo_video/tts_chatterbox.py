"""Narrate a clip with Chatterbox in a cloned voice: one wav per caption "say" line.

Runs in the separate Chatterbox env (torch, ~6 GB), never in the ANTS env:

    uv run --project ../workbench/modules/tts-chatterbox \
        python dev/demo_video/tts_chatterbox.py repair --ref data/demo_video/tts/voice_ref.wav

Writes data/demo_video/clips/<clip>/voice/NN.wav and voice.json (file, seconds, caption window),
which Remotion places at each caption's start. Lines are cached by text + ref + settings, so
editing one line only regenerates that line. Standard library + chatterbox only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CLIPS = REPO / "data" / "demo_video" / "clips"


def seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("clip")
    ap.add_argument("--ref", type=Path, required=True, help="~10 s wav of the voice to clone")
    ap.add_argument("--exaggeration", type=float, default=0.5, help="0.25 flat .. 1.0 dramatic")
    ap.add_argument("--cfg-weight", type=float, default=0.5, help="lower = slower, calmer pace")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    shots = json.loads((HERE / "remotion" / "src" / "shots" / f"{a.clip}.json").read_text("utf-8"))
    tl = json.loads((CLIPS / a.clip / "timeline.json").read_text("utf-8"))
    times = {e["name"]: e["t"] for e in tl["events"]}

    def at(x: dict) -> float:
        base = x["at"] if isinstance(x["at"], (int, float)) else times[x["at"]]
        return min(base + x.get("offset", 0), tl["duration"])

    out = CLIPS / a.clip / "voice"
    out.mkdir(parents=True, exist_ok=True)
    ref_hash = hashlib.sha256(a.ref.read_bytes()).hexdigest()[:12]
    model = None
    rows = []
    for i, c in enumerate(shots["captions"]):
        say = c.get("say", "").strip()
        if not say:
            continue
        key = f"{say}|{ref_hash}|{a.exaggeration}|{a.cfg_weight}|{a.seed}"
        h = hashlib.sha256(key.encode()).hexdigest()[:10]
        wav = out / f"{i:02d}_{h}.wav"
        if not wav.is_file():
            if model is None:
                import torch
                import torchaudio as ta
                from chatterbox.tts import ChatterboxTTS

                model = ChatterboxTTS.from_pretrained(device="cuda")
            torch.manual_seed(a.seed)
            w = model.generate(
                say,
                audio_prompt_path=str(a.ref),
                exaggeration=a.exaggeration,
                cfg_weight=a.cfg_weight,
            )
            ta.save(str(wav), w.cpu(), model.sr)
        start, end = at(c["from"]), at(c["to"])
        dur = seconds(wav)
        rows.append({"caption": i, "file": f"voice/{wav.name}", "start": round(start, 3),
                     "window": round(end - start, 3), "seconds": round(dur, 3),
                     "overrun": round(max(0.0, dur - (end - start)), 3), "say": say})  # fmt: skip
        print(f"{i:02d} {dur:5.1f} s in {end - start:5.1f} s window  {say[:60]}")
    meta = {"ref": str(a.ref), "ref_sha": ref_hash, "exaggeration": a.exaggeration,
            "cfg_weight": a.cfg_weight, "seed": a.seed, "lines": rows}  # fmt: skip
    (CLIPS / a.clip / "voice.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    total = sum(r["overrun"] for r in rows)
    print(f"voice.json written; total overrun {total:.1f} s (lines longer than their caption)")


if __name__ == "__main__":
    main()
