/* /policy-dev wizard client. The questions live in docs/studio/skills/policy-dev.json and the
   state machine in policy_wizard.py; this file only renders turns and sends answers. It reuses
   console.js globals (addTurn, esc, setChatStatus). */
(function () {
  let active = false;
  let seen = 0; // history items already shown
  let outTurn = null; // the streamed generation-output turn
  let outLines = [];

  const input = document.getElementById("chat-input");
  const attach = document.getElementById("chat-attach");
  const bar = document.getElementById("chatbar");
  if (!input || !bar) return;

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
  function agentTurn(text, cls) {
    addTurn("chat-turn wizard-turn " + (cls || ""), `<div class="tk">${cls === "needs" ? "cannot launch" : "policy-dev"}</div><div class="main">${esc(text)}</div>`);
  }

  function render(state, includeUser) {
    const hist = state.history || [];
    for (; seen < hist.length; seen++) {
      const m = hist[seen];
      if (m.role === "agent") agentTurn(m.text);
      else if (includeUser) userBubble(m.text);
    }
    active = state.status === "active";
    chip.textContent = active ? "cancel wizard" : "/policy-dev";
    chip.title = active ? "Stop the policy-dev wizard" : "Run the policy development loop (type /policy-dev setup for the guided questions)";
    const askUpload = !!state.awaiting_upload;
    attach.disabled = !askUpload;
    attach.classList.toggle("wizard-ask", askUpload);
    attach.title = askUpload ? "Attach the demo video" : "Attach a video (during /policy-dev)";
    if (state.status === "confirmed") setChatStatus("Wizard confirmed - launching.", true);
    else if (!active) setChatStatus("");
  }

  const chip = document.createElement("button");
  chip.type = "button";
  chip.className = "wizard-chip";
  chip.textContent = "/policy-dev";
  chip.addEventListener("click", () => {
    if (active) {
      post("/wizard", {action: "cancel"}).then((s) => render(s, false));
      return;
    }
    input.value = "/policy-dev";
    input.focus(); // press Enter to start
  });
  bar.insertAdjacentElement("afterend", chip); // below the chat field

  const picker = document.createElement("input");
  picker.type = "file";
  picker.accept = "video/*,.mkv,.avi,.m4v";
  picker.style.display = "none";
  document.body.appendChild(picker);
  attach.addEventListener("click", () => { if (!attach.disabled) picker.click(); });
  picker.addEventListener("change", () => {
    const f = picker.files[0];
    picker.value = "";
    if (!f) return;
    userBubble("[attaching " + f.name + "]");
    setChatStatus("Uploading " + f.name + "...", true);
    fetch("/upload", {method: "POST", headers: {"X-Filename": encodeURIComponent(f.name)}, body: f})
      .then((r) => r.json())
      .then((s) => {
        if (s.ok === false) { agentTurn(s.error, "needs"); setChatStatus(""); return; }
        render(s, false);
        setChatStatus("");
      })
      .catch(() => { agentTurn("Upload failed.", "needs"); setChatStatus(""); });
  });

  window.wizardHandle = function (message) {
    const text = message.trim();
    const low = text.toLowerCase();
    if (low === "/policy-dev" || low === "/policy-dev run") {
      userBubble(text);
      if (window.startPolicyLoop) window.startPolicyLoop(); // asks for confirmation, then runs the loop
      return true;
    }
    if (low.startsWith("/policy-dev")) { // "/policy-dev setup": the guided questions
      userBubble(text);
      seen = 0;
      post("/wizard", {action: "start"}).then((s) => render(s, false));
      return true;
    }
    if (!active) return false;
    userBubble(text);
    post("/wizard", {action: "message", message: text}).then((s) => render(s, false));
    return true;
  };

  /* generation progress arrives via the console's shared SSE connection (wizard_* kinds only) */
  window.wizardEvent = (d) => {
    if (!d.kind || !d.kind.startsWith("wizard_")) return;
    if (d.kind === "wizard_needs") agentTurn(d.message, "needs");
    else if (d.kind === "wizard_launch") {
      outLines = [];
      agentTurn("Generation started:\n" + d.command.join(" "));
      addTurn("chat-turn wizard-turn", `<div class="tk">generation output</div><div class="main" id="wizard-out">...</div>`);
      outTurn = document.getElementById("wizard-out");
    } else if (d.kind === "wizard_output" && outTurn) {
      outLines.push(d.line);
      outTurn.textContent = outLines.slice(-40).join("\n");
    } else if (d.kind === "wizard_generation_done") {
      agentTurn("Generation finished (exit " + d.returncode + "). Output: " + d.out, d.returncode ? "needs" : "");
    } else if (d.kind === "wizard_finished") {
      setChatStatus("");
      fetch("/wizard").then((r) => r.json()).then((s) => render(s, false));
    }
  };

  /* reload: re-render an unfinished wizard from the server */
  fetch("/wizard").then((r) => r.json()).then((s) => {
    if (s.status === "active") render(s, true);
  }).catch(() => {});
})();
