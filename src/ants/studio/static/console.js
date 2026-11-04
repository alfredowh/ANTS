/* report client-side errors to the server (session folder client_errors.jsonl) so a stuck page can be diagnosed */
(function () {
  function report(msg, src, line) {
    try {
      fetch("/clientlog", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({message: String(msg), source: String(src || ""), line: line || 0})});
    } catch (e) {}
  }
  window.addEventListener("error", (e) => report(e.message, e.filename, e.lineno));
  window.addEventListener("unhandledrejection", (e) => report("unhandled rejection: " + (e.reason && e.reason.message || e.reason)));
})();
/* DATA is a global set by the inline <script> in views/shell.html before this file loads. */

function esc(s) {
  return String(s ?? "").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
}

/* ---------- shared modal ---------- */
function openModal(html) {
  document.getElementById("modal-content").innerHTML = html;
  document.getElementById("modal-backdrop").classList.add("on");
}
function closeModal() {
  document.getElementById("modal-backdrop").classList.remove("on");
}
document.getElementById("modal-close").addEventListener("click", closeModal);
document.getElementById("modal-backdrop").addEventListener("click", (e) => {
  if (e.target.id === "modal-backdrop") closeModal();
});

/* ---------- light/dark theme toggle (shell.html's inline <script> applies the saved choice
   before first paint; this just handles the button and keeps localStorage in sync) ---------- */
const THEME_KEY = "ants-studio-theme";
const themeBtn = document.getElementById("theme-toggle");
function applyThemeIcon() {
  const dark = document.documentElement.dataset.theme !== "light";
  themeBtn.textContent = dark ? "☽" : "☀"; // moon when dark (switch to light), sun when light
  themeBtn.title = dark ? "Switch to light theme" : "Switch to dark theme";
}
themeBtn.addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
  applyThemeIcon();
});
applyThemeIcon();

function renderToolList(el, tools) {
  el.innerHTML = tools.map((t, i) => `<span class="tool-chip" data-i="${i}">${esc(t.name)}</span>`).join("");
  el.querySelectorAll(".tool-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const t = tools[+chip.dataset.i];
      openModal(`<h3>${esc(t.name)}</h3><div class="sub">${esc(t.role)}</div><div class="section">${esc(t.desc)}</div>`);
    });
  });
}

document.getElementById("incumbent-name").textContent = "incumbent: " + DATA.incumbent_name;
renderToolList(document.getElementById("tools-left-wrap"), DATA.tools_left);

/* ---------- run settings (Loop config + Orchestrator/Adversary tools): a modal, not a column ---------- */
function renderRunSettings() {
  const tpl = document.getElementById("run-settings-template");
  openModal(tpl.innerHTML);
  renderToolList(document.getElementById("tools-right"), DATA.tools_right);
  if (DATA.mode === "loop" && DATA.loop_config) {
    const c = DATA.loop_config;
    const friendly = (v) => v === "mock" ? "offline (built-in)" : v;
    document.getElementById("config-tiles").innerHTML = [
      ["Backend", friendly(c.backend)], ["Max cycles", c.cycles], ["Severity (rho)", c.rho], ["Eta", c.eta],
      ["Stall window (W)", c.stall_window], ["Nominal seeds", c.nominal_seeds.join(", ")],
      ["Min tests to stop", c.min_tests], ["Adversary model", friendly(c.adversary_model)],
      ["Reasoning effort", c.reasoning_effort], ["Max model steps", c.max_model_steps],
      ["Synth token budget", c.synth_token_budget],
    ].map(([l, v]) => `<div class="tile"><div class="l">${l}</div><div class="v">${v}</div></div>`).join("");
  } else {
    document.getElementById("config-tiles").innerHTML = `<div class="empty">n/a (single-step mode)</div>`;
  }
}
document.getElementById("run-settings-btn").addEventListener("click", renderRunSettings);

/* ---------- resizable columns ---------- */
(function () {
  const root = document.documentElement;
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem("ants-console-cols") || "{}"); } catch (e) {}
  if (saved.lw) root.style.setProperty("--lw", saved.lw + "px");
  if (saved.rw) root.style.setProperty("--rw", saved.rw + "px");

  function setupHandle(handle, varName, min, max, fromRight) {
    handle.addEventListener("pointerdown", (e) => {
      handle.classList.add("dragging");
      handle.setPointerCapture(e.pointerId);
      const onMove = (ev) => {
        const r = document.getElementById("console-main").getBoundingClientRect();
        const px = fromRight ? r.right - ev.clientX : ev.clientX - r.left;
        const clamped = Math.max(min, Math.min(max, px));
        root.style.setProperty(varName, clamped + "px");
      };
      const onUp = () => {
        handle.classList.remove("dragging");
        handle.removeEventListener("pointermove", onMove);
        handle.removeEventListener("pointerup", onUp);
        try {
          const lw = parseInt(getComputedStyle(root).getPropertyValue("--lw")) || 280;
          const rw = parseInt(getComputedStyle(root).getPropertyValue("--rw")) || 300;
          localStorage.setItem("ants-console-cols", JSON.stringify({ lw, rw }));
        } catch (err) {}
      };
      handle.addEventListener("pointermove", onMove);
      handle.addEventListener("pointerup", onUp);
    });
  }
  setupHandle(document.getElementById("handle-left"), "--lw", 200, 520, false);
  setupHandle(document.getElementById("handle-right"), "--rw", 220, 520, true);
})();

/* ---------- 2D scene illustration ---------- */
/* object/category colors are fixed per category, shown as a <title> tooltip on each shape now
   instead of an always-visible legend -- hover an object to see what it is */
const SCENE_COLOR = { task: "#6fb2e0", rack: "#e8a553", other: "#8a8a8a" };
const SCENE_COLOR_NAME = { task: "task object", rack: "wine rack", other: "other object" };
let sceneKind = "generation"; // internal data source only
function layerOn(id) { return document.getElementById(id).checked; }
function renderScene2D(kind) {
  sceneKind = kind;
  const svg = document.getElementById("scene2d-svg");
  const noteEl = document.getElementById("scene2d-note");
  const asofEl = document.getElementById("scene-asof");
  const s2d = DATA.scene2d || {};
  const scene = s2d[kind];
  if (!scene) {
    svg.innerHTML = "";
    asofEl.textContent = "";
    noteEl.textContent = "no scene data";
    noteEl.title = "Pass --scene / --scene-repair to the console.";
    return;
  }
  asofEl.textContent = "as of " + scene.as_of;
  noteEl.textContent = "Scene given to Synthesizer";
  noteEl.title = "S4-style scene text: oracle geometry, no robot trajectory.";

  const pad = 14;
  let xs = [], ys = [];
  for (const o of scene.objects) { xs.push(o.x0, o.x1); ys.push(o.y0, o.y1); }
  if (scene.gripper) { xs.push(scene.gripper.x); ys.push(scene.gripper.y); }
  const xMin = Math.min(...xs), xMax = Math.max(...xs), yMin = Math.min(...ys), yMax = Math.max(...ys);
  const scale = 1000; // metres -> mm -> px (1 px per mm)
  const w = (yMax - yMin) * scale + pad * 2;
  const h = (xMax - xMin) * scale + pad * 2;
  // screen x = -y (left is left on screen), screen y = -x (forward/+x is up on screen)
  const toX = (y) => (yMax - y) * scale + pad;
  const toY = (x) => (xMax - x) * scale + pad;
  const cx = (o) => toX((o.y0 + o.y1) / 2), cy = (o) => toY((o.x0 + o.x1) / 2);
  const byLabel = {};
  for (const o of scene.objects) byLabel[o.label] = o;

  // three independently-toggleable layers, same underlying data, split for display only
  let relParts = [], sizeParts = [], posParts = [];
  for (const r of scene.relations) {
    const a = byLabel[r.a], b = byLabel[r.b];
    if (!a || !b) continue;
    const x1 = cx(a), y1 = cy(a), x2 = cx(b), y2 = cy(b);
    relParts.push(`<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="#666" stroke-dasharray="4,3" stroke-width="2"><title>${esc(r.a)} ↔ ${esc(r.b)}: ${r.mm} mm</title></line>`);
    relParts.push(`<text class="m" x="${((x1+x2)/2).toFixed(1)}" y="${((y1+y2)/2 - 3).toFixed(1)}">${r.mm} mm</text>`);
  }
  for (const o of scene.objects) {
    const color = SCENE_COLOR[o.cat] || "#8a8a8a";
    const catName = SCENE_COLOR_NAME[o.cat] || o.cat;
    const titleEl = `<title>${esc(o.label)} (${esc(catName)})</title>`;
    if (sceneGraphOn) {
      sizeParts.push(`<circle cx="${cx(o).toFixed(1)}" cy="${cy(o).toFixed(1)}" r="10" fill="${color}" fill-opacity="0.85" stroke="#222" stroke-width="2">${titleEl}</circle>`);
      sizeParts.push(`<text x="${(cx(o) + 13).toFixed(1)}" y="${(cy(o) + 4).toFixed(1)}">${esc(o.label)}</text>`);
      continue;
    }
    const x = toX(o.y1), y = toY(o.x1); // y1/x1 give the top-left corner under this axis mapping
    const bw = (o.y1 - o.y0) * scale, bh = (o.x1 - o.x0) * scale;
    sizeParts.push(`<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" fill="${color}" fill-opacity="0.35" stroke="${color}" stroke-width="2">${titleEl}</rect>`);
    sizeParts.push(`<text x="${(x + 3).toFixed(1)}" y="${(y + 14).toFixed(1)}">${esc(o.label)}</text>`);
    posParts.push(`<circle cx="${cx(o).toFixed(1)}" cy="${cy(o).toFixed(1)}" r="3.5" fill="${color}" stroke="#111" stroke-width="1">${titleEl}</circle>`);
  }
  if (scene.gripper) {
    const gx = toX(scene.gripper.y), gy = toY(scene.gripper.x);
    posParts.push(`<circle cx="${gx.toFixed(1)}" cy="${gy.toFixed(1)}" r="3" fill="none" stroke="#ff4d4d" stroke-width="1.4" stroke-dasharray="2,1.5"><title>gripper</title></circle>`);
    posParts.push(`<text x="${(gx + 5).toFixed(1)}" y="${(gy + 3).toFixed(1)}">gripper</text>`);
  }
  svg.innerHTML =
    `<g id="layer-relationship-g">${relParts.join("")}</g>` +
    `<g id="layer-size-g">${sizeParts.join("")}</g>` +
    `<g id="layer-position-g">${posParts.join("")}</g>`;
  applySceneLayers();
  sceneBaseVB = { x: 0, y: 0, w: Math.max(1, w), h: Math.max(1, h) };
  resetSceneView();
}
function applySceneLayers() {
  document.getElementById("layer-relationship-g").style.display = layerOn("layer-relationship") ? "" : "none";
  document.getElementById("layer-size-g").style.display = layerOn("layer-size") ? "" : "none";
  document.getElementById("layer-position-g").style.display = layerOn("layer-position") ? "" : "none";
}
for (const id of ["layer-position", "layer-size", "layer-relationship"]) {
  document.getElementById(id).addEventListener("change", applySceneLayers);
}
let sceneGraphOn = false;
document.getElementById("scene-graph-btn").addEventListener("click", (e) => {
  sceneGraphOn = !sceneGraphOn;
  e.target.classList.toggle("on", sceneGraphOn);
  e.target.textContent = sceneGraphOn ? "layout view" : "scene graph";
  renderScene2D(sceneKind);
  const el = document.getElementById("scene-graph");
  el.style.display = sceneGraphOn ? "" : "none";
  if (!sceneGraphOn) return;
  const scene = currentScene();
  if (!scene) { el.innerHTML = `<div class="empty">no scene data</div>`; return; }
  el.innerHTML = `${scene.objects.length} objects (nodes), ${scene.relations.length} relations (edges, gap in mm)`;
});
function currentScene() {
  return (DATA.scene2d || {})[sceneKind];
}

/* pan (drag) + zoom (wheel) over the scene SVG, via viewBox manipulation */
let sceneBaseVB = { x: 0, y: 0, w: 240, h: 240 };
let sceneVB = { ...sceneBaseVB };
function resetSceneView() {
  sceneVB = { ...sceneBaseVB };
  document.getElementById("scene2d-svg").setAttribute(
    "viewBox", `${sceneVB.x.toFixed(1)} ${sceneVB.y.toFixed(1)} ${sceneVB.w.toFixed(1)} ${sceneVB.h.toFixed(1)}`
  );
}
(function () {
  const svgEl = document.getElementById("scene2d-svg");
  let dragging = false, lastX = 0, lastY = 0;
  function applyVB() {
    svgEl.setAttribute("viewBox", `${sceneVB.x.toFixed(1)} ${sceneVB.y.toFixed(1)} ${sceneVB.w.toFixed(1)} ${sceneVB.h.toFixed(1)}`);
  }
  svgEl.addEventListener("pointerdown", (e) => {
    dragging = true; lastX = e.clientX; lastY = e.clientY;
    svgEl.setPointerCapture(e.pointerId);
  });
  svgEl.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const rect = svgEl.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    sceneVB.x -= (e.clientX - lastX) * (sceneVB.w / rect.width);
    sceneVB.y -= (e.clientY - lastY) * (sceneVB.h / rect.height);
    lastX = e.clientX; lastY = e.clientY;
    applyVB();
  });
  ["pointerup", "pointercancel", "pointerleave"].forEach((ev) => svgEl.addEventListener(ev, () => { dragging = false; }));
  svgEl.addEventListener("wheel", (e) => {
    e.preventDefault();
    const rect = svgEl.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const mx = sceneVB.x + (e.clientX - rect.left) * (sceneVB.w / rect.width);
    const my = sceneVB.y + (e.clientY - rect.top) * (sceneVB.h / rect.height);
    const factor = e.deltaY > 0 ? 1.12 : 1 / 1.12;
    sceneVB.x = mx - (mx - sceneVB.x) * factor;
    sceneVB.y = my - (my - sceneVB.y) * factor;
    sceneVB.w *= factor; sceneVB.h *= factor;
    applyVB();
  }, { passive: false });
  svgEl.addEventListener("dblclick", resetSceneView); // quick way back to the fitted view
})();

renderScene2D("generation");

document.body.dataset.tab = "console";

/* ---------- navigator + side-panel visibility (claude.ai-style: only the main window by default) ---------- */
const NAV_KEY = "ants-studio-nav", PANELS_KEY = "ants-studio-panels";
(function () {
  const nav = document.getElementById("nav-toggle");
  function setNav(show) {
    document.body.classList.toggle("nav-hidden", !show);
    nav.title = show ? "Hide navigator" : "Show navigator";
    try { localStorage.setItem(NAV_KEY, show ? "1" : "0"); } catch (e) {}
  }
  let showNav = true;
  try { showNav = localStorage.getItem(NAV_KEY) !== "0"; } catch (e) {}
  setNav(showNav);
  nav.addEventListener("click", () => setNav(document.body.classList.contains("nav-hidden")));

  const main = document.getElementById("console-main");
  const btns = { left: document.getElementById("toggle-left"), right: document.getElementById("toggle-right") };
  const labels = { left: "context panel (primitives, scene prompt)", right: "run details (usage, reply, settings)" };
  let panels = { left: false, right: false };
  try { panels = Object.assign(panels, JSON.parse(localStorage.getItem(PANELS_KEY) || "{}")); } catch (e) {}
  function applyPanels() {
    for (const side of ["left", "right"]) {
      main.classList.toggle("show-" + side, !!panels[side]);
      btns[side].classList.toggle("on", !!panels[side]);
      btns[side].title = (panels[side] ? "Hide " : "Show ") + labels[side];
      btns[side].innerHTML = (side === "left") === !!panels[side] ? "&#9666;" : "&#9656;";
    }
    try { localStorage.setItem(PANELS_KEY, JSON.stringify(panels)); } catch (e) {}
  }
  for (const side of ["left", "right"]) btns[side].addEventListener("click", () => { panels[side] = !panels[side]; applyPanels(); });
  applyPanels();
})();

/* ---------- navigator: stored runs (read-only; loading a past run into the view is not built yet) ---------- */
function refreshRunList() {
  fetch("/runs").then((r) => r.json()).then((d) => {
    const el = document.getElementById("navruns");
    const runs = d.runs || [];
    el.innerHTML = runs.length
      ? runs.slice(0, 30).map((r) => `<div class="navrun${r.name === currentRunName ? " cur" : ""}" title="${esc(r.name)} -- ${r.cycles} cycle(s)${r.attacks ? ", " + r.attacks + " attack(s)" : ""}. Loading a stored run into the view is not built yet.">${esc(r.name.replace(/^run-/, ""))}</div>`).join("")
      : `<div class="navnote">no runs stored yet</div>`;
  }).catch(() => { document.getElementById("navruns").innerHTML = `<div class="navnote">runs unavailable</div>`; });
}
refreshRunList();

/* ---------- session: one folder per session on the server (chat, events, runs); "New session" resets ---------- */
function refreshSession() {
  fetch("/session").then((r) => r.json()).then((d) => {
    const el = document.getElementById("session-id");
    el.textContent = d.id || "no session";
    if (d.dir) el.title = "Stored in " + d.dir + "/ (session.json, chat.jsonl, events.jsonl, runs/)";
  }).catch(() => {});
}
refreshSession();
// Clears the conversation view and the saved snapshot; theme, column and panel prefs stay.
function resetSessionUi() {
  try { localStorage.removeItem(UI_STATE_KEY); } catch (e) {}
  document.getElementById("restored-note")?.remove();
  turnsEl.innerHTML = "";
  turnCount = 0;
  rewriteTokenTotal = 0;
  cycleDetails = [];
  currentRunName = null;
  chatMode = "idle";
  chatBuffer = "";
  chatTurnEl = null;
  document.getElementById("chat-input").placeholder = "Message the agent...";
  setChatStatus("");
  hideBanner();
  setSys("sys1", false, "idle"); setSys("sys2", false, "idle"); setSys("orch", false, "idle"); setSys("escalate", false, "none");
  setStatus("idle", "idle");
  document.getElementById("run-folder").textContent = "";
  document.getElementById("usage-tiles").innerHTML = "";
  document.getElementById("reply-box").textContent = "(waiting)";
  runBtn.disabled = false;
  updateCenterLayout();
  refreshRunList();
  refreshSession();
}
document.getElementById("new-session").addEventListener("click", () => {
  const msg = document.getElementById("session-msg");
  msg.textContent = "";
  fetch("/session/new", { method: "POST" }).then((r) => r.json().then((d) => ({ ok: r.ok, d }))).then(({ ok, d }) => {
    if (!ok || !d.ok) { msg.textContent = d.error || "could not start a new session"; return; }
    // the session_reset SSE event clears the page too (other open tabs); this covers a missed event
    resetSessionUi();
  }).catch(() => { msg.textContent = "server unreachable"; });
});

window.startPolicyLoop = () => runBtn.click(); // /policy-dev in the chat does the same as the run button
function runBtnLabel() {
  document.getElementById("run-btn").textContent =
    DATA.mode === "loop" ? "Run policy development loop" : "Run policy development step";
}
runBtnLabel();

const turnsEl = document.getElementById("turns");
const pill = document.getElementById("status-pill");
const runBtn = document.getElementById("run-btn");
let turnCount = 0;
let rewriteTokenTotal = 0;
let cycleDetails = [];
let currentRunName = null;

/* centered-when-empty chat layout, like claude.ai/new -- docks to the bottom once there's content */
function updateCenterLayout() {
  document.getElementById("col-center").classList.toggle("idle", turnCount === 0);
}
updateCenterLayout();

function openCycleDetailModal(idx) {
  const row = cycleDetails[idx];
  if (!row) return;
  const detail = row.rewrite_detail || {};
  const u = detail.usage || {};
  openModal(`
    <h3>Cycle ${esc(String(row.cycle))} repair</h3>
    <div class="sub">v${esc(row.policy_version ?? "?")} &rarr; v${esc(row.candidate_version ?? "?")} &middot; ${esc(row.signature || "")}</div>
    <div class="section"><div class="h">Why the model changed the code</div><div class="delta">${esc(detail.why || "(no WHY note found)")}</div></div>
    <div class="section"><div class="h">Tokens &amp; cache</div><div class="tiles">
      ${[["Input", u.input_tokens], ["Output", u.output_tokens], ["Reasoning", u.reasoning_tokens],
         ["Cached (prompt-cache)", u.cached_tokens ?? 0]]
        .map(([l, v]) => `<div class="tile"><div class="l">${l}</div><div class="v">${v ?? 0}</div></div>`).join("")}
    </div>
    ${(u.cached_tokens ?? 0) > 0
      ? `<div class="scene2d-note" style="margin-top:6px">${u.cached_tokens} input tokens were served from prompt cache, not recomputed.</div>`
      : `<div class="scene2d-note" style="margin-top:6px">No cached tokens on this call — the prompt was processed fresh.</div>`}
    </div>
    <div class="section"><div class="h">Program changes vs. the failed program</div><div class="delta">${esc(row.diff || "(no diff)")}</div></div>
  `);
}

turnsEl.addEventListener("click", (e) => {
  const tk = e.target.closest(".tk");
  if (tk && !e.target.closest("a,button")) {
    tk.closest(".turn").classList.toggle("collapsed");
    return;
  }
  const link = e.target.closest(".details-link");
  if (!link) return;
  openCycleDetailModal(+link.dataset.detailI);
});

function setStatus(kind, text) {
  pill.className = "status-pill " + kind;
  pill.textContent = text;
  const sb = document.getElementById("stop-btn");
  if (sb) { sb.hidden = kind !== "running"; sb.disabled = false; sb.textContent = "Stop"; }
}

/* each turn shows at most ~10 lines; a per-turn button expands it */
function addClampToggle(div) {
  const main = div.querySelector(".main");
  if (!main) return;
  requestAnimationFrame(() => {
    if (main.scrollHeight <= main.clientHeight + 2) return;
    div.classList.add("clamped");
    const b = document.createElement("button");
    b.type = "button";
    b.className = "turn-more";
    b.textContent = "Show more";
    b.addEventListener("click", () => {
      const open = div.classList.toggle("expanded");
      b.textContent = open ? "Show less" : "Show more";
    });
    main.insertAdjacentElement("afterend", b);
  });
}

function addTurn(cls, html) {
  if (turnCount === 0) turnsEl.innerHTML = "";
  turnCount++;
  updateCenterLayout();
  const div = document.createElement("div");
  div.className = "turn " + cls;
  div.innerHTML = html;
  const stick = turnsEl.scrollHeight - turnsEl.scrollTop - turnsEl.clientHeight < 80; // follow the feed only if already at the bottom
  turnsEl.appendChild(div); // oldest on top, newest at the bottom
  if (stick || cls.includes("you")) requestAnimationFrame(() => { turnsEl.scrollTop = turnsEl.scrollHeight; });
  addClampToggle(div);
}

/* ---------- Synthesizer / Adversary / Orchestrator status ---------- */
function setSys(id, active, stage) {
  const badge = document.getElementById(id + "-badge");
  badge.classList.toggle("active", active);
  document.getElementById(id + "-stage").textContent = stage;
}
function resetSys() {
  setSys("sys1", false, "idle");
  setSys("sys2", false, "idle");
  setSys("orch", false, "idle");
  setSys("escalate", false, "none");
}

/* ---------- blocking-state banner ---------- */
function showBanner(html) {
  const el = document.getElementById("banner");
  el.innerHTML = html;
  el.classList.add("on");
}
function hideBanner() {
  document.getElementById("banner").classList.remove("on");
}

function handleMuseEvent(event) {
  const pt = event.payload_type || "";
  if (pt.startsWith("task.lifecycle.")) {
    const payload = event.payload || {};
    const inner = payload.event || {};
    const kind = inner.kind || payload.kind || "?";
    const taskKind = inner.task_kind || "task";
    addTurn("task " + esc(kind), `<div class="tk">${esc(taskKind)}</div><div class="main">${esc(kind)}</div>`);
  } else if (pt === "run.output.delta") {
    const text = (event.payload || {}).text || "";
    addTurn("delta", `<div class="tk">output</div><div class="delta">${esc(text)}</div>`);
  } else {
    addTurn("other", `<div class="tk">${esc(pt || "event")}</div>`);
  }
}

function handleLoopEvent(row) {
  const event = row.event;
  if (event === "start") {
    setSys("sys2", false, "idle (nominal check)");
    setSys("orch", true, "checking nominal cases");
    addTurn("task started", `<div class="tk">loop</div><div class="main">started: ${esc(row.policy && row.policy.id)} v${row.policy && row.policy.version}</div>`);
  } else if (event === "cycle") {
    setSys("sys1", false, "idle");
    const decision = row.decision || "?";
    const cls = decision === "accepted" ? "task completed" : decision === "rejected" ? "error" : "task";
    if (decision === "no_failure") {
      setSys("sys2", true, "selecting next attack");
      setSys("orch", false, "idle");
    } else if (decision === "budget_stop") {
      setSys("sys2", false, "idle");
      setSys("orch", true, "blocked: budget exhausted");
      setSys("escalate", true, "budget exhausted");
      showBanner(`<b>Budget exhausted.</b> Synthesizer's rewrite budget (${esc(String(row.cycle))} cycles in) ran out before the loop could reach a stop condition. It cannot continue on its own from here &mdash; raise <code>--synth-token-budget</code> and re-run, or treat this as a point for human review.`);
    } else {
      setSys("sys2", false, "idle (result logged)");
      setSys("orch", true, decision === "accepted" ? "gate: accepted" : "gate: rejected");
    }
    let main = `cycle ${row.cycle}: attack <b>${esc(row.category)}</b> (severity ${row.severity}) &rarr; <b>${esc(row.outcome)}</b>`;
    if (row.decision) main += ` &rarr; <b>${esc(decision)}</b>`;
    if (row.signature) main += `<br><span class="delta">signature: ${esc(row.signature)}</span>`;
    if (row.rewrite_tokens) {
      rewriteTokenTotal += row.rewrite_tokens;
      main += `<br><span class="delta">rewrite: ${row.rewrite_tokens} tokens ($${row.rewrite_cost_usd ?? "?"})</span>`;
      const budget = DATA.loop_config ? DATA.loop_config.synth_token_budget : null;
      document.getElementById("usage-tiles").innerHTML = [
        ["Rewrites so far", row.candidate_version ? "see cycles" : "-"],
        ["Rewrite tokens (running)", rewriteTokenTotal],
      ].concat(budget ? [["Budget remaining", Math.max(0, budget - rewriteTokenTotal)]] : [])
        .map(([l, v]) => `<div class="tile"><div class="l">${l}</div><div class="v">${v}</div></div>`).join("");
      if (row.rewrite_detail) {
        const idx = cycleDetails.push(row) - 1;
        main += `<br><span class="details-link" data-detail-i="${idx}">View details (reasoning, diff, cache)</span>`;
      }
    }
    if (row.gate) {
      main += `<br><span class="delta">gate: ${row.gate.accepted ? "accepted" : "rejected"} (${row.gate.cases} cases, +${(row.gate.improvements||[]).length})</span>`;
    }
    addTurn(cls, `<div class="tk">cycle ${row.cycle}</div><div class="main">${main}</div>`);
    if (row.diff) {
      addTurn("delta", `<div class="tk">diff v${row.policy_version || "?"} &rarr; v${row.candidate_version || "?"}</div><div class="delta">${esc(row.diff)}</div>`);
    }
  } else if (event === "escalate") {
    setSys("sys1", false, "idle");
    setSys("sys2", false, "idle");
    setSys("orch", true, "blocked: escalated");
    setSys("escalate", true, "signature " + row.signature);
    showBanner(`<b>Escalated &mdash; needs human intervention.</b> ${esc(row.request)}<br>signature <code>${esc(row.signature)}</code> stalled ${row.stalled_cycles} cycles in a row (W). The loop will not continue past this without a human answer.`);
    addTurn("error", `<div class="tk">escalate</div><div class="main">${esc(row.request)}<br><span class="delta">signature: ${esc(row.signature)}, stalled ${row.stalled_cycles} cycles</span></div>`);
  } else if (event === "no_working_policy") {
    setSys("sys1", false, "idle");
    setSys("sys2", false, "idle");
    setSys("orch", true, "blocked: no working policy");
    setSys("escalate", true, "no working policy");
    showBanner(`<b>No working policy &mdash; needs human intervention.</b> ${esc(row.request)}. v0 fails its own nominal cases, so there is nothing for Adversary to attack yet.`);
    addTurn("error", `<div class="tk">no working policy</div><div class="main">${esc(row.request)}</div>`);
  } else if (event === "end") {
    addTurn("done", `<div class="tk">loop end</div><div class="main">stopped: <b>${esc(row.stopped)}</b>, stage: ${esc(row.stage)}, final v${row.final_version}, cycles run: ${row.cycles_run}</div>`);
  } else {
    addTurn("other", `<div class="tk">${esc(event || "loop event")}</div>`);
  }
}

function handleAttackEvent(a) {
  setSys("sys2", false, "idle");
  if (a.outcome === "failure") {
    setSys("orch", true, "failure found, routing to Synthesizer");
    setSys("sys1", true, "writing repair (muse exec)");
  } else {
    setSys("orch", true, "replaying candidate / checking robust");
  }
  addTurn("task", `<div class="tk">attack ${esc(a.attack_id)}</div><div class="main">Adversary attacked with <b>${esc(a.category)}</b> (severity ${a.severity}) &rarr; <b>${esc(a.outcome)}</b><br><span class="replay-link" data-attack="${esc(a.attack_id)}">Open in Replay</span></div>`);
}

function handleDone(payload) {
  setStatus("done", "done");
  runBtn.disabled = false;
  resetSys();
  if (DATA.mode === "loop") {
    const blocked = ["budget", "escalate", "no_working_policy"].includes(payload.stopped);
    if (blocked && !document.getElementById("banner").classList.contains("on")) {
      showBanner(`<b>Stopped: ${esc(payload.stopped)} &mdash; needs human intervention.</b> The loop cannot make further progress on its own.`);
    }
    addTurn("done", `<div class="tk">run complete</div><div class="main">stopped: <b>${esc(payload.stopped)}</b>, stage: ${esc(payload.stage)}, accepted versions: ${JSON.stringify(payload.accepted_versions)}</div>`);
    document.getElementById("reply-box").textContent = JSON.stringify(payload, null, 1);
    return;
  }
  addTurn("done", `<div class="tk">run complete</div><div class="main">final reply received</div>`);
  const u = payload.usage || {};
  document.getElementById("usage-tiles").innerHTML = [
    ["Input tokens", u.input_tokens], ["Output tokens", u.output_tokens],
    ["Reasoning tokens", u.reasoning_tokens], ["Cached tokens", u.cached_tokens],
  ].map(([l, v]) => `<div class="tile"><div class="l">${l}</div><div class="v">${v ?? 0}</div></div>`).join("");
  document.getElementById("reply-box").textContent = payload.text || "(empty reply)";
}

function handleError(payload) {
  setStatus("error", "error");
  runBtn.disabled = false;
  addTurn("error", `<div class="tk">error</div><div class="main">${esc(payload.message)}</div>`);
}

/* ---------- persist the last UI state locally, so a reload shows it, not a blank page ---------- */
const UI_STATE_KEY = "ants-console-last-state";
function saveUiState() {
  try {
    localStorage.setItem(UI_STATE_KEY, JSON.stringify({
      ts: new Date().toISOString(),
      turnsHTML: turnsEl.innerHTML,
      turnCount, rewriteTokenTotal,
      statusClass: pill.className, statusText: pill.textContent,
      bannerOn: document.getElementById("banner").classList.contains("on"),
      bannerHTML: document.getElementById("banner").innerHTML,
      sys: ["sys1", "sys2", "orch", "escalate"].reduce((o, id) => {
        o[id] = [document.getElementById(id + "-badge").classList.contains("active"), document.getElementById(id + "-stage").textContent];
        return o;
      }, {}),
      usageTilesHTML: document.getElementById("usage-tiles").innerHTML,
      replyText: document.getElementById("reply-box").textContent,
      sceneKind,
    }));
  } catch (e) {}
}
function restoreUiState() {
  let snap;
  try { snap = JSON.parse(localStorage.getItem(UI_STATE_KEY) || "null"); } catch (e) { snap = null; }
  if (!snap || !snap.turnCount) return;
  turnsEl.innerHTML = snap.turnsHTML;
  turnCount = snap.turnCount;
  updateCenterLayout();
  rewriteTokenTotal = snap.rewriteTokenTotal || 0;
  const wasRunning = (snap.statusClass || "").includes("running");
  setStatus(wasRunning ? "idle" : snap.statusClass.replace("status-pill", "").trim(), wasRunning ? "idle (reload)" : snap.statusText);
  if (snap.bannerOn) {
    document.getElementById("banner").innerHTML = snap.bannerHTML;
    document.getElementById("banner").classList.add("on");
  }
  for (const id of ["sys1", "sys2", "orch", "escalate"]) {
    const [active, stage] = snap.sys[id] || [false, "idle"];
    setSys(id, wasRunning ? false : active, wasRunning ? "idle (reload)" : stage);
  }
  if (snap.usageTilesHTML) document.getElementById("usage-tiles").innerHTML = snap.usageTilesHTML;
  if (snap.replyText) document.getElementById("reply-box").textContent = snap.replyText;
  if (snap.sceneKind) renderScene2D(snap.sceneKind);
  const note = document.createElement("div");
  note.id = "restored-note";
  note.style.cssText = "font-size:13.2px;color:var(--dim);margin-bottom:8px";
  note.textContent = "restored from this browser's last session (" + new Date(snap.ts).toLocaleString() + ")";
  turnsEl.parentElement.insertBefore(note, turnsEl);
}

function openStream() {
  // One persistent connection for the whole page session (the server never closes it after a
  // run's "done" -- see console_server.py's /events handler). Reconnects on its own via
  // EventSource's built-in retry if the server restarts; no manual close/reopen needed here.
  const es = new EventSource("/events");
  es.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    if (window.studioEvent) window.studioEvent(data); // Adversary view refresh
    if (window.wizardEvent) window.wizardEvent(data); // one shared connection (browsers allow only ~6 per site)
    if (data.kind === "muse_event") handleMuseEvent(data.event);
    else if (data.kind === "loop_event") handleLoopEvent(data.row);
    else if (data.kind === "attack_event") handleAttackEvent(data);
    else if (data.kind === "run_started") {
      document.getElementById("run-folder").textContent = "saving to " + data.run_dir;
      addTurn("task", `<div class="tk">run started</div><div class="main">saving this run to <b>${esc(data.run_dir)}</b> (backend: ${esc(data.backend)})</div>`);
      currentRunName = data.run_dir.split("/").pop();
    }
    else if (data.kind === "session_reset") { resetSessionUi(); return; }
    else if (data.kind === "done") handleDone(data);
    else if (data.kind === "error") handleError(data);
    else if (data.kind === "awaiting_answer") handleAwaitingAnswer(data);
    else if (data.kind === "chat_muse_event") handleChatMuseEvent(data.event);
    else if (data.kind === "chat_done") handleChatDone(data);
    else if (data.kind === "chat_error") handleChatError(data);
    saveUiState();
  };
}

runBtn.addEventListener("click", () => {
  // no confirmation dialog: the run starts immediately (the server still needs the confirmed flag the client sends)
  document.getElementById("restored-note")?.remove();
  rewriteTokenTotal = 0;
  cycleDetails = [];
  currentRunName = null;
  runBtn.disabled = true;
  turnCount = 0;
  turnsEl.innerHTML = "";
  document.getElementById("col-center").classList.remove("idle"); // leaving the empty/centered state the moment a run starts, not waiting for the first turn
  hideBanner();
  setSys("sys1", DATA.mode === "single", "active (muse exec)");
  setSys("escalate", false, "none");
  if (DATA.mode === "loop") { setSys("sys2", false, "idle"); setSys("orch", true, "starting"); }
  setStatus("running", "running");
  document.getElementById("reply-box").textContent = "(waiting)";
  saveUiState();
  fetch("/run", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({confirmed: true}),
  }).then(r => r.json()).then(r => {
    if (!r.ok) { handleError({message: r.error}); }
  });
});

/* ---------- chat composer: three cases (see docs/studio/chat-field-design.md) ---------- */
let chatMode = "idle"; // "idle" | "awaiting_answer" | "queued"
let chatBuffer = ""; // accumulates chat_muse_event output.delta text for the current chat turn
let chatTurnEl = null;

function setChatStatus(text, pending) {
  const el = document.getElementById("chat-status");
  el.textContent = text || "";
  el.classList.toggle("pending", !!pending);
}

function handleAwaitingAnswer(data) {
  chatMode = "awaiting_answer";
  document.getElementById("chat-input").placeholder = "Answer the escalation...";
  setChatStatus("Waiting for your answer to the escalation above.", true);
  addTurn("chat-turn answer", `<div class="tk">escalation (needs your answer)</div><div class="main">${esc((data.escalation || {}).request || "")}</div>`);
}

function newAgentChatTurn() {
  chatBuffer = "";
  const idx = turnCount; // addTurn increments turnCount; capture the element it creates
  addTurn("chat-turn", `<div class="tk">agent</div><div class="main" id="chat-out-${idx}">...</div>`);
  chatTurnEl = document.getElementById("chat-out-" + idx);
}

function handleChatMuseEvent(event) {
  const pt = event.payload_type || "";
  if (pt === "run.output.delta" && chatTurnEl) {
    chatBuffer += (event.payload || {}).text || "";
    chatTurnEl.textContent = chatBuffer;
  }
}

function handleChatDone(payload) {
  if (chatTurnEl) chatTurnEl.textContent = payload.text || chatBuffer || "(empty reply)";
  chatMode = "idle";
  document.getElementById("chat-input").placeholder = "Message the agent...";
  document.getElementById("chat-input").disabled = false;
  setChatStatus("");
}

function handleChatError(payload) {
  addTurn("chat-turn error", `<div class="tk">chat error</div><div class="main">${esc(payload.message)}</div>`);
  chatMode = "idle";
  document.getElementById("chat-input").disabled = false;
  setChatStatus("");
}

function sendChat() {
  const input = document.getElementById("chat-input");
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  if (window.wizardHandle && window.wizardHandle(message)) return; // /policy-dev wizard
  if (chatMode === "awaiting_answer") {
    addTurn("chat-turn you", `<div class="tk">you (answering)</div><div class="main">${esc(message)}</div>`);
  } else {
    addTurn("chat-turn you", `<div class="tk">you</div><div class="main">${esc(message)}</div>`);
    newAgentChatTurn();
  }
  fetch("/chat", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({message}),
  }).then(r => r.json()).then(r => {
    if (!r.ok) { setChatStatus(r.error || "failed to send", false); return; }
    if (r.case === "answer") {
      chatMode = "idle";
      document.getElementById("chat-input").placeholder = "Message the agent...";
      setChatStatus("Answer sent — the loop will resume.");
    } else if (r.case === "queued") {
      chatMode = "queued";
      setChatStatus("A run is active — this will send automatically once it finishes.", true);
    } else if (r.case === "oneshot") {
      setChatStatus("Sent.", true);
    }
  }).catch(() => setChatStatus("failed to send", false));
}
document.getElementById("chat-send").addEventListener("click", sendChat);
document.getElementById("chat-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendChat();
});

/* ---------- voice input (Web Speech API; client-side, never auto-sends) ----------
   Chrome/Edge send the audio to the browser vendor's speech service (not local); needs https or
   localhost for the mic permission. Language: navigator.language, override with
   localStorage "ants-studio-voice-lang". */
(function () {
  const btn = document.getElementById("chat-mic");
  const input = document.getElementById("chat-input");
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!btn) return;
  if (!SR) { btn.disabled = true; btn.title = "Voice input needs a Chromium-based browser"; return; }
  btn.disabled = false;
  const IDLE_TITLE = "Voice input (Chrome sends the audio to Google's speech service; it is not processed locally)";
  btn.title = IDLE_TITLE;
  let rec = null, listening = false, base = "";
  function lang() { try { return localStorage.getItem("ants-studio-voice-lang") || navigator.language || "en-US"; } catch (e) { return navigator.language || "en-US"; } }
  function setUi(on) {
    listening = on;
    btn.classList.toggle("listening", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.title = on ? "Stop listening" : IDLE_TITLE;
  }
  function stop() { if (rec) { try { rec.stop(); } catch (e) {} } }
  function start() {
    if (input.disabled) return;
    rec = new SR();
    rec.lang = lang(); rec.interimResults = true; rec.continuous = true;
    base = input.value;
    let finals = "";
    rec.onresult = (ev) => {
      let interim = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const r = ev.results[i];
        if (r.isFinal) finals += r[0].transcript; else interim += r[0].transcript;
      }
      const spoken = (finals + interim).trim();
      input.value = (base && spoken ? base.replace(/\s+$/, "") + " " : base) + spoken;
    };
    rec.onerror = (ev) => {
      const err = ev.error;
      if (err === "not-allowed" || err === "service-not-allowed") setChatStatus("Microphone blocked — allow it in the browser's site settings", false);
      else if (err === "network") setChatStatus("Voice input needs internet: Chrome's speech service is unreachable.", false);
      else if (err !== "no-speech" && err !== "aborted") setChatStatus("Voice input error: " + err, false);
      setUi(false);
    };
    rec.onend = () => { if (listening) setUi(false); if (document.getElementById("chat-status").textContent === "Listening…") setChatStatus(""); rec = null; };
    try { rec.start(); setUi(true); setChatStatus("Listening…", true); }
    catch (e) { setUi(false); rec = null; }
  }
  btn.addEventListener("click", () => (listening ? stop() : start()));
  document.getElementById("chat-send").addEventListener("click", stop, true);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") stop(); }, true);
  document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); });
  new MutationObserver(() => {
    btn.disabled = input.disabled;
    if (input.disabled) stop();
  }).observe(input, {attributes: true, attributeFilter: ["disabled"]});
})();

openStream();
restoreUiState();

document.getElementById("stop-btn").addEventListener("click", () => {
  const sb = document.getElementById("stop-btn");
  sb.disabled = true;
  sb.textContent = "Stopping...";
  fetch("/stop", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"})
    .then((r) => r.json())
    .then((r) => { if (!r.ok) { sb.disabled = false; sb.textContent = "Stop"; handleError({message: r.error}); } })
    .catch(() => { sb.disabled = false; sb.textContent = "Stop"; });
});
