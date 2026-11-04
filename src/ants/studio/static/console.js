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

/* ---------- top-level tabs: data-driven, so adding a tab is one entry here + matching markup ---------- */
const TAB_KEY = "ants-console-active-tab";
const TABS = ["console", "perception", "synthesizer", "adversary"].filter(
  (name) => document.getElementById("tab-" + name)
);
function switchTab(name) {
  if (!TABS.includes(name)) name = "console";
  TABS.forEach((t) => {
    document.getElementById("tab-" + t).classList.toggle("on", t === name);
    document.getElementById("tabbtn-" + t).classList.toggle("on", t === name);
  });
  document.body.dataset.tab = name;
  try { localStorage.setItem(TAB_KEY, name); } catch (e) {}
}
TABS.forEach((t) => document.getElementById("tabbtn-" + t).addEventListener("click", () => switchTab(t)));
document.getElementById("perception-btn").addEventListener("click", () => switchTab("perception"));
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
  renderSynthPanel();
  renderAdvPanel();
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

/* ---------- source badge: LIVE (green, pulsing) or ARCHIVED (muted) or MISSING ---------- */
function renderSrcBadge(elId, live, available, archivedLabel) {
  const el = document.getElementById(elId);
  if (available === false) { el.textContent = "missing"; el.className = "src-badge missing"; return; }
  el.textContent = live ? "live" : "archived";
  el.className = "src-badge" + (live ? " live" : "");
  el.title = live ? "" : archivedLabel;
}

/* ---------- Perception tab: agentview scrubber + SAM 3 grounding + cuRobo view, each togglable ----------
   Each layer starts on its archived fallback. If the loop is run with --backend cap_harness, the
   server's watch_aspire_live() thread tails the real rollout's keyframes/SAM3 overlays on disk as
   cap_harness writes them (one directory per primitive call, written WHILE the subprocess is still
   running -- confirmed in ASPIRE/src/cap_harness/artifacts.py) and broadcasts perception_run /
   perception_keyframe / perception_sam3 over the same SSE channel as everything else. The first such
   event for a layer flips it from archived to live and starts replacing its content; nothing here
   fakes liveness the data doesn't have -- cuRobo's trajectory/collision view has no such live path
   (its archived plan_viewer.html is built by a separate offline script, dev/curobo/make_viewer.py,
   not produced by an ordinary rollout), so it stays on its archived embed permanently, honestly. */
let percAgentviewFrames = [];
let percAgentviewIdx = 0, percAgentviewPlaying = false, percAgentviewTimer = null;
let percSam3Frames = [];
let percLiveRunId = null;
let percMode = localStorage.getItem("ants-perc-mode") || "auto"; // auto | live | replay
let percRolloutActive = false;
let percLiveFrames = [], percLiveSam3 = [];
let percArchivedFrames = [], percArchivedSam3 = [];

function percShowLive() { return percMode === "live" || (percMode === "auto" && percRolloutActive); }
function percApplySource() {
  const live = percShowLive() && percLiveFrames.length;
  // Live is a stream, not a replay: hide slider/play controls while live frames arrive.
  // They come back automatically when the rollout ends (percRolloutEnded -> auto replay).
  document.getElementById("perc-controls").style.display = live ? "none" : "";
  percAgentviewFrames = live ? percLiveFrames : percArchivedFrames;
  percSam3Frames = live ? percLiveSam3 : percArchivedSam3;
  percAgentviewIdx = Math.min(percAgentviewIdx, Math.max(0, percAgentviewFrames.length - 1));
  if (percAgentviewFrames.length) percRenderFrame();
  percRenderSam3();
  for (const m of ["auto", "live", "replay"]) {
    document.getElementById("perc-mode-" + m).classList.toggle("on", percMode === m);
  }
}

function percRenderFrame() {
  const f = percAgentviewFrames[percAgentviewIdx];
  if (!f) return;
  document.getElementById("perc-player-img").src = f.src;
  document.getElementById("perc-player-pos").textContent = percAgentviewIdx + 1;
  document.getElementById("perc-player-total").textContent = percAgentviewFrames.length;
  document.getElementById("perc-player-call").textContent = (f.phase || "") + " " + (f.call || "");
  document.getElementById("perc-player-index").textContent = "#" + (f.index ?? "");
  const slider = document.getElementById("perc-player-slider");
  slider.max = percAgentviewFrames.length - 1;
  slider.value = percAgentviewIdx;
}

function percRenderSam3() {
  document.getElementById("perc-sam3-grid").innerHTML = percSam3Frames.map((s) => `
    <div class="sam3-item">
      <img src="${s.src}" loading="lazy" title="${esc(s.name)}" alt="SAM 3: ${esc(s.label || "")}">
      <div class="cap">${esc(s.label || "?")}${s.score != null ? " " + s.score : ""}</div>
    </div>`).join("") || `<div class="empty">no frames found</div>`;
}

function percGoLive(runId) {
  percRolloutActive = true;
  if (percLiveRunId === runId) { percApplySource(); return; }
  percLiveRunId = runId;
  percLiveFrames = [];
  percLiveSam3 = [];
  percAgentviewPlaying = false;
  clearInterval(percAgentviewTimer);
  document.getElementById("perc-player-play").textContent = "play";
  if (percShowLive()) {
    renderSrcBadge("perc-agentview-badge", true, true, "");
    document.getElementById("perc-agentview-note").textContent =
      "LIVE — policy rollout running (run " + runId + "). Expect one new frame each time the robot " +
      "finishes a primitive call, every few seconds — this is a rollout, not video. The frame slider " +
      "is hidden while live and returns when the rollout ends.";
    renderSrcBadge("perc-sam3-badge", true, true, "");
    document.getElementById("perc-sam3-note").textContent = "Live detections for run " + runId + ".";
  }
  percApplySource();
}

function percPushKeyframe(ev) {
  percGoLive(ev.run_id);
  percLiveFrames.push(ev);
  if (percShowLive()) { percAgentviewIdx = percLiveFrames.length - 1; }
  percApplySource();
}

function percPushSam3(ev) {
  percGoLive(ev.run_id);
  percLiveSam3.push(ev);
  percApplySource();
}

function percRolloutEnded() {
  percRolloutActive = false;
  if (percMode === "auto") {
    renderSrcBadge("perc-agentview-badge", false, percArchivedFrames.length ? true : null,
      "Rollout finished — back to replay. Run with --backend cap_harness for live.");
    document.getElementById("perc-agentview-note").textContent = "Rollout finished — showing replay (archived).";
    renderSrcBadge("perc-sam3-badge", false, percArchivedSam3.length ? true : null,
      "Rollout finished — back to replay.");
    document.getElementById("perc-sam3-note").textContent = "Rollout finished — showing replay (archived).";
  }
  percApplySource();
}

(function () {
  const agentview = DATA.agentview_archive || { frames: [], live: false };
  const sam3 = DATA.sam3_archive || { frames: [], live: false };
  const planViewer = DATA.plan_viewer || { available: false, live: false };

  // -- layer toggles, persisted --
  const TOGGLE_KEY = "ants-perception-toggles";
  const panels = { agentview: "perc-panel-agentview", sam3: "perc-panel-sam3", curobo: "perc-panel-curobo" };
  let toggles = { agentview: true, sam3: true, curobo: true };
  try { toggles = { ...toggles, ...JSON.parse(localStorage.getItem(TOGGLE_KEY) || "{}") }; } catch (e) {}
  function applyToggles() {
    for (const [k, panelId] of Object.entries(panels)) {
      document.getElementById(panelId).classList.toggle("off", !toggles[k]);
      document.getElementById("perc-toggle-" + k).checked = toggles[k];
    }
  }
  for (const k of Object.keys(panels)) {
    document.getElementById("perc-toggle-" + k).addEventListener("change", (e) => {
      toggles[k] = e.target.checked;
      applyToggles();
      try { localStorage.setItem(TOGGLE_KEY, JSON.stringify(toggles)); } catch (err) {}
    });
  }
  applyToggles();

  // -- agentview player, mounted directly in the tab (not a modal); starts on the archive --
  renderSrcBadge("perc-agentview-badge", false, agentview.frames.length ? true : null,
    `From ${agentview.source} — run with --backend cap_harness for a live camera feed during the rollout.`);
  document.getElementById("perc-agentview-note").textContent = agentview.frames.length
    ? "Showing an archived rollout; switches to the live feed the moment a real rollout starts."
    : "No archived example found either.";
  percArchivedFrames = agentview.frames;
  percAgentviewFrames = agentview.frames;
  for (const m of ["auto", "live", "replay"]) {
    document.getElementById("perc-mode-" + m).addEventListener("click", () => {
      percMode = m;
      localStorage.setItem("ants-perc-mode", m);
      percApplySource();
    });
  }
  percApplySource();
  if (percAgentviewFrames.length) {
    percRenderFrame();
  } else {
    document.getElementById("perc-panel-agentview").querySelector(".player-frame").innerHTML = `<div class="empty">no frames found</div>`;
  }
  document.getElementById("perc-player-prev").addEventListener("click", () => { percAgentviewIdx = Math.max(0, percAgentviewIdx - 1); percRenderFrame(); });
  document.getElementById("perc-player-next").addEventListener("click", () => { percAgentviewIdx = Math.min(percAgentviewFrames.length - 1, percAgentviewIdx + 1); percRenderFrame(); });
  document.getElementById("perc-player-slider").addEventListener("input", (e) => { percAgentviewIdx = +e.target.value; percRenderFrame(); });
  document.getElementById("perc-player-play").addEventListener("click", (e) => {
    percAgentviewPlaying = !percAgentviewPlaying;
    e.target.textContent = percAgentviewPlaying ? "pause" : "play";
    if (percAgentviewPlaying) {
      percAgentviewTimer = setInterval(() => {
        percAgentviewIdx = percAgentviewIdx + 1 >= percAgentviewFrames.length ? 0 : percAgentviewIdx + 1;
        percRenderFrame();
      }, 500);
    } else { clearInterval(percAgentviewTimer); }
  });

  // -- SAM 3 grounding gallery; starts on the archive --
  renderSrcBadge("perc-sam3-badge", false, sam3.frames.length ? true : null,
    `From ${sam3.source} — run with --backend cap_harness for live detections during the rollout.`);
  document.getElementById("perc-sam3-note").textContent = sam3.frames.length
    ? "Showing archived detections; switches to live the moment a real rollout starts."
    : "No archived example found either.";
  percArchivedSam3 = sam3.frames;
  percSam3Frames = sam3.frames;
  percRenderSam3();

  // -- cuRobo trajectory & collision view, embedded (not linked out); no live path exists --
  renderSrcBadge("perc-curobo-badge", false, planViewer.available,
    "From data/runs/curobo/exp10 (exp09-11, the held-bowl-attached work). Its plan_viewer.html is " +
    "built by a separate offline script (dev/curobo/make_viewer.py), not produced by an ordinary " +
    "rollout, so this stays archived even with --backend cap_harness -- there is no live path for it.");
  if (planViewer.available) {
    const frame = document.getElementById("perc-curobo-frame");
    frame.src = "/perception/planviewer";
    document.getElementById("perc-curobo-note").textContent =
      "Latest archived cuRobo 3D viewer (" + (planViewer.name || "exp11") + "), embedded as-is; no live trajectory source exists yet. " +
      "Collision bodies / 3D scan / Paths buttons above toggle the viewer's own layers.";
    // The viewer is same-origin, so the console toggles click its own layer buttons
    // (data-l="cloud|start|goal|straight|planned"). If a future viewer changes those,
    // the buttons degrade to no-ops and the viewer's own controls still work.
    const layerGroups = {
      "curobo-tgl-collision": ["start", "goal"],
      "curobo-tgl-scan": ["cloud"],
      "curobo-tgl-paths": ["straight", "planned"],
    };
    const clickLayers = (layers, on) => {
      try {
        const doc = frame.contentDocument;
        if (!doc) return;
        for (const l of layers) {
          const b = doc.querySelector(`[data-l="${l}"]`);
          if (b && b.classList.contains("on") !== on) b.click();
        }
      } catch (e) { /* viewer changed; its own layer buttons still work */ }
    };
    for (const [btnId, layers] of Object.entries(layerGroups)) {
      document.getElementById(btnId).addEventListener("click", (e) => {
        const on = !e.target.classList.contains("on");
        e.target.classList.toggle("on", on);
        clickLayers(layers, on);
      });
    }
    frame.addEventListener("load", () => {
      for (const [btnId, layers] of Object.entries(layerGroups)) {
        clickLayers(layers, document.getElementById(btnId).classList.contains("on"));
      }
    });
  } else {
    document.getElementById("perc-curobo-frame").remove();
    document.getElementById("perc-curobo-note").textContent = "No archived cuRobo plan viewer found.";
  }
})();

switchTab((() => { try { return localStorage.getItem(TAB_KEY) || "console"; } catch (e) { return "console"; } })());

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
  turnsEl.insertBefore(div, turnsEl.firstChild); // newest on top
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
        renderSynthPanel();
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
  addTurn("task", `<div class="tk">attack ${esc(a.attack_id)}</div><div class="main">Adversary attacked with <b>${esc(a.category)}</b> (severity ${a.severity}) &rarr; <b>${esc(a.outcome)}</b></div>`);
  renderAdvPanel();
}

function handleDone(payload) {
  percRolloutEnded();
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
  percRolloutEnded();
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
    if (data.kind === "muse_event") handleMuseEvent(data.event);
    else if (data.kind === "loop_event") handleLoopEvent(data.row);
    else if (data.kind === "attack_event") handleAttackEvent(data);
    else if (data.kind === "run_started") {
      if (data.backend === "mock") {
        document.getElementById("perc-agentview-note").textContent =
          "This run uses the mock backend — there is no robot and no camera, so no live frames will " +
          "arrive. For the live robot view, restart the console with --backend cap_harness.";
      }
      document.getElementById("run-folder").textContent = "saving to " + data.run_dir;
      addTurn("task", `<div class="tk">run started</div><div class="main">saving this run to <b>${esc(data.run_dir)}</b> (backend: ${esc(data.backend)})</div>`);
      currentRunName = data.run_dir.split("/").pop();
      renderAdvPanel();
    }
    else if (data.kind === "perception_run") percGoLive(data.run_id);
    else if (data.kind === "perception_keyframe") percPushKeyframe(data);
    else if (data.kind === "perception_sam3") percPushSam3(data);
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
  const realBackend = DATA.loop_config && DATA.loop_config.backend === "cap_harness";
  const gateMsg = DATA.mode === "loop"
    ? "Ready to run the policy development phase?\n\n" +
      "This runs the real closed loop: Adversary attacks (" +
      (realBackend ? "real ASPIRE/LIBERO rollouts, ~40s+ and real GPU time each" : "mock backend, free") +
      ") and Synthesizer rewrites for real via muse exec (Muse Code), up to " +
      (DATA.loop_config ? DATA.loop_config.cycles : "N") +
      " cycles. Each rewrite spends Muse tokens (observed ~$0.5 per rewrite); the loop stops " +
      "earlier if it becomes robust, stalls, or hits the token budget." +
      (realBackend ? "\n\nThe Perception tab will switch to live frames from this rollout as it runs." : "")
    : "Ready to run the policy development phase?\n\n" +
      "This sends one real request to muse exec (Muse Code) and spends Muse tokens " +
      "(observed ~$0.5 per repair step). It runs one Phase A repair step against the incumbent " +
      "program shown here, not the full loop.";
  const ok = window.confirm(gateMsg);
  if (!ok) return;
  document.getElementById("restored-note")?.remove();
  rewriteTokenTotal = 0;
  cycleDetails = [];
  currentRunName = null;
  renderSynthPanel();
  renderAdvPanel();
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

/* ---------- Perception tab: Synthesizer / Adversary detail toggle ----------
   Merges the loop's own rollout/result logging into one place: the Synthesizer side reuses
   cycleDetails (same data the per-cycle "View details" modal already uses), the Adversary side
   reads this run's attacks.jsonl (written in ants.studio.run's exact row shape by on_attack in
   console_server.py, so it is readable by Daniel's existing Replay-view data shape too). Either
   side shows a simple "missing" badge instead of an error when a run has no such logging yet
   (an old run folder, or a run that hasn't reached its first attack/repair). */
let percDetailSide = "synth";

function setPercDetailBadge(hasData) {
  const el = document.getElementById("perc-detail-badge");
  el.textContent = hasData ? "archived" : "missing";
  el.className = "src-badge" + (hasData ? "" : " missing");
}

function renderSynthPanel() {
  const body = document.getElementById("perc-detail-synth-body");
  if (!cycleDetails.length) {
    body.innerHTML = `<div class="perc-empty">no repairs logged yet for this run</div>`;
  } else {
    body.innerHTML = cycleDetails.map((row, idx) => {
      const detail = row.rewrite_detail || {};
      const why = (detail.why || "").slice(0, 200);
      return `<div class="turn">
        <div class="tk">cycle ${esc(String(row.cycle))} &middot; v${esc(row.policy_version ?? "?")} &rarr; v${esc(row.candidate_version ?? "?")}</div>
        <div class="main">${esc(why) || "(no WHY note)"}</div>
        <span class="details-link" data-detail-i="${idx}">View full details</span>
      </div>`;
    }).reverse().join("");
  }
  if (percDetailSide === "synth") setPercDetailBadge(cycleDetails.length > 0);
}

function renderAdvPanel() {
  const body = document.getElementById("perc-detail-adv-body");
  if (!currentRunName) {
    body.innerHTML = `<div class="perc-empty">no run yet</div>`;
    if (percDetailSide === "adv") setPercDetailBadge(false);
    return;
  }
  fetch("/attacks/" + encodeURIComponent(currentRunName))
    .then((r) => { if (!r.ok) throw new Error("no attacks.jsonl"); return r.text(); })
    .then((text) => {
      const rows = text.split("\n").filter((l) => l.trim()).map((l) => {
        try { return JSON.parse(l); } catch (e) { return null; }
      }).filter(Boolean);
      if (!rows.length) {
        body.innerHTML = `<div class="perc-empty">no attacks logged yet</div>`;
      } else {
        body.innerHTML = rows.map((row) => {
          const p = (row.report && row.report.perturbation) || {};
          const res = (row.report && row.report.result) || {};
          return `<div class="turn">
            <div class="tk">${esc(p.category || "?")} &middot; severity ${p.severity ?? "?"}</div>
            <div class="main"><b>${esc(res.outcome || "?")}</b>${row.explanation ? "<br>" + esc(row.explanation) : ""}</div>
          </div>`;
        }).reverse().join("");
      }
      if (percDetailSide === "adv") setPercDetailBadge(rows.length > 0);
    })
    .catch(() => {
      body.innerHTML = `<div class="perc-empty">no attacks logged yet</div>`;
      if (percDetailSide === "adv") setPercDetailBadge(false);
    });
}

function switchPercDetailSide(side) {
  percDetailSide = side;
  document.getElementById("perc-side-synth").classList.toggle("on", side === "synth");
  document.getElementById("perc-side-adv").classList.toggle("on", side === "adv");
  document.getElementById("perc-detail-synth-body").hidden = side !== "synth";
  document.getElementById("perc-detail-adv-body").hidden = side !== "adv";
  if (side === "synth") renderSynthPanel(); else renderAdvPanel();
}
document.getElementById("perc-side-synth").addEventListener("click", () => switchPercDetailSide("synth"));
document.getElementById("perc-side-adv").addEventListener("click", () => switchPercDetailSide("adv"));
document.getElementById("perc-detail-synth-body").addEventListener("click", (e) => {
  const link = e.target.closest(".details-link");
  if (link) openCycleDetailModal(+link.dataset.detailI);
});
renderSynthPanel();
renderAdvPanel();

openStream();
restoreUiState();
