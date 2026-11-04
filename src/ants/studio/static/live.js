/* Live simulator panel: visible only while a rollout of this console's run is in progress. It sits
   above both views, because Daniel's page is an iframe in this window. Polling only: holding a
   connection open per camera would use up the browser's per-site limit. */
(function () {
  const STATUS_MS = 1000, FRAME_MS = 125, STALE_S = 2;
  let status = {active: false}, dismissed = false, pos = null;
  const panel = document.createElement("aside");
  panel.id = "live-panel";
  panel.hidden = true;
  panel.innerHTML = `<div class="live-head" id="live-head">
      <span class="live-badge" id="live-badge">LIVE</span>
      <span class="live-label" id="live-label"></span>
      <button type="button" id="live-close" title="Hide; the Live button brings it back" aria-label="Hide live view">&times;</button>
    </div>
    <div class="live-views" id="live-views"></div>
    <div class="live-foot" id="live-foot"></div>`;
  const chip = document.createElement("button");
  chip.id = "live-chip";
  chip.type = "button";
  chip.hidden = true;
  chip.textContent = "Live";
  chip.title = "Show the live simulator view";
  document.body.append(panel, chip);
  const views = {};

  function label(s) {
    const parts = [];
    if (s.stage) parts.push(s.stage);
    const names = Object.keys(s.perturbation || {});
    const short = (v) => JSON.stringify(v, (k, x) => (typeof x === "number" ? +x.toFixed(3) : x));
    parts.push(names.length ? names.map((n) => n + " " + short(s.perturbation[n])).join(", ") : "no perturbation");
    if (s.seed) parts.push("seed " + s.seed);
    if (s.program && s.program !== "program.py") parts.push(s.program);
    return parts.join(" · ");
  }

  function camera(name) {
    if (views[name]) return views[name];
    const box = document.createElement("figure");
    const img = document.createElement("img");
    img.alt = name;
    const cap = document.createElement("figcaption");
    cap.textContent = name === "robot0_eye_in_hand" ? "wrist" : name;
    box.append(img, cap);
    document.getElementById("live-views").appendChild(box);
    const v = {img, n: 0, busy: false, name};
    views[name] = v;
    return v;
  }

  function clear() {
    Object.keys(views).forEach((k) => { views[k].img.closest("figure").remove(); delete views[k]; });
  }

  function loadFrame(v) {
    if (v.busy || !status.active || dismissed || document.hidden || status.age_s === null) return;
    v.busy = true;
    const next = new Image();
    const done = () => { v.busy = false; };
    next.onload = () => { v.img.src = next.src; done(); };
    next.onerror = done;
    next.src = `/live/frame/${v.name}.jpg?n=${v.n++}`;
  }

  function render() {
    const on = !!status.active;
    panel.hidden = !on || dismissed;
    chip.hidden = !on || !dismissed;
    if (!on) { clear(); return; }
    (status.cameras || []).forEach(camera);
    const live = status.age_s !== null && status.age_s < STALE_S;
    const badge = document.getElementById("live-badge");
    badge.textContent = live ? "LIVE" : "WAITING";
    badge.classList.toggle("on", live);
    panel.classList.toggle("stale", !live);
    document.getElementById("live-label").textContent = label(status);
    document.getElementById("live-label").title = label(status);
    const foot = document.getElementById("live-foot");
    if (status.age_s === null) foot.textContent = "No frames yet: the simulator is starting.";
    else if (live) foot.textContent = `step ${status.step} · frame ${status.age_s.toFixed(1)} s old`;
    else foot.textContent = `No new frame for ${status.age_s.toFixed(0)} s (planning or perception). Last frame shown from step ${status.step}.`;
  }

  function poll() {
    fetch("/live/status").then((r) => r.json()).then((s) => {
      if (s.pid !== status.pid) clear(); // another rollout: its first frame replaces nothing old
      status = s;
      render();
    }).catch(() => { status = {active: false}; render(); });
  }

  document.getElementById("live-close").addEventListener("click", () => { dismissed = true; render(); });
  chip.addEventListener("click", () => { dismissed = false; render(); });

  const head = document.getElementById("live-head");
  head.addEventListener("pointerdown", (e) => {
    if (e.target.closest("button")) return;
    const r = panel.getBoundingClientRect();
    const dx = e.clientX - r.left, dy = e.clientY - r.top;
    head.setPointerCapture(e.pointerId);
    const move = (m) => {
      pos = {
        left: Math.max(0, Math.min(innerWidth - r.width, m.clientX - dx)),
        top: Math.max(0, Math.min(innerHeight - 40, m.clientY - dy)),
      };
      panel.style.left = pos.left + "px";
      panel.style.top = pos.top + "px";
      panel.style.right = panel.style.bottom = "auto";
    };
    const up = () => { head.removeEventListener("pointermove", move); head.removeEventListener("pointerup", up); };
    head.addEventListener("pointermove", move);
    head.addEventListener("pointerup", up);
  });

  poll();
  setInterval(poll, STATUS_MS);
  setInterval(() => Object.values(views).forEach(loadFrame), FRAME_MS);
})();
