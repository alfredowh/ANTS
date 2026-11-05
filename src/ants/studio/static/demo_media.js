/* Human demonstration in the right column: the chosen clip, then, once the demo is extracted, the
   same clip with hurobo's overlay (hand, markers, trajectory, gripper), looping at recorded speed. */
(function () {
  const box = document.getElementById("demo-box"), video = document.getElementById("demo-video");
  const title = document.getElementById("demo-title"), note = document.getElementById("demo-note");
  const toggle = document.getElementById("demo-toggle"), hint = document.getElementById("demo-hint");
  if (!box) return;
  let shown = null;
  const KEY = "ants-demo-collapsed";
  let collapsed = false;
  try { collapsed = localStorage.getItem(KEY) === "1"; } catch (e) {}

  function applyCollapsed() {
    video.hidden = collapsed;
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.querySelector(".demo-arrow").innerHTML = collapsed ? "&#9656;" : "&#9662;";
    hint.textContent = collapsed ? "Show" : "Hide";
    if (collapsed) video.pause();
    else if (video.getAttribute("src")) video.play().catch(() => {});
  }
  toggle.addEventListener("click", () => {
    collapsed = !collapsed;
    try { localStorage.setItem(KEY, collapsed ? "1" : "0"); } catch (e) {}
    applyCollapsed();
  });

  function show(kind) {
    if (shown === kind) return;
    shown = kind;
    box.hidden = false;
    title.textContent = kind === "overlay" ? "Human demonstration: extracted overlay" : "Human demonstration";
    video.src = `/demo-video/${kind}?t=${Date.now()}`;
    video.playbackRate = 1;
    applyCollapsed();
    if (window.studioForceRight) window.studioForceRight("demo", true);
  }
  function hide() {
    shown = null;
    box.hidden = true;
    video.removeAttribute("src");
    video.load();
    note.textContent = "";
    if (window.studioForceRight) window.studioForceRight("demo", false);
  }
  function refresh() {
    fetch("/demo-video/status").then((r) => r.json()).then((s) => {
      if (s.overlay) { note.textContent = ""; show("overlay"); }
      else if (s.raw) show("raw");
      else hide();
    }).catch(() => {});
  }
  const cBox = document.getElementById("candidate-box"), cVideo = document.getElementById("candidate-video");
  function showCandidate(on) {
    if (cBox.hidden === !on) return;
    cBox.hidden = !on;
    if (on) { cVideo.src = `/demo-video/candidate?t=${Date.now()}`; cVideo.play().catch(() => {}); }
    else { cVideo.removeAttribute("src"); cVideo.load(); }
    if (window.studioForceRight) window.studioForceRight("candidate", on);
  }
  fetch("/demo-video/status").then((r) => r.json()).then((s) => showCandidate(!!s.candidate)).catch(() => {});
  window.demoEvent = (d) => {
    if (d.kind === "pipeline_candidate") showCandidate(true);
    if (d.kind === "pipeline_start" || d.kind === "session_reset") showCandidate(false);
    if (d.kind === "pipeline_start") { shown = null; refresh(); }
    else if (d.kind === "session_reset") hide();
    else if (d.kind === "pipeline_demo_video") {
      if (d.state === "rendering") note.textContent = "Rendering the overlay...";
      else if (d.state === "overlay") { note.textContent = ""; show("overlay"); }
      else if (d.state === "failed") note.textContent = "Overlay could not be rendered: " + (d.detail || "");
    }
  };
  applyCollapsed();
  window.addEventListener("demo-video-picked", () => { shown = null; refresh(); });
  refresh();
})();
