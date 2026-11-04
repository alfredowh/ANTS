/* Human demonstration in the right column: the chosen clip, then, once the demo is extracted, the
   same clip with hurobo's overlay (hand, markers, trajectory, gripper), looping at recorded speed. */
(function () {
  const box = document.getElementById("demo-box"), video = document.getElementById("demo-video");
  const title = document.getElementById("demo-title"), note = document.getElementById("demo-note");
  if (!box) return;
  let shown = null;

  function show(kind) {
    if (shown === kind) return;
    shown = kind;
    box.hidden = false;
    title.textContent = kind === "overlay" ? "Human demonstration: extracted overlay" : "Human demonstration";
    video.src = `/demo-video/${kind}?t=${Date.now()}`;
    video.playbackRate = 1;
    video.play().catch(() => {});
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
  window.demoEvent = (d) => {
    if (d.kind === "pipeline_start") { shown = null; refresh(); }
    else if (d.kind === "session_reset") hide();
    else if (d.kind === "pipeline_demo_video") {
      if (d.state === "rendering") note.textContent = "Rendering the overlay...";
      else if (d.state === "overlay") { note.textContent = ""; show("overlay"); }
      else if (d.state === "failed") note.textContent = "Overlay could not be rendered: " + (d.detail || "");
    }
  };
  window.addEventListener("demo-video-picked", () => { shown = null; refresh(); });
  refresh();
})();
