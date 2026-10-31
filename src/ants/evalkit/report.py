"""Local viewer for an experiment run directory: a trace UI in one self-contained HTML file.

    uv run python -m ants.evalkit.report data/runs/<name> [--serve] [--open]

Reads `config.json`, `events.jsonl`, and per sample `record.json`, programs, replies, prompts,
feedback and program diffs; keyframe images are linked by relative path, so keep `report.html`
inside the run directory. Older runs (without replies, diffs or events) still render: diffs and
feedback are recomputed from the programs and run directories.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import re
import webbrowser
from pathlib import Path

from ants.adversary.rollout import feedback
from ants.evalkit.runlog import unified_diff


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


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
        prompt = msgs[-1]["content"] if k else "\n\n".join(m["content"] for m in msgs[1:])
    return {
        "attempt": k,
        "role": a.get("role", "initial" if k == 0 else "repair"),
        "tokens": a["tokens"],
        "from_cache": a["from_cache"],
        "program": program,
        "diff": diff or "",
        "reply": _read(sample_dir / f"reply_attempt{k}.md"),
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


def collect(root: Path) -> dict:
    root = root.resolve()
    config = json.loads(_read(root / "config.json") or "{}")
    events = [
        json.loads(line)
        for line in (_read(root / "events.jsonl") or "").splitlines()
        if line.strip()
    ]
    samples = []
    for rec_path in sorted(root.glob("*/sample*/record.json")):
        sample_dir = rec_path.parent
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        attempts, prev = [], None
        for a in rec["attempts"]:
            item = _attempt(sample_dir, root, a, prev)
            attempts.append(item)
            prev = item["program"]
        evals = [
            {
                "scene": e.get("scene", "stock"),
                "seed": int(re.sub(r"\D", "", e["case_id"].split("-")[-1]) or 0),
                "success": e["task_success"],
                "reason": e["termination_reason"],
                "wall_s": e.get("wall_s"),
                "frames": _keyframes(e.get("run_dir"), root, 3),
            }
            for e in rec.get("evaluation", [])
        ]
        new_tokens = sum(a["tokens"] for a in rec["attempts"] if not a["from_cache"])
        samples.append(
            {
                "id": f"{rec['arm']}/sample{rec['sample']}",
                "arm": rec["arm"],
                "sample": rec["sample"],
                "temperature": rec["temperature"],
                "attempts": attempts,
                "evaluation": evals,
                "stopped": rec.get("stopped"),
                "tokens_all": sum(a["tokens"] for a in rec["attempts"]),
                "tokens_new": new_tokens,
            }
        )
    return {
        "name": root.name,
        "config": config,
        "events": events,
        "samples": samples,
        "usd_per_mtok": float(config.get("usd_per_mtok", 13.5)),
    }


def build(root: Path) -> Path:
    data = json.dumps(collect(root)).replace("</", "<\\/")
    out = root / "report.html"
    out.write_text(TEMPLATE.replace("__DATA__", data), encoding="utf-8")
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
:root{--bg:#f6f7f9;--panel:#fff;--ink:#1d2330;--mute:#677086;--line:#e1e4ea;--ok:#1a7f4b;--okbg:#e3f5ea;--bad:#b4281f;--badbg:#fbe7e5;--acc:#2f5fd0;--accbg:#e8eefc;--code:#f1f3f7;--add:#e3f5ea;--del:#fbe7e5}
@media(prefers-color-scheme:dark){:root{--bg:#12151c;--panel:#1a1f29;--ink:#e6e9f0;--mute:#98a1b5;--line:#2b3240;--ok:#5fd394;--okbg:#17321f;--bad:#ff8a80;--badbg:#3a1c1a;--acc:#8aa9ff;--accbg:#1f2a47;--code:#10131a;--add:#16301f;--del:#3a1c1a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
header{display:flex;gap:16px;align-items:center;padding:10px 16px;background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
header h1{font-size:15px;margin:0}header .sp{flex:1}
.layout{display:grid;grid-template-columns:260px minmax(0,1fr);min-height:calc(100vh - 49px)}
nav{border-right:1px solid var(--line);background:var(--panel);padding:8px;overflow:auto}
nav button{display:block;width:100%;text-align:left;border:0;background:none;color:var(--ink);padding:8px 10px;border-radius:8px;cursor:pointer;font:inherit}
nav button:hover{background:var(--bg)}nav button.on{background:var(--accbg);color:var(--acc)}
nav .sub{font-size:12px;color:var(--mute)}nav h4{margin:12px 10px 4px;font-size:11px;text-transform:uppercase;color:var(--mute);letter-spacing:.06em}
main{padding:16px 20px;max-width:1100px;min-width:0}
.chip{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;background:var(--code);color:var(--mute);margin-right:4px}
.chip.ok{background:var(--okbg);color:var(--ok)}.chip.bad{background:var(--badbg);color:var(--bad)}.chip.acc{background:var(--accbg);color:var(--acc)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;margin:0 0 12px}
.card>summary,.card>.hd{padding:10px 14px;cursor:pointer;display:flex;gap:8px;align-items:center;font-weight:600;list-style:none}
.card>summary::-webkit-details-marker{display:none}.card>summary:before{content:"▸";color:var(--mute)}.card[open]>summary:before{content:"▾"}
.card .bd{padding:0 14px 12px}
.rail{border-left:3px solid var(--line);margin-left:6px;padding-left:14px}
.rail.ok{border-color:var(--ok)}.rail.bad{border-color:var(--bad)}.rail.acc{border-color:var(--acc)}
pre{margin:6px 0;padding:10px;background:var(--code);border-radius:8px;overflow:auto;font:12px/1.4 ui-monospace,Menlo,Consolas,monospace;max-height:460px}
.ln{display:block;white-space:pre}.ln i{color:var(--mute);font-style:normal;display:inline-block;width:3em;text-align:right;margin-right:10px;user-select:none}
.add{background:var(--add)}.del{background:var(--del)}.hunk{color:var(--acc)}
table{border-collapse:collapse;width:100%}th,td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left}th{color:var(--mute);font-weight:600;font-size:12px}
.calls span{display:inline-block;margin:2px;padding:1px 7px;border-radius:6px;font-size:12px;background:var(--okbg);color:var(--ok)}.calls span.f{background:var(--badbg);color:var(--bad)}
.frames{display:flex;gap:8px;overflow:auto;padding:4px 0}.frames figure{margin:0;flex:none;width:200px}.frames img{width:200px;border-radius:8px;border:1px solid var(--line);cursor:zoom-in}.frames figcaption{font-size:11px;color:var(--mute)}
.muted{color:var(--mute)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.stat{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px 14px}.stat b{display:block;font-size:20px}
#lb{position:fixed;inset:0;background:#000c;display:none;align-items:center;justify-content:center;z-index:9}#lb img{max-width:92vw;max-height:92vh}
@media(max-width:800px){.layout{grid-template-columns:1fr}nav{border-right:0;border-bottom:1px solid var(--line)}}
</style></head><body>
<header><h1>ANTS run viewer</h1><span id="rn" class="muted"></span><span class="sp"></span><span id="hd"></span></header>
<div class="layout"><nav id="nav"></nav><main id="main"></main></div>
<div id="lb" onclick="this.style.display='none'"><img id="lbi"></div>
<script>
const D=__DATA__;
const $=s=>document.querySelector(s);
const esc=s=>String(s??"").replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const usd=t=>"$"+(t/1e6*D.usd_per_mtok).toFixed(2);
const chip=(t,c="")=>`<span class="chip ${c}">${esc(t)}</span>`;
const okc=b=>b?"ok":"bad";
function code(t){return `<pre>${String(t).split("\n").map((l,i)=>`<span class="ln"><i>${i+1}</i>${esc(l)}</span>`).join("")}</pre>`}
function diff(t){if(!t)return `<div class="muted">no changes (identical program)</div>`;
 return `<pre>${t.split("\n").map(l=>`<span class="ln ${l.startsWith("+")&&!l.startsWith("+++")?"add":l.startsWith("-")&&!l.startsWith("---")?"del":l.startsWith("@@")?"hunk":""}">${esc(l)}</span>`).join("")}</pre>`}
function det(title,body,open=false,cls=""){return `<details class="card" ${open?"open":""}><summary>${title}</summary><div class="bd ${cls}">${body}</div></details>`}
function frames(f){return f&&f.length?`<div class="frames">${f.map(x=>`<figure><img loading="lazy" src="${esc(x.src)}" onclick="zoom(this.src)"><figcaption>${esc(x.label)}</figcaption></figure>`).join("")}</div>`:""}
function zoom(s){$("#lbi").src=s;$("#lb").style.display="flex"}
const solved=s=>s.attempts.some(a=>a.success);
const evalSum=s=>{const m={};s.evaluation.forEach(e=>{(m[e.scene]??={n:0,ok:0});m[e.scene].n++;m[e.scene].ok+=e.success?1:0});return m};
function header(){const n=D.samples.reduce((a,s)=>a+s.tokens_new,0);
 $("#rn").textContent=D.name;$("#hd").innerHTML=chip(n.toLocaleString()+" new tokens")+chip("≈ "+usd(n),"acc")+chip(D.samples.length+" samples")}
function nav(cur){const by={};D.samples.forEach(s=>(by[s.arm]??=[]).push(s));
 let h=`<button class="${cur==="overview"?"on":""}" onclick="show('overview')">Overview</button><button class="${cur==="events"?"on":""}" onclick="show('events')">Events (${D.events.length})</button>`;
 for(const arm in by){h+=`<h4>${esc(arm)}</h4>`+by[arm].map(s=>{const e=evalSum(s);return `<button class="${cur===s.id?"on":""}" onclick="show('${s.id}')">sample ${s.sample} · T ${s.temperature}<div class="sub">${solved(s)?"✓ solved debug":"✗ not solved"} · ${Object.entries(e).map(([k,v])=>k+" "+v.ok+"/"+v.n).join(" · ")||"no eval"}</div></button>`}).join("")}
 $("#nav").innerHTML=h}
function overview(){
 const arms=[...new Set(D.samples.map(s=>s.arm))];
 const stat=arms.map(a=>{const ss=D.samples.filter(s=>s.arm===a);return `<div class="stat"><span class="muted">${esc(a)}</span><b>${ss.filter(solved).length}/${ss.length}</b><span class="muted">samples solved the debug seed</span></div>`}).join("");
 const rows=D.samples.map(s=>{const e=evalSum(s);return `<tr style="cursor:pointer" onclick="show('${s.id}')"><td>${esc(s.arm)}</td><td>${s.sample}</td><td>${s.temperature}</td><td>${s.attempts.length}</td><td>${solved(s)?chip("yes","ok"):chip("no","bad")}</td>${["stock","scaled"].map(k=>`<td>${e[k]?e[k].ok+"/"+e[k].n:"–"}</td>`).join("")}<td>${s.tokens_new.toLocaleString()}</td><td>${usd(s.tokens_new)}</td></tr>`}).join("");
 const cfg=Object.entries(D.config).filter(([k])=>!["scenes"].includes(k)).map(([k,v])=>`<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("");
 return `<div class="grid">${stat}</div><h3>Samples</h3><div class="card"><table><tr><th>Arm</th><th>Sample</th><th>T</th><th>Attempts</th><th>Solved debug</th><th>Eval stock</th><th>Eval scaled</th><th>New tokens</th><th>≈ cost</th></tr>${rows}</table></div>
 <p class="muted">Cost uses ${D.usd_per_mtok} $/M tokens (an estimate). "New tokens" excludes cached replies. Click a row to open the trace.</p>
 ${det("Run config",`<table>${cfg}</table>`)}`}
function events(){return `<h3>Events</h3><div class="card"><table><tr><th>Time</th><th>Kind</th><th>Details</th></tr>${D.events.map(e=>{const{time,kind,...r}=e;return `<tr><td class="muted">${esc(time.slice(11))}</td><td>${chip(kind,/stop/.test(kind)?"bad":"")}</td><td>${esc(JSON.stringify(r))}</td></tr>`}).join("")||"<tr><td colspan=3 class=muted>no events recorded (older run)</td></tr>"}</table></div>`}
function attempt(a){const rail=okc(a.success);
 const calls=a.calls.map(c=>`<span class="${c.ok?"":"f"}" title="${esc(c.code||"")}">${esc(c.name)}</span>`).join("");
 const fb=a.feedback?det("Feedback sent to the model for the next attempt",`<pre>${esc(JSON.stringify(a.feedback,null,1))}</pre>`):"";
 return `<div class="rail ${rail}"><details class="card" open><summary>Attempt ${a.attempt} · ${a.role==="initial"?"initial policy":"repair"} ${chip(a.success?"success":"failed",okc(a.success))}${chip(a.tokens.toLocaleString()+" tokens"+(a.from_cache?" (cached)":""))}</summary><div class="bd">
 ${a.prompt?det(a.attempt?"Message sent to the model":"Prompt (task + demonstration)",`<pre>${esc(a.prompt)}</pre>`):""}
 ${a.reply?det("Model reply",`<pre>${esc(a.reply)}</pre>`):""}
 ${a.attempt?det("Program changes vs attempt "+(a.attempt-1),diff(a.diff),true):""}
 ${det("Program ("+a.program.split("\n").length+" lines)",code(a.program),a.attempt===0)}
 ${det("Rollout on the debug seed "+chip(a.reason,okc(a.success))+chip((a.wall_s??"?")+" s"),`<div class="calls">${calls||"<span class=muted>no tool calls</span>"}</div>${a.error?`<pre>${esc(a.error)}</pre>`:""}${frames(a.frames)}`,true)}
 ${fb}</div></details></div>`}
function sample(s){const e=s.evaluation;
 const scenes=[...new Set(e.map(x=>x.scene))];
 const ev=e.length?`<div class="card"><table><tr><th>Scene</th><th>Seed</th><th>Result</th><th>Reason</th><th>Time</th></tr>${e.map(x=>`<tr><td>${esc(x.scene)}</td><td>${x.seed}</td><td>${chip(x.success?"success":"failed",okc(x.success))}</td><td>${esc(x.reason)}</td><td>${x.wall_s??""} s</td></tr>`).join("")}</table></div>${scenes.length?"":""}`:`<p class="muted">no evaluation</p>`;
 const sm=Object.entries(evalSum(s)).map(([k,v])=>chip(k+" "+v.ok+"/"+v.n,v.ok===v.n?"ok":v.ok?"acc":"bad")).join("");
 return `<h2 style="margin:0 0 6px">${esc(s.id)} <span class="muted" style="font-weight:400">T ${s.temperature}</span></h2><div style="margin-bottom:12px">${chip(s.attempts.length+" attempts")}${chip(s.tokens_new.toLocaleString()+" new tokens · ≈ "+usd(s.tokens_new),"acc")}${sm}${s.stopped?chip("stopped: "+s.stopped,"bad"):""}</div>
 ${s.attempts.map(attempt).join("")}<h3>Evaluation of the final program</h3>${ev}`}
function show(id){location.hash=id;nav(id);$("#main").innerHTML=id==="overview"?overview():id==="events"?events():sample(D.samples.find(s=>s.id===id));window.scrollTo(0,0)}
header();show(decodeURIComponent(location.hash.slice(1))||"overview");
</script></body></html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
