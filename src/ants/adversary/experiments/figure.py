"""Figure for the adaptive vs uniform experiment: cumulative failures found per attack.

    uv run python -m ants.adversary.experiments.figure data/runs/adaptive_vs_uniform_<time>

Reads `results.json` and writes two files next to it:
- `figure.svg`: static, light, for slides and the demo video.
- `figure.html`: the same chart with light/dark themes, a crosshair tooltip and a table view.

One line per arm: the mean over seeds of failures found after each attack, with a band from the
lowest to the highest seed. Colors: categorical slots 1 (blue, adaptive) and 2 (orange, uniform)
of the dataviz reference palette, validated for both themes. Both lines are also labelled at their
end, so identity never depends on color alone. The title says when the backend is the mock world.
"""

from __future__ import annotations

import html
import json
import statistics
import sys
from pathlib import Path
from typing import Any

W, H = 720, 400
PAD_L, PAD_R, PAD_T, PAD_B = 56, 110, 64, 48
ARM_LABEL = {"adaptive": "Adaptive (η 0.2)", "uniform": "Uniform (η 1.0)"}
ARM_VAR = {"adaptive": "--series-1", "uniform": "--series-2"}
LIGHT = {"--surface": "#fcfcfb", "--text-primary": "#0b0b0b", "--text-secondary": "#52514e",
         "--grid": "#e4e3df", "--series-1": "#2a78d6", "--series-2": "#eb6834"}  # fmt: skip
DARK = {"--surface": "#1a1a19", "--text-primary": "#f0efec", "--text-secondary": "#c3c2b7",
        "--grid": "#33332f", "--series-1": "#3987e5", "--series-2": "#d95926"}  # fmt: skip


def series(results: dict[str, Any]) -> dict[str, dict[str, list[float]]]:
    """Per arm: mean, low and high cumulative failures after attack 1..n, over seeds."""
    out: dict[str, dict[str, list[float]]] = {}
    for arm in results["arms"]:
        curves = [r["cumulative"] for r in results["runs"] if r["arm"] == arm]
        if not curves:
            continue
        cols = list(zip(*curves, strict=True))
        out[arm] = {
            "mean": [round(statistics.mean(c), 3) for c in cols],
            "low": [float(min(c)) for c in cols],
            "high": [float(max(c)) for c in cols],
        }
    return out


def _nice_max(v: float) -> int:
    step = 2 if v <= 10 else 5 if v <= 30 else 10
    return max(step, int(-(-v // step) * step))


def svg(results: dict[str, Any], themed: bool = False) -> str:
    data = series(results)
    n = results["attacks"]
    ymax = _nice_max(max((max(s["high"]) for s in data.values()), default=1))
    pw, ph = W - PAD_L - PAD_R, H - PAD_T - PAD_B

    def x(i: int) -> float:  # attack index 1..n
        return PAD_L + (i - 1) / max(1, n - 1) * pw

    def y(v: float) -> float:
        return PAD_T + ph - v / ymax * ph

    def c(var: str) -> str:
        return f"var({var})" if themed else (LIGHT[var])

    mock = results.get("config", {}).get("backend") == "mock"
    title = "Failures found per attack budget"
    sub = (f"{len(results['seeds'])} seeds × {n} attacks per arm, one fixed policy · mean, band = "
           "range over seeds" + (" · MOCK WORLD, not a result" if mock else ""))  # fmt: skip
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" '
        f'aria-label="{html.escape(title)}" font-family="system-ui, sans-serif">',
        f'<rect width="{W}" height="{H}" fill="{c("--surface")}"/>',
        f'<text x="{PAD_L}" y="26" font-size="17" font-weight="600" '
        f'fill="{c("--text-primary")}">{html.escape(title)}</text>',
        f'<text x="{PAD_L}" y="46" font-size="12" fill="{c("--text-secondary")}">'
        f"{html.escape(sub)}</text>",
    ]
    for t in range(0, ymax + 1, max(1, ymax // 5)):
        parts.append(f'<line x1="{PAD_L}" x2="{PAD_L + pw}" y1="{y(t):.1f}" y2="{y(t):.1f}" '
                     f'stroke="{c("--grid")}" stroke-width="1"/>')  # fmt: skip
        parts.append(f'<text x="{PAD_L - 8}" y="{y(t) + 4:.1f}" font-size="11" text-anchor="end" '
                     f'fill="{c("--text-secondary")}" style="font-variant-numeric:tabular-nums">'
                     f"{t}</text>")  # fmt: skip
    ticks = sorted({1, *range(5, n + 1, 5), n})
    for i in ticks:
        parts.append(f'<text x="{x(i):.1f}" y="{PAD_T + ph + 18}" font-size="11" '
                     f'text-anchor="middle" fill="{c("--text-secondary")}">{i}</text>')  # fmt: skip
    parts.append(f'<text x="{PAD_L + pw / 2:.1f}" y="{H - 10}" font-size="12" text-anchor="middle" '
                 f'fill="{c("--text-secondary")}">Attacks run</text>')  # fmt: skip
    parts.append(f'<text x="14" y="{PAD_T + ph / 2:.1f}" font-size="12" text-anchor="middle" '
                 f'fill="{c("--text-secondary")}" transform="rotate(-90 14 {PAD_T + ph / 2:.1f})">'
                 "Task failures found</text>")  # fmt: skip
    ends = []
    for arm, s in data.items():
        col = c(ARM_VAR.get(arm, "--series-1"))
        idx = range(1, len(s["mean"]) + 1)
        band = [f"{x(i):.1f},{y(v):.1f}" for i, v in zip(idx, s["high"], strict=True)]
        low = list(zip(idx, s["low"], strict=True))
        band += [f"{x(i):.1f},{y(v):.1f}" for i, v in reversed(low)]
        parts.append(f'<polygon points="{" ".join(band)}" fill="{col}" fill-opacity="0.14"/>')
        line = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in zip(idx, s["mean"], strict=True))
        parts.append(f'<polyline points="{line}" fill="none" stroke="{col}" stroke-width="2" '
                     'stroke-linejoin="round" stroke-linecap="round"/>')  # fmt: skip
        ex, ey = x(len(s["mean"])), y(s["mean"][-1])
        parts.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="4" fill="{col}" '
                     f'stroke="{c("--surface")}" stroke-width="2"/>')  # fmt: skip
        ends.append([arm, ey, s["mean"][-1]])
    ends.sort(key=lambda e: e[1])
    for k in range(1, len(ends)):  # keep end labels at least 30 px apart
        ends[k][1] = max(ends[k][1], ends[k - 1][1] + 30)
    for arm, ly, v in ends:
        parts.append(f'<text x="{PAD_L + pw + 10}" y="{ly + 4:.1f}" font-size="12" '
                     f'font-weight="600" fill="{c("--text-primary")}">{ARM_LABEL.get(arm, arm)}'
                     f'<tspan x="{PAD_L + pw + 10}" dy="15" font-weight="400" '
                     f'fill="{c("--text-secondary")}">{v:g} failures</tspan></text>')  # fmt: skip
    parts.append("</svg>")
    return "\n".join(parts)


def page(results: dict[str, Any]) -> str:
    data = series(results)

    def tokens(d: dict[str, str]) -> str:
        return "".join(f"{k}:{v};" for k, v in d.items())

    rows = "".join(
        f"<tr><td>{i}</td>"
        + "".join(f"<td>{data[a]['mean'][i - 1]:g}</td>" for a in data)
        + "</tr>"
        for i in range(1, results["attacks"] + 1)
    )
    head = "".join(f"<th>{ARM_LABEL.get(a, a)} (mean)</th>" for a in data)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Adaptive vs uniform</title>
<style>
:root {{ {tokens(LIGHT)} color-scheme: light; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ {tokens(DARK)}
  color-scheme: dark; }} }}
:root[data-theme="dark"] {{ {tokens(DARK)} color-scheme: dark; }}
body {{ margin: 0; padding: 24px 16px; background: var(--surface); color: var(--text-primary);
  font-family: system-ui, sans-serif; }}
.wrap {{ max-width: 760px; margin: 0 auto; position: relative; }}
svg {{ width: 100%; height: auto; display: block; }}
#tip {{ position: absolute; pointer-events: none; background: var(--surface);
  border: 1px solid var(--grid); border-radius: 6px; padding: 6px 9px; font-size: 13px;
  box-shadow: 0 2px 8px rgba(0,0,0,.15); display: none; font-variant-numeric: tabular-nums; }}
table {{ border-collapse: collapse; font-size: 13px; margin-top: 16px;
  font-variant-numeric: tabular-nums; }}
th, td {{ padding: 3px 10px; text-align: right; border-bottom: 1px solid var(--grid); }}
summary {{ cursor: pointer; color: var(--text-secondary); margin-top: 12px; }}
</style></head><body><div class="wrap">
{svg(results, themed=True)}
<div id="tip"></div>
<details><summary>Table view</summary><table><thead><tr><th>Attack</th>{head}</tr></thead>
<tbody>{rows}</tbody></table></details>
</div>
<script>
const DATA = {json.dumps({"series": data, "n": results["attacks"], "labels": ARM_LABEL})};
const svgEl = document.querySelector("svg"), tip = document.getElementById("tip");
const [PL, PR, W] = [{PAD_L}, {PAD_R}, {W}];
const cross = document.createElementNS("http://www.w3.org/2000/svg", "line");
cross.setAttribute("y1", {PAD_T}); cross.setAttribute("y2", {H - PAD_B});
cross.setAttribute("stroke", "var(--text-secondary)");
cross.setAttribute("stroke-dasharray", "3 3");
cross.style.display = "none"; svgEl.appendChild(cross);
svgEl.addEventListener("pointermove", (e) => {{
  const r = svgEl.getBoundingClientRect(), sx = (e.clientX - r.left) / r.width * W;
  const i = Math.round((sx - PL) / (W - PL - PR) * (DATA.n - 1)) + 1;
  if (i < 1 || i > DATA.n) {{ tip.style.display = cross.style.display = "none"; return; }}
  const cx = PL + (i - 1) / Math.max(1, DATA.n - 1) * (W - PL - PR);
  cross.setAttribute("x1", cx); cross.setAttribute("x2", cx); cross.style.display = "";
  const lines = Object.entries(DATA.series).map(([a, s]) => `${{DATA.labels[a] || a}}: ` +
    `${{s.mean[i - 1]}} (range ${{s.low[i - 1]}}–${{s.high[i - 1]}})`);
  tip.innerHTML = `<b>After attack ${{i}}</b><br>` + lines.join("<br>");
  tip.style.display = "block";
  tip.style.left = Math.min(e.clientX - r.left + 14, r.width - 230) + "px";
  tip.style.top = (e.clientY - r.top + 14) + "px";
}});
svgEl.addEventListener("pointerleave", () => {{
  tip.style.display = cross.style.display = "none";
}});
</script></body></html>
"""


def write(run_dir: Path) -> tuple[Path, Path]:
    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    out_svg, out_html = run_dir / "figure.svg", run_dir / "figure.html"
    out_svg.write_text(svg(results), encoding="utf-8")
    out_html.write_text(page(results), encoding="utf-8")
    return out_svg, out_html


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__)
        return 2
    for p in write(Path(args[0])):
        print(f"wrote {p.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
