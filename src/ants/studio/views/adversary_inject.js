/* ANTS Studio only: the switch, the run status and the theme follow the console in the parent. */
(function () {
  const host = window.parent !== window ? window.parent : null;
  document.querySelectorAll(".ants-switch button").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.view === "adversary") return;
    if (host && host.antsSetView) { host.antsSetView(b.dataset.view); return; }
    try { localStorage.setItem("ants-studio-view", b.dataset.view); } catch (e) {}
    location.href = "/";
  }));
  function theme() {
    let t = null;
    try { t = localStorage.getItem("ants-studio-theme"); } catch (e) {}
    if (t === "light") document.documentElement.dataset.theme = "light";
    else delete document.documentElement.dataset.theme;
  }
  theme();
  window.addEventListener("storage", theme);
  if (!host) return;
  const stop = document.getElementById("ants-stop");
  stop.addEventListener("click", () => {
    const b = host.document.getElementById("stop-btn");
    if (b && !b.disabled) b.click();
  });
  setInterval(() => {
    const pill = host.document.getElementById("status-pill");
    if (!pill) return;
    const running = pill.classList.contains("running");
    document.getElementById("ants-run").hidden = !running;
    stop.hidden = !running;
    const hostStop = host.document.getElementById("stop-btn");
    stop.disabled = hostStop.disabled;
    stop.textContent = hostStop.textContent;
    document.getElementById("ants-pill").textContent = pill.textContent;
  }, 1000);
})();
