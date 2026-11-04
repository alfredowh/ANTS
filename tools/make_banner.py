"""Build the README banner: a pixel ant lays down the "ants" logo, then the tagline appears.

    uv run python tools/make_banner.py            # writes docs/images/banner.svg

Standard library only. The output is one animated SVG (SMIL), which GitHub plays inside an
<img>. One loop: the lead ant walks in from the right and lays the word down behind it, parks
left of the word (the logo pose) and holds; ant and word fade out; the tagline sweeps in line by
line, holds, fades; repeat. A trail of small ants marches along the bottom the whole time.
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs" / "images" / "banner.svg"

W, H = 1280, 360  # canvas, px
P = 10  # pixel size of the logo, px
TP = 5  # pixel size of the tagline, px
BG = "#0d1117"
INK = "#f0f3f6"  # revealed text
GLOW = "#f5a524"  # the freshly laid edge of the text; also the accent word

TAGLINE = ["Adversarial agentic task synthesis", "for robot programs"]
ACCENT = "Adversarial"  # drawn in GLOW

# Timeline, seconds.
CYCLE = 15.0
WALK = (0.0, 4.2)  # lead ant walks in and lays "ants"
LOGO_FADE = (6.4, 7.1)  # ant and "ants" fade out
LINES = [(7.3, 9.0), (9.0, 10.0)]  # tagline sweeps, one per line
END_FADE = (14.2, 14.9)  # tagline fades out

# Lead ant, facing left like the logo. One character per pixel:
# B body, S stripe/highlight, E eye, A antenna, L leg (frame-dependent rows below).
ANT_BODY = [
    "...A....A.............",
    "....A....A............",
    "....A...A.............",
    "...BBBBBB.............",
    "..BBBBBBBB.....BBBBB..",
    ".BBEEBBBBB...BBBBBBBB.",
    "BBBEEBBBBBB.BBBBSBBSBB",
    "BBBBBBBBBSSBBBBBSBBSBB",
    ".BBBBBBBBSSBBBBBSBBSBB",
    "..BBBBBBBBBBBBBBBSBBSB",
    "....BB...BBBB..BBBBBB.",
]
ANT_LEGS = [
    [  # frame A
        "....L....L.....L......",
        "...L.....L......L.....",
        "..L.....L........L....",
        "..L.....L.........L...",
        ".L......L.........L...",
    ],
    [  # frame B
        ".....L...L....L.......",
        ".....L....L....L......",
        "....L.....L.....L.....",
        "...L.......L.....L....",
        "...L.......L......L...",
    ],
]
ANT_COLORS = {"B": "#8b9296", "S": "#c3c7c9", "E": "#0d1117", "A": "#8b9296", "L": "#6e7478"}

# Bold lowercase pixel glyphs for the logo: x-height 12 rows, "t" rises 4 rows above.
LOGO_GLYPHS = {
    "a": [
        "..#######.",
        ".#########",
        ".##....###",
        ".......###",
        "..########",
        ".#########",
        "###....###",
        "###....###",
        "###...####",
        "##########",
        ".#########",
        "..####.###",
    ],
    "n": [
        "###.#####.",
        "##########",
        "####...###",
        "###....###",
        "###....###",
        "###....###",
        "###....###",
        "###....###",
        "###....###",
        "###....###",
        "###....###",
        "###....###",
    ],
    "t": [
        ".###....",
        ".###....",
        ".###....",
        ".###....",
        "########",
        "########",
        ".###....",
        ".###....",
        ".###....",
        ".###....",
        ".###....",
        ".###....",
        ".###....",
        ".####...",
        "..######",
        "...#####",
    ],
    "s": [
        "..######..",
        ".########.",
        "###....###",
        "###.......",
        ".######...",
        "..#######.",
        "......####",
        ".......###",
        "###....###",
        "###....###",
        ".########.",
        "..######..",
    ],
}

# 5x9 pixel font for the tagline: rows 0-6 sit on the baseline, rows 7-8 are descenders.
# Glyphs shorter than 9 rows are padded at the bottom.
SMALL_GLYPHS = {
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "a": [".....", ".....", ".###.", "....#", ".####", "#...#", ".####"],
    "b": ["#....", "#....", "####.", "#...#", "#...#", "#...#", "####."],
    "c": [".....", ".....", ".###.", "#....", "#....", "#....", ".###."],
    "d": ["....#", "....#", ".####", "#...#", "#...#", "#...#", ".####"],
    "e": [".....", ".....", ".###.", "#...#", "#####", "#....", ".###."],
    "f": ["..##.", ".#...", "####.", ".#...", ".#...", ".#...", ".#..."],
    "g": [".....", ".....", ".####", "#...#", "#...#", "#...#", ".####", "....#", ".###."],
    "h": ["#....", "#....", "####.", "#...#", "#...#", "#...#", "#...#"],
    "i": ["..#..", ".....", ".##..", "..#..", "..#..", "..#..", ".###."],
    "k": ["#....", "#....", "#..#.", "#.#..", "##...", "#.#..", "#..#."],
    "l": [".##..", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "m": [".....", ".....", "##.#.", "#.#.#", "#.#.#", "#.#.#", "#.#.#"],
    "n": [".....", ".....", "####.", "#...#", "#...#", "#...#", "#...#"],
    "o": [".....", ".....", ".###.", "#...#", "#...#", "#...#", ".###."],
    "p": [".....", ".....", "####.", "#...#", "#...#", "#...#", "####.", "#....", "#...."],
    "r": [".....", ".....", "#.##.", "##..#", "#....", "#....", "#...."],
    "s": [".....", ".....", ".####", "#....", ".###.", "....#", "####."],
    "t": [".#...", ".#...", "####.", ".#...", ".#...", ".#..#", "..##."],
    "v": [".....", ".....", "#...#", "#...#", "#...#", ".#.#.", "..#.."],
    "y": [".....", ".....", "#...#", "#...#", "#...#", "#...#", ".####", "....#", ".###."],
    " ": ["...", "...", "...", "...", "...", "...", "..."],
}
SMALL_H = 9


def text_rows(
    text: str, glyphs: dict[str, list[str]], gap: int, height: int, *, bottom: bool
) -> list[str]:
    """Render text as pixel rows ('#' on), each glyph padded to `height`.

    bottom=True aligns glyphs on their last row (the logo's baseline); False on their first row
    (the tagline font, whose descenders hang below row 6).
    """
    rows = [""] * height
    for i, ch in enumerate(text):
        glyph = glyphs[ch]
        w = len(glyph[0])
        if bottom:
            padded = ["." * w] * (height - len(glyph)) + glyph
        else:
            padded = glyph + ["." * w] * (height - len(glyph))
        sep = "." * gap if i < len(text) - 1 else ""
        rows = [r + g + sep for r, g in zip(rows, padded, strict=True)]
    return rows


def rects(rows: list[str], colors: dict[str, str], ox: float, oy: float, p: float) -> str:
    """Pixel rows as <rect>s, merging horizontal runs of one color."""
    out = []
    for r, row in enumerate(rows):
        c = 0
        while c < len(row):
            v = row[c]
            if v in colors:
                end = c
                while end + 1 < len(row) and row[end + 1] == v:
                    end += 1
                out.append(
                    f'<rect x="{ox + c * p:g}" y="{oy + r * p:g}" width="{(end - c + 1) * p:g}" '
                    f'height="{p:g}" fill="{colors[v]}"/>'
                )
                c = end + 1
            else:
                c += 1
    return "".join(out)


def ant_svg(p: int, frame: int) -> str:
    return rects(ANT_BODY + ANT_LEGS[frame], ANT_COLORS, 0, 0, p)


def fmt(xs: list[float]) -> str:
    return ";".join(f"{x:g}" for x in xs)


def discrete(attr: str, values: list[float], times: list[float]) -> str:
    """A discrete SMIL animation over one cycle; `times` in seconds, first must be 0."""
    kt = fmt([round(t / CYCLE, 5) for t in times])
    return (
        f'<animate attributeName="{attr}" values="{fmt(values)}" keyTimes="{kt}" '
        f'dur="{CYCLE:g}s" calcMode="discrete" repeatCount="indefinite"/>'
    )


def opacity(points: list[tuple[float, float]]) -> str:
    """Linear opacity keyframes over one cycle: [(seconds, opacity), ...], from 0 to CYCLE."""
    kt = ";".join(f"{t / CYCLE:.4f}" for t, _ in points)
    vals = ";".join(f"{o:g}" for _, o in points)
    return (
        f'<animate attributeName="opacity" values="{vals}" keyTimes="{kt}" '
        f'dur="{CYCLE:g}s" repeatCount="indefinite"/>'
    )


def sweep(
    x0: float, cols: int, p: float, t0: float, t1: float, cid: str, height: float
) -> tuple[str, str]:
    """Clip paths revealing `cols` pixel columns from x0 between t0 and t1, column by column.

    Returns (defs, glow_defs): the growing reveal clip, and a 3-column band at its leading edge
    that exists only during the sweep.
    """
    times = [0.0, t0] + [t0 + (t1 - t0) * (i + 1) / cols for i in range(cols)]
    widths = [0.0, 0.0] + [(i + 1) * p for i in range(cols)]
    band_x = [-W, -W] + [x0 + (i + 1) * p - 3 * p for i in range(cols)]
    times.append(t1 + 0.05)
    widths.append(cols * p)
    band_x.append(-W)
    reveal = (
        f'<clipPath id="{cid}"><rect x="{x0:g}" y="0" width="0" height="{height:g}">'
        f"{discrete('width', widths, times)}</rect></clipPath>"
    )
    glow = (
        f'<clipPath id="{cid}-glow"><rect x="{-W}" y="0" width="{3 * p:g}" height="{height:g}">'
        f"{discrete('x', band_x, times)}</rect></clipPath>"
    )
    return reveal, glow


def logo() -> str:
    """The lead ant walking in and laying "ants"; parks in the logo pose; fades out."""
    rows = text_rows("ants", LOGO_GLYPHS, 2, 16, bottom=True)
    word_w = len(rows[0])
    ant_w, ant_h = len(ANT_BODY[0]), len(ANT_BODY) + len(ANT_LEGS[0])
    gx0 = (W // P - (ant_w + 3 + word_w)) // 2  # grid column of the parked ant
    word_x0 = gx0 + ant_w + 3
    word_y0 = 8
    ant_y0 = word_y0 + len(rows) - ant_h  # feet on the baseline, like the logo

    cols = list(range(W // P + 1, gx0 - 1, -1))
    t0, t1 = WALK
    times = [t0 + (t1 - t0) * i / (len(cols) - 1) for i in range(len(cols))]
    ant_x = [c * P for c in cols]
    edge = [x + ant_w * P for x in ant_x]  # the reveal edge is the ant's tail
    legs_a = [1 - i % 2 for i in range(len(cols))]
    legs_b = [i % 2 for i in range(len(cols))]
    move = (
        f'<animateTransform attributeName="transform" type="translate" '
        f'values="{";".join(f"{x:g} 0" for x in ant_x)}" '
        f'keyTimes="{fmt([round(t / CYCLE, 5) for t in times])}" dur="{CYCLE:g}s" '
        f'calcMode="discrete" repeatCount="indefinite"/>'
    )

    ink = rects(rows, {"#": INK}, word_x0 * P, word_y0 * P, P)
    glow = rects(rows, {"#": GLOW}, word_x0 * P, word_y0 * P, P)
    f0, f1 = LOGO_FADE
    return (
        f"<defs>"
        f'<clipPath id="laid"><rect y="0" width="{W}" height="{H}">'
        f"{discrete('x', edge, times)}</rect></clipPath>"
        f'<clipPath id="fresh"><rect y="0" width="{3 * P}" height="{H}">'
        f"{discrete('x', edge, times)}</rect></clipPath>"
        f"</defs>"
        f"<g>{opacity([(0, 1), (f0, 1), (f1, 0), (CYCLE, 0)])}"
        f'<g clip-path="url(#laid)">{ink}</g>'
        f'<g clip-path="url(#fresh)">{glow}</g>'
        f'<g transform="translate(0 {ant_y0 * P})"><g>{move}'
        f"<g>{discrete('opacity', legs_a, times)}{ant_svg(P, 0)}</g>"
        f'<g opacity="0">{discrete("opacity", legs_b, times)}{ant_svg(P, 1)}</g>'
        f"</g></g></g>"
    )


def tagline() -> str:
    """The tagline sweeping in line by line after the logo fades, with the accent word in GLOW."""
    line_gap = 4 * TP
    block_h = len(TAGLINE) * SMALL_H * TP + (len(TAGLINE) - 1) * line_gap
    y = (8 * P + 24 * P) / 2 - block_h / 2  # centred on the logo's vertical span
    defs, body = [], []
    for i, (line, (t0, t1)) in enumerate(zip(TAGLINE, LINES, strict=True)):
        rows = text_rows(line, SMALL_GLYPHS, 1, SMALL_H, bottom=False)
        cols = len(rows[0])
        x0 = (W - cols * TP) / 2
        # Accent: colour the accent word's columns.
        colored = rows
        if ACCENT in line:
            start = line.index(ACCENT)
            a0 = sum(len(SMALL_GLYPHS[c][0]) + 1 for c in line[:start])
            a1 = a0 + sum(len(SMALL_GLYPHS[c][0]) + 1 for c in ACCENT) - 1
            colored = [r[:a0] + r[a0:a1].replace("#", "@") + r[a1:] for r in rows]
        reveal, glow = sweep(x0, cols, TP, t0, t1, f"line{i}", H)
        defs += [reveal, glow]
        body.append(
            f'<g clip-path="url(#line{i})">{rects(colored, {"#": INK, "@": GLOW}, x0, y, TP)}</g>'
            f'<g clip-path="url(#line{i}-glow)">{rects(rows, {"#": GLOW}, x0, y, TP)}</g>'
        )
        y += SMALL_H * TP + line_gap
    e0, e1 = END_FADE
    return (
        f"<defs>{''.join(defs)}</defs>"
        f"<g>{opacity([(0, 1), (e0, 1), (e1, 0), (CYCLE, 0)])}{''.join(body)}</g>"
    )


def trail() -> str:
    """Small ants marching left along the bottom, forever."""
    sp, spacing = 3, 150
    ant_h = len(ANT_BODY) + len(ANT_LEGS[0])
    lane_y = H - ant_h * sp - 14
    ants = []
    for i in range(W // spacing + 2):
        tick = f'dur="0.36s" calcMode="discrete" repeatCount="indefinite" begin="{i * 0.09:.2f}s"'
        ants.append(
            f'<g transform="translate({i * spacing} {lane_y})"><g opacity="0.55">'
            f'<g>{ant_svg(sp, 0)}<animate attributeName="opacity" values="1;0" {tick}/></g>'
            f'<g opacity="0">{ant_svg(sp, 1)}'
            f'<animate attributeName="opacity" values="0;1" {tick}/></g>'
            f"</g></g>"
        )
    march = (
        f'<animateTransform attributeName="transform" type="translate" '
        f'values="0 0;-{spacing} 0" dur="2.4s" repeatCount="indefinite"/>'
    )
    return f"<g>{''.join(ants)}{march}</g>"


def build() -> str:
    label = "ants: a pixel ant lays down the word ants; then: " + " ".join(TAGLINE)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" '
        f'height="{H}" shape-rendering="crispEdges" role="img" aria-label="{label}">'
        f"<title>ants</title>"
        f'<rect width="{W}" height="{H}" fill="{BG}"/>'
        f"{logo()}{tagline()}{trail()}"
        f"</svg>\n"
    )


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT}")
