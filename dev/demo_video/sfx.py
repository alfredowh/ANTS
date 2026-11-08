"""Generate the film's few sound effects (royalty-free, synthesized): whoosh, click, tick, thud,
chime and sting. Quiet and short; used sparingly.

    uv run --with numpy python dev/demo_video/sfx.py   # -> remotion/public/film/sfx/*.wav
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 44100
OUT = Path(__file__).resolve().parent / "remotion" / "public" / "film" / "sfx"
RNG = np.random.default_rng(1)


def t_of(dur: float) -> np.ndarray:
    return np.arange(int(dur * SR)) / SR


def onepole(x: np.ndarray, cutoff: np.ndarray) -> np.ndarray:
    """Time-varying low-pass; cutoff in Hz per sample."""
    a = 1 - np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += a[i] * (x[i] - acc)
        y[i] = acc
    return y


def whoosh() -> np.ndarray:
    t = t_of(0.55)
    x = RNG.standard_normal(len(t))
    sweep = 300 + 5200 * np.sin(np.pi * t / t[-1]) ** 2  # opens and closes
    y = onepole(x, sweep) - onepole(x, sweep * 0.25)  # band-pass-ish
    return y * np.sin(np.pi * t / t[-1]) ** 1.5


def click() -> np.ndarray:
    t = t_of(0.06)
    return (np.sin(2 * np.pi * 2400 * t) * 0.6 + RNG.standard_normal(len(t)) * 0.4) * np.exp(
        -t * 90
    )


def tick() -> np.ndarray:
    t = t_of(0.08)
    return np.sin(2 * np.pi * 1800 * t) * np.exp(-t * 70)


def thud() -> np.ndarray:
    t = t_of(0.5)
    f = 90 * np.exp(-t * 6) + 45
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7)


def chime() -> np.ndarray:
    t = t_of(1.4)
    notes = [(1046.5, 0.0), (1318.5, 0.09), (1568.0, 0.18)]  # C6 E6 G6
    y = np.zeros_like(t)
    for f, d in notes:
        s = t - d
        on = s >= 0
        y[on] += (np.sin(2 * np.pi * f * s[on]) + 0.3 * np.sin(4 * np.pi * f * s[on])) * np.exp(
            -s[on] * 3.5
        )
    return y


def sting() -> np.ndarray:
    t = t_of(2.6)
    y = np.zeros_like(t)
    for f in (261.6, 329.6, 392.0, 523.3, 659.3):  # C major spread
        y += np.sin(2 * np.pi * f * t) * np.exp(-t * 1.4)
    rise = RNG.standard_normal(len(t)) * np.exp(-((t - 0.05) ** 2) / 0.002) * 0.4
    return y / 5 + rise


def write(name: str, x: np.ndarray, peak: float) -> None:
    x = peak * x / np.max(np.abs(x))
    fade = np.minimum(1, np.arange(len(x))[::-1] / (0.01 * SR))
    with wave.open(str(OUT / f"{name}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * fade * 32767).astype(np.int16).tobytes())


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sounds = [
        ("whoosh", whoosh, 0.5),
        ("click", click, 0.35),
        ("tick", tick, 0.25),
        ("thud", thud, 0.6),
        ("chime", chime, 0.4),
        ("sting", sting, 0.6),
    ]
    for name, fn, peak in sounds:
        write(name, fn(), peak)
    print(OUT, sorted(p.name for p in OUT.glob("*.wav")))


if __name__ == "__main__":
    main()
