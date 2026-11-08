"""Generate a quiet, royalty-free background bed for the demo film: warm pads plus a soft,
sparse piano-like arpeggio, slow (72 bpm), I-V-vi-IV in C major, gentle fade in and out.

    uv run --with numpy python dev/demo_video/music.py 240   # -> remotion/public/film/music.wav
"""

from __future__ import annotations

import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

SR = 44100
OUT = Path(__file__).resolve().parent / "remotion" / "public" / "film" / "music.wav"


def note(midi: int) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def pad(freqs: list[float], dur: float) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    sig = np.zeros_like(t)
    for f in freqs:
        for detune in (-0.12, 0.0, 0.12):  # slight chorus
            ff = f * 2 ** (detune / 12)
            sig += np.sin(2 * np.pi * ff * t) + 0.25 * np.sin(4 * np.pi * ff * t)
    env = np.minimum(1, t / 1.6) * np.minimum(1, (dur - t) / 1.6)
    return sig * env / (len(freqs) * 3)


def pluck(f: float, dur: float) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    tone = (
        np.sin(2 * np.pi * f * t)
        + 0.35 * np.sin(4 * np.pi * f * t)
        + 0.1 * np.sin(6 * np.pi * f * t)
    )
    env = (1 - np.exp(-t * 60)) * np.exp(-t * 2.2)
    return tone * env


def main(seconds: float) -> None:
    beat = 60 / 72
    bar = 4 * beat
    # C, G/B, Am, F  (pads one octave low, arpeggio notes on top)
    chords = [[48, 55, 64], [47, 55, 62], [45, 52, 60], [41, 53, 60]]
    arps = [[72, 76, 79, 76], [71, 74, 79, 74], [69, 72, 76, 72], [69, 72, 77, 72]]
    n = int(seconds * SR)
    mix = np.zeros(n + SR * 8)
    t0, i = 0.0, 0
    while t0 < seconds:
        c = chords[i % 4]
        start = int(t0 * SR)
        p = pad([note(m) for m in c], bar + 1.0)
        mix[start : start + len(p)] += 0.5 * p
        for k, m in enumerate(arps[i % 4]):
            if (i + k) % 3 == 2:  # sparse: skip some notes
                continue
            s = int((t0 + k * beat) * SR)
            pl = pluck(note(m), 2.5)
            mix[s : s + len(pl)] += 0.22 * pl
        t0 += bar
        i += 1
    mix = mix[:n]
    t = np.arange(n) / SR
    mix *= np.minimum(1, t / 3) * np.minimum(1, (seconds - t) / 4)
    mix = 0.6 * mix / np.max(np.abs(mix))
    pcm = (mix * 32767).astype(np.int16)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    # warm it up: low-pass and a touch of room, done by ffmpeg (fast)
    tmp = OUT.with_suffix(".tmp.wav")
    OUT.rename(tmp)
    warm = "lowpass=f=2800,aecho=0.8:0.6:90|170:0.25|0.15"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-af", warm, str(OUT)]
    subprocess.run(cmd, check=True)
    tmp.unlink()
    print(OUT, f"{seconds:.0f} s")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 240)
