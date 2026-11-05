/* ANTS Studio: Adversary | Synthesizer. Both views stay alive: the console (SSE, chat, Stop, mic)
   keeps running underneath while Daniel's page (/adversary/) covers the window in its iframe.
   His page has its own header, with the same switch injected by adversary_view.py, so exactly one
   header and one switch are visible at a time. */
(function () {
  const KEY = "ants-studio-view";
  const frame = document.getElementById("adversary-view");
  let stale = true;
  let scroll = 0;

  function replaying() {
    /* never reload under the video player; a stale Replay refreshes when the user leaves it */
    try {
      const h = frame.contentWindow.location.hash;
      return h === "#replay" || h.startsWith("#a-");
    } catch (e) { return false; }
  }
  function loadFrame(hash) {
    stale = false;
    if (!frame.getAttribute("src")) { frame.setAttribute("src", "/adversary/" + (hash || "")); return; }
    try {
      scroll = frame.contentWindow.scrollY || 0;
      if (hash) frame.contentWindow.location.hash = hash;
      frame.contentWindow.location.reload();
    } catch (e) { frame.setAttribute("src", "/adversary/" + (hash || "")); }
  }
  frame.addEventListener("load", () => {
    try { if (scroll) frame.contentWindow.scrollTo(0, scroll); } catch (e) {}
    scroll = 0;
  });

  function setView(view, hash) {
    if (view !== "adversary") view = "synthesizer";
    document.body.dataset.view = view;
    document.querySelectorAll(".view-switch button").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.view === view));
    });
    try { localStorage.setItem(KEY, view); } catch (e) {}
    if (view === "adversary" && (stale || hash || !frame.getAttribute("src"))) loadFrame(hash);
  }
  window.antsSetView = setView;

  document.querySelectorAll(".view-switch button").forEach((b) => {
    b.addEventListener("click", () => setView(b.dataset.view));
  });

  /* a run wrote new logs: refresh his page if it is on screen and no video is open */
  window.studioEvent = (data) => {
    if (["run_started", "attack_event", "loop_event", "done", "session_reset"].includes(data.kind)) stale = true;
  };
  setInterval(() => {
    if (stale && document.body.dataset.view === "adversary" && !replaying()) loadFrame();
  }, 2000);

  document.getElementById("turns").addEventListener("click", (e) => {
    const link = e.target.closest(".replay-link");
    if (link) setView("adversary", "#a-" + link.dataset.attack);
  });

  let saved = "synthesizer";
  try { saved = localStorage.getItem(KEY) || saved; } catch (e) {}
  setView(saved);
})();
