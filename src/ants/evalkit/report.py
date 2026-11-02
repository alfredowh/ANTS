"""Local viewer for an experiment run directory: a trace UI in one self-contained HTML file.

    uv run python -m ants.evalkit.report data/runs/<name> [--serve] [--open]
    uv run python -m ants.evalkit.report data/runs [--open]        # all runs, pick one in the UI

An interactive dashboard: success rates with confidence intervals, a seed-by-sample heatmap,
failure causes, a sortable rollout table, a synced video + signal explorer per rollout (end-effector
pose, gripper, tracking error, tool-call spans with failure details), a side-by-side comparison, and
the per-sample trace (prompts, replies, program diffs, feedback).

Reads `config.json`, `events.jsonl`, per sample `record.json`, programs, replies, prompts, feedback
and diffs, and per rollout `episode/steps.jsonl`, `trace/events.jsonl`, `outcome.json` and the videos.
Videos and images are linked by relative path, so keep `report.html` in the folder you point at.
Older runs (without replies, diffs or events) still render.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import re
import webbrowser
from datetime import datetime
from pathlib import Path

from ants.adversary.rollout import feedback
from ants.evalkit.phases import STAGES, targets_from_run, task_phases
from ants.evalkit.runlog import unified_diff
from ants.evalkit.scene_view import JS as SCENE_JS
from ants.evalkit.system2_view import JS as SYSTEM2_JS


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def _resolve(run_dir: str | None, root: Path) -> Path | None:
    """A rollout directory as logged, or re-anchored under `root` if the run was moved."""
    if not run_dir:
        return None
    path = Path(run_dir)
    if path.is_dir():
        return path
    parts = path.parts
    if root.name in parts:
        moved = root.joinpath(*parts[len(parts) - parts[::-1].index(root.name) :])
        if moved.is_dir():
            return moved
    return None


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _arr(v):
    return v["$array_inline"] if isinstance(v, dict) and "$array_inline" in v else v


def _steps(run: Path) -> list[tuple]:
    """Per step: (sim time, eef position, gripper state, gripper command, joint error)."""
    path = run / "episode" / "steps.jsonl"
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            st = json.loads(line)
            state = st.get("robot_state") or {}
            arm = ((st.get("action") or {}).get("arms") or {}).get("primary") or {}
            pos = _arr(
                ((state.get("end_effector_poses") or {}).get("primary") or {}).get("position")
            )
            joints = _arr((state.get("joint_positions") or {}).get("primary"))
            target = _arr(arm.get("target"))
            err = None
            if (
                arm.get("mode") == "joint_position"
                and joints
                and target
                and len(joints) == len(target)
            ):
                err = sum((a - b) ** 2 for a, b in zip(joints, target, strict=True)) ** 0.5
            rows.append((st["simulator_time_s"], pos, (state.get("gripper_positions") or {}).get("primary"),
                         arm.get("gripper_position"), err))  # fmt: skip
    return rows


def _signals(rows: list[tuple], max_points: int = 500) -> dict | None:
    """The per-step rows thinned to at most `max_points`, as parallel lists."""
    if not rows:
        return None
    stride = max(1, -(-len(rows) // max_points))
    rows = rows[::stride]
    r4 = lambda v: None if v is None else round(v, 4)  # noqa: E731
    return {
        "t": [r4(r[0]) for r in rows],
        "x": [r4(r[1][0]) if r[1] else None for r in rows],
        "y": [r4(r[1][1]) if r[1] else None for r in rows],
        "z": [r4(r[1][2]) if r[1] else None for r in rows],
        "grip": [r4(r[2]) for r in rows],
        "grip_cmd": [r4(r[3]) for r in rows],
        "err": [r4(r[4]) for r in rows],
    }


def _spans(run: Path) -> list[dict]:
    """Top-level program calls with simulator-time windows and, for failures, the API error."""
    path = run / "trace" / "events.jsonl"
    if not path.exists():
        return []
    starts, spans = {}, []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("category") != "program" or e.get("parent_id") is not None:
            continue
        if e["event"] == "span_start":
            starts[e["span_id"]] = e
        elif e["event"] == "span_end" and e["span_id"] in starts:
            s0 = starts[e["span_id"]]
            span = {
                "name": e["name"],
                "t0": s0["simulator_time_s"],
                "t1": e["simulator_time_s"],
                "wall_s": round(e.get("duration_s", 0.0), 3),
                "ok": bool(e.get("ok", True)),
            }
            if not span["ok"]:
                n = int(re.sub(r"\D", "", e["span_id"]) or 0)
                for d in (run / "trace" / "calls").glob(f"call-{n:06d}-*"):
                    out = _json(d / "output.json") or {}
                    err = out.get("error") or {}
                    span["error"] = {
                        "code": err.get("code"),
                        "message": err.get("message"),
                        "details": err.get("details"),
                        "diagnostics": out.get("diagnostics"),
                    }
            spans.append(span)
    return spans


def _rollout(
    run_dir: Path | None, base: Path, success: bool, reason: str, error: str | None
) -> dict:
    """Everything the explorer needs about one simulator rollout."""
    if run_dir is None:
        return {"missing": True, "cause": "success" if success else reason}
    rel = lambda p: os.path.relpath(p, base).replace(os.sep, "/")  # noqa: E731
    videos = {p.stem: rel(p) for p in sorted((run_dir / "media" / "videos").glob("*.mp4"))}
    overlays = [rel(p) for p in sorted((run_dir / "media" / "overlays").glob("*.png"))[:6]]
    outcome = _json(run_dir / "outcome.json") or {}
    index = _json(run_dir / "media" / "video-index.json") or {}
    spans = _spans(run_dir)
    failed = next((s for s in spans if not s["ok"]), None)
    if success:
        cause = "success"
    elif failed:
        cause = f"{failed['name']}: {(failed.get('error') or {}).get('code') or 'failed'}"
    elif error or outcome.get("error"):
        cause = "program error"
    else:
        cause = "finished, task not done"
    rows = _steps(run_dir)
    phases = task_phases(
        [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows],
        targets_from_run(run_dir), success,
    )  # fmt: skip
    out = run_dir / "logs" / "program.stdout"
    err = run_dir / "logs" / "program.stderr"
    return {
        "cause": cause,
        "videos": videos,
        "fps": index.get("fps", 20.0),
        "overlays": overlays,
        "keyframes": _keyframes(str(run_dir), base, 8),
        "signals": _signals(rows),
        "phases": phases,
        "phase": phases["label"] if phases else None,
        "depth": phases["depth"] if phases else None,
        "spans": spans,
        "steps": outcome.get("steps_executed"),
        "sim_s": outcome.get("simulator_duration_s"),
        "reward": outcome.get("cumulative_reward"),
        "success_step": outcome.get("success_observed_step"),
        "description": outcome.get("termination_description"),
        "error": error or outcome.get("error"),
        "stdout": (_read(out) or "")[-4000:],
        "stderr": (_read(err) or "")[-2000:],
    }


def _keyframes(run_dir: str | None, root: Path, limit: int = 14) -> list[dict]:
    if not run_dir:
        return []
    base = Path(run_dir) / "media" / "keyframes"
    if not base.is_dir():
        return []
    frames = []
    for d in sorted(p for p in base.iterdir() if p.is_dir())[:limit]:
        img = d / "agentview.png"
        if img.exists():
            frames.append({"label": d.name, "src": os.path.relpath(img, root).replace(os.sep, "/")})
    return frames


def _reasoning_tokens(sample_dir: Path, k: int) -> dict | None:
    """Completion and reasoning token counts of one reply, from the logged API response."""
    raw = _read(sample_dir / f"api_response_attempt{k}.json")
    if raw is not None:
        usage = json.loads(raw).get("usage") or {}
        detail = usage.get("completion_tokens_details") or {}
        return {"reasoning": detail.get("reasoning_tokens", 0),
                "completion": usage.get("completion_tokens", 0)}  # fmt: skip
    return None


def _why(reply: str | None) -> str | None:
    """The 'WHY:' rationale a repair reply may carry before its code block."""
    if not reply or "WHY:" not in reply:
        return None
    return reply.split("```", 1)[0].strip() or None


def _attempt(sample_dir: Path, root: Path, a: dict, prev_text: str | None) -> dict:
    k = a["attempt"]
    program = _read(sample_dir / f"program_attempt{k}.py") or ""
    diff = _read(sample_dir / f"diff_attempt{k}.diff")
    if diff is None and prev_text is not None:
        diff = unified_diff(prev_text, program, f"attempt{k - 1}", f"attempt{k}")
    trace = a["trace"]
    fb = _read(sample_dir / f"feedback_attempt{k}.json")
    fb_obj = json.loads(fb) if fb else None
    run_dir = trace.get("run_dir")
    if fb_obj is None and not trace["task_success"] and run_dir and Path(run_dir).exists():
        try:
            fb_obj = feedback(Path(run_dir))
        except (OSError, ValueError):
            fb_obj = None
    messages = _read(sample_dir / f"messages_attempt{k}.json")
    prompt = None
    if messages:
        msgs = json.loads(messages)
        prompt = (
            msgs[-1]["content"]
            if k or len(msgs) > 2
            else "\n\n".join(m["content"] for m in msgs[1:])
        )
    return {
        "attempt": k,
        "role": a.get("role", "initial" if k == 0 else "repair"),
        "tokens": a["tokens"],
        "reasoning_tokens": _reasoning_tokens(sample_dir, k),
        "from_cache": a["from_cache"],
        "program": program,
        "diff": diff or "",
        "reply": _read(sample_dir / f"reply_attempt{k}.md"),
        "why": _why(_read(sample_dir / f"reply_attempt{k}.md")),
        "prompt": prompt,
        "feedback": fb_obj,
        "success": trace["task_success"],
        "program_ok": trace["program_ok"],
        "reason": trace["termination_reason"],
        "error": trace.get("error"),
        "wall_s": trace.get("wall_s"),
        "calls": [
            {"name": c["name"], "ok": c["ok"], "code": c.get("failure_code")}
            for c in trace.get("calls", [])
        ],
        "frames": _keyframes(run_dir, root),
    }


def is_run(path: Path) -> bool:
    return (path / "config.json").exists() or any(path.glob("*/sample*/record.json"))


def _system2(root: Path) -> list[dict]:
    """Cycles of the adversary loop, one JSON object per line of `<run>/system2.jsonl`."""
    text = _read(root / "system2.jsonl") or ""
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def collect(root: Path, base: Path | None = None) -> dict:
    """One run as plain data; image paths are relative to `base` (where report.html lives)."""
    root = root.resolve()
    base = (base or root).resolve()
    config = json.loads(_read(root / "config.json") or "{}")
    events = [
        json.loads(line)
        for line in (_read(root / "events.jsonl") or "").splitlines()
        if line.strip()
    ]
    samples, rollouts = [], []

    def add_rollout(sid: str, rid: str, meta: dict, run_dir: Path | None, ok: bool, reason: str,
                    error: str | None) -> None:  # fmt: skip
        rollouts.append({"id": rid, "sample": sid, **meta, "success": ok, "reason": reason,
                         **_rollout(run_dir, base, ok, reason, error)})  # fmt: skip

    for rec_path in sorted(root.glob("*/sample*/record.json")):
        sample_dir = rec_path.parent
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        sid = f"{rec['arm']}/sample{rec['sample']}"
        meta = {"arm": rec["arm"], "temperature": rec["temperature"], "n": rec["sample"]}
        for a in rec["attempts"]:
            a["trace"]["run_dir"] = str(_resolve(a["trace"].get("run_dir"), root) or "") or None
        for e in rec.get("evaluation", []):
            e["run_dir"] = str(_resolve(e.get("run_dir"), root) or "") or None
        attempts, prev = [], None
        for a in rec["attempts"]:
            item = _attempt(sample_dir, base, a, prev)
            item["rid"] = f"{sid}|debug{a['attempt']}"
            tr = a["trace"]
            add_rollout(
                sid, item["rid"],
                {**meta, "kind": "debug", "scene": config.get("debug_scene", "stock"),
                 "seed": int(re.sub(r"\D", "", tr["case_id"].split("-")[-1]) or 0),
                 "attempt": a["attempt"]},
                Path(tr["run_dir"]) if tr.get("run_dir") else None,
                tr["task_success"], tr["termination_reason"], tr.get("error"),
            )  # fmt: skip
            attempts.append(item)
            prev = item["program"]
        evals = []
        for i, e in enumerate(rec.get("evaluation", [])):
            seed = int(re.sub(r"\D", "", e["case_id"].split("-")[-1]) or 0)
            rid = f"{sid}|eval{i}"
            add_rollout(
                sid, rid,
                {**meta, "kind": "eval", "scene": e.get("scene", "stock"), "seed": seed,
                 "attempt": len(rec["attempts"]) - 1},
                Path(e["run_dir"]) if e.get("run_dir") else None,
                e["task_success"], e["termination_reason"], e.get("error"),
            )  # fmt: skip
            evals.append(
                {
                    "rid": rid,
                    "scene": e.get("scene", "stock"),
                    "seed": seed,
                    "success": e["task_success"],
                    "reason": e["termination_reason"],
                    "wall_s": e.get("wall_s"),
                    "frames": _keyframes(e.get("run_dir"), base, 3),
                }
            )
        new_tokens = sum(a["tokens"] for a in rec["attempts"] if not a["from_cache"])
        exp = rec.get("exp")
        if exp:
            exp = {**exp, "overlay": _json(sample_dir / "overlay.json")}
        samples.append(
            {
                "id": sid,
                "arm": rec["arm"],
                "sample": rec["sample"],
                "temperature": rec["temperature"],
                "attempts": attempts,
                "evaluation": evals,
                "stopped": rec.get("stopped"),
                "exp": exp,
                "tokens_all": sum(a["tokens"] for a in rec["attempts"]),
                "tokens_new": new_tokens,
            }
        )
    return {
        "name": root.name,
        "date": str(
            config.get("started") or datetime.fromtimestamp(root.stat().st_mtime).isoformat()
        )[:16].replace("T", " "),
        "config": config,
        "events": events,
        "samples": samples,
        "rollouts": rollouts,
        "system2": _system2(root),
        "a0": _json(root / "a0.json"),
        "a3": _json(root / "a3.json"),
        "scenes": {p.stem: _json(p) for p in sorted((root / "scenes").glob("*.json"))},
        "stages": STAGES,
        "usd_per_mtok": float(config.get("usd_per_mtok", 13.5)),
    }


def build(root: Path) -> Path:
    """Write report.html: for a run directory, that run; for a folder of runs, all of them."""
    root = root.resolve()
    runs = (
        [root]
        if is_run(root)
        else sorted(
            (d for d in root.iterdir() if d.is_dir() and is_run(d)),
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
    )
    if not runs:
        raise SystemExit(f"no runs found in {root}")
    payload = {"runs": [collect(r, root) for r in runs]}
    data = json.dumps(payload).replace("</", "<\\/")
    out = root / "report.html"
    out.write_text(
        TEMPLATE.replace("__SYSTEM2_JS__", SYSTEM2_JS)
        .replace("__SCENE_JS__", SCENE_JS)
        .replace("__DATA__", data),
        encoding="utf-8",
    )
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    p.add_argument("--serve", action="store_true", help="serve the run directory over http")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--open", action="store_true", help="open the report in a browser")
    args = p.parse_args(argv)
    out = build(args.run)
    print(f"wrote {out}")
    if args.serve:
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(args.run))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
        url = f"http://127.0.0.1:{args.port}/report.html"
        print(f"serving {url} (Ctrl+C to stop)")
        if args.open:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    elif args.open:
        webbrowser.open(out.as_uri())
    return 0


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ANTS run viewer</title>
<style>
:root{--bg:#f6f7f9;--panel:#fff;--ink:#1d2330;--mute:#677086;--line:#e1e4ea;--ok:#1a7f4b;--okbg:#e3f5ea;--bad:#b4281f;--badbg:#fbe7e5;--acc:#2f5fd0;--accbg:#e8eefc;--code:#f1f3f7;--add:#e3f5ea;--del:#fbe7e5;--s1:#2f5fd0;--s2:#d9822b;--s3:#1f9d8a;--s4:#8a5cd0}
@media(prefers-color-scheme:dark){:root{--bg:#12151c;--panel:#1a1f29;--ink:#e6e9f0;--mute:#98a1b5;--line:#2b3240;--ok:#5fd394;--okbg:#17321f;--bad:#ff8a80;--badbg:#3a1c1a;--acc:#8aa9ff;--accbg:#1f2a47;--code:#10131a;--add:#16301f;--del:#3a1c1a;--s1:#8aa9ff;--s2:#f0a35e;--s3:#4fd1bd;--s4:#b693f0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
header{display:flex;gap:16px;align-items:center;padding:10px 16px;background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
header h1{font-size:15px;margin:0}header .sp{flex:1}
.layout{display:grid;grid-template-columns:240px minmax(0,1fr);min-height:calc(100vh - 49px)}
nav{border-right:1px solid var(--line);background:var(--panel);padding:8px;overflow:auto}
nav button{display:block;width:100%;text-align:left;border:0;background:none;color:var(--ink);padding:8px 10px;border-radius:8px;cursor:pointer;font:inherit}
nav button:hover{background:var(--bg)}nav button.on{background:var(--accbg);color:var(--acc)}
nav .sub{font-size:12px;color:var(--mute)}nav h4{margin:12px 10px 4px;font-size:11px;text-transform:uppercase;color:var(--mute);letter-spacing:.06em}
select,input[type=search]{font:inherit;color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:4px 8px;max-width:340px}
main{padding:16px 20px;max-width:1320px;min-width:0}
.chip{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;background:var(--code);color:var(--mute);margin-right:4px;border:0;font-family:inherit}
button.chip{cursor:pointer}.chip.ok{background:var(--okbg);color:var(--ok)}.chip.bad{background:var(--badbg);color:var(--bad)}.chip.acc{background:var(--accbg);color:var(--acc)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;margin:0 0 12px}
.card>summary,.card>.hd{padding:10px 14px;cursor:pointer;display:flex;gap:8px;align-items:center;font-weight:600;list-style:none}
.card>.hd{cursor:default}.card>summary::-webkit-details-marker{display:none}.card>summary:before{content:"▸";color:var(--mute)}.card[open]>summary:before{content:"▾"}
.card .bd{padding:0 14px 12px}.card.pad{padding:12px 14px}
.rail{border-left:3px solid var(--line);margin-left:6px;padding-left:14px}
.rail.ok{border-color:var(--ok)}.rail.bad{border-color:var(--bad)}.rail.acc{border-color:var(--acc)}
pre{margin:6px 0;padding:10px;background:var(--code);border-radius:8px;overflow:auto;font:12px/1.4 ui-monospace,Menlo,Consolas,monospace;max-height:460px}
.ln{display:block;white-space:pre}.ln i{color:var(--mute);font-style:normal;display:inline-block;width:3em;text-align:right;margin-right:10px;user-select:none}
.add{background:var(--add)}.del{background:var(--del)}.hunk{color:var(--acc)}
table{border-collapse:collapse;width:100%}th,td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{color:var(--mute);font-weight:600;font-size:12px;white-space:nowrap}
th.s{cursor:pointer;user-select:none}th.s:hover{color:var(--ink)}tr.row{cursor:pointer}tr.row:hover td{background:var(--bg)}
.calls span{display:inline-block;margin:2px;padding:1px 7px;border-radius:6px;font-size:12px;background:var(--okbg);color:var(--ok)}.calls span.f{background:var(--badbg);color:var(--bad)}
.frames{display:flex;gap:8px;overflow:auto;padding:4px 0}.frames figure{margin:0;flex:none;width:200px}.frames img{width:200px;border-radius:8px;border:1px solid var(--line);cursor:zoom-in}.frames figcaption{font-size:11px;color:var(--mute)}
.muted{color:var(--mute)}.mono{font:12px ui-monospace,Menlo,Consolas,monospace}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:12px}.stat{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 14px}.stat b{display:block;font-size:22px}
.pd{width:100%;table-layout:fixed;font:12px/1.4 ui-monospace,Menlo,Consolas,monospace;border-collapse:collapse}.pd td{padding:0 6px;border:0;white-space:pre-wrap;word-break:break-all;vertical-align:top}.pd td.n{width:34px;color:var(--mute);text-align:right;user-select:none}.pd td.del{background:color-mix(in srgb,var(--bad) 22%,transparent)}.pd td.add{background:color-mix(in srgb,var(--ok) 22%,transparent)}.pd td.gap{color:var(--mute);text-align:center;background:var(--code)}.pd td.emp{background:var(--code)}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:12px;margin-bottom:12px}.two>.card{margin:0}
.bar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:0 0 12px}
h3.t{margin:0 0 6px;font-size:13px;color:var(--mute);font-weight:600}
.viz svg{width:100%;height:auto;display:block}.viz svg text{fill:var(--mute);font-size:11px;font-family:inherit}.viz .cl{cursor:pointer}.viz .cl:hover{opacity:.75}
.vids{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:12px}.vids figure{margin:0}.vids video{width:100%;border-radius:10px;background:#000;display:block}.vids figcaption{font-size:12px;color:var(--mute);margin-top:2px}
.ctl{display:flex;gap:10px;align-items:center;margin:10px 0}.ctl input[type=range]{flex:1}.ctl button{font:inherit;color:var(--ink);background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:3px 10px;cursor:pointer}
.why{border-left:4px solid var(--bad);background:var(--badbg);padding:10px 14px;border-radius:8px;margin:0 0 12px}.why.ok{border-color:var(--ok);background:var(--okbg)}
#lb{position:fixed;inset:0;background:#000c;display:none;align-items:center;justify-content:center;z-index:9}#lb img{max-width:92vw;max-height:92vh}
@media(max-width:800px){.layout{grid-template-columns:1fr}nav{border-right:0;border-bottom:1px solid var(--line)}.two{grid-template-columns:1fr}}
</style></head><body>
<header><h1>ANTS run viewer</h1><span id="rn" class="muted"></span><span class="sp"></span><span id="hd"></span></header>
<div class="layout"><nav id="nav"></nav><main id="main"></main></div>
<div id="lb" onclick="this.style.display='none'"><img id="lbi"></div>
<script>
__SYSTEM2_JS__
__SCENE_JS__
const ALL=__DATA__;let D=ALL.runs[0],cur="dash";
const $=s=>document.querySelector(s);
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const usd=t=>"$"+(t/1e6*D.usd_per_mtok).toFixed(2);
const chip=(t,c="")=>`<span class="chip ${c}">${esc(t)}</span>`;
const okc=b=>b?"ok":"bad";
const PAL=["var(--s1)","var(--s2)","var(--s3)","var(--s4)"];
const fmt=(v,d=1)=>v==null?"–":(+v).toFixed(d);
const med=a=>{a=a.filter(x=>x!=null).sort((x,y)=>x-y);return a.length?(a.length%2?a[(a.length-1)/2]:(a[a.length/2-1]+a[a.length/2])/2):null};
const wilson=(k,n)=>{if(!n)return[0,0,0];const z=1.96,p=k/n,d=1+z*z/n,c=(p+z*z/(2*n))/d,h=z*Math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d;return[p,Math.max(0,c-h),Math.min(1,c+h)]};
function code(t){return `<pre>${String(t).split("\n").map((l,i)=>`<span class="ln"><i>${i+1}</i>${esc(l)}</span>`).join("")}</pre>`}
function diff(t){if(!t)return `<div class="muted">no changes (identical program)</div>`;
 return `<pre>${t.split("\n").map(l=>`<span class="ln ${l.startsWith("+")&&!l.startsWith("+++")?"add":l.startsWith("-")&&!l.startsWith("---")?"del":l.startsWith("@@")?"hunk":""}">${esc(l)}</span>`).join("")}</pre>`}
function det(title,body,open=false,cls=""){return `<details class="card" ${open?"open":""}><summary>${title}</summary><div class="bd ${cls}">${body}</div></details>`}
function frames(f){return f&&f.length?`<div class="frames">${f.map(x=>`<figure><img loading="lazy" src="${esc(x.src)}" onclick="zoom(this.src)"><figcaption>${esc(x.label)}</figcaption></figure>`).join("")}</div>`:""}
function zoom(s){$("#lbi").src=s;$("#lb").style.display="flex"}
const solved=s=>s.attempts.some(a=>a.success);
const evalSum=s=>{const m={};s.evaluation.forEach(e=>{(m[e.scene]??={n:0,ok:0});m[e.scene].n++;m[e.scene].ok+=e.success?1:0});return m};

/* ---------- rollout helpers, filters ---------- */
const RO=()=>D.rollouts,byId=id=>D.rollouts.find(r=>r.id===id),smp=id=>D.samples.find(s=>s.id===id);
const arms=()=>[...new Set(RO().map(r=>r.arm))];
const armCol=a=>PAL[Math.max(0,arms().indexOf(a))%PAL.length];
const grp=r=>r.kind==="debug"?"debug ("+r.scene+")":r.scene;
const groups=()=>[...new Set(RO().map(grp))];
const label=r=>`${r.sample} · ${r.kind==="debug"?"debug a"+r.attempt:"eval "+grp(r)+" "+r.seed}`;
let F={arm:"",scene:"",outcome:"",cause:"",q:""},S={key:0,dir:1},CM="tool",HM="result";
const causeOf=r=>CM==="phase"?(r.phase||r.cause):r.cause;
const filt=()=>RO().filter(r=>(!F.arm||r.arm===F.arm)&&(!F.scene||grp(r)===F.scene)&&(!F.outcome||(F.outcome==="success")===r.success)&&(!F.cause||causeOf(r)===F.cause)&&(!F.q||(r.id+" "+r.cause+" "+(r.phase||"")+" "+grp(r)+" "+r.seed).toLowerCase().includes(F.q)));
function setCM(v){CM=v;F.cause="";show(cur,true)}
function setHM(v){HM=v;show(cur,true)}
function setF(k,v){F[k]=v;if(k==="q")renderRes();else show(cur,true)}
function filterBar(){
 const opt=(k,vals,all)=>`<select onchange="setF('${k}',this.value)"><option value="">${all}</option>${vals.map(v=>`<option ${F[k]===v?"selected":""}>${esc(v)}</option>`).join("")}</select>`;
 return `<div class="bar">${opt("arm",arms(),"all arms")}${opt("scene",groups(),"all scenes")}<select onchange="setF('outcome',this.value)"><option value="">success + failure</option><option value="success" ${F.outcome==="success"?"selected":""}>success only</option><option value="failure" ${F.outcome==="failure"?"selected":""}>failure only</option></select>${F.cause?`<button class="chip acc" onclick="setF('cause','')">cause: ${esc(F.cause)} ✕</button>`:""}<input type="search" placeholder="search rollouts" value="${esc(F.q)}" oninput="setF('q',this.value.toLowerCase())"><span id="cnt" class="muted"></span></div>`}

/* ---------- charts (inline SVG) ---------- */
function barChart(rs){
 const gs=groups().filter(g=>rs.some(r=>grp(r)===g)),as=arms().filter(a=>rs.some(r=>r.arm===a));
 if(!gs.length)return `<div class="muted">no rollouts match</div>`;
 const W=560,H=230,L=34,B=44,T=14,gw=(W-L-8)/gs.length,bw=Math.min(46,(gw-14)/as.length);
 let o=[0,.25,.5,.75,1].map(v=>{const y=T+(H-T-B)*(1-v);return `<line x1="${L}" x2="${W}" y1="${y}" y2="${y}" stroke="var(--line)"/><text x="${L-5}" y="${y+4}" text-anchor="end">${v*100}%</text>`}).join("");
 gs.forEach((g,gi)=>{const x0=L+gi*gw+(gw-bw*as.length)/2;
  o+=`<text x="${L+gi*gw+gw/2}" y="${H-B+16}" text-anchor="middle">${esc(g)}</text>`;
  as.forEach((a,ai)=>{const x=rs.filter(r=>r.arm===a&&grp(r)===g),k=x.filter(r=>r.success).length,[p,lo,hi]=wilson(k,x.length);if(!x.length)return;
   const px=x0+ai*bw,yv=v=>T+(H-T-B)*(1-v),cx=px+bw/2;
   o+=`<g><title>${esc(a)} · ${esc(g)}: ${k}/${x.length} = ${(p*100).toFixed(0)}% (95% Wilson CI ${(lo*100).toFixed(0)}–${(hi*100).toFixed(0)}%)</title><rect x="${px+2}" y="${yv(p)}" width="${bw-4}" height="${Math.max(1,H-B-yv(p))}" rx="3" fill="${armCol(a)}" opacity=".85"/><line x1="${cx}" x2="${cx}" y1="${yv(lo)}" y2="${yv(hi)}" stroke="var(--ink)" stroke-width="1.5"/><line x1="${cx-4}" x2="${cx+4}" y1="${yv(hi)}" y2="${yv(hi)}" stroke="var(--ink)"/><line x1="${cx-4}" x2="${cx+4}" y1="${yv(lo)}" y2="${yv(lo)}" stroke="var(--ink)"/><text x="${cx}" y="${H-B+30}" text-anchor="middle">${k}/${x.length}</text></g>`})});
 const lg=as.map((a,i)=>`<span class="chip" style="color:${armCol(a)}">■ ${esc(a)}</span>`).join("");
 return `<svg viewBox="0 0 ${W} ${H}">${o}</svg><div>${lg}<span class="muted">bars = success rate, whiskers = 95% Wilson interval</span></div>`}
const gtitle=g=>g.startsWith("debug")?`Debug · ${g.slice(7,-1)} assets · the seed the generator repairs on`:GTITLE[g]||g;
const GTITLE={"stock":"Evaluation · stock assets","scaled":"Evaluation · scaled assets (real-size bowl and plate)"};
function heatmaps(rs){
 if(!rs.length)return `<div class="muted">no rollouts match</div>`;
 const order=g=>g.startsWith("debug")?0:g==="stock"?1:g==="scaled"?2:3,gs=[...new Set(rs.map(grp))].sort((a,b)=>order(a)-order(b)||a.localeCompare(b));
 const col=r=>r.kind==="debug"?"a"+r.attempt:String(r.seed);
 const one=g=>{const x=rs.filter(r=>grp(r)===g),cols=[...new Set(x.map(col))],rows=[...new Set(x.map(r=>r.sample))],cw=30,rh=26,L=104,T=24,W=L+cols.length*cw+6,H=T+rows.length*rh+4,k=x.filter(r=>r.success).length;
  let o=cols.map((c,i)=>`<text x="${L+i*cw+cw/2}" y="${T-8}" text-anchor="middle">${esc(c)}</text>`).join("");
  rows.forEach((s,ri)=>{o+=`<text x="${L-6}" y="${T+ri*rh+17}" text-anchor="end">${esc(s)}</text>`;
   cols.forEach((c,ci)=>{const r=x.find(r=>r.sample===s&&col(r)===c);if(!r)return;
    const ph=HM==="phase"&&!r.success&&r.depth!=null,fill=r.success?"var(--ok)":ph?"var(--s2)":"var(--bad)",op=r.success?.85:ph?.18+.13*r.depth:.9;
    o+=`<g class="cl" onclick="show('r:${r.id}')"><rect x="${L+ci*cw+1}" y="${T+ri*rh+1}" width="${cw-2}" height="${rh-2}" rx="4" fill="${fill}" opacity="${op}"/>${HM==="phase"&&r.depth!=null?`<text x="${L+ci*cw+cw/2}" y="${T+ri*rh+17}" text-anchor="middle" style="fill:var(--ink);font-weight:600">${r.success?"✓":r.depth}</text>`:""}<title>${esc(label(r))}\n${r.success?"success":"failed: "+esc(r.cause)}${r.phase&&!r.success?"\nstopped at: "+esc(r.phase):""}</title></g>`})});
  return `<div style="margin:0 24px 8px 0"><div style="font-weight:600;color:var(--ink)">${esc(gtitle(g))} <span class="muted" style="font-weight:400">· ${k}/${x.length} success</span></div><svg viewBox="0 0 ${W} ${H}" style="width:${W}px;max-width:100%">${o}</svg></div>`};
 const legend=HM==="phase"?`failed cells show the furthest stage reached (0 = never closed the gripper … 6 = released over the plate, task not done); darker orange = further. ✓ = success.`:"green = success, red = failure.";
 return `<div style="display:flex;flex-wrap:wrap">${gs.map(one).join("")}</div><div class="muted">${legend} Click a cell to open the rollout.</div>`}
function causeChart(rs){
 const fails=rs.filter(r=>!r.success),m={};fails.forEach(r=>{const c=causeOf(r);(m[c]??={n:0,by:{}});m[c].n++;m[c].by[r.arm]=(m[c].by[r.arm]||0)+1});
 const ents=Object.entries(m).sort((a,b)=>b[1].n-a[1].n);window._causes=ents.map(e=>e[0]);
 if(!ents.length)return `<div class="muted">no failures in this selection</div>`;
 const W=560,rh=26,L=210,mx=ents[0][1].n,H=ents.length*rh+6;
 const o=ents.map(([c,v],i)=>{let x=L;const y=i*rh+3;return `<g class="cl" onclick="setF('cause',window._causes[${i}])"><text x="${L-6}" y="${y+16}" text-anchor="end" style="${F.cause===c?"fill:var(--ink);font-weight:700":""}">${esc(c.length>32?c.slice(0,31)+"…":c)}</text>${Object.entries(v.by).map(([a,n])=>{const w=(W-L-30)*n/mx,r=`<rect x="${x}" y="${y}" width="${w}" height="${rh-8}" rx="3" fill="${armCol(a)}" opacity=".85"><title>${esc(c)} · ${esc(a)}: ${n}</title></rect>`;x+=w;return r}).join("")}<text x="${x+5}" y="${y+16}">${v.n}</text></g>`}).join("");
 return `<svg viewBox="0 0 ${W} ${H}">${o}</svg><div class="muted">failed rollouts by ${CM==="phase"?"the task phase they stopped at":"first failing tool call (or end state)"} · click a bar to filter</div>`}
function scatter(rs){
 const pts=D.samples.map(s=>{const e=rs.filter(r=>r.sample===s.id&&r.kind==="eval");return e.length?{s,n:e.length,p:e.filter(r=>r.success).length/e.length,x:s.tokens_new}:null}).filter(Boolean);
 if(!pts.length)return `<div class="muted">no evaluated samples match</div>`;
 const W=560,H=230,L=40,B=34,T=10,mx=Math.max(...pts.map(p=>p.x),1)*1.08,X=v=>L+(W-L-12)*v/mx,Y=v=>T+(H-T-B)*(1-v);
 let o=[0,.5,1].map(v=>`<line x1="${L}" x2="${W}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)"/><text x="${L-5}" y="${Y(v)+4}" text-anchor="end">${v*100}%</text>`).join("");
 for(let i=0;i<=4;i++){const v=mx*i/4;o+=`<text x="${X(v)}" y="${H-B+16}" text-anchor="middle">${v>=1000?Math.round(v/1000)+"k":Math.round(v)}</text>`}
 o+=`<text x="${(L+W)/2}" y="${H-4}" text-anchor="middle">new tokens spent on the sample</text>`;
 o+=pts.map(p=>`<circle class="cl" cx="${X(p.x)}" cy="${Y(p.p)}" r="7" fill="${armCol(p.s.arm)}" opacity=".85" onclick="show('${p.s.id}')"><title>${esc(p.s.id)}: ${Math.round(p.p*p.n)}/${p.n} eval rollouts, ${p.x.toLocaleString()} tokens (${usd(p.x)})</title></circle>`).join("");
 return `<svg viewBox="0 0 ${W} ${H}">${o}</svg><div class="muted">one dot per sample · click to open its trace</div>`}
function summaryTable(rs){
 const rows=[];arms().forEach(a=>[true,false].forEach(ok=>{const x=rs.filter(r=>r.arm===a&&r.success===ok);if(x.length)rows.push(`<tr><td>${esc(a)}</td><td>${chip(ok?"success":"failed",okc(ok))}</td><td>${x.length}</td><td>${fmt(med(x.map(r=>r.steps)),0)}</td><td>${fmt(med(x.map(r=>r.sim_s)))}</td><td>${fmt(med(x.map(r=>(r.spans||[]).reduce((s,c)=>s+c.wall_s,0))))}</td><td>${fmt(med(x.map(r=>(r.spans||[]).length)),0)}</td></tr>`)}));
 return `<table><tr><th>Arm</th><th>Outcome</th><th>n</th><th>median steps</th><th>median sim s</th><th>median program s</th><th>median tool calls</th></tr>${rows.join("")}</table>`}

/* ---------- dashboard ---------- */
const cmToggle=()=>["tool","phase"].map(m=>`<button class="chip ${CM===m?"acc":""}" onclick="setCM('${m}')">${m==="tool"?"by tool call":"by task phase"}</button>`).join("");
function funnel(rs){
 const st=D.stages||[],rr=rs.filter(r=>r.depth!=null);
 if(!rr.length)return `<div class="muted">no phase data (rollouts without a step log)</div>`;
 const as=arms().filter(a=>rr.some(r=>r.arm===a)),W=560,rh=26,L=150,H=st.length*rh+6,mx=rr.length;
 const o=st.map((nm,i)=>{let x=L;const y=i*rh+3,n=rr.filter(r=>r.depth>=i+1).length;
  return `<g><text x="${L-6}" y="${y+16}" text-anchor="end">${i+1}. ${esc(nm)}</text>${as.map(a=>{const k=rr.filter(r=>r.arm===a&&r.depth>=i+1).length,w=(W-L-80)*k/mx,r=`<rect x="${x}" y="${y}" width="${w}" height="${rh-8}" rx="3" fill="${armCol(a)}" opacity=".85"><title>${esc(a)} · reached "${esc(nm)}": ${k} of ${rr.filter(r=>r.arm===a).length}</title></rect>`;x+=w;return r}).join("")}<text x="${x+5}" y="${y+16}">${n} (${Math.round(100*n/mx)}%)</text></g>`}).join("");
 return `<svg viewBox="0 0 ${W} ${H}" style="max-width:720px">${o}</svg><div class="muted">rollouts that reached each stage of put-the-bowl-on-the-plate. Proxies from the gripper width, the end-effector track and the perception estimate of bowl and plate (no ground-truth object poses are logged).</div>`}
function dashRes(){const rs=filt(),ev=rs.filter(r=>r.kind==="eval"),k=rs.filter(r=>r.success).length,[p,lo,hi]=wilson(k,rs.length);
 const ke=ev.filter(r=>r.success).length,[pe,loe,hie]=wilson(ke,ev.length);
 const tok=D.samples.reduce((a,s)=>a+s.tokens_new,0),nc=new Set(rs.filter(r=>!r.success).map(r=>r.cause)).size;
 return `<div class="grid"><div class="stat"><span class="muted">rollouts</span><b>${rs.length}</b><span class="muted">${k} success · ${rs.length-k} failed</span></div>
 <div class="stat"><span class="muted">success rate</span><b>${rs.length?(p*100).toFixed(0)+"%":"–"}</b><span class="muted">95% CI ${(lo*100).toFixed(0)}–${(hi*100).toFixed(0)}%</span></div>
 <div class="stat"><span class="muted">evaluation only</span><b>${ev.length?(pe*100).toFixed(0)+"%":"–"}</b><span class="muted">${ke}/${ev.length} · CI ${(loe*100).toFixed(0)}–${(hie*100).toFixed(0)}%</span></div>
 <div class="stat"><span class="muted">distinct failure causes</span><b>${nc}</b><span class="muted">click a bar below to drill in</span></div>
 <div class="stat"><span class="muted">new tokens</span><b>${tok.toLocaleString()}</b><span class="muted">≈ ${usd(tok)}</span></div></div>
 <div class="two viz"><div class="card pad"><h3 class="t">Success rate by scene and arm</h3>${barChart(rs)}</div><div class="card pad"><h3 class="t">Why rollouts fail ${cmToggle()}</h3>${causeChart(rs)}</div></div>
 <div class="card pad viz"><h3 class="t">How far rollouts got</h3>${funnel(rs)}</div>
 <div class="card pad viz" style="margin-top:12px"><h3 class="t">Every rollout: sample × seed ${["result","phase"].map(m=>`<button class="chip ${HM===m?"acc":""}" onclick="setHM('${m}')">colour by ${m}</button>`).join("")}</h3>${heatmaps(rs)}</div>
 <div class="two viz" style="margin-top:12px"><div class="card pad"><h3 class="t">Token spend vs evaluation success</h3>${scatter(rs)}</div><div class="card pad"><h3 class="t">What a success looks like vs a failure</h3>${summaryTable(rs)}<p class="muted">Medians over the selected rollouts. A large gap in steps or program time between outcomes points to a stuck or aborted motion.</p></div></div>`}
function dash(){return `${filterBar()}<div id="res">${dashRes()}</div>
 <p class="muted">Run config: ${Object.entries(D.config).filter(([k])=>!["scenes"].includes(k)).map(([k,v])=>esc(k)+"="+esc(v)).join(" · ")}</p>`}

/* ---------- rollout table ---------- */
const COLS=[["Rollout",r=>r.id],["Arm",r=>r.arm],["T",r=>r.temperature],["Scene",r=>grp(r)],["Seed",r=>r.seed],["Result",r=>r.success?1:0],["Cause",r=>r.cause],["Phase reached",r=>r.depth],["Bowl cm",r=>r.phases?.bowl_cm],["Lift cm",r=>r.phases?.lift_cm],["Plate cm",r=>r.phases?.plate_cm],["Steps",r=>r.steps],["Sim s",r=>r.sim_s],["Program s",r=>(r.spans||[]).reduce((s,c)=>s+c.wall_s,0)],["Calls ok",r=>(r.spans||[]).filter(c=>c.ok).length/Math.max(1,(r.spans||[]).length)],["Video",r=>Object.keys(r.videos||{}).length]];
const sorted=rs=>{const g=COLS[S.key][1];return [...rs].sort((a,b)=>{const x=g(a),y=g(b);return (x==null)-(y==null)||(x<y?-1:x>y?1:0)*S.dir})};
function sortBy(i){S.dir=S.key===i?-S.dir:1;S.key=i;renderRes()}
function rowsRes(){const rs=sorted(filt());
 return `<div class="card"><table><tr>${COLS.map((c,i)=>`<th class="s" onclick="sortBy(${i})">${c[0]}${S.key===i?(S.dir>0?" ▲":" ▼"):""}</th>`).join("")}</tr>${rs.map(r=>`<tr class="row" onclick="show('r:${r.id}')"><td>${esc(label(r))}</td><td>${esc(r.arm)}</td><td>${r.temperature}</td><td>${esc(grp(r))}</td><td>${r.seed}</td><td>${chip(r.success?"success":"failed",okc(r.success))}</td><td>${esc(r.cause)}</td><td>${r.success?"✓ success":r.phase?r.depth+" · "+esc(r.phase):"–"}</td><td>${fmt(r.phases?.bowl_cm)}</td><td>${fmt(r.phases?.lift_cm)}</td><td>${fmt(r.phases?.plate_cm)}</td><td>${r.steps??"–"}</td><td>${fmt(r.sim_s)}</td><td>${fmt((r.spans||[]).reduce((s,c)=>s+c.wall_s,0))}</td><td>${(r.spans||[]).filter(c=>c.ok).length}/${(r.spans||[]).length}</td><td>${Object.keys(r.videos||{}).length?"▶":""}</td></tr>`).join("")||"<tr><td colspan=16 class=muted>no rollouts match</td></tr>"}</table></div>`}
function rollouts(){return `<h2 style="margin:0 0 10px">Rollouts</h2>${filterBar()}<div id="res">${rowsRes()}</div><p class="muted">Click a header to sort and a row to open the video and signal explorer. The filters are shared with the dashboard.</p>`}
function updCnt(){const c=$("#cnt");if(c)c.textContent=`${filt().length} of ${RO().length} rollouts`}
function renderRes(){const e=$("#res");if(e)e.innerHTML=cur==="dash"?dashRes():rowsRes();updCnt()}

/* ---------- synced player + signal plot ---------- */
const P={vids:[],master:null,raf:0,rs:[],view:null};
function stopPlayer(){cancelAnimationFrame(P.raf);P.vids.forEach(v=>v.pause());P.vids=[];P.master=null}
const dur=r=>r.steps!=null?(r.steps+1)/(r.fps||20):(r.signals?r.signals.t.at(-1):1);
function videoTag(r,cam,cap){const src=r.videos?.[cam];return src?`<figure><video data-sync data-dur="${dur(r)}" src="${esc(src)}" muted playsinline preload="auto"></video><figcaption>${esc(cap)}</figcaption></figure>`:`<figure><div class="card pad muted">no ${esc(cam)} video recorded</div></figure>`}
function controls(rs){const d=Math.max(...rs.map(dur));return `<div class="ctl"><button id="pp" onclick="toggle()" title="space">▶</button><button onclick="stepF(-1)" title="←">⏮</button><button onclick="stepF(1)" title="→">⏭</button><input id="sc" type="range" min="0" max="${d}" step="0.01" value="0" oninput="seek(+this.value)"><span id="tl" class="mono">0.00 / ${d.toFixed(2)} s</span><select onchange="setRate(+this.value)" title="speed">${[.25,.5,1,2].map(x=>`<option ${x===1?"selected":""} value="${x}">${x}×</option>`).join("")}</select></div>`}
function mount(rs,mode){stopPlayer();P.vids=[...document.querySelectorAll("video[data-sync]")];P.rs=rs;P.view=mode;
 P.master=P.vids.reduce((a,b)=>(+b.dataset.dur>+(a?.dataset.dur||0)?b:a),null);
 if(P.master)P.master.addEventListener("ended",()=>{$("#pp").textContent="▶"});
 P.vids.forEach(v=>v.addEventListener("seeked",()=>{if(v===P.master)cursor(v.currentTime)}));
 const svg=$("#plot");if(svg){const W=1000,T=+svg.dataset.t,L=+svg.dataset.l,R=+svg.dataset.r;svg._m={T,L,R,X:t=>L+(W-L-R)*t/T};const tOf=e=>{const b=svg.getBoundingClientRect(),m=svg._m;return Math.max(0,Math.min(m.T,((e.clientX-b.left)/b.width*W-m.L)/(W-m.L-m.R)*m.T))};
  svg.addEventListener("pointerdown",e=>{svg.setPointerCapture(e.pointerId);seek(tOf(e))});
  svg.addEventListener("pointermove",e=>{const t=tOf(e);ghost(t);if(e.buttons)seek(t)});svg.addEventListener("pointerleave",()=>ghost(null))}
 cursor(0)}
function toggle(){if(!P.master)return;if(P.master.paused){if(P.master.ended||P.master.currentTime>=+P.master.dataset.dur-.06)seek(0);P.vids.forEach(v=>v.play());$("#pp").textContent="⏸";loop()}else{P.vids.forEach(v=>v.pause());$("#pp").textContent="▶"}}
function loop(){cancelAnimationFrame(P.raf);const f=()=>{if(!P.master)return;cursor(P.master.currentTime);if(!P.master.paused&&!P.master.ended)P.raf=requestAnimationFrame(f);else $("#pp").textContent="▶"};f()}
function seek(t){P.vids.forEach(v=>{v.currentTime=Math.max(0,Math.min(t,(v.duration||t)-.001))});cursor(t)}
function stepF(n){if(!P.master)return;P.vids.forEach(v=>v.pause());$("#pp").textContent="▶";seek(P.master.currentTime+n/(P.rs[0].fps||20))}
function setRate(x){P.vids.forEach(v=>v.playbackRate=x)}
function cursor(t){const sc=$("#sc");if(sc)sc.value=t;const tl=$("#tl");if(tl)tl.textContent=`${t.toFixed(2)} / ${(+sc?.max||0).toFixed(2)} s`;
 const svg=$("#plot");if(svg&&svg._m){const x=svg._m.X(t);svg.querySelectorAll(".cur").forEach(l=>{l.setAttribute("x1",x);l.setAttribute("x2",x)})}
 const ro=$("#readout");if(ro)ro.innerHTML=readout(t)}
function ghost(t){const svg=$("#plot");if(!svg)return;svg.querySelectorAll(".gh").forEach(l=>{if(t==null)l.setAttribute("opacity",0);else{const x=svg._m.X(t);l.setAttribute("x1",x);l.setAttribute("x2",x);l.setAttribute("opacity",.5)}})}
function at(r,t){const s=r.signals;if(!s)return null;let i=0;while(i<s.t.length-1&&s.t[i+1]<=t)i++;return i}
function readout(t){return P.rs.map((r,k)=>{const s=r.signals,i=at(r,t);if(i==null)return "";const span=[...(r.spans||[])].reverse().find(c=>c.t0<=t&&t<=c.t1);
 const v=n=>fmt(s[n][i],3);return `<span style="color:${P.rs.length>1?PAL[k]:"inherit"}">${P.rs.length>1?esc(label(r))+" · ":""}t=${t.toFixed(2)}s · eef (${v("x")}, ${v("y")}, ${v("z")}) · gripper ${v("grip")} / cmd ${v("grip_cmd")} · err ${v("err")} rad${span?` · in <b>${esc(span.name)}</b>${span.ok?"":" ✗"}`:""}</span>`}).join("<br>")}
function niceStep(T){const c=[.5,1,2,5,10,20,50];return c.find(s=>T/s<=10)||100}
function plot(rs,mode){
 const W=1000,L=58,R=12,PH=mode==="single"?110:90,GAP=26,top=mode==="single"?34:18,T=Math.max(0.1,...rs.map(r=>r.signals?r.signals.t.at(-1):0));
 const X=t=>L+(W-L-R)*t/T;
 const pan=mode==="single"?[["end-effector position (m)",[["x","x"],["y","y"],["z","z"]]],["gripper state / command",[["grip","state"],["grip_cmd","command"]]],["joint tracking error ‖q − q_target‖ (rad)",[["err","error"]]]]:[["height z (m)",[["z","z"]]],["x (m)",[["x","x"]]],["y (m)",[["y","y"]]],["gripper state",[["grip","state"]]],["joint tracking error (rad)",[["err","error"]]]];
 const H=top+pan.length*(PH+GAP)+8;let o="";
 if(mode==="single")(rs[0].spans||[]).forEach((c,i)=>{const x0=X(c.t0),w=Math.max(1.5,X(c.t1)-x0);
  o+=`<rect x="${x0}" y="${top}" width="${w}" height="${H-top-22}" fill="${c.ok?(i%2?"var(--acc)":"var(--mute)"):"var(--bad)"}" opacity="${c.ok?.07:.12}"><title>${esc(c.name)} · sim ${c.t0.toFixed(2)}–${c.t1.toFixed(2)} s · program ${c.wall_s}s${c.ok?"":"\nFAILED "+esc(JSON.stringify(c.error||{}))}</title></rect>`;
  if(w>34)o+=`<text x="${x0+3}" y="14" style="font-size:10px;${c.ok?"":"fill:var(--bad)"}">${esc(c.name.replace(/_/g," ").slice(0,Math.floor(w/5.5)))}</text>`});
 pan.forEach(([title,chs],pi)=>{const y0=top+pi*(PH+GAP);
  const vals=rs.flatMap(r=>chs.flatMap(([k])=>r.signals?.[k]||[])).filter(v=>v!=null);if(!vals.length){o+=`<text x="${L}" y="${y0+PH/2}">no data: ${esc(title)}</text>`;return}
  let lo=Math.min(...vals),hi=Math.max(...vals);if(hi-lo<1e-6){lo-=.5;hi+=.5}const pd=(hi-lo)*.08;lo-=pd;hi+=pd;const Y=v=>y0+PH-(v-lo)/(hi-lo)*PH;
  o+=`<text x="${L}" y="${y0-4}" style="font-weight:600">${esc(title)}</text><rect x="${L}" y="${y0}" width="${W-L-R}" height="${PH}" fill="none" stroke="var(--line)"/><text x="${L-4}" y="${y0+9}" text-anchor="end">${(hi).toFixed(2)}</text><text x="${L-4}" y="${y0+PH}" text-anchor="end">${lo.toFixed(2)}</text>`;
  rs.forEach((r,ri)=>chs.forEach(([k,nm],ci)=>{const s=r.signals;if(!s)return;let d="",pen=false;s[k].forEach((v,i)=>{if(v==null){pen=false;return}d+=(pen?"L":"M")+X(s.t[i]).toFixed(1)+" "+Y(v).toFixed(1);pen=true});
   const col=mode==="single"?PAL[ci]:PAL[ri];o+=`<path d="${d}" fill="none" stroke="${col}" stroke-width="1.6" ${mode!=="single"||k!=="grip_cmd"?"":"stroke-dasharray='4 3'"}><title>${esc(nm)}</title></path>`}));
  if(mode==="single")o+=chs.map(([,nm],ci)=>`<text x="${W-R-6-(chs.length-1-ci)*60}" y="${y0+12}" text-anchor="end" style="fill:${PAL[ci]}">${esc(nm)}</text>`).join("")});
 if(mode==="single"&&rs[0].phases)[["close_t","grasp"],["release_t","release"]].forEach(([k,nm])=>{const t=rs[0].phases[k];if(t!=null)o+=`<line x1="${X(t)}" x2="${X(t)}" y1="${top}" y2="${H-22}" stroke="var(--ok)" stroke-dasharray="4 3"/><text x="${X(t)+3}" y="${H-12}" style="fill:var(--ok)">${nm}</text>`});
 const st=niceStep(T),yb=H-8;for(let t=0;t<=T+1e-6;t+=st)o+=`<text x="${X(t)}" y="${yb}" text-anchor="middle">${t}s</text>`;
 o+=`<line class="gh" y1="${top}" y2="${H-22}" stroke="var(--ink)" opacity="0" pointer-events="none"/><line class="cur" y1="${top}" y2="${H-22}" stroke="var(--ink)" stroke-width="1.5" pointer-events="none"/>`;
 return `<svg id="plot" viewBox="0 0 ${W} ${H}" style="touch-action:none;cursor:crosshair" data-t="${T}" data-l="${L}" data-r="${R}">${o}</svg>`}
function spanTable(r){return `<table><tr><th>#</th><th>call</th><th>sim time</th><th>program s</th><th>status</th><th>detail</th></tr>${(r.spans||[]).map((c,i)=>`<tr class="row" onclick="seek(${c.t0})"><td>${i+1}</td><td class="mono">${esc(c.name)}</td><td class="mono">${c.t0.toFixed(2)}–${c.t1.toFixed(2)}</td><td>${c.wall_s}</td><td>${chip(c.ok?"ok":(c.error?.code||"failed"),okc(c.ok))}</td><td>${c.error?`${esc(c.error.message||"")}<pre>${esc(JSON.stringify({details:c.error.details,diagnostics:c.error.diagnostics},null,1))}</pre>`:""}</td></tr>`).join("")||"<tr><td colspan=6 class=muted>no tool-call trace</td></tr>"}</table>`}
function whyBox(r){const f=(r.spans||[]).find(c=>!c.ok),s=smp(r.sample),att=r.kind==="debug"?s?.attempts[r.attempt]:null;
 if(r.success)return `<div class="why ok"><b>Success</b> after ${r.steps??"?"} steps (${fmt(r.sim_s)} s simulated)${r.success_step!=null?`, task detected at step ${r.success_step}`:""}. ${esc(r.description||"")}</div>`;
 const d=f?.error?.details;
 return `<div class="why"><b>Failed: ${esc(r.cause)}</b><br>${f?`${esc(f.name)} failed at sim ${f.t1.toFixed(2)} s${f.error?.message?": "+esc(f.error.message):""}${d&&d.joint_error_rad!=null?` (joint error ${(+d.joint_error_rad).toFixed(3)} rad vs tolerance ${d.tolerance_rad} after ${d.max_steps} steps)`:""}.`:esc(r.description||"The program ended without the task being completed.")}${r.error?`<pre>${esc(r.error)}</pre>`:""}${att?.feedback?det("Feedback the model received for the next attempt",`<pre>${esc(JSON.stringify(att.feedback,null,1))}</pre>`):""}</div>`}
function phaseBox(r){const p=r.phases;if(!p)return "";const st=D.stages||[];
 const f=(v,u)=>v==null?"n/a":v+u;
 return `<div class="card pad"><h3 class="t">Task phases · proxies from the gripper, the end-effector track and the perception estimate of bowl and plate</h3><div>${st.map((nm,i)=>chip((i+1)+". "+nm,r.depth>=i+1?"ok":"bad")).join("")}</div>
 <table style="margin-top:8px"><tr><th>gripper closed at</th><th>distance eef → bowl at close</th><th>width while closed</th><th>lift while held</th><th>distance eef → plate at release</th><th>released at</th><th>grasp attempts</th></tr><tr><td>${f(p.close_t," s")}</td><td>${f(p.bowl_cm," cm")}</td><td>${f(p.hold_width,"")}${p.hold_width!=null?(p.hold_width>=0.03?" (holding an object)":" (closed on nothing)"):""}</td><td>${f(p.lift_cm," cm")}</td><td>${f(p.plate_cm," cm")}</td><td>${f(p.release_t," s")}</td><td>${p.grasps}</td></tr></table>
 <div class="muted">Shown for the best grasp attempt. Thresholds: held ≥ 0.03 width, near bowl ≤ 10 cm, lifted ≥ 5 cm, over plate ≤ 12 cm. Bowl and plate positions are perception estimates from the first localization, not ground truth.</div></div>`}
function explorer(r){
 const list=sorted(filt().includes(r)?filt():RO()),i=list.indexOf(r),pv=list[i-1],nx=list[i+1],s=smp(r.sample);
 const cams=Object.keys(r.videos||{}),vids=cams.map(c=>videoTag(r,c,c.replace(/_/g," "))).join("");
 return `<div class="bar"><button class="chip" onclick="show('rollouts')">← rollouts</button><button class="chip" ${pv?`onclick="show('r:${pv.id}')"`:"disabled"}>◀ prev</button><button class="chip" ${nx?`onclick="show('r:${nx.id}')"`:"disabled"}>next ▶</button><button class="chip acc" onclick="C.a='${r.id}';show('compare')">compare…</button><button class="chip acc" onclick="show('${r.sample}')">open sample trace</button></div>
 <h2 style="margin:0 0 6px">${esc(label(r))}</h2><div style="margin-bottom:10px">${chip(r.success?"success":"failed",okc(r.success))}${chip(grp(r)+" · seed "+r.seed)}${chip("T "+r.temperature)}${chip((r.steps??"?")+" steps")}${chip(fmt(r.sim_s)+" s sim")}${r.reward!=null?chip("reward "+r.reward):""}</div>
 ${r.missing?`<div class="why">This rollout's directory is no longer on disk, so only the summary is available.</div>`:whyBox(r)}
 ${phaseBox(r)}
 ${cams.length?`<div class="vids">${vids}</div>${controls([r])}`:""}
 ${r.signals?`<div class="card pad viz"><h3 class="t">Signals, aligned with the video · shaded bands are tool calls (red = failed) · click or drag to seek</h3>${plot([r],"single")}<div id="readout" class="mono muted"></div></div>`:""}
 ${det("Tool calls ("+(r.spans||[]).length+")",spanTable(r),true)}
 ${r.overlays?.length?det("Perception overlays (SAM3 segmentation)",frames(r.overlays.map((p,k)=>({src:p,label:"overlay "+(k+1)}))),true):""}
 ${r.keyframes?.length?det("Keyframes around each action",frames(r.keyframes)):""}
 ${r.stdout?det("Program stdout",`<pre>${esc(r.stdout)}</pre>`):""}${r.stderr?det("Program stderr",`<pre>${esc(r.stderr)}</pre>`):""}`}

/* ---------- compare ---------- */
let C={a:"",b:"",cam:"agentview"};
function compare(){const vr=RO().filter(r=>Object.keys(r.videos||{}).length);
 if(!vr.length)return `<h2>Compare</h2><p class="muted">No rollout videos in this run.</p>`;
 if(!byId(C.a)){const a=vr.find(r=>r.success)||vr[0];C.a=a.id}
 if(!byId(C.b)){const A=byId(C.a),b=vr.find(r=>r!==A&&r.success!==A.success&&grp(r)===grp(A)&&r.seed===A.seed)||vr.find(r=>r!==A&&r.success!==A.success)||vr.find(r=>r!==A);C.b=(b||A).id}
 const A=byId(C.a),B=byId(C.b),cams=[...new Set(vr.flatMap(r=>Object.keys(r.videos)))];
 const sel=(k)=>`<select onchange="C.${k}=this.value;show('compare')">${vr.map(r=>`<option value="${esc(r.id)}" ${C[k]===r.id?"selected":""}>${esc(label(r))} ${r.success?"✓":"✗"}</option>`).join("")}</select>`;
 const side=(r,k)=>`<div><div style="margin-bottom:6px;color:${PAL[k]}">■ ${k?"B":"A"} ${chip(r.success?"success":"failed",okc(r.success))}${chip(r.cause)}${chip((r.steps??"?")+" steps")}</div>${videoTag(r,C.cam,label(r))}</div>`;
 return `<h2 style="margin:0 0 10px">Compare two rollouts</h2><div class="bar"><span style="color:var(--s1)">A</span>${sel("a")}<span style="color:var(--s2)">B</span>${sel("b")}<select onchange="C.cam=this.value;show('compare')">${cams.map(c=>`<option ${C.cam===c?"selected":""}>${esc(c)}</option>`).join("")}</select><button class="chip" onclick="[C.a,C.b]=[C.b,C.a];show('compare')">swap</button></div>
 <div class="vids">${side(A,0)}${side(B,1)}</div>${controls([A,B])}
 <div class="card pad viz"><h3 class="t">Signals overlaid · blue = A, orange = B · click or drag to seek both videos</h3>${plot([A,B],"cmp")}<div id="readout" class="mono muted"></div></div>
 <div class="two"><div class="card pad"><h3 class="t">A · tool calls</h3>${spanTable(A)}</div><div class="card pad"><h3 class="t">B · tool calls</h3>${spanTable(B)}</div></div>
 ${policyDiff(A,B)}
 <p class="muted">Pairs are preselected as a success and a failure on the same scene and seed when one exists, so the difference is down to the program.</p>`}


/* ---------- policy (program) comparison with line diff ---------- */
function lineDiff(a,b){let i=0;while(i<a.length&&i<b.length&&a[i]===b[i])i++;let ea=a.length,eb=b.length;while(ea>i&&eb>i&&a[ea-1]===b[eb-1]){ea--;eb--}
 const x=a.slice(i,ea),y=b.slice(i,eb),n=x.length,m=y.length,L=Array.from({length:n+1},()=>new Uint16Array(m+1));
 for(let p=n-1;p>=0;p--)for(let q=m-1;q>=0;q--)L[p][q]=x[p]===y[q]?L[p+1][q+1]+1:Math.max(L[p+1][q],L[p][q+1]);
 const ops=[];for(let k=0;k<i;k++)ops.push(["=",a[k],b[k]]);
 let p=0,q=0;while(p<n||q<m){if(p<n&&q<m&&x[p]===y[q]){ops.push(["=",x[p],y[q]]);p++;q++}else if(q<m&&(p>=n||L[p][q+1]>=L[p+1][q])){ops.push(["+",null,y[q]]);q++}else{ops.push(["-",x[p],null]);p++}}
 for(let k=ea;k<a.length;k++)ops.push(["=",a[k],b[eb+k-ea]]);return ops}
const PD={full:false};
function progOf(r){const s=smp(r.sample);if(!s||!s.attempts.length)return null;const a=s.attempts[Math.min(r.attempt??s.attempts.length-1,s.attempts.length-1)];return{s,a,label:r.sample+" · attempt "+a.attempt}}
function policyDiff(A,B){const pa=progOf(A),pb=progOf(B);
 if(!pa||!pb)return `<div class="card pad"><h3 class="t">Policy comparison</h3><p class="muted">No program recorded for one of the rollouts.</p></div>`;
 const hdr=`<div class="card pad"><h3 class="t">Policy comparison ${chip(pa.label)}${chip(pb.label)}<button class="chip ${PD.full?"acc":""}" onclick="PD.full=!PD.full;show('compare',true)">${PD.full?"full programs":"changed lines only"}</button><button class="chip acc" onclick="show('policies')">compare more programs ▸</button></h3>`;
 if(pa.a===pb.a)return hdr+`<p class="muted">A and B ran the same program, so the difference is down to the scene or seed.</p></div>`;
 const ops=lineDiff(pa.a.program.split("\n"),pb.a.program.split("\n")),ch=ops.filter(o=>o[0]!=="=").length;
 let ln=0,rn=0;const rows=[];ops.forEach((o,k)=>{const l=o[0]!=="+"?++ln:0,r=o[0]!=="-"?++rn:0;rows.push({o,l,r,k})});
 const near=new Array(ops.length).fill(PD.full);if(!PD.full)ops.forEach((o,k)=>{if(o[0]!=="=")for(let d=-3;d<=3;d++)if(near[k+d]!==undefined)near[k+d]=true});
 let h="",skip=0;const flush=()=>{if(skip){h+=`<tr><td class="gap" colspan="4">… ${skip} unchanged lines</td></tr>`;skip=0}};
 rows.forEach(({o,l,r,k})=>{if(!near[k]){skip++;return}flush();const t=o[0],c1=t==="-"?"del":t==="+"?"emp":"",c2=t==="+"?"add":t==="-"?"emp":"";
  h+=`<tr><td class="n">${l||""}</td><td class="${c1}">${o[1]==null?"":esc(o[1])}</td><td class="n">${r||""}</td><td class="${c2}">${o[2]==null?"":esc(o[2])}</td></tr>`});flush();
 const add=ops.filter(o=>o[0]==="+").length,del=ops.filter(o=>o[0]==="-").length;
 return hdr+`<p class="muted" style="margin-top:0"><span style="color:var(--bad)">${del} lines only in A</span> · <span style="color:var(--ok)">${add} lines only in B</span>${ch?"":" · programs are identical"}</p><div style="overflow:auto;max-height:640px"><table class="pd"><colgroup><col style="width:38px"><col><col style="width:38px"><col></colgroup><tr><th></th><th style="color:var(--s1)">A · ${esc(pa.label)}</th><th></th><th style="color:var(--s2)">B · ${esc(pb.label)}</th></tr>${h}</table></div></div>`}


/* ---------- Policies tab: pick any number of programs, differences shown against a reference ---------- */
let PL={sel:null,ref:"",full:false};
const pkey=(s,a)=>s.id+"#"+a.attempt,allPol=()=>D.samples.flatMap(s=>s.attempts.map(a=>({key:pkey(s,a),s,a,label:s.arm+" s"+s.sample+" (T "+s.temperature+") · attempt "+a.attempt})));
function polDefault(){const last=s=>s.attempts.length?pkey(s,s.attempts[s.attempts.length-1]):null,sm=D.samples,d=sm.find(s=>s.arm==="demo"),n=sm.find(s=>s.arm==="nodemo");
 PL.sel=(d&&n?[last(n),last(d)]:sm.slice(0,2).map(last)).filter(Boolean);PL.ref=PL.sel[0]||""}
function polToggle(k,on){if(on&&!PL.sel.includes(k))PL.sel.push(k);if(!on)PL.sel=PL.sel.filter(x=>x!==k);if(!PL.sel.includes(PL.ref))PL.ref=PL.sel[0]||"";show("policies",true)}
function polAlign(ref,others){const N=ref.length,gaps=others.map(()=>Array.from({length:N+1},()=>[])),match=others.map(()=>new Array(N).fill(null));
 others.forEach((o,k)=>{let ri=0;lineDiff(ref,o).forEach(op=>{if(op[0]==="=")match[k][ri++]=op[2];else if(op[0]==="-")ri++;else gaps[k][ri].push(op[2])})});return{gaps,match}}
function policies(){if(!PL.sel)polDefault();const all=allPol(),by={};all.forEach(x=>(by[x.s.arm]??=[]).push(x));
 const pick=`<div class="card pad"><h3 class="t">Choose programs to compare ${chip(PL.sel.length+" selected")}<button class="chip" onclick="PL.sel=[];PL.ref='';show('policies',true)">clear</button><button class="chip" onclick="PL.sel=allPol().map(x=>x.key);PL.ref=PL.ref||PL.sel[0];show('policies',true)">all</button></h3>
  <table><tr><th>compare</th><th>reference</th><th>program</th><th>lines</th><th>outcome</th></tr>${all.map(x=>`<tr><td><input type="checkbox" ${PL.sel.includes(x.key)?"checked":""} onchange="polToggle('${x.key}',this.checked)"></td><td><input type="radio" name="polref" ${PL.ref===x.key?"checked":""} ${PL.sel.includes(x.key)?"":"disabled"} onchange="PL.ref='${x.key}';show('policies',true)"></td><td>${esc(x.label)}</td><td>${x.a.program.split("\n").length}</td><td>${chip(x.a.success?"solved debug":"debug failed",okc(x.a.success))}</td></tr>`).join("")}</table>
  <p class="muted">Every other selected program is aligned to the reference line by line: <span style="color:var(--ok)">green</span> = line not in the reference, <span style="color:var(--bad)">red</span> = reference line missing in that program (also marked in the reference column).</p></div>`;
 if(PL.sel.length<2)return `<h2 style="margin:0 0 10px">Policies</h2>${pick}<p class="muted">Select at least two programs.</p>`;
 const pol=PL.sel.map(k=>all.find(x=>x.key===k)).filter(Boolean),ri=Math.max(0,pol.findIndex(x=>x.key===PL.ref)),R=pol[ri],oth=pol.filter((_,i)=>i!==ri),
  refL=R.a.program.split("\n"),{gaps,match}=polAlign(refL,oth.map(x=>x.a.program.split("\n"))),N=refL.length,cols=[R,...oth];
 const rows=[],cell=(t,c)=>({t,c});
 for(let g=0;g<=N;g++){const m=Math.max(0,...gaps.map(x=>x[g].length));for(let j=0;j<m;j++)rows.push({ch:true,c:[cell(null,"emp"),...gaps.map(x=>x[g][j]!=null?cell(x[g][j],"add"):cell(null,"emp"))]});
  if(g<N){const del=match.some(x=>x[g]===null);rows.push({ch:del,c:[cell(refL[g],del?"del":""),...match.map(x=>x[g]===null?cell(null,"emp"):cell(x[g],""))]})}}
 const near=new Array(rows.length).fill(PL.full);if(!PL.full)rows.forEach((r,k)=>{if(r.ch)for(let d=-3;d<=3;d++)if(near[k+d]!==undefined)near[k+d]=true});
 const cnt=cols.map(()=>0);let h="",skip=0;const flush=()=>{if(skip){h+=`<tr><td class="gap" colspan="${cols.length*2}">… ${skip} unchanged lines</td></tr>`;skip=0}};
 rows.forEach((r,k)=>{r.c.forEach((c,i)=>{if(c.t!=null)cnt[i]++;c.n=c.t!=null?cnt[i]:""});if(!near[k]){skip++;return}flush();h+="<tr>"+r.c.map(c=>`<td class="n">${c.n}</td><td class="${c.c}">${c.t==null?"":esc(c.t)}</td>`).join("")+"</tr>"});flush();
 const stat=oth.map((x,k)=>{const a=gaps[k].reduce((n,g)=>n+g.length,0),d=match[k].filter(v=>v===null).length;return `<tr><td>${esc(x.label)}</td><td style="color:var(--ok)">+${a}</td><td style="color:var(--bad)">−${d}</td><td>${a+d?"":chip("identical","acc")}</td></tr>`}).join("");
 return `<h2 style="margin:0 0 10px">Policies</h2>${pick}
 <div class="card pad"><h3 class="t">Differences vs reference ${chip(R.label,"acc")}</h3><table><tr><th>program</th><th>lines added</th><th>lines removed</th><th></th></tr>${stat}</table></div>
 <div class="card pad"><h3 class="t">Code<button class="chip ${PL.full?"acc":""}" onclick="PL.full=!PL.full;show('policies',true)">${PL.full?"full programs":"changed lines only"}</button></h3><div style="overflow:auto;max-height:720px"><table class="pd" style="min-width:${cols.length*420}px"><colgroup>${cols.map(()=>'<col style="width:38px"><col>').join("")}</colgroup><tr>${cols.map((x,i)=>`<th></th><th style="color:${i?"var(--ink)":"var(--s1)"}">${i?"":"reference · "}${esc(x.label)}</th>`).join("")}</tr>${h}</table></div></div>`}

/* ---------- System 2 tab: extension point. Reads D.system2 (one object per cycle from <run>/system2.jsonl).
   Replace the body of system2() to build the real view; the nav entry and routing exist already. ---------- */
function system2(){return system2View(D.system2||[])}

/* ---------- events, samples (program trace) ---------- */
/* ---------- matched demo vs nodemo ---------- */
let MC={all:false};
const fmtP=p=>p<0.001?"< 0.001":"= "+p.toFixed(3);
function binP(k,n){if(!n)return 1;const m=Math.min(k,n-k);let c=1,t=0;for(let i=0;i<=m;i++){if(i>0)c=c*(n-i+1)/i;t+=c}return Math.min(1,2*t/Math.pow(2,n))}
function matchedData(){const by={};D.samples.forEach(s=>{(by[s.temperature]??={})[s.arm]=s});
 const P=[],U=[];Object.keys(by).map(Number).sort((a,b)=>a-b).forEach(t=>{const g=by[t];g.demo&&g.nodemo?P.push({t,d:g.demo,n:g.nodemo}):U.push(...Object.values(g))});
 const ev=s=>RO().filter(r=>r.sample===s.id&&r.kind==="eval"),cases=[];
 P.forEach(p=>ev(p.n).forEach(rb=>{const ra=ev(p.d).find(r=>grp(r)===grp(rb)&&r.seed===rb.seed);if(ra)cases.push({p,t:p.t,g:grp(rb),seed:rb.seed,a:ra,b:rb})}));
 return{P,U,cases}}
const outc=c=>c.a.success&&c.b.success?"both succeed":c.a.success?"demo only":c.b.success?"nodemo only":"both fail";
const outCls=o=>o==="demo only"?"ok":o==="nodemo only"?"bad":o==="both succeed"?"acc":"";
function mcell(r,x,y,w,h){const ph=HM==="phase"&&!r.success&&r.depth!=null,fill=r.success?"var(--ok)":ph?"var(--s2)":"var(--bad)",op=r.success?.85:ph?.18+.13*r.depth:.9;
 return `<g class="cl" onclick="show('r:${r.id}')"><rect x="${x+1}" y="${y+1}" width="${w-2}" height="${h-2}" rx="4" fill="${fill}" opacity="${op}"/>${HM==="phase"&&r.depth!=null?`<text x="${x+w/2}" y="${y+h-8}" text-anchor="middle" style="fill:var(--ink);font-weight:600">${r.success?"✓":r.depth}</text>`:""}<title>${esc(label(r))}\n${r.success?"success":"failed: "+esc(r.cause)}${r.phase&&!r.success?"\nstopped at: "+esc(r.phase):""}</title></g>`}
function pairGrid(M,g){const x=M.cases.filter(c=>c.g===g),seeds=[...new Set(x.map(c=>c.seed))].sort((a,b)=>a-b),cw=30,rh=26,L=120,T=24,rows=M.P.flatMap(p=>[[p,"demo",p.d],[p,"nodemo",p.n]]),W=L+seeds.length*cw+6,H=T+rows.length*rh+4;
 let o=seeds.map((sd,i)=>`<text x="${L+i*cw+cw/2}" y="${T-8}" text-anchor="middle">${sd}</text>`).join("");
 rows.forEach(([p,arm,s],ri)=>{o+=`<text x="${L-6}" y="${T+ri*rh+17}" text-anchor="end" style="${arm==="demo"?"fill:var(--s1)":"fill:var(--s2)"}">T ${p.t} · ${arm}</text>`;
  seeds.forEach((sd,ci)=>{const c=x.find(c=>c.p===p&&c.seed===sd);if(c)o+=mcell(arm==="demo"?c.a:c.b,L+ci*cw,T+ri*rh,cw,rh)});
  if(ri%2)o+=`<line x1="4" x2="${W}" y1="${T+(ri+1)*rh+2}" y2="${T+(ri+1)*rh+2}" stroke="var(--line)"/>`});
 return `<div style="margin:0 24px 8px 0"><div style="font-weight:600;color:var(--ink)">${esc(gtitle(g))}</div><svg viewBox="0 0 ${W} ${H}" style="width:${W}px;max-width:100%">${o}</svg></div>`}
function matched(){const M=matchedData(),{P,U,cases}=M;
 if(!P.length)return `<h2 style="margin:0 0 10px">Matched demo vs nodemo</h2><p class="muted">This run has no demo and nodemo sample at the same temperature, so there is nothing to match.</p>`;
 const n=k=>cases.filter(c=>outc(c)===k).length,da=n("demo only"),nb=n("nodemo only"),bo=n("both succeed"),ne=n("both fail"),dis=da+nb,gs=[...new Set(cases.map(c=>c.g))].sort((a,b)=>(a.startsWith("debug")?0:a==="stock"?1:2)-(b.startsWith("debug")?0:b==="stock"?1:2));
 const sc=gs.map(g=>{const x=cases.filter(c=>c.g===g),a=x.filter(c=>c.a.success).length,b=x.filter(c=>c.b.success).length,d=x.filter(c=>outc(c)==="demo only").length,e=x.filter(c=>outc(c)==="nodemo only").length;return `<tr><td>${esc(gtitle(g))}</td><td>${x.length}</td><td>${a}/${x.length}</td><td>${b}/${x.length}</td><td>${d}</td><td>${e}</td><td>${x.filter(c=>outc(c)==="both succeed").length}</td><td>${x.filter(c=>outc(c)==="both fail").length}</td><td>${d+e?fmtP(binP(d,d+e)).replace("= ",""):"–"}</td></tr>`}).join("");
 const dbg=P.map(p=>{const f=s=>{const k=s.attempts.findIndex(a=>a.success);return k>=0?`${chip("solved","ok")} after ${k+1} of ${s.attempts.length}`:`${chip("not solved","bad")} ${s.attempts.length} attempts`};return `<tr class="row" onclick="show('${p.d.id}')"><td>T ${p.t}</td><td>${f(p.d)}</td><td>${f(p.n)}</td><td>${(p.d.tokens_new/1e3).toFixed(0)}k / ${(p.n.tokens_new/1e3).toFixed(0)}k</td></tr>`}).join("");
 const st=D.stages||[],dd=cases.filter(c=>c.a.depth!=null&&c.b.depth!=null);
 const stg=st.map((nm,i)=>{const a=dd.filter(c=>c.a.depth>=i+1).length,b=dd.filter(c=>c.b.depth>=i+1).length;return `<tr><td>${i+1}. ${esc(nm)}</td><td>${a}</td><td>${b}</td><td style="color:${a>b?"var(--ok)":a<b?"var(--bad)":"var(--mute)"}">${a-b>0?"+":""}${a-b}</td></tr>`}).join("");
 const shown=cases.filter(c=>MC.all||outc(c)==="demo only"||outc(c)==="nodemo only");
 const list=shown.map(c=>{const o=outc(c);return `<tr><td>T ${c.t}</td><td>${esc(c.g)}</td><td>${c.seed}</td><td>${chip(o,outCls(o))}</td><td class="muted">${esc(c.a.phase||"–")}</td><td class="muted">${esc(c.b.phase||"–")}</td><td><button class="chip acc" onclick="C.a='${c.a.id}';C.b='${c.b.id}';show('compare')">compare videos ▸</button></td></tr>`}).join("")||"<tr><td colspan=7 class=muted>no cases</td></tr>";
 return `<h2 style="margin:0 0 6px">Matched demo vs nodemo</h2>
 <p class="muted" style="margin-top:0">A demo sample is paired with the nodemo sample at the <b>same temperature</b>; their evaluation rollouts are paired on the <b>same scene and seed</b>. Only matched pairs and cases count here${U.length?`; ignored for lack of a partner: ${U.map(s=>esc(s.id)+" (T "+s.temperature+")").join(", ")}`:""}.</p>
 <div class="grid"><div class="stat"><span class="muted">matched pairs</span><b>${P.length}</b><span class="muted">${cases.length} matched cases</span></div><div class="stat"><span class="muted">demo succeeds, nodemo fails</span><b style="color:var(--ok)">${da}</b></div><div class="stat"><span class="muted">nodemo succeeds, demo fails</span><b style="color:var(--bad)">${nb}</b></div><div class="stat"><span class="muted">both succeed / both fail</span><b>${bo} / ${ne}</b></div><div class="stat"><span class="muted">sign test (exact, two-sided)</span><b>${dis?"p "+fmtP(binP(da,dis)):"–"}</b><span class="muted">on the ${dis} cases where they differ</span></div></div>
 <div class="card pad"><h3 class="t">By scene</h3><table><tr><th>Scene</th><th>cases</th><th>demo ok</th><th>nodemo ok</th><th>demo only</th><th>nodemo only</th><th>both ok</th><th>both fail</th><th>sign test p</th></tr>${sc}</table><p class="muted">The cases of one pair share a program, so they are not independent: read p as a rough guide with ${P.length} pairs, not as evidence. Debug columns are not matched case by case (attempt counts differ); see the debug table.</p></div>
 <div class="card pad viz"><h3 class="t">Matched rollouts ${["result","phase"].map(m=>`<button class="chip ${HM===m?"acc":""}" onclick="setHM('${m}')">colour by ${m}</button>`).join("")}</h3><div style="display:flex;flex-wrap:wrap">${gs.map(g=>pairGrid(M,g)).join("")}</div><div class="muted">One row per sample, one column per seed; blue label = demo, orange = nodemo. Click a cell to open the rollout.</div></div>
 <div class="two"><div class="card pad"><h3 class="t">Debug (each pair)</h3><table><tr><th>pair</th><th>demo</th><th>nodemo</th><th>new tokens demo / nodemo</th></tr>${dbg}</table></div>
 <div class="card pad"><h3 class="t">Task phases reached, matched cases only</h3><table><tr><th>stage</th><th>demo</th><th>nodemo</th><th>difference</th></tr>${stg}</table><p class="muted">Counts of the ${dd.length} matched cases with a step log. Proxies, see the explorer.</p></div></div>
 <div class="card pad"><h3 class="t">Cases ${chip(shown.length+" shown")}<button class="chip ${MC.all?"acc":""}" onclick="MC.all=!MC.all;show('matched',true)">${MC.all?"all matched cases":"only cases where they differ"}</button></h3><table><tr><th>T</th><th>scene</th><th>seed</th><th>outcome</th><th>demo stopped at</th><th>nodemo stopped at</th><th></th></tr>${list}</table></div>`}
function events(){return `<h3>Events</h3><div class="card"><table><tr><th>Time</th><th>Kind</th><th>Details</th></tr>${D.events.map(e=>{const{time,kind,...r}=e;return `<tr><td class="muted">${esc(time.slice(11))}</td><td>${chip(kind,/stop/.test(kind)?"bad":"")}</td><td>${esc(JSON.stringify(r))}</td></tr>`}).join("")||"<tr><td colspan=3 class=muted>no events recorded (older run)</td></tr>"}</table></div>`}
function attempt(a){const rail=okc(a.success);
 const calls=a.calls.map(c=>`<span class="${c.ok?"":"f"}" title="${esc(c.code||"")}">${esc(c.name)}</span>`).join("");
 const fb=a.feedback?det("Feedback sent to the model for the next attempt",`<pre>${esc(JSON.stringify(a.feedback,null,1))}</pre>`):"";
 return `<div class="rail ${rail}"><details class="card" open><summary>Attempt ${a.attempt} · ${a.role==="initial"?"initial policy":"repair"} ${chip(a.success?"success":"failed",okc(a.success))}${chip(a.tokens.toLocaleString()+" tokens"+(a.from_cache?" (cached)":""))}${a.reasoning_tokens?chip(a.reasoning_tokens.reasoning.toLocaleString()+" of "+a.reasoning_tokens.completion.toLocaleString()+" output tokens were reasoning","acc"):""}<button class="chip acc" onclick="event.preventDefault();show('r:${a.rid}')">watch rollout ▸</button></summary><div class="bd">
 ${a.prompt?det(a.attempt?"Message sent to the model":"Prompt (task + demonstration)",`<pre>${esc(a.prompt)}</pre>`):""}
 ${a.reply?det("Model reply",`<pre>${esc(a.reply)}</pre>`):""}
 ${a.why?det("Why the model changed the code (its own explanation)",`<pre>${esc(a.why)}</pre>`,true):""}
 ${a.attempt||a.diff?det(a.attempt?"Program changes vs attempt "+(a.attempt-1):"Program changes vs the failed program being repaired",diff(a.diff),true):""}
 ${det("Program ("+a.program.split("\n").length+" lines)",code(a.program),a.attempt===0)}
 ${det("Rollout on the debug seed "+chip(a.reason,okc(a.success))+chip((a.wall_s??"?")+" s"),`<div class="calls">${calls||"<span class=muted>no tool calls</span>"}</div>${a.error?`<pre>${esc(a.error)}</pre>`:""}${frames(a.frames)}`,true)}
 ${fb}</div></details></div>`}
function sample(s){const e=s.evaluation;
 const ev=e.length?`<div class="card"><table><tr><th>Scene</th><th>Seed</th><th>Result</th><th>Reason</th><th>Time</th></tr>${e.map(x=>`<tr class="row" onclick="show('r:${x.rid}')"><td>${esc(x.scene)}</td><td>${x.seed}</td><td>${chip(x.success?"success":"failed",okc(x.success))}</td><td>${esc(x.reason)}</td><td>${x.wall_s??""} s</td></tr>`).join("")}</table></div>`:`<p class="muted">no evaluation</p>`;
 const sm=Object.entries(evalSum(s)).map(([k,v])=>chip(k+" "+v.ok+"/"+v.n,v.ok===v.n?"ok":v.ok?"acc":"bad")).join("");
 return `<h2 style="margin:0 0 6px">${esc(s.id)} <span class="muted" style="font-weight:400">T ${s.temperature}</span></h2><div style="margin-bottom:12px">${s.exp?expChips(s):""}${chip(s.attempts.length+" attempts")}${chip(s.tokens_new.toLocaleString()+" new tokens · ≈ "+usd(s.tokens_new),"acc")}${sm}${s.stopped?chip("stopped: "+s.stopped,"bad"):""}</div>
 ${s.attempts.map(attempt).join("")}<h3>Evaluation of the final program <span class="muted" style="font-weight:400">(click a row to watch)</span></h3>${ev}`}

/* ---------- shell ---------- */
function pick(i){D=ALL.runs[i];F={arm:"",scene:"",outcome:"",cause:"",q:""};PL={sel:null,ref:"",full:false};C={a:"",b:"",cam:"agentview"};header();show(EXP()?"about":"dash")}
function header(){const n=D.samples.reduce((a,s)=>a+s.tokens_new,0);
 $("#rn").innerHTML=`<select onchange="pick(this.value)" title="Run">${ALL.runs.map((r,i)=>`<option value="${i}" ${r===D?"selected":""}>${esc(r.name)} · ${esc(r.date)} · ${r.samples.length} samples</option>`).join("")}</select>`;$("#hd").innerHTML=chip(RO().length+" rollouts")+chip(n.toLocaleString()+" new tokens")+chip("≈ "+usd(n),"acc")}
function nav(c){const by={};D.samples.forEach(s=>(by[s.arm]??=[]).push(s));const sel=c.startsWith("r:")?"rollouts":c;
 const b=(id,t)=>`<button class="${sel===id?"on":""}" onclick="show('${id}')">${t}</button>`;
 let h=(EXP()?b("about","About this run")+b("results","Results")+b("scene","Scene"):"")+b("dash","Dashboard")+b("rollouts","Rollouts ("+RO().length+")")+b("compare","Compare")+b("matched","Matched")+b("policies","Policies")+b("system2","System 2"+((D.system2||[]).length?" ("+D.system2.length+")":""))+b("events","Events ("+D.events.length+")");
 for(const arm in by){h+=`<h4>${esc(arm)} · trace</h4>`+by[arm].map(s=>{const e=evalSum(s);return `<button class="${c===s.id?"on":""}" onclick="show('${s.id}')">${s.exp?s.exp.level+" · "+((D.config.levels||{})[s.exp.level]||{}).title:"sample "+s.sample+" · T "+s.temperature}<div class="sub">${solved(s)?"✓ solved debug":"✗ not solved"} · ${Object.entries(e).map(([k,v])=>k+" "+v.ok+"/"+v.n).join(" · ")||"no eval"}</div></button>`}).join("")}
 $("#nav").innerHTML=h}
function show(id,keep){const y=window.scrollY;stopPlayer();if(id==="overview")id="dash";cur=id;location.hash=encodeURIComponent(D.name)+"|"+id;nav(id);const m=$("#main");
 if(id==="dash")m.innerHTML=dash();else if(id==="about")m.innerHTML=expAbout();else if(id==="results")m.innerHTML=expResults();else if(id==="scene")m.innerHTML=expScene();else if(id==="rollouts")m.innerHTML=rollouts();else if(id==="events")m.innerHTML=events();else if(id==="system2")m.innerHTML=system2();
 else if(id==="matched")m.innerHTML=matched();else if(id==="policies")m.innerHTML=policies();else if(id==="compare"){m.innerHTML=compare();mount([byId(C.a),byId(C.b)].filter(Boolean),"cmp")}
 else if(id.startsWith("r:")){const r=byId(id.slice(2));if(!r){m.innerHTML="<p>rollout not found</p>";return}m.innerHTML=explorer(r);mount([r],"single")}
 else{const s=smp(id);m.innerHTML=s?sample(s):"<p>not found</p>"}
 updCnt();
 window.scrollTo(0,keep?y:0)}
document.addEventListener("keydown",e=>{if(!P.master||/INPUT|SELECT|TEXTAREA/.test(e.target.tagName))return;if(e.code==="Space"){e.preventDefault();toggle()}else if(e.code==="ArrowRight"){e.preventDefault();stepF(1)}else if(e.code==="ArrowLeft"){e.preventDefault();stepF(-1)}});
{const [rn,...v]=decodeURIComponent(location.hash.slice(1)).split("|");const i=ALL.runs.findIndex(r=>r.name===rn);if(i>=0)D=ALL.runs[i];
header();show(v.join("|")||(EXP()?"about":"dash"))}
</script></body></html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
