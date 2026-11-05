/* Live simulator panel: in the right column under the reply, wrist view on top, agent view below.
   It exists only while a rollout of this console's run is in progress, and opens the column for
   that time. Polling only: holding a connection open per camera would use up the browser's per-site
   limit. */
(function () {
  const STATUS_MS = 1000, FRAME_MS = 125, STALE_S = 2;
  let status = {active: false};
  const panel = document.createElement("aside");
  panel.id = "live-panel";
  panel.hidden = true;
  panel.innerHTML = `<div class="live-head" id="live-head">
      <span class="live-badge" id="live-badge">LIVE</span>
      <span class="live-label" id="live-label"></span>
    </div>
    <div class="live-views" id="live-views"></div>
    <div class="live-foot" id="live-foot"></div>`;
  (document.getElementById("media-slot") || document.body).append(panel);
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
    if (v.busy || !status.active || document.hidden || status.age_s === null) return;
    v.busy = true;
    const next = new Image();
    const done = () => { v.busy = false; };
    next.onload = () => { v.img.src = next.src; done(); };
    next.onerror = done;
    next.src = `/live/frame/${v.name}.jpg?n=${v.n++}`;
  }

  function render() {
    const on = !!status.active;
    panel.hidden = !on;
    if (window.studioForceRight) window.studioForceRight("live", on);
    if (!on) { clear(); return; }
    // wrist on top, agent view below
    [...(status.cameras || [])].sort((a, b) => (b === "robot0_eye_in_hand") - (a === "robot0_eye_in_hand")).forEach(camera);
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
      window.dispatchEvent(new CustomEvent("live-status", {detail: {status, shown: !panel.hidden}}));
    }).catch(() => { status = {active: false}; render(); });
  }

  poll();
  setInterval(poll, STATUS_MS);
  setInterval(() => Object.values(views).forEach(loadFrame), FRAME_MS);
})();
