/* Chat commands: /policy-dev <task> (with an optional demo video) and /deploy. The pipeline itself
   is in policy_dev.py; this file only starts it and renders its pipeline_* events. It reuses
   console.js globals (addTurn, esc, openModal, closeModal, setChatStatus, setStatus, setSys). */
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
  chipButton("/policy-dev", "Run the whole pipeline: attach a demo video with +, type the task, press Enter, then choose the settings", () => {
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
    attach.disabled = false; // always clickable: choosing a video starts a /policy-dev message
    attach.classList.toggle("wizard-ask", on && !video);
    attach.title = "Choose the human demo video for /policy-dev";
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
    if (!input.value.trimStart().toLowerCase().startsWith("/policy-dev")) {
      input.value = "/policy-dev " + input.value.trimStart();
      syncAttach();
    }
    setChatStatus("Choose the video in the file dialog...", true);
    post("/pick-video", {}).then((r) => {
      setChatStatus("");
      if (r.ok) {
        video = {path: r.path, name: r.name};
        renderChosen();
        window.dispatchEvent(new CustomEvent("demo-video-picked"));
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
    if (low === "/continue") {
      userBubble(text);
      resumeRun();
      return true;
    }
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
      if (!task) {
        agentTurn("policy-dev", "Type the task after /policy-dev, for example: /policy-dev put the bowl on the plate", "needs");
        input.value = "/policy-dev ";
        return true;
      }
      openSettings(task);
      return true;
    }
    return false;
  };
  function syncAttachSoon() { setTimeout(syncAttach, 0); }

  /* ---------- the settings dialog; its fields and defaults come from the skill file ---------- */
  function fieldHtml(key, f) {
    const help = f.help ? `<div class="set-help">${esc(f.help)}</div>` : "";
    let control;
    if (f.type === "bool") control = `<input type="checkbox" id="set-${key}"${f.default ? " checked" : ""}>`;
    else if (f.type === "int") control = `<input type="number" id="set-${key}" value="${f.default}" min="${f.min}" max="${f.max}">`;
    else if (f.type === "choice") control = `<select id="set-${key}">` + f.choices.map((c) => `<option value="${esc(c.value)}"${c.value === f.default ? " selected" : ""}>${esc(c.label)}</option>`).join("") + "</select>";
    else control = `<input type="text" id="set-${key}" value="${esc(f.default || "")}" placeholder="path to a .py file"> <button class="btn sm" id="set-browse" type="button">Browse</button>`;
    return `<div class="set-row" id="row-${key}"><label for="set-${key}">${esc(f.label)}</label><div>${control}${help}</div></div>`;
  }
  function openSettings(task) {
    fetch("/policy-dev").then((r) => r.json()).then((info) => {
      const spec = info.settings, budget = info.budget;
      openModal(`<h3>Policy development run</h3>
        <div class="sub">${esc(task)}<br>Video: ${esc(video ? video.name : "none (no-demo run)")}</div>
        ${Object.keys(spec).map((k) => fieldHtml(k, spec[k])).join("")}
        <div class="set-note" id="set-note"></div>
        <div class="set-error" id="set-error"></div>
        <div class="set-actions"><button class="btn" id="set-cancel" type="button">Cancel</button> <button class="btn" id="set-run" type="button">Run</button></div>`);
      // dismissing the dialog keeps what was typed, so nothing has to be retyped
      modalOnClose = () => { input.value = "/policy-dev " + task; syncAttach(); input.focus(); };
      document.getElementById("set-cancel").addEventListener("click", closeModal);
      const el = (k) => document.getElementById("set-" + k);
      function refresh() {
        const synth = el("synthesizer").checked, adv = el("adversary").checked;
        document.getElementById("row-main_script").style.display = synth ? "none" : "";
        document.getElementById("row-max_retries").style.display = synth ? "" : "none";
        document.getElementById("row-token_cap").style.display = synth ? "" : "none";
        for (const k of ["pause_after_v0", "strategy", "attacks", "seeds", "spark"]) document.getElementById("row-" + k).style.display = adv ? "" : "none";
        document.getElementById("row-spark_token_cap").style.display = adv && el("spark").checked ? "" : "none";
        const cap = +el("token_cap").value || 0;
        const usd = (cap / 1e6 * budget.usd_per_million_tokens).toFixed(2);
        const calls = (+el("max_retries").value || 0) + 1 + (adv ? (+el("attacks").value || 0) : 0);
        const need = calls * budget.tokens_per_call_estimate;
        let note = synth
          ? `Worst case about $${usd} at the cap (${cap.toLocaleString()} tokens). Up to ${calls} calls, about ${need.toLocaleString()} tokens.`
          : "No Muse tokens: the script is attacked and reported on, nothing is rewritten.";
        const over = synth && need > cap - budget.one_call_headroom_tokens;
        if (over) note += " That can pass the cap; the run then ends as a budget stop.";
        const n = document.getElementById("set-note");
        n.textContent = note;
        n.classList.toggle("warn", over);
        const both = !synth && !adv;
        document.getElementById("set-error").textContent = both ? "Both modules are off, so there is nothing to run." : "";
        document.getElementById("set-run").disabled = both;
      }
      for (const k of Object.keys(spec)) el(k).addEventListener("input", refresh);
      refresh();
      document.getElementById("set-browse").addEventListener("click", () => {
        post("/pick-script", {}).then((r) => {
          if (r.ok) el("main_script").value = r.path;
          else if (!r.cancelled) document.getElementById("set-error").textContent = (r.reason || r.error) + " Type the path instead.";
        });
      });
      document.getElementById("set-run").addEventListener("click", () => {
        const settings = {};
        for (const k of Object.keys(spec)) settings[k] = spec[k].type === "bool" ? el(k).checked : el(k).value;
        post("/policy-dev", {task, video: video ? video.path : null, settings}).then((r) => {
          if (!r.ok) { document.getElementById("set-error").textContent = r.error; return; }
          modalOnClose = null;
          closeModal();
          userBubble("/policy-dev " + task + (video ? "\n[video: " + video.name + "]" : ""));
          video = null;
          renderChosen();
        }).catch(() => { document.getElementById("set-error").textContent = "The server did not answer."; });
      });
    }).catch(() => agentTurn("cannot start", "The server did not answer.", "needs"));
  }

  /* ---------- pipeline events, via the console's shared SSE connection ---------- */
  const BADGE = {
    video: "sys1", extract: "sys1", demospec: "sys1", prompt: "sys1", generate: "sys1", nominal: "sys1",
    attack: "sys2", diagnose: "sys2", rewrite: "sys1", gate: "orch", deploy: "orch",
  };
  // the loop's own events already draw turns for these
  const LOOP_STAGES = ["attack", "diagnose", "rewrite", "gate"];
  function onStage(d) {
    if (d.status === "started") {
      for (const id of ["sys1", "sys2", "orch"]) setSys(id, false, "idle");
      setSys(BADGE[d.stage], true, d.stage);
      outEl = null;
    }
    if (LOOP_STAGES.includes(d.stage)) return;
    let text = d.detail || d.status;
    if (d.path) text += "\n" + d.path;
    agentTurn(d.stage + " " + d.status, text, d.status === "failed" ? "needs" : "");
  }
  /* the hold after candidate v0: the run continues only from here or from /continue */
  function showReview(program) {
    if (document.getElementById("review-continue")) return;
    addTurn("chat-turn wizard-turn", `<div class="tk">your call</div><div class="main">Candidate v0 is ready${program ? " (" + esc(program) + ")" : ""}. It passed its nominal seed; its rollout is playing on the right. Nothing is being spent while this waits.<div class="review-actions"><button class="btn sm" id="review-continue" type="button">Continue to the Adversary</button></div></div>`);
    setStatus("running", "waiting for you");
    document.getElementById("review-continue").addEventListener("click", resumeRun);
  }
  function resumeRun() {
    const b = document.getElementById("review-continue");
    if (b) { b.disabled = true; b.textContent = "Continuing..."; }
    post("/policy-dev/continue", {}).then((r) => {
      if (!r.ok && b) { b.textContent = r.error; return; }
      if (b) b.textContent = "Continued";
      setStatus("running", "running");
    });
  }
  fetch("/policy-dev").then((r) => r.json()).then((i) => { if (i.waiting) showReview(); }).catch(() => {});

  function onNote(d) {
    if (d.status === "ok" && d.note === "preflight") return;
    const bad = d.note === "finished" && d.status !== "user_stop" && d.status !== "deployed";
    let text = d.detail || d.status;
    if (d.path) text += "\n" + d.path;
    agentTurn(d.note, text, bad ? "needs" : "");
  }
  function onOutput(d) {
    if (!outEl || outStage !== d.stage) {
      outLines = [];
      outStage = d.stage;
      addTurn("chat-turn wizard-turn", `<div class="tk">${esc(d.stage)} output</div><div class="main pipeline-out"></div>`);
      const all = document.querySelectorAll(".pipeline-out");
      outEl = all[all.length - 1];
    }
    outLines.push(d.line);
    if (outLines.length > 5000) outLines.shift();
    outEl.textContent = outLines.join("\n");
    // clamped to 5 lines, this one follows the newest lines; Show more opens the whole output
    if (!outEl.closest(".turn").classList.contains("expanded")) outEl.scrollTop = outEl.scrollHeight;
  }
  window.wizardEvent = (d) => {
    if (d.kind === "session_reset") {
      video = null;
      runTokenCap = null;
      renderChosen();
      syncAttach();
    } else if (d.kind === "pipeline_start") {
      setStatus("running", "running");
      runTokenCap = (d.settings && d.settings.synthesizer && d.settings.token_cap) || null;
      hideBanner();
      document.getElementById("incumbent-name").textContent = "task: " + d.task;
    } else if (d.kind === "pipeline_wait") {
      showReview(d.program);
    } else if (d.kind === "pipeline_stage") onStage(d);
    else if (d.kind === "pipeline_note") onNote(d);
    else if (d.kind === "pipeline_output") onOutput(d);
  };

  /* reload during a run: the server still runs it; say so, and keep Stop reachable */
  fetch("/policy-dev").then((r) => r.json()).then((s) => {
    if (s.running) setStatus("running", "running");
    if (s.running && s.current) {
      agentTurn("policy-dev", "A run is in progress: " + s.current.task + "\n" + s.current.run_dir);
    }
  }).catch(() => {});
})();
