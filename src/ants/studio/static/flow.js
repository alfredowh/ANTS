/* Live process-flow panel: which block of the policy dev pipeline is running, from SSE events only.
   Blocks come from docs/studio/process-flow-blocks.json. window.flowEvent is called by console.js
   for every event on the shared /events connection.

   Honesty rules:
   - a block lights up only when an event proves it; the one inference (the next attack after a
     cycle row) is drawn dashed and says so;
   - inner steps of one call (Adversary.attack()) share the parent's grouped state;
   - planned blocks never light up. */
(function () {
  const STORE = "ants-flow-state", COLLAPSE = "ants-flow-collapsed";
  const root = document.getElementById("flow-panel");
  if (!root) return;
  const W = 936, CELL_W = 131, NODE_W = 116, ROW_H = 80, NODE_H = 58, TOP = 42;
  let sparkOn = false; // from the skill file: the Adversary's model in /policy-dev
  fetch("/policy-dev").then((r) => r.json()).then((i) => { sparkOn = i.proposer_model === "muse-spark"; render(); }).catch(() => {});
  const OWNER = { synthesizer: "Synthesizer", adversary: "Adversary", orchestrator: "Orchestrator", io: "Input / output" };
  const LABEL = { idle: "idle", running: "running", done: "done", failed: "failed", skipped: "skipped" };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  let G = null, byId = {}, parentOf = {};
  let S = fresh();
  let path = []; // drill-down: ids from the overview inward
  let sel = null; // clicked block, shown in the detail strip
  let collapsed = true; // collapsed by default; an explicit choice persists
  let nextAttack = null; // pending inference after a cycle row
  try { collapsed = localStorage.getItem(COLLAPSE) !== "0"; } catch (e) {}

  function fresh() { return { b: {}, looping: false, active: false, pipeline: false, attackSeen: false, attacks: 0, msg: "" }; }
  function get(id) { return S.b[id] || { st: "idle" }; }
  function set(id, st, detail, extra) {
    const prev = get(id);
    S.b[id] = Object.assign({}, prev, { st, detail: detail == null ? prev.detail : detail, inferred: false }, extra || {});
  }
  function clearTimer() { if (nextAttack) { clearTimeout(nextAttack); nextAttack = null; } }
  function settle(st, detail) { // nothing can still be running
    clearTimer();
    for (const id of Object.keys(S.b)) if (S.b[id].st === "running") set(id, st, detail === undefined ? S.b[id].detail : detail);
    S.looping = false; S.active = false; S.pipeline = false;
  }
  const PRE = ["video", "extract", "demospec", "prompt", "generate"];
  function startRun() {
    clearTimer();
    const keep = S.pipeline;
    const old = S.b;
    S = fresh();
    S.active = true; S.pipeline = keep;
    if (keep) PRE.forEach((id) => { if (old[id]) S.b[id] = old[id]; });
    else PRE.forEach((id) => { S.b[id] = { st: "skipped", detail: "not in this run" }; });
  }
  function scheduleAttack(cycle) { // inferred: the cycle row is logged, the loop goes on with the next attack
    clearTimer();
    nextAttack = setTimeout(() => { // an end row in the same log poll cancels this
      nextAttack = null;
      if (!S.active) return;
      set("attack", "running", "next attack", { inferred: true, cycle: cycle + 2 });
      save(); render();
    }, 800);
  }
  function verdict(row) {
    const cycle = (row.cycle || 0) + 1;
    S.looping = true;
    if (get("nominal").st === "running") set("nominal", "done", "passed");
    const hit = (row.category || "") + " sev " + Number(row.severity || 0).toFixed(2) + " → " + (row.outcome || "");
    set("attack", "done", hit, { cycle });
    const d = row.decision;
    if (d === "no_failure") {
      set("diagnose", "skipped", "no task failure", { cycle });
      set("rewrite", "skipped", "nothing to fix", { cycle });
      set("gate", "skipped", "", { cycle });
      if (row.robust) return;
      scheduleAttack(row.cycle || 0);
    } else if (d === "budget_stop") {
      set("diagnose", "done", row.signature || "", { cycle });
      set("rewrite", "failed", "token budget spent", { cycle });
      set("gate", "skipped", "no candidate", { cycle });
    } else {
      set("diagnose", "done", row.signature || "", { cycle });
      set("rewrite", "done", row.rewrite_tokens ? row.rewrite_tokens + " tokens" : "candidate written", { cycle });
      set("gate", d === "accepted" ? "done" : "failed", (d || "?") + (row.candidate_version != null ? " v" + row.candidate_version : ""), { cycle });
      scheduleAttack(row.cycle || 0);
    }
  }
  function loopRow(row) {
    const e = row.event;
    if (e === "start") { if (!S.attackSeen) set("nominal", "running", "nominal cases"); }
    else if (e === "no_working_policy") { set("nominal", "failed", "fails its nominal cases"); }
    else if (e === "cycle") verdict(row);
    else if (e === "escalate") { clearTimer(); set("escalation", "running", row.signature || "stalled"); }
    else if (e === "human_answer") { set("escalation", "done", "answered"); scheduleAttack(row.cycle || 0); }
    else if (e === "end") { settle("done"); S.msg = "stopped: " + row.stopped; }
  }
  function onEvent(d) {
    const k = d.kind;
    if (k === "session_reset") {
      clearTimer(); S = fresh(); path = []; sel = null;
      try { if (d.session) localStorage.setItem("ants-flow-session", d.session); } catch (e) {}
    }
    else if (k === "pipeline_start") { sparkOn = !!(d.settings && d.settings.spark); clearTimer(); S = fresh(); S.pipeline = true; S.active = true; }
    else if (k === "pipeline_stage") {
      if (byId[d.stage] === undefined && G) return;
      if (!S.pipeline && PRE.includes(d.stage)) { clearTimer(); S = fresh(); S.pipeline = true; S.active = true; }
      if (d.stage === "attack" && d.status === "started") { clearTimer(); S.looping = true; }
      const st = { started: "running", done: "done", failed: "failed", skipped: "skipped" }[d.status];
      if (!st) return;
      const extra = {};
      if (d.cycle != null) extra.cycle = d.cycle;
      set(d.stage, st, d.detail, extra);
      if (d.stage === "deploy" && st !== "running" && !S.looping) S.active = false;
    }
    else if (k === "run_started") startRun();
    else if (k === "attack_event") {
      clearTimer();
      S.attackSeen = true; S.looping = true; S.attacks += 1;
      if (["running", "idle"].includes(get("nominal").st)) set("nominal", "done", "passed");
      const fail = d.outcome === "failure";
      const hit = d.category + " sev " + Number(d.severity || 0).toFixed(2) + " → " + d.outcome;
      set("attack", "done", hit, { cycle: S.attacks });
      set("diagnose", fail ? "done" : "skipped", fail ? "diagnosis in the report" : "no task failure", { cycle: S.attacks });
      set("gate", "idle", "");
      if (fail) set("rewrite", "running", "muse exec", { cycle: S.attacks });
      else set("rewrite", "idle", "");
    }
    else if (k === "loop_event") loopRow(d.row || {});
    else if (k === "awaiting_answer") { clearTimer(); set("escalation", "running", "waiting for a person"); }
    else if (k === "stop_requested") { settle("failed", "stopped by user"); S.msg = "stopped by user"; }
    else if (k === "done") {
      const stopped = d.stopped;
      settle(stopped === "user_stop" ? "failed" : "done", stopped === "user_stop" ? "stopped by user" : undefined);
      if (stopped) S.msg = "stopped: " + stopped;
    }
    else if (k === "error") {
      if (!S.active || /logging failed/.test(d.message || "")) return;
      settle("failed", "error"); S.msg = String(d.message || "error").slice(0, 200);
    }
    else return;
    save();
    render();
  }
  window.flowEvent = onEvent;

  function save() { try { localStorage.setItem(STORE, JSON.stringify(S)); } catch (e) {} }

  /* a block's displayed state: its own, or its nearest ancestor's when the step is inside one call */
  function shown(b) {
    if (b.status === "planned") return { st: "planned", detail: "planned" };
    if (b.stage) return get(b.stage === b.id ? b.id : b.stage);
    if (b.inherit && parentOf[b.id]) {
      const p = shown(parentOf[b.id]);
      return { st: p.st, inferred: p.inferred, detail: p.st === "running" ? "grouped" : "" };
    }
    return { st: "idle" };
  }
  function runningTop() { return G ? G.blocks.find((b) => b.stage && get(b.id).st === "running") : null; }

  /* ---------- rendering ---------- */
  function nodeHtml(b, x, y, w, h) {
    const s = shown(b);
    const hasKids = (b.children || []).length > 0;
    const cls = ["fl-nd", "own-" + b.owner, s.st, s.inferred ? "inferred" : "", sel === b.id ? "sel" : ""].join(" ");
    const tip = [b.summary, b.live && b.live.note, s.detail].filter(Boolean).join(" — ");
    const badge = s.cycle ? "c" + s.cycle : hasKids ? b.children.length + " ▸" : "";
    return `<foreignObject x="${x}" y="${y}" width="${w}" height="${h}"><button xmlns="http://www.w3.org/1999/xhtml" type="button" class="${cls}" data-id="${esc(b.id)}" title="${esc(tip)}">
      <span class="fl-l">${esc(b.label)}</span><span class="fl-o">${esc((!sparkOn && b.off_model) || b.model || OWNER[b.owner] || "")}</span>
      <span class="fl-d">${esc(s.detail || (b.status === "planned" ? "planned" : ""))}</span>
      ${badge ? `<span class="fl-badge">${esc(badge)}</span>` : ""}</button></foreignObject>`;
  }
  function edgeClass(e, a, b) {
    const sa = shown(a).st, sb = shown(b).st;
    const c = ["fl-ed"];
    if (e.loop) c.push("loop");
    if (e.planned) c.push("planned");
    if (e.loop && S.looping && S.active && e.from === "gate") c.push("flowing");
    else if (sb === "running" && (sa === "done" || sa === "running") && !e.loop) c.push("lit");
    else if (sa === "done" && (sb === "done" || sb === "failed") && !e.loop) c.push("done");
    return c.join(" ");
  }
  function overview() {
    const tops = G.blocks.filter((b) => b.pos);
    const at = (b) => ({ x: 7 + b.pos.col * CELL_W, y: TOP + b.pos.row * ROW_H });
    const box = (cls, label, c0, r0, c1, r1) => {
      const o = at({ pos: { col: c0, row: r0 } }), pad = 6;
      const w = (c1 - c0) * CELL_W + NODE_W + 2 * pad, h = (r1 - r0) * ROW_H + NODE_H + 2 * pad;
      return `<rect class="fl-box ${cls}" x="${o.x - pad}" y="${o.y - pad}" width="${w}" height="${h}"/>` +
        `<text class="fl-boxl ${cls}" x="${o.x - pad + 2}" y="${o.y - pad - 4}">${label}</text>`;
    };
    const whole = at({ pos: { col: 1, row: 0 } });
    const boxes = `<rect class="fl-box orch" x="${whole.x - 13}" y="${whole.y - 28}" width="${6 * CELL_W + 26 - 15 + 2}" height="${3 * ROW_H + NODE_H + 42}"/>` +
      `<text class="fl-boxl orch" x="${whole.x - 9}" y="${whole.y - 31}">ORCHESTRATOR: orchestrator/loop.py runs every step in code. Muse Wonder writes programs; it does not decide.</text>` +
      box("syn", "SYNTHESIZER", 1, 0, 3, 2) + box("adv", "ADVERSARY", 5, 0, 6, 2);
    let edges = "";
    for (const e of G.edges) {
      const a = byId[e.from], b = byId[e.to];
      const p = at(a), q = at(b);
      let d, lx = null, ly = null;
      if (e.from === "gate" && e.to === "attack") { // up the gutter between orchestrator and Adversary
        const up = p.y - 7, side = q.x - 7, y = q.y + NODE_H * 0.8;
        d = `M${p.x + NODE_W * 0.8} ${p.y} L${p.x + NODE_W * 0.8} ${up} L${side} ${up} L${side} ${y} L${q.x} ${y}`;
        lx = p.x + NODE_W * 0.8 + 4; ly = up - 3;
      } else if (e.from === "rewrite" && e.to === "gate") { // down, then right, into the gate from above
        const y = p.y + NODE_H + 11, x = q.x + NODE_W * 0.3;
        d = `M${p.x + NODE_W / 2} ${p.y + NODE_H} L${p.x + NODE_W / 2} ${y} L${x} ${y} L${x} ${q.y}`;
      } else if (p.y === q.y) { // same row
        const left = q.x < p.x;
        d = `M${left ? p.x : p.x + NODE_W} ${p.y + NODE_H / 2} L${left ? q.x + NODE_W : q.x} ${q.y + NODE_H / 2}`;
        if (e.label && Math.abs(q.x - p.x) > CELL_W) { lx = (left ? q.x + NODE_W : p.x + NODE_W) + 1; ly = p.y + NODE_H / 2 - 4; }
      } else if (q.y < p.y) { // straight up
        d = `M${p.x + NODE_W / 2} ${p.y} L${q.x + NODE_W / 2} ${q.y + NODE_H}`;
        if (e.label) { lx = p.x + NODE_W / 2 + 4; ly = p.y - 9; }
      } else { // straight down
        d = `M${p.x + NODE_W / 2} ${p.y + NODE_H} L${q.x + NODE_W / 2} ${q.y}`;
      }
      edges += `<path class="${edgeClass(e, a, b)}" d="${d}" marker-end="url(#fl-arrow)"/>`;
      if (e.label && lx != null) edges += `<text class="fl-elabel" x="${lx}" y="${ly}">${esc(e.label)}</text>`;
    }
    const H = TOP + 4 * ROW_H + 8;
    const legend = `<foreignObject x="7" y="${TOP + ROW_H}" width="${NODE_W - 8}" height="${2 * ROW_H}"><div xmlns="http://www.w3.org/1999/xhtml" class="fl-legend">
      <span><i class="running"></i>running</span><span><i class="running inferred"></i>inferred</span><span><i class="done"></i>done</span><span><i class="failed"></i>failed</span><span><i class="skipped"></i>skipped</span><span><i class="planned"></i>planned</span></div></foreignObject>`;
    return svg(W, H, boxes + edges + legend + tops.map((b) => { const p = at(b); return nodeHtml(b, p.x, p.y, NODE_W, NODE_H); }).join(""));
  }
  function childView(b) {
    const kids = b.children.map((id) => byId[id]);
    const n = kids.length, cols = Math.min(n, 5), w = Math.min(190, (W - 14 - (cols - 1) * 24) / cols), h = 70;
    const rows = Math.ceil(n / cols), H = 8 + rows * (h + 16);
    const pos = (i) => ({ x: 7 + (i % cols) * (w + 24), y: 4 + Math.floor(i / cols) * (h + 16) });
    let edges = "";
    if (b.flow) for (let i = 0; i + 1 < n; i++) {
      if (Math.floor(i / cols) !== Math.floor((i + 1) / cols)) continue;
      const p = pos(i), q = pos(i + 1);
      edges += `<path class="fl-ed" d="M${p.x + w} ${p.y + h / 2} L${q.x} ${q.y + h / 2}" marker-end="url(#fl-arrow)"/>`;
    }
    return svg(W, H, edges + kids.map((k, i) => { const p = pos(i); return nodeHtml(k, p.x, p.y, w, h); }).join(""));
  }
  function svg(w, h, inner) {
    return `<svg class="flow-svg" viewBox="0 0 ${w} ${h}" role="group" aria-label="Process blocks"><defs><marker id="fl-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path class="fl-arrow" d="M0 0L8 4L0 8z"/></marker></defs>${inner}</svg>`;
  }
  function detailHtml() {
    const r = runningTop();
    const b = byId[sel] || r;
    if (!b) return `<div class="flow-detail"><p class="sig">${esc(S.msg || "Nothing is running. Click a block to see what it does; blocks with ▸ open their sub-steps.")}</p></div>`;
    const s = shown(b), st = s.st || "idle";
    if (!byId[sel]) { // following the run: one line, so the chat is not pushed down
      return `<div class="flow-detail one"><span class="fd-t">${esc(b.label)}</span> <span class="flow-chip ${esc(st)}">${esc(s.inferred ? "running (inferred)" : LABEL[st] || st)}</span> <span class="sig">${esc(b.summary)}</span></div>`;
    }
    return `<div class="flow-detail"><div class="h2"><span>${esc(b.label)}</span><span class="flow-chip ${esc(st)}">${esc(s.inferred ? "running (inferred)" : LABEL[st] || st)}</span>${s.cycle ? `<span class="flow-chip">cycle ${esc(s.cycle)}</span>` : ""}</div>
      ${s.detail ? `<p>${esc(s.detail)}</p>` : ""}<p>${esc(b.summary)}${b.details ? " " + esc(b.details) : ""}</p>
      ${b.live && b.live.note ? `<p class="sig">How we know: ${esc(b.live.note)}</p>` : ""}
      ${(b.code || []).length ? `<p>${b.code.map((c) => `<code>${esc(c)}</code>`).join(" ")}</p>` : ""}
      ${(b.docs || []).length ? `<p class="sig">Docs: ${b.docs.map((c) => `<code>${esc(c)}</code>`).join(" ")}</p>` : ""}</div>`;
  }
  function nowText() {
    const r = runningTop();
    if (r) { const s = get(r.id); return r.label + (s.inferred ? " (inferred)" : "") + (s.detail ? ": " + s.detail : ""); }
    return S.msg || "idle";
  }
  function render() {
    if (!G) return;
    const dots = G.stages.map((id) => `<span class="flow-dot ${esc(get(id).st)}" title="${esc(byId[id].label)}: ${esc(LABEL[get(id).st] || "idle")}"></span>`).join("");
    const head = `<button type="button" class="flow-head" id="flow-toggle" aria-expanded="${!collapsed}"><span class="flow-caret">${collapsed ? "▸" : "▾"}</span><span class="flow-t">Process flow</span><span class="flow-now">${esc(nowText())}</span><span class="flow-dots">${dots}</span></button>`;
    if (collapsed) { root.innerHTML = head; return; }
    const cur = path.length ? byId[path[path.length - 1]] : null;
    const crumbs = `<div class="flow-crumbs"><button type="button" class="flow-crumb" data-depth="0" ${path.length ? "" : "disabled"}>Overview</button>${path.map((id, i) => `<span>›</span><button type="button" class="flow-crumb" data-depth="${i + 1}" ${i === path.length - 1 ? "disabled" : ""}>${esc(byId[id].label)}</button>`).join("")}</div>`;
    const grouped = cur && cur.children.some((id) => byId[id].inherit);
    const note = grouped ? `<p class="flow-note">${esc(byId[cur.children.find((id) => byId[id].inherit)].live.note)}</p>` : "";
    root.innerHTML = head + `<div class="flow-body">${path.length ? crumbs : ""}${note}${cur ? childView(cur) : overview()}${detailHtml()}</div>`;
  }
  root.addEventListener("click", (ev) => {
    if (ev.target.closest("#flow-toggle")) {
      collapsed = !collapsed;
      try { localStorage.setItem(COLLAPSE, collapsed ? "1" : "0"); } catch (e) {}
      render();
      return;
    }
    const c = ev.target.closest(".flow-crumb");
    if (c) { path = path.slice(0, +c.dataset.depth); sel = path[path.length - 1] || null; render(); return; }
    const n = ev.target.closest(".fl-nd");
    if (!n) return;
    const b = byId[n.dataset.id];
    sel = sel === b.id && !(b.children || []).length ? null : b.id;
    if ((b.children || []).length) path = path.concat(b.id);
    render();
  });

  /* ---------- start: blocks, then the snapshot of this page's last state ---------- */
  fetch("/static/flow_blocks.json").then((r) => r.json()).then((data) => {
    G = data;
    G.blocks.forEach((b) => { byId[b.id] = b; });
    G.blocks.forEach((b) => (b.children || []).forEach((id) => { parentOf[id] = b; }));
    try {
      const snap = JSON.parse(localStorage.getItem(STORE) || "null");
      if (snap && snap.b && !Object.keys(S.b).length) S = Object.assign(fresh(), snap);
    } catch (e) {}
    render();
    return fetch("/session").then((r) => r.json()).then((d) => {
      // the saved state belongs to one server session; a new session starts clean
      let same = false;
      try {
        same = localStorage.getItem("ants-flow-session") === d.id;
        localStorage.setItem("ants-flow-session", d.id);
      } catch (e) {}
      if (!same) { clearTimer(); S = fresh(); path = []; sel = null; save(); render(); }
      if (!d.running && S.active) { settle("idle", ""); S.msg = "state from before the reload"; save(); render(); }
    });
  }).catch(() => { root.innerHTML = `<div class="flow-head"><span class="flow-now">Process flow unavailable</span></div>`; });
})();
