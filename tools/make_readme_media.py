"""Build README media from logged LIBERO rollouts (seed 53) and the human demo clip.

Run from the repo root:
    uv run --with imageio --with imageio-ffmpeg --with pillow python tools/make_readme_media.py

Needs the GPU run folders in data/runs (git-ignored) and the demo clip in data/demo/.
"""

import glob
import json
import os
import re
import sys
from pathlib import Path

import imageio.v2 as imageio
import imageio_ffmpeg  # noqa: F401  (registers the bundled ffmpeg)
from PIL import Image, ImageDraw, ImageFont

RUNS = Path("data/runs")
OUT = Path("docs/images")
SEED = 53
BG = (13, 17, 23)
INK = (232, 237, 243)
ACCENT = (245, 165, 36)
FAIL = (248, 81, 73)


def font(size):
    for f in ("/System/Library/Fonts/SFNSMono.ttf", "/System/Library/Fonts/Menlo.ttc"):
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default(size=size)


def rollouts():
    rows = []
    for top in glob.glob(str(RUNS / "libero_*/aspire/*")):
        m = re.search(r"_s(\d+)_", top)
        if not m or int(m.group(1)) != SEED:
            continue
        sc = Path(top) / "scene.json"
        scene = json.loads(sc.read_text()) if sc.exists() else {}
        vid = glob.glob(top + "/libero-pro/*/*/*/run-*/media/videos/agentview.mp4")
        oc = glob.glob(top + "/libero-pro/*/*/*/run-*/outcome.json")
        if vid and oc:
            rows.append(
                {
                    "cat": next(iter(scene), "nominal") if scene else "nominal",
                    "scene": scene,
                    "ok": json.loads(Path(oc[0]).read_text())["task_success"],
                    "video": vid[0],
                }
            )
    return rows


def frames(video, times_frac):
    r = imageio.get_reader(video)
    n = r.count_frames()
    out = [r.get_data(min(n - 1, int(f * (n - 1)))) for f in times_frac]
    r.close()
    return [Image.fromarray(x) for x in out]


def label(img, text, color=INK, sub=None):
    w, h = img.size
    bar = 34 if not sub else 54
    canvas = Image.new("RGB", (w, h + bar), BG)
    canvas.paste(img, (0, bar))
    d = ImageDraw.Draw(canvas)
    d.text((10, 7), text, fill=color, font=font(18))
    if sub:
        d.text((10, 30), sub, fill=(139, 151, 166), font=font(14))
    return canvas


def grid(tiles, cols, gap=6):
    w, h = tiles[0].size
    rows = (len(tiles) + cols - 1) // cols
    g = Image.new("RGB", (cols * w + (cols - 1) * gap, rows * h + (rows - 1) * gap), BG)
    for i, t in enumerate(tiles):
        g.paste(t, ((i % cols) * (w + gap), (i // cols) * (h + gap)))
    return g


def gif(video, out, width, fps_out, speed, start=0.0, end=1.0, crop=None):
    r = imageio.get_reader(video)
    meta = r.get_meta_data()
    fps_in = meta.get("fps", 20)
    n = r.count_frames()
    step = max(1, round(fps_in * speed / fps_out))
    imgs = []
    for i in range(int(start * n), int(end * n), step):
        im = Image.fromarray(r.get_data(i))
        if crop:
            im = im.crop(crop)
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        imgs.append(im.convert("P", palette=Image.ADAPTIVE, colors=96))
    r.close()
    imgs[0].save(
        out,
        save_all=True,
        append_images=imgs[1:],
        duration=int(1000 / fps_out),
        loop=0,
        optimize=True,
    )
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = rollouts()
    by = {}
    for r in rows:
        by.setdefault(r["cat"], []).append(r)

    def pick(cat, key, fail=None):
        cands = [r for r in by.get(cat, []) if fail is None or r["ok"] == (not fail)]
        return max(cands, key=key)

    nominal = next(r for r in by["nominal"] if r["ok"])
    pose = pick(
        "pose", lambda r: sum(abs(v) for v in next(iter(r["scene"]["pose"]["offsets_m"].values())))
    )
    size = pick("scale", lambda r: r["scene"]["scale"]["bodies"].get("plate_1_main", 1), fail=True)
    camera = pick(
        "camera",
        lambda r: (
            abs(r["scene"]["camera"].get("fovy_delta_deg", 0))
            + 50 * sum(map(abs, r["scene"]["camera"].get("pos_offset_m", [0])))
        ),
    )
    lighting = pick("lighting", lambda r: -r["scene"]["lighting"]["diffuse_scale"])
    physics = pick("physics", lambda r: r["scene"]["physics"].get("mass_scale", 1))
    actuation = pick("actuation", lambda r: r["scene"]["actuation"].get("noise_std", 0))

    # 1. The LIBERO-Pro scene: start and end of the nominal v0 rollout
    a, b = frames(nominal["video"], [0.02, 0.98])
    scene = grid(
        [
            label(a, "LIBERO-Pro · start", sub="Franka arm, bowl, plate (task 8)"),
            label(b, "v0 · end", ACCENT, sub="bowl on the plate (task success)"),
        ],
        2,
    )
    scene.save(OUT / "libero_scene.png", optimize=True)

    # 2. Attacks: the same starting scene (seed 53) under each category
    def sub(r):
        s = r["scene"]
        c = r["cat"]
        if c == "pose":
            dx, dy = next(iter(s["pose"]["offsets_m"].values()))
            return f"bowl moved {100 * dx:+.1f} / {100 * dy:+.1f} cm"
        if c == "scale":
            b = s["scale"]["bodies"]
            return f"plate x{b['plate_1_main']:.2f}, bowl x{b['akita_black_bowl_1_main']:.2f}"
        if c == "camera":
            off = s["camera"].get("pos_offset_m", [0, 0, 0])
            fov = s["camera"].get("fovy_delta_deg", 0)
            return f"camera moved {100 * max(off, key=abs):+.1f} cm, fov {fov:+.1f} deg"
        if c == "lighting":
            return f"light x{s['lighting']['diffuse_scale']:.2f}"
        if c == "physics":
            p = s["physics"]
            return f"friction x{p.get('friction_scale', 1):.2f}, mass x{p.get('mass_scale', 1):.2f}"
        if c == "actuation":
            a = s["actuation"]
            return f"noise {100 * a['noise_std']:.1f} cm, latency {a['latency_steps']} steps"
        return "no perturbation"

    tiles = []
    for name, r in (
        ("nominal", nominal),
        ("pose", pose),
        ("size", size),
        ("camera", camera),
        ("lighting", lighting),
        ("physics", physics),
    ):
        f = frames(r["video"], [0.02])[0]
        verdict = "passed" if r["ok"] else "FAILED"
        tiles.append(label(f, f"{name} · {verdict}", FAIL if not r["ok"] else INK, sub=sub(r)))
    grid(tiles, 3).save(OUT / "attacks.png", optimize=True)

    # 3. The size failure: release moment vs nominal, same seed
    fail_frames = frames(size["video"], [0.55, 0.75, 0.98])
    nom_frames = frames(nominal["video"], [0.55, 0.75, 0.98])
    rows_ = [
        label(f, f"nominal {t}", sub=None)
        for f, t in zip(nom_frames, ("carry", "release", "end"), strict=True)
    ]
    rows_ += [
        label(f, f"plate x{size['scene']['scale']['bodies']['plate_1_main']:.1f} {t}", FAIL)
        for f, t in zip(fail_frames, ("carry", "release", "end"), strict=True)
    ]
    grid(rows_, 3).save(OUT / "size_failure.png", optimize=True)

    # 4. GIFs: the human demo and the robot recreating it
    demo = Path("data/demo/20261016_233859.mp4")
    if demo.exists():
        gif(str(demo), OUT / "demo_human.gif", 360, 7, 1.5)
    gif(nominal["video"], OUT / "demo_robot.gif", 420, 8, 4.0)

    for p in sorted(OUT.glob("*")):
        if p.suffix in (".png", ".gif"):
            print(f"{p}  {p.stat().st_size / 1e6:.2f} MB")
    print(
        "used:",
        {
            k: v["video"].split("/aspire/")[1][:45]
            for k, v in (
                ("nominal", nominal),
                ("pose", pose),
                ("size", size),
                ("camera", camera),
                ("lighting", lighting),
                ("physics", physics),
                ("actuation", actuation),
            )
        },
    )


if __name__ == "__main__":
    sys.exit(main())
