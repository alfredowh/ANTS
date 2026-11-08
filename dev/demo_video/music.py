"""Generate an uplifting, beat-driven, royalty-free track for the demo film (product-video style):
C-G-Am-F, eighth-note piano arpeggio, pad, bass, four-on-the-floor kick, claps and hats.

With --film, the sections follow the film (remotion/public/film/film.json): calm intro under the
problem, a riser into a full drop when the Studio appears, a breakdown at the gate, a build into
the ending, one beat of silence before the closing card, then a held final chord.

    uv run --with numpy python dev/demo_video/music.py --film   # -> remotion/public/film/music.wav
    uv run --with numpy python dev/demo_video/music.py 200      # plain track, 104 bpm
"""

from __future__ import annotations

import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

SR = 44100
OUT = Path(__file__).resolve().parent / "remotion" / "public" / "film" / "music.wav"
RNG = np.random.default_rng(0)


def hz(midi: int) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def env(n: int, attack: float, decay: float) -> np.ndarray:
    t = np.arange(n) / SR
    return (1 - np.exp(-t / max(attack, 1e-4))) * np.exp(-t * decay)


def piano(f: float, dur: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    w = 2 * np.pi * f * t
    tone = np.sin(w) + 0.5 * np.sin(2 * w) * np.exp(-t * 3) + 0.15 * np.sin(3 * w)
    return tone * env(n, 0.004, 3.0)


def pad(freqs: list[float], dur: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    sig = sum(np.sin(2 * np.pi * f * 2 ** (d / 12) * t) for f in freqs for d in (-0.1, 0.1))
    fade = np.minimum(1, t / 0.8) * np.minimum(1, (dur - t) / 0.8)
    return sig * fade / (2 * len(freqs))


def bass(f: float, dur: float) -> np.ndarray:
    n = int(dur * SR)
    w = 2 * np.pi * f * np.arange(n) / SR
    return (np.sin(w) + 0.3 * np.sin(2 * w)) * env(n, 0.01, 1.6)


def kick() -> np.ndarray:
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    f = 120 * np.exp(-t * 25) + 45
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)


def noise_hit(dur: float, decay: float) -> np.ndarray:
    n = int(dur * SR)
    x = np.diff(RNG.standard_normal(n), prepend=0)  # brighter (high-passed) noise
    return x * env(n, 0.001, decay)


def main(seconds: float) -> None:
    beat = 60 / 104
    bar = 4 * beat
    chords = [[60, 64, 67], [59, 62, 67], [57, 60, 64], [57, 60, 65]]  # C, G/B, Am, F
    roots = [36, 43, 45, 41]
    arp = [
        [72, 76, 79, 84, 79, 76, 79, 76],
        [71, 74, 79, 83, 79, 74, 79, 74],
        [69, 72, 76, 81, 76, 72, 76, 72],
        [69, 72, 77, 81, 77, 72, 77, 72],
    ]
    n = int(seconds * SR)
    mix = np.zeros(n + 10 * SR)

    def add(at: float, sig: np.ndarray, gain: float) -> None:
        s = int(at * SR)
        mix[s : s + len(sig)] += gain * sig

    t0, i = 0.0, 0
    while t0 < seconds:
        c = i % 4
        add(t0, pad([hz(m) for m in chords[c]], bar + 0.6), 0.30)
        add(t0, bass(hz(roots[c]), bar * 0.95), 0.45)
        for k, m in enumerate(arp[c]):
            if i < 2 and k % 2:  # sparser in the first two bars
                continue
            add(t0 + k * beat / 2, piano(hz(m), 1.2), 0.20)
        if i >= 4:  # rhythm enters after four bars
            for b in range(4):
                if b in (0, 2):
                    add(t0 + b * beat, kick(), 0.55)
                if b in (1, 3):
                    add(t0 + b * beat, noise_hit(0.25, 18), 0.10)  # soft clap
                for h in (0, 0.5):
                    add(t0 + (b + h) * beat, noise_hit(0.08, 60), 0.035)  # shaker
        t0 += bar
        i += 1
    mix = mix[:n]
    t = np.arange(n) / SR
    mix *= np.minimum(1, t / 2.5) * np.minimum(1, (seconds - t) / 4)
    mix = 0.7 * mix / np.max(np.abs(mix))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp.wav")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((mix * 32767).astype(np.int16).tobytes())
    room = "lowpass=f=6500,aecho=0.8:0.5:60|130:0.18|0.10,loudnorm=I=-18:TP=-2"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-af", room]
    subprocess.run([*cmd, "-ar", str(SR), str(OUT)], check=True)
    tmp.unlink()
    print(OUT, f"{seconds:.0f} s")


def riser(dur: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = np.diff(RNG.standard_normal(n), prepend=0)
    return x * (t / dur) ** 2.5


def film_track() -> None:
    import json

    film = json.loads((OUT.parent / "film.json").read_text(encoding="utf-8"))
    start = {sc["id"]: sc["start"] for sc in film["scenes"]}
    total = film["duration"]
    beat = 60 / film.get("bpm", 116)
    bar = 4 * beat
    drop, brk, build, close = (
        start["v04-prompt"],
        start["v13-gate"],
        start["v14-deploy"],
        start["v17-close"],
    )
    chords = [[60, 64, 67], [59, 62, 67], [57, 60, 64], [57, 60, 65]]
    roots = [36, 43, 45, 41]
    arp = [
        [72, 76, 79, 84, 79, 76, 79, 76],
        [71, 74, 79, 83, 79, 74, 79, 74],
        [69, 72, 76, 81, 76, 72, 76, 72],
        [69, 72, 77, 81, 77, 72, 77, 72],
    ]
    n = int((total + 4) * SR)
    mix = np.zeros(n + 10 * SR)

    def add(at: float, sig: np.ndarray, gain: float) -> None:
        s0 = int(at * SR)
        if s0 < 0:
            return
        mix[s0 : s0 + len(sig)] += gain * sig

    t0, i = 0.0, 0
    stop = close - beat
    while t0 < stop:
        c = i % 4
        full = drop <= t0 < brk or build <= t0 < stop
        intro = t0 < drop
        add(t0, pad([hz(m) for m in chords[c]], bar + 0.6), 0.30 if not full else 0.22)
        if not intro:
            add(t0, bass(hz(roots[c]), bar * 0.95), 0.45)
        for k, m in enumerate(arp[c]):
            at = t0 + k * beat / 2
            if at >= stop or (intro and k % 2):
                continue
            add(at, piano(hz(m), 1.1), 0.22 if full else 0.17)
        for b in range(4):
            at = t0 + b * beat
            if at >= stop or not full:
                continue
            add(at, kick(), 0.6)  # four on the floor
            if b in (1, 3):
                add(at, noise_hit(0.22, 16), 0.14)  # clap
            add(at + beat / 2, noise_hit(0.07, 55), 0.06)  # off-beat hat
            if build <= t0:
                add(at + beat / 4, noise_hit(0.05, 70), 0.025)  # extra shimmer in the finale
        t0 += bar
        i += 1
    add(drop - 2 * bar, riser(2 * bar), 0.35)  # into the drop
    add(build - bar, riser(bar), 0.3)  # into the finale
    add(close, pad([hz(m) for m in (48, 60, 64, 67, 72)], 3.2), 0.5)  # final chord under the logo
    mix = mix[: int(total * SR)]
    t = np.arange(len(mix)) / SR
    mix *= np.minimum(1, t / 1.5)
    mix *= np.where(t > total - 1.2, np.maximum(0, (total - t) / 1.2), 1)
    mix = 0.75 * mix / np.max(np.abs(mix))
    tmp = OUT.with_suffix(".tmp.wav")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((mix * 32767).astype(np.int16).tobytes())
    room = "lowpass=f=9000,aecho=0.8:0.4:50|110:0.15|0.08,loudnorm=I=-16:TP=-1.5"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-af", room]
    subprocess.run([*cmd, "-ar", str(SR), str(OUT)], check=True)
    tmp.unlink()
    print(OUT, f"{total:.0f} s, drop {drop:.1f} s, breakdown {brk:.1f} s, close {close:.1f} s")


if __name__ == "__main__":
    if sys.argv[1:] == ["--film"]:
        film_track()
    else:
        main(float(sys.argv[1]) if len(sys.argv) > 1 else 200)
