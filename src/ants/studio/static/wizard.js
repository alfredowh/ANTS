/* Chat commands: /policy-dev <task> (with an optional demo video) and /deploy. The pipeline itself
   is in policy_dev.py; this file only starts it and renders its pipeline_* events. It reuses
   console.js globals (addTurn, esc, setChatStatus, setStatus, setSys, handleError). */
(function () {
  const input = document.getElementById("chat-input");
  const attach = document.getElementById("chat-attach");
  const bar = document.getElementById("chatbar");
  if (!input || !bar) return;

  let video = null; // {path, name}
  let outEl = null, outStage = null, outLines = [];

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    }).then((r) => r.json());
  }
  function userBubble(text) {
    addTurn("chat-turn you", `<div class="tk">you</div><div class="main">${esc(text)}</div>`);
  }
  function agentTurn(title, text, cls) {
    addTurn("chat-turn wizard-turn " + (cls || ""), `<div class="tk">${esc(title)}</div><div class="main">${esc(text)}</div>`);
  }

  /* ---------- chips ---------- */
  const row = document.createElement("div");
  row.className = "chip-row";
  function chipButton(label, title, onClick) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "wizard-chip";
    b.textContent = label;
    b.title = title;
    b.addEventListener("click", onClick);
    row.appendChild(b);
  }
  chipButton("/policy-dev", "Run the whole pipeline: attach a demo video with +, type the task, press Enter", () => {
    input.value = "/policy-dev ";
    input.focus();
    syncAttach();
  });
  chipButton("/deploy", "Save the latest main program (highest accepted version of this session, else the incumbent) to data/deploy/", () => {
    input.value = "/deploy";
    input.focus();
    syncAttach();
  });
  const chosen = document.createElement("span");
  chosen.className = "video-chip";
  chosen.style.display = "none";
  row.appendChild(chosen);
  bar.insertAdjacentElement("afterend", row); // below the chat field

  function renderChosen() {
    chosen.style.display = video ? "" : "none";
    chosen.innerHTML = "";
    if (!video) return;
    const name = document.createElement("span");
    name.textContent = video.name;
    name.title = video.path;
    const x = document.createElement("button");
    x.type = "button";
    x.innerHTML = "&times;";
    x.title = "Remove this video";
    x.addEventListener("click", () => { video = null; renderChosen(); });
    chosen.append(name, x);
  }

  /* ---------- the + button: native dialog on the server, browser picker as a fallback ---------- */
  function syncAttach() {
    const on = input.value.trimStart().toLowerCase().startsWith("/policy-dev");
    attach.disabled = !on;
    attach.classList.toggle("wizard-ask", on && !video);
    attach.title = on ? "Choose the human demo video" : "Click /policy-dev first to attach a demo video";
  }
  input.addEventListener("input", syncAttach);
  syncAttach();

  const picker = document.createElement("input");
  picker.type = "file";
  picker.accept = "video/*,.mkv,.avi,.m4v";
  picker.style.display = "none";
  document.body.appendChild(picker);
  picker.addEventListener("change", () => {
    const f = picker.files[0];
    picker.value = "";
    if (!f) return;
    setChatStatus("Uploading " + f.name + "...", true);
    fetch("/upload", {method: "POST", headers: {"X-Filename": encodeURIComponent(f.name)}, body: f})
      .then((r) => r.json())
      .then((s) => {
        setChatStatus("");
        if (!s.ok) { agentTurn("cannot attach", s.error, "needs"); return; }
        video = {path: s.path, name: s.name};
        renderChosen();
        syncAttach();
      })
      .catch(() => { setChatStatus(""); agentTurn("cannot attach", "Upload failed.", "needs"); });
  });
  attach.addEventListener("click", () => {
    if (attach.disabled) return;
    setChatStatus("Choose the video in the file dialog...", true);
    post("/pick-video", {}).then((r) => {
      setChatStatus("");
      if (r.ok) {
        video = {path: r.path, name: r.name};
        renderChosen();
        syncAttach();
        input.focus();
      } else if (r.fallback) {
        setChatStatus("Native dialog unavailable (" + r.reason + "); the browser picker cannot open at the clips folder.");
        picker.click();
      } else if (r.error) {
        agentTurn("cannot attach", r.error, "needs");
      }
    }).catch(() => { setChatStatus(""); picker.click(); });
  });

  /* ---------- commands ---------- */
  window.wizardHandle = function (message) {
    const text = message.trim();
    const low = text.toLowerCase();
    syncAttachSoon();
    if (low === "/deploy") {
      userBubble(text);
      post("/deploy", {}).then((r) => agentTurn("deploy", r.ok
        ? "Deployed v" + r.version + " to " + r.dir + "/" + r.file + " (also latest.py)."
        : "Deploy failed: " + r.error, r.ok ? "" : "needs"))
        .catch(() => agentTurn("deploy", "Deploy failed: server unreachable.", "needs"));
      return true;
    }
    if (low === "/policy-dev" || low.startsWith("/policy-dev ")) {
      const task = text.slice("/policy-dev".length).trim();
      userBubble(text + (video ? "\n[video: " + video.name + "]" : ""));
      post("/policy-dev", {task, video: video ? video.path : null}).then((r) => {
        if (!r.ok) { agentTurn("cannot start", r.error, "needs"); return; }
        video = null;
        renderChosen();
      }).catch(() => agentTurn("cannot start", "The server did not answer.", "needs"));
      return true;
    }
    return false;
  };
  function syncAttachSoon() { setTimeout(syncAttach, 0); }

  /* ---------- pipeline events, via the console's shared SSE connection ---------- */
  const BADGE = {
    preflight: ["orch", "preflight"],
    extraction: ["sys1", "reading the video"],
    demospec: ["sys1", "building DemoSpec"],
    prompt: ["sys1", "building the prompt"],
    generation: ["sys1", "writing the program (Muse)"],
    nominal: ["sys1", "nominal check"],
    adversary: ["sys2", "attacking"],
  };
  const TITLE = {
    start: "policy-dev", preflight: "1 preflight", extraction: "2 extraction", demospec: "3 DemoSpec",
    prompt: "4 prompt", generation: "5 Synthesizer", nominal: "5 nominal check", adversary: "6 Adversary", finished: "finished",
  };
  function onStage(d) {
    const b = BADGE[d.stage];
    if (b && d.status === "running") {
      for (const id of ["sys1", "sys2", "orch"]) setSys(id, false, "idle");
      setSys(b[0], true, b[1]);
    }
    if (d.status === "command") return; // the exact command is in pipeline.jsonl
    if (d.status === "running" && d.stage !== "start") outEl = null;
    const bad = ["failed", "rejected"].includes(d.status) || (d.stage === "finished" && !["user_stop"].includes(d.status) && d.detail);
    let text = d.detail || d.status;
    if (d.path) text += "\n" + d.path;
    agentTurn(TITLE[d.stage] || d.stage, text, bad ? "needs" : "");
  }
  function onOutput(d) {
    if (!outEl || outStage !== d.stage) {
      outLines = [];
      outStage = d.stage;
      addTurn("chat-turn wizard-turn", `<div class="tk">${esc(TITLE[d.stage] || d.stage)} output</div><div class="main pipeline-out"></div>`);
      const all = document.querySelectorAll(".pipeline-out");
      outEl = all[all.length - 1];
    }
    outLines.push(d.line);
    outEl.textContent = outLines.slice(-5).join("\n");
  }
  window.wizardEvent = (d) => {
    if (d.kind === "pipeline_start") {
      setStatus("running", "running");
      const rb = document.getElementById("run-btn");
      if (rb) rb.disabled = true;
    } else if (d.kind === "pipeline_stage") onStage(d);
    else if (d.kind === "pipeline_output") onOutput(d);
  };

  /* reload during a run: the server still runs it; say so, and keep Stop reachable */
  fetch("/policy-dev").then((r) => r.json()).then((s) => {
    if (s.running && s.current) {
      setStatus("running", "running");
      agentTurn("policy-dev", "A run is in progress: " + s.current.task + "\n" + s.current.run_dir);
    }
  }).catch(() => {});
})();
