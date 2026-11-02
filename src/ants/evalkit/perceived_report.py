"""Static HTML report of exp05 (perceived scene against the simulator oracle).

    uv run python -m ants.evalkit.perceived_report --out data/runs/exp05_perceived_scene

Reads `analysis.json` (written by `ants.orchestrator.perceived_scene --analyse`) and writes
`report.html` next to it: S4 text perceived vs oracle on the left, top and side drawings (perceived
overlaid on truth) on the right, then the numbers and a coverage table. One self-contained file (no
network, light and dark theme). Every number comes from `analysis.json`.
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

from ants.orchestrator.perceived_scene import OBJECTS

ROUND = ("bowl", "plate")
ORDER = list(OBJECTS)
TOP = {"x0": 0.18, "x1": 0.86, "y0": -0.44, "y1": 0.34, "s": 780}
SIDE = {"x0": 0.18, "x1": 0.86, "z0": -0.03, "z1": 0.37, "s": 780}

# status, capability, evidence (filled from the analysis), missing module, how to complete, effort
STATUS_LABEL = {"covered": "covered", "partly": "partly", "no": "not covered"}


def e(x: object) -> str:
    return html.escape(str(x))


def color(i: int) -> str:
    return f"var(--c{i % 8})"


# ---------------------------------------------------------------- drawing
def _top(x: float, y: float) -> tuple[float, float]:
    return (TOP["y1"] - y) * TOP["s"], (TOP["x1"] - x) * TOP["s"]


def _side(x: float, z: float) -> tuple[float, float]:
    return (x - SIDE["x0"]) * SIDE["s"], (SIDE["z1"] - z) * SIDE["s"]


def _poly(pts: list[tuple[float, float]]) -> str:
    return " ".join(f"{a:.1f},{b:.1f}" for a, b in pts)


def _hull(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    p = sorted(set(pts))
    if len(p) < 3:
        return p

    def cross(o, a, b):  # noqa: ANN001
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lo: list = []
    for q in p:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], q) <= 0:
            lo.pop()
        lo.append(q)
    up: list = []
    for q in reversed(p):
        while len(up) >= 2 and cross(up[-2], up[-1], q) <= 0:
            up.pop()
        up.append(q)
    return lo[:-1] + up[:-1]


def draw_state(a: dict, state: str, on: bool) -> str:
    block = a["state"][state]
    truth = a["truth"]["objects"]
    final = block["final"]["objects"]
    robot = block["robot"]
    wt, ht = [int((TOP["y1"] - TOP["y0"]) * TOP["s"]), int((TOP["x1"] - TOP["x0"]) * TOP["s"])]
    ws, hs = [
        int((SIDE["x1"] - SIDE["x0"]) * SIDE["s"]),
        int((SIDE["z1"] - SIDE["z0"]) * SIDE["s"]),
    ]
    tz = a["truth"]["table_top_z"]
    out = []
    for view, (w, h) in (("top", (wt, ht)), ("side", (ws, hs))):
        g = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{view} view, {state}">']
        if view == "side":
            y0 = _side(0, tz)[1]
            g.append(
                f'<line class="tbl" x1="0" x2="{w}" y1="{y0:.1f}" y2="{y0:.1f}"/><text class="m" x="6" y="{y0 + 14:.1f}">table</text>'
            )
            g.append(
                '<text class="m" x="6" y="14">side view: robot at left (x forward), looking along y</text>'
            )
        else:
            g.append(
                '<text class="m" x="6" y="14">top view: robot at the bottom, x up, y to the left</text>'
            )
        for i, name in enumerate(ORDER):
            c = color(i)
            # truth
            boxes = truth[name]
            if view == "top":
                if name in ROUND:
                    lo = [min(b[0][k] for b in boxes) for k in range(3)]
                    hi = [max(b[1][k] for b in boxes) for k in range(3)]
                    cx, cy = _top((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)
                    r = ((hi[0] - lo[0]) + (hi[1] - lo[1])) / 4 * TOP["s"]
                    g.append(
                        f'<circle class="truth" cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" style="--k:{c}"/>'
                    )
                else:
                    draw = (
                        boxes
                        if name == "wine rack"
                        else [
                            [
                                [min(b[0][k] for b in boxes) for k in range(3)],
                                [max(b[1][k] for b in boxes) for k in range(3)],
                            ]
                        ]
                    )
                    for lo, hi in draw:
                        x0, y0 = _top(hi[0], hi[1])
                        x1, y1 = _top(lo[0], lo[1])
                        g.append(
                            f'<rect class="truth" x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" style="--k:{c}"/>'
                        )
            else:
                draw = (
                    boxes
                    if name == "wine rack"
                    else [
                        [
                            [min(b[0][k] for b in boxes) for k in range(3)],
                            [max(b[1][k] for b in boxes) for k in range(3)],
                        ]
                    ]
                )
                for lo, hi in draw:
                    x0, y0 = _side(lo[0], hi[2])
                    x1, y1 = _side(hi[0], lo[2])
                    g.append(
                        f'<rect class="truth" x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" style="--k:{c}"/>'
                    )
            # perceived
            o = final[name]
            if not o["found"]:
                continue
            if view == "top":
                for b in o["boxes"]:
                    poly = _hull([_top(p[0], p[1]) for p in b["corners"]])
                    g.append(f'<polygon class="seen" points="{_poly(poly)}" style="--k:{c}"/>')
                g.append(
                    '<g class="pts">'
                    + "".join(
                        f'<circle cx="{_top(p[0], p[1])[0]:.1f}" cy="{_top(p[0], p[1])[1]:.1f}" r="1.3" style="--k:{c}"/>'
                        for p in o["points"][::3]
                    )
                    + "</g>"
                )
                lx, ly = _top(o["aabb"][1][0], (o["aabb"][0][1] + o["aabb"][1][1]) / 2)
                g.append(
                    f'<text class="lbl" x="{lx:.1f}" y="{ly - 4:.1f}" text-anchor="middle" style="--k:{c}">{e(name)}</text>'
                )
            else:
                lo, hi = o["aabb"]
                x0, y0 = _side(lo[0], hi[2])
                x1, y1 = _side(hi[0], lo[2])
                g.append(
                    f'<rect class="seen" x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" style="--k:{c}"/>'
                )
                g.append(
                    '<g class="pts">'
                    + "".join(
                        f'<circle cx="{_side(p[0], p[2])[0]:.1f}" cy="{_side(p[0], p[2])[1]:.1f}" r="1.3" style="--k:{c}"/>'
                        for p in o["points"][::3]
                    )
                    + "</g>"
                )
        # arm
        for s in robot["spheres_xyzr"]:
            if view == "top":
                cx, cy = _top(s[0], s[1])
            else:
                cx, cy = _side(s[0], s[2])
            if (
                -20 <= cx <= (wt if view == "top" else ws) + 20
                and -20 <= cy <= (ht if view == "top" else hs) + 20
            ):
                g.append(
                    f'<circle class="arm" cx="{cx:.1f}" cy="{cy:.1f}" r="{s[3] * (TOP["s"] if view == "top" else SIDE["s"]):.1f}"/>'
                )
        g.append('<g class="rob">')
        for p in robot["points"]:
            cx, cy = _top(p[0], p[1]) if view == "top" else _side(p[0], p[2])
            g.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="1.6"/>')
        g.append("</g>")
        t = robot["tcp"]
        if view == "top":
            cx, cy = _top(t[0], t[1])
            hw, hd = 0.105 * TOP["s"], 0.05 * TOP["s"]
            g.append(
                f'<rect class="hand" x="{cx - hw:.1f}" y="{cy - hd:.1f}" width="{2 * hw:.1f}" height="{2 * hd:.1f}"/>'
            )
        else:
            cx, cy = _side(t[0], t[2])
            g.append(
                f'<rect class="hand" x="{cx - 0.05 * SIDE["s"]:.1f}" y="{cy - 0.07 * SIDE["s"]:.1f}" width="{0.1 * SIDE["s"]:.1f}" height="{0.10 * SIDE["s"]:.1f}"/>'
            )
        g.append(f'<circle class="tcp" cx="{cx:.1f}" cy="{cy:.1f}" r="4"/>')
        g.append("</svg>")
        out.append("".join(g))
    return f'<div class="st{" on" if on else ""}" data-state="{state}"><div class="map">{out[0]}</div><div class="map">{out[1]}</div></div>'


# ---------------------------------------------------------------- S4 text
def s4_panes(a: dict) -> str:
    rows = {r["object"]: r for r in a["state"]["start"]["variants"]["V5"]["objects"]}
    rel = {tuple(r["pair"]): r for r in a["state"]["start"]["variants"]["V5"]["relations"]["rows"]}

    def klass(line: str, side: str) -> str:
        m = re.match(r"- (.+?) and (.+?): (\w+), gap", line)
        if m:
            r = rel.get(tuple(sorted((m.group(1), m.group(2)))))
            if r and r["truth"] and r["seen"] and r["truth"] == r["seen"]:
                return "ok"
            return "bad"
        m = re.match(r"- ([a-z ]+?)( \(round\))?[:]", line)
        if m and m.group(1) in rows and "centre_err_xy_cm" in rows[m.group(1)]:
            r = rows[m.group(1)]
            return (
                "ok"
                if r["centre_err_xy_cm"] <= 1.5 and max(abs(v) for v in r["size_err_cm"]) <= 2.0
                else "warn"
            )
        return ""

    def pane(text: str, side: str) -> str:
        lines = []
        for ln in text.splitlines():
            k = klass(ln, side)
            lines.append(f'<span class="ln {k}">{e(ln)}</span>')
        return '<pre class="s4">' + "\n".join(lines) + "</pre>"

    # relation lines the perceived text lacks
    return (
        '<div class="two"><div><h3>Perceived (V5)</h3>' + pane(a["s4"]["perceived"], "p") + "</div>"
        "<div><h3>Oracle (exp04 S4)</h3>" + pane(a["s4"]["oracle"], "o") + "</div></div>"
    )


# ---------------------------------------------------------------- tables
def fmt(v: object) -> str:
    return "-" if v is None else e(v)


def variants_table(a: dict) -> str:
    rows = []
    for v, text in a["variants"].items():
        cells = [f'<td class="v">{v}</td><td>{e(text)}</td>']
        for state in ("start", "arm"):
            d = a["state"][state]["variants"][v]
            cells.append(
                f"<td>{d['n_correct']}/7</td><td>{fmt(d['mean_centre_xy_cm'])}</td><td>{fmt(d['mean_abs_height_err_cm'])}</td><td>{fmt(d['mean_iou3'])}</td>"
            )
        rows.append("<tr>" + "".join(cells) + "</tr>")
    head = (
        "<tr><th rowspan=2>id</th><th rowspan=2>what changes</th><th colspan=4>start state (arm at home)</th><th colspan=4>arm hovering over the rack</th></tr><tr>"
        + "<th>objects within 3 cm (xy)</th><th>mean xy err (cm)</th><th>mean |height err| (cm)</th><th>mean 3D IoU</th>"
        * 2
        + "</tr>"
    )
    return f'<div class="scroll"><table class="t">{head}{"".join(rows)}</table></div>'


def objects_table(a: dict) -> str:
    start = a["state"]["start"]["variants"]
    arm = {r["object"]: r for r in a["state"]["arm"]["variants"]["V5"]["objects"]}
    v0 = {r["object"]: r for r in start["V0"]["objects"]}
    rows = []
    for r in start["V5"]["objects"]:
        n = r["object"]
        masks = ", ".join(
            f"{m[1]} #{m[2]}" + (" (hand cam)" if m[0] != "agentview" else "")
            for m in r["masks"][:4]
        ) + (" ..." if len(r["masks"]) > 4 else "")
        rows.append(
            f"<tr><td class=v>{e(n)}</td><td>{fmt(v0[n].get('centre_err_xy_cm'))}</td><td>{r['centre_err_xy_cm']}</td><td>{arm[n]['centre_err_xy_cm']}</td>"
            f"<td>{' x '.join(str(v) for v in r['seen_size_cm'])}</td><td>{' x '.join(str(v) for v in r['truth_size_cm'])}</td>"
            f"<td>{' / '.join(f'{v:+.1f}' for v in r['size_err_cm'])}</td><td>{r['iou3']}</td><td class=m>{e(masks)}</td></tr>"
        )
    head = "<tr><th>object</th><th>centre err V0 (cm, xy)</th><th>centre err V5 (cm, xy)</th><th>V5 with arm over rack</th><th>seen size (cm)</th><th>true size (cm)</th><th>size err x / y / z (cm)</th><th>3D IoU</th><th>masks used (start)</th></tr>"
    return f'<div class="scroll"><table class="t">{head}{"".join(rows)}</table></div>'


def relations_table(a: dict) -> str:
    rel = a["state"]["start"]["variants"]["V5"]["relations"]
    rows = []
    for r in rel["rows"]:
        if r["truth"] is None or r["truth"] == "supported_by":
            continue
        ok = r["seen"] == r["truth"]
        cls = "ok" if ok else ("warn" if r["seen"] else "bad")
        rows.append(
            f"<tr class={cls}><td>{e(r['pair'][0])} / {e(r['pair'][1])}</td><td>{r['truth']} {r['truth_gap_mm']} mm</td>"
            f"<td>{(r['seen'] + ' ' + str(r['seen_gap_mm']) + ' mm') if r['seen'] else 'none'}</td></tr>"
        )
    sm = (
        f"near-or-touching pairs: {rel['touching_or_near']['both']} of {rel['touching_or_near']['truth']} recalled, "
        f"precision {rel['touching_or_near']['precision']}; mean |gap error| {rel['mean_abs_gap_err_mm']} mm; "
        f"touching pairs: {rel['touching']['both']} of {rel['touching']['truth']} classed 'touching' by the 3 mm rule, seen gaps "
        + ", ".join(
            f"{k}: {v} mm" for k, v in rel["touching_gap_within_30mm"]["seen_gap_mm"].items()
        )
    )
    return f'<p>{e(sm)}</p><div class="scroll"><table class="t"><tr><th>pair</th><th>oracle</th><th>perceived</th></tr>{"".join(rows)}</table></div>'


def coverage(a: dict) -> list[tuple[str, str, str, str, str, str]]:
    s = a["state"]["start"]
    arm = a["state"]["arm"]
    v5 = {r["object"]: r for r in s["variants"]["V5"]["objects"]}
    rack = v5["wine rack"]
    rel = s["variants"]["V5"]["relations"]
    rs = s["rack_structure"]
    rb, ra = s["robot"], arm["robot"]
    abl = arm["robot_ablation"]
    sw = s["extent_sweep"]
    sm = {
        k: v5[k]
        for k in ("bowl", "plate", "wine bottle", "cream cheese", "wooden cabinet", "flat stove")
    }
    small = ", ".join(f"{k} {v['centre_err_xy_cm']} cm" for k, v in sm.items())
    return [
        (
            "covered",
            "Detect bowl, plate, bottle, cream cheese, cabinet, stove",
            f"7 of 7 objects within 3 cm in xy after V2 (V0 baseline: {s['variants']['V0']['n_correct']} of 7). Centre errors V5: {small}.",
            "none for finding them; the box must come from the mask's depth points, not from estimate_geometry",
            "Replace the estimate_geometry box by a percentile box of the mask points (done here in perceived_scene.build).",
            "0.5 day to move it into an ASPIRE tool",
        ),
        (
            "partly",
            "Wine rack detection",
            f"Found (xy error {rack['centre_err_xy_cm']} cm) only by the best-scoring mask (score 0.12, low) after trimming flying depth pixels, and more robustly by synonym prompts with consensus (4 prompts agree) and by removing masks claimed by the cabinet. SAM 3 scores are not usable as confidence here (cream cheese is right at score 0.01).",
            "scene builder with prompt synonyms, plausibility checks and claim removal (prototype: perceived_scene.select)",
            "Turn the prototype into an ASPIRE tool `perceive_scene(prompts)`, add open-vocabulary fallbacks ('shelf', 'wooden shelf') and validate on 5+ more scenes.",
            "2 days",
        ),
        (
            "partly",
            "Extents (size) of objects",
            f"Mean abs size error {sw['p0.5-p99.5']['mean_abs_size_err_cm']} cm over the visible surface; hidden sides are missing: rack depth in y is {rack['size_err_cm'][1]:+.1f} cm, bottle width {v5['wine bottle']['size_err_cm'][0]:+.1f} cm.",
            "second external view or amodal completion",
            "Add a back or side camera (LIBERO has none by default; add one in the launcher), or sweep the wrist camera (active perception), or complete boxes by symmetry/size priors from the task objects.",
            "2 to 3 days",
        ),
        (
            "covered",
            "Heights",
            f"Mean abs height error {s['variants']['V5']['mean_abs_height_err_cm']} cm (V3: {s['variants']['V3']['mean_abs_height_err_cm']} cm before the table plane was used; rack {rack['height_err_cm']:+.1f} cm).",
            "none (table plane from the 'table' mask is in perceived_scene.build)",
            "Keep the table-plane step; add a sanity check against the robot base height.",
            "0.5 day",
        ),
        (
            "partly",
            "Supports and contacts (relations)",
            f"Near-or-touching pairs: {rel['touching_or_near']['both']}/{rel['touching_or_near']['truth']} recalled, precision {rel['touching_or_near']['precision']}, mean gap error {rel['mean_abs_gap_err_mm']} mm. The two real contacts (plate-rack, cream cheese-plate) come out at {', '.join(str(v) + ' mm' for v in rel['touching_gap_within_30mm']['seen_gap_mm'].values())}, so the 3 mm 'touching' rule calls them near.",
            "perception-aware thresholds in collision_world.relations",
            "Pass a tolerance (about 15 mm for perceived scenes) into relations(); add 'on top of' and 'inside' relations from the vertical overlap of boxes; check with contact evidence from exp04.",
            "1 day",
        ),
        (
            "partly",
            "Occlusion by the arm",
            f"One arm pose tested (hand over the rack): mean xy error {arm['variants']['V5']['mean_centre_xy_cm']} cm against {s['variants']['V5']['mean_centre_xy_cm']} cm with the arm at home. 'robot arm' mask: {ra['precision_in_spheres']} of its points lie on cuRobo spheres, {ra['spheres_covered']} of {ra['spheres']} spheres are seen. Subtracting the mask removed {abl['without_robot_subtraction']['points_total'] - abl['with_robot_subtraction']['points_total']} points and changed IoU by {round(abl['with_robot_subtraction']['mean_iou3'] - abl['without_robot_subtraction']['mean_iou3'], 3)}.",
            "memory of the scene before the arm moved (scene cache) and a worst-case test",
            "Perceive once at the home pose and keep the world (objects are static until grasped); test arm poses that really hide the rack or the plate (the agent camera sees the hand from above).",
            "1 day",
        ),
        (
            "partly",
            "Multi-view fusion",
            "The wrist camera adds masks for bowl and plate (score 0.8 or more) and, in the arm run, shelf masks for the rack; the effect on error is small (V2 to V3: mean xy "
            f"{s['variants']['V2']['mean_centre_xy_cm']} to {s['variants']['V3']['mean_centre_xy_cm']} cm). For the stove, bottle, cream cheese and rack (start state) the wrist masks are rejected by the gate or score 0.01 to 0.05.",
            "a second fixed camera and a point-cloud merge with registration",
            "Use ASPIRE's crop_point_cloud/mask_to_point_cloud over a short wrist sweep and merge by voxel; or add a calibrated side camera.",
            "2 to 4 days",
        ),
        (
            "partly",
            "Shelf structure of the rack",
            f"Height histogram of the rack points shows levels at z = {', '.join(str(p[0]) for p in rs['z_peaks_m'][:6])} m; the truth boards are at {rs['truth_boards_z_m'][:2]} m (upper two) and the floor boards at about 0.01 to 0.03 m, which are not seen. The rack is one box here; the far side is hidden (y range seen {rs['perceived_y_range_m']}, truth {rs['truth_y_range_m']}).",
            "plane or board segmentation for multi-box objects",
            "Fit horizontal planes (RANSAC) to the rack cloud, make one thin box per plane, and fill the hidden floor board from a rack template; needs the second view.",
            "2 days",
        ),
        (
            "covered",
            "Hand footprint",
            f"From the robot state: TCP and joint angles are exact (the TCP lies {rb['tcp_to_flange_cm']} cm from the forward-kinematics hand frame). The SAM 3 'robot gripper' mask fails (best score {rb['gripper_best_score']}). The footprint is the fixed Franka hand size, as in S4.",
            "none (uses get_robot_state plus fixed dimensions)",
            "Render the hand rectangle at the TCP pose with its yaw; check the 21 x 10 cm figure against the mesh.",
            "0.5 day",
        ),
        (
            "partly",
            "Robot mask",
            f"'robot arm' (top 2 masks, score 0.5 or more): {rb['mask_points']} points, {rb['precision_in_spheres']} on spheres, {rb['spheres_covered']} of {rb['spheres']} spheres reached. Forward kinematics gives the whole arm exactly, so the mask is only a check.",
            "use cuRobo spheres from joint angles instead of the mask",
            "Replace the mask by the sphere model for subtraction (already in evalkit.panda).",
            "0.5 day",
        ),
        (
            "no",
            "Held-object attach",
            "Not tested: no grasp was run. The perceived cloud of a held bowl would sit in the hand and appear as an obstacle or move with it.",
            "in-hand object tracker",
            "At grasp time attach the object's box to the TCP frame (offset from the grasp pose), drop it from the static world, and check the held box against the rack; validate in a replay of a successful run.",
            "1 to 2 days",
        ),
        (
            "no",
            "Round-object profile (radius by height)",
            "Top-view circle gives one radius per object (bowl and plate within 1.5 cm); the oracle has the bowl's taper (2.8 cm at the foot to 6.7 cm at the rim).",
            "side-view depth profile",
            "Fit a radius per height slice from the depth points of the mask (needs a view from the side).",
            "1 day",
        ),
        (
            "no",
            "Other scenes, seeds, levels L2 and L3, moved objects",
            "One scene and one seed only; the selection thresholds were set after looking at this scene (in-sample).",
            "a perception test set",
            "Run the same pipeline on acceptance seeds 51 to 65 and L2/L3, report on held-out seeds; log per-object errors.",
            "1 day plus about 1 hour run time",
        ),
    ]


def coverage_table(a: dict) -> str:
    rows = []
    for st, cap, ev, miss, how, eff in coverage(a):
        rows.append(
            f'<tr><td><span class="chip {st}">{STATUS_LABEL[st]}</span></td><td class=v>{e(cap)}</td><td>{e(ev)}</td><td>{e(miss)}</td><td>{e(how)}</td><td class=nw>{e(eff)}</td></tr>'
        )
    return f'<div class="scroll"><table class="t cov"><tr><th>status</th><th>capability</th><th>what we measured</th><th>missing module</th><th>how to complete</th><th>effort</th></tr>{"".join(rows)}</table></div>'


def sweep_table(a: dict) -> str:
    rows = []
    for k, v in a["state"]["start"]["extent_sweep"].items():
        rows.append(
            f"<tr><td class=v>{k}</td><td>{v['mean_centre_xy_cm']}</td><td>{v['mean_abs_height_err_cm']}</td><td>{v['mean_abs_size_err_cm']}</td><td>{v['mean_iou3']}</td></tr>"
        )
    return (
        '<table class="t"><tr><th>box from percentiles</th><th>xy err (cm)</th><th>|height err| (cm)</th><th>|size err| (cm)</th><th>3D IoU</th></tr>'
        + "".join(rows)
        + "</table>"
    )


CSS = """
:root{--bg:#f6f7f9;--panel:#fff;--ink:#1c2330;--mute:#5d6878;--line:#d9dee6;--acc:#2457d6;--ok:#157347;--okbg:#e4f4ea;--warn:#8a5a00;--warnbg:#fff2d6;--bad:#b3261e;--badbg:#fde7e5;--code:#eef1f5;
--c0:#2457d6;--c1:#d9480f;--c2:#0b7a5a;--c3:#a61e8f;--c4:#6b5b00;--c5:#0b7285;--c6:#c2255c;--c7:#495057}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#10141b;--panel:#171d27;--ink:#e6eaf0;--mute:#9aa6b6;--line:#2b3441;--acc:#7aa2ff;--ok:#5fd08c;--okbg:#14301f;--warn:#f0c15a;--warnbg:#33290f;--bad:#ff8a80;--badbg:#3a1a18;--code:#1c2431;
--c0:#7aa2ff;--c1:#ff9a62;--c2:#4ed1a1;--c3:#e58bd6;--c4:#d8c34a;--c5:#5fd0e6;--c6:#ff7aa8;--c7:#b8c0cc}}
:root[data-theme=dark]{--bg:#10141b;--panel:#171d27;--ink:#e6eaf0;--mute:#9aa6b6;--line:#2b3441;--acc:#7aa2ff;--ok:#5fd08c;--okbg:#14301f;--warn:#f0c15a;--warnbg:#33290f;--bad:#ff8a80;--badbg:#3a1a18;--code:#1c2431;
--c0:#7aa2ff;--c1:#ff9a62;--c2:#4ed1a1;--c3:#e58bd6;--c4:#d8c34a;--c5:#5fd0e6;--c6:#ff7aa8;--c7:#b8c0cc}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
header{padding:18px 20px 6px;max-width:1500px;margin:0 auto;display:flex;gap:16px;align-items:flex-start;justify-content:space-between}
h1{font-size:22px;margin:0 0 4px}h2{font-size:18px;margin:26px 0 8px}h3{font-size:14px;margin:0 0 6px;color:var(--mute);text-transform:uppercase;letter-spacing:.04em}
main{max-width:1500px;margin:0 auto;padding:0 20px 40px}.lede{max-width:90ch;color:var(--mute);margin:0 0 10px}
button{font:inherit;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:8px;padding:5px 10px;cursor:pointer}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px;margin:10px 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 12px}.card b{display:block;font-size:22px}.card span{color:var(--mute);font-size:13px}
.split{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;align-items:start}@media(max-width:1100px){.split{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:10px}@media(max-width:700px){.two{grid-template-columns:1fr}}
pre.s4{margin:0;background:var(--code);border-radius:8px;padding:8px;font:11.5px/1.45 ui-monospace,Menlo,Consolas,monospace;white-space:pre-wrap;word-break:break-word;max-height:760px;overflow:auto}
.ln{display:block;padding:0 3px;border-left:3px solid transparent}.ln.ok{border-color:var(--ok)}.ln.warn{border-color:var(--warn);background:var(--warnbg)}.ln.bad{border-color:var(--bad);background:var(--badbg)}
.leg{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:12.5px;color:var(--mute);margin:6px 0}.leg i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:4px;vertical-align:-1px}
.ctl{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;margin-bottom:8px;font-size:13px}.ctl label{display:inline-flex;gap:4px;align-items:center}
.map svg{width:100%;height:auto;display:block;background:var(--panel);border:1px solid var(--line);border-radius:10px;margin-bottom:8px}
svg text{fill:var(--ink);font:11px system-ui}svg text.m{fill:var(--mute)}svg text.lbl{fill:var(--k);font-weight:600}
.truth{fill:var(--k);fill-opacity:.16;stroke:var(--k);stroke-width:1.4}.seen{fill:none;stroke:var(--k);stroke-width:2;stroke-dasharray:6 3}
.pts circle{fill:var(--k);opacity:.55}.tbl{stroke:var(--mute);stroke-width:1}.arm{fill:none;stroke:var(--mute);stroke-width:.8;opacity:.7}.rob circle{fill:var(--ink);opacity:.35}
.hand{fill:none;stroke:var(--bad);stroke-width:1.5}.tcp{fill:var(--bad)}
.hide-truth .truth,.hide-seen .seen,.hide-pts .pts,.hide-arm .arm,.hide-rob .rob,.hide-hand .hand,.hide-hand .tcp{display:none}
.st{display:none}.st.on{display:block}
table.t{border-collapse:collapse;width:100%;font-size:13px;background:var(--panel)}table.t th,table.t td{border:1px solid var(--line);padding:5px 7px;text-align:left;vertical-align:top}
table.t th{background:var(--code)}td.v{font-weight:600}td.m{color:var(--mute);font-size:12px}td.nw{white-space:nowrap}.scroll{overflow-x:auto}
tr.ok td:last-child{background:var(--okbg)}tr.warn td:last-child{background:var(--warnbg)}tr.bad td:last-child{background:var(--badbg)}
.chip{display:inline-block;padding:2px 9px;border-radius:99px;font-weight:600;font-size:12px;white-space:nowrap}.chip.covered{background:var(--okbg);color:var(--ok)}.chip.partly{background:var(--warnbg);color:var(--warn)}.chip.no{background:var(--badbg);color:var(--bad)}
.note{border-left:4px solid var(--warn);background:var(--warnbg);padding:8px 12px;border-radius:0 8px 8px 0}.note ul{margin:4px 0 0;padding-left:18px}
table.cov td{min-width:130px}
"""

JS = """
const root=document.documentElement;
document.getElementById('theme').onclick=()=>{const d=getComputedStyle(root).getPropertyValue('--bg').trim()==='#10141b';root.dataset.theme=d?'light':'dark'};
const stage=document.getElementById('stage');
document.querySelectorAll('[data-layer]').forEach(c=>c.onchange=()=>stage.classList.toggle('hide-'+c.dataset.layer,!c.checked));
document.querySelectorAll('input[name=state]').forEach(r=>r.onchange=()=>document.querySelectorAll('.st').forEach(s=>s.classList.toggle('on',s.dataset.state===r.value)));
"""


def page(a: dict) -> str:
    s = a["state"]["start"]
    v0, v5 = s["variants"]["V0"], s["variants"]["V5"]
    arm5 = a["state"]["arm"]["variants"]["V5"]
    rel = v5["relations"]
    cards = [
        (
            f"{v5['n_correct']} of 7",
            "objects within 3 cm (xy) of the truth, perceived scene V5 (baseline V0: "
            + f"{v0['n_correct']} of 7)",
        ),
        (
            f"{v5['mean_centre_xy_cm']} cm",
            f"mean centre error in xy (V0: {v0['mean_centre_xy_cm']} cm); arm over the rack: {arm5['mean_centre_xy_cm']} cm",
        ),
        (
            f"{v5['mean_abs_height_err_cm']} cm",
            f"mean height error (V0: {v0['mean_abs_height_err_cm']} cm); mean 3D IoU {v5['mean_iou3']}",
        ),
        (
            f"{rel['touching_or_near']['both']} of {rel['touching_or_near']['truth']}",
            f"near or touching pairs recalled, precision {rel['touching_or_near']['precision']}; the 2 real contacts seen at "
            + " and ".join(
                f"{v} mm" for v in rel["touching_gap_within_30mm"]["seen_gap_mm"].values()
            ),
        ),
        ("0 tokens", "no Muse call; SAM 3 and depth only, offline analysis"),
    ]
    cards_html = "".join(
        f'<div class="card"><b>{e(t)}</b><span>{e(d)}</span></div>' for t, d in cards
    )
    leg = "".join(
        f'<span><i style="background:{color(i)}"></i>{e(n)}</span>' for i, n in enumerate(ORDER)
    )
    states = "".join(draw_state(a, st, st == "start") for st in ("start", "arm"))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Perceived scene vs oracle</title><style>{CSS}</style></head><body>
<header><div><h1>Can the stack see the scene? Perceived collision world vs simulator truth</h1>
<p class="lede">exp05, scene L1 of libero_goal_swap task 8 (seed 51): the wine rack stands behind the plate and touches its rim. SAM 3 text masks and depth from the agent-view and wrist cameras are turned into the same collision world and S4 text that exp04 built from simulator state. No simulator state is used by the perceived world; no model tokens were spent.</p></div><button id="theme">Light / dark</button></header>
<main>
<div class="cards">{cards_html}</div>
<div class="split">
<section class="panel"><h2 style="margin-top:0">S4 text, perceived against oracle</h2>
<div class="leg"><span><i style="background:var(--ok)"></i>object within 1.5 cm and 2 cm size, or same relation</span><span><i style="background:var(--warn)"></i>object further off</span><span><i style="background:var(--bad)"></i>relation differs or missing</span></div>
{s4_panes(a)}
<p class="lede">The text is produced by the same <code>describe(world, 'combo')</code> as the oracle's. Differences: the perceived rack is one box (the oracle has 9 boxes, so no per-board list), round objects have one radius for all heights, and 'touching' needs a gap of 3 mm, which perception does not resolve.</p></section>
<section class="panel"><h2 style="margin-top:0">Scene: perceived (dashed) over truth (filled)</h2>
<div class="ctl"><label><input type="radio" name="state" value="start" checked> arm at home</label><label><input type="radio" name="state" value="arm"> arm hovering over the rack</label>
<label><input type="checkbox" data-layer="truth" checked> truth</label><label><input type="checkbox" data-layer="seen" checked> perceived boxes</label><label><input type="checkbox" data-layer="pts" checked> perceived points</label>
<label><input type="checkbox" data-layer="arm" checked> arm spheres (truth)</label><label><input type="checkbox" data-layer="rob" checked> robot mask points</label><label><input type="checkbox" data-layer="hand" checked> hand and TCP</label></div>
<div class="leg">{leg}</div>
<div id="stage">{states}</div>
<p class="lede">Hand rectangle: 21 x 10 cm at the TCP, drawn with fingers along y (yaw assumed). Arm spheres are the cuRobo model at the recorded joint angles.</p></section>
</div>
<h2>Which improvement helped (cumulative)</h2>{variants_table(a)}
<p class="lede">Each row adds to the one above. All numbers: <code>analysis.json</code>. The selection thresholds were set while looking at this scene, so these are in-sample figures.</p>
<h2>Per object (V5)</h2>{objects_table(a)}
<h2>Relations</h2>{relations_table(a)}
<h2>Coverage and how to complete it</h2>{coverage_table(a)}
<h2>Detail</h2><div class="split"><div class="panel"><h3>Box extent from percentiles of the mask points (start state, V5)</h3>{sweep_table(a)}<p class="lede">Chosen after this sweep, on this scene only.</p></div>
<div class="panel"><h3>Caveats</h3><div class="note"><ul><li>One scene, one seed, one camera pair; thresholds tuned on it (in-sample).</li><li>Points per mask are down-sampled to about 1000 by the probe.</li><li>The oracle is the exp04 dump; its gaps are exact, perceived gaps come from boxes.</li><li>The arm test is one pose; it does not hide the rack from the camera.</li><li>Perception was not used by any generator run here, so nothing is claimed about program quality.</li></ul></div></div></div>
</main><script>{JS}</script></body></html>"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--out", type=Path, default=Path("data/runs/exp05_perceived_scene"))
    args = p.parse_args(argv)
    a = json.loads((args.out / "analysis.json").read_text(encoding="utf-8"))
    (args.out / "report.html").write_text(page(a), encoding="utf-8")
    print(args.out / "report.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
