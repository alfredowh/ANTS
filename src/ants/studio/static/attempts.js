/* Generation attempts in the chat feed, one turn per attempt, from logged files only: why the model
   changed the code, the program changes, the feedback sent back, the rollout's keyframes playing. */
(function () {
  const FRAME_MS = 700;
  const safe = (s) => esc(s == null ? "" : String(s));
  function diffHtml(d) {
    return d.split("\n").map((l) => {
      const c = l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : "";
      return c ? `<span class="${c}">${safe(l)}</span>` : safe(l);
    }).join("\n");
  }
  function body(a) {
    const passed = String(a.success) === "True" || a.success === true;
    const has = a.success !== undefined;
    const media = (a.frames || []).map((f) => "/attempts/media/" + encodeURI(f.src));
    const labels = (a.frames || []).map((f) => f.label);
    return `<div class="att"><b>Attempt ${safe(a.attempt)}</b> ${safe(a.role === "initial" ? "initial program" : "repair")}
      ${has ? `<span class="chipx ${passed ? "ok" : "bad"}">${passed ? "passed" : "failed"}: ${safe(a.reason)}</span>` : `<span class="chipx">rollout running</span>`}
      <span class="chipx">${Number(a.tokens || 0).toLocaleString()} tokens${String(a.from_cache) === "True" ? " (cache " + safe(a.cache_kind) + ")" : ""}</span>
      ${a.why ? `<details open><summary>Why it failed before, and what the model changed</summary><pre>${safe(a.why)}</pre></details>` : ""}
      ${a.diff ? `<details open><summary>Program changes vs attempt ${Number(a.attempt) - 1}</summary><pre>${diffHtml(a.diff)}</pre></details>` : ""}
      ${media.length ? `<details open><summary>Rollout on debug seed ${safe(a.seed)} (keyframes, looping)</summary><figure><img class="att-gif" src="${media[0]}" data-frames='${safe(JSON.stringify(media))}' data-labels='${safe(JSON.stringify(labels))}' alt="rollout keyframes"><figcaption>${safe(labels[0])}</figcaption></figure></details>` : ""}
      ${a.feedback ? `<details><summary>Feedback sent to the model for the next attempt</summary><pre>${safe(JSON.stringify(a.feedback, null, 1))}</pre></details>` : ""}
    </div>`;
  }
  const lastSeen = {};
  function refresh() {
    fetch("/attempts").then((r) => r.json()).then((d) => {
      (d.attempts || []).forEach((a) => {
        const id = `attempt-turn-${a.arm}-${a.attempt}`;
        const html = body(a);
        const el = document.getElementById(id);
        if (lastSeen[id] === html && el) return;
        lastSeen[id] = html;
        if (el) { const open = [...el.querySelectorAll("details")].map((x) => x.open); el.innerHTML = html; el.querySelectorAll("details").forEach((x, i) => { if (open[i] !== undefined) x.open = open[i]; }); return; }
        addTurn("attempt-turn", `<div class="main" id="${id}">${html}</div>`);
      });
    }).catch(() => {});
  }
  window.attemptsEvent = (d) => {
    if (d.kind === "session_reset") { Object.keys(lastSeen).forEach((k) => delete lastSeen[k]); return; }
    if (d.kind === "pipeline_stage" && (d.stage === "generate" || d.stage === "nominal")) refresh();
  };
  setInterval(() => {
    if (document.hidden) return;
    document.querySelectorAll("img.att-gif").forEach((img) => {
      const f = JSON.parse(img.dataset.frames), l = JSON.parse(img.dataset.labels);
      const i = ((+img.dataset.i || 0) + 1) % f.length;
      img.dataset.i = i;
      img.src = f[i];
      const cap = img.parentElement.querySelector("figcaption");
      if (cap) cap.textContent = l[i];
    });
  }, FRAME_MS);
  refresh();
})();
