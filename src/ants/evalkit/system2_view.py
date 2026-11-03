"""The "System 2" tab of the run viewer: the adversarial hardening loop, cycle by cycle.

Reads `<run>/system2.jsonl` (one object per cycle, written by `ants.orchestrator.system2`). The
JavaScript is kept here and spliced into `report.py`'s template, so the viewer's own file only
carries a one-line hook (`system2()` calls `system2View(cycles)`).
"""

JS = r"""
/* ---------- System 2 view (src/ants/evalkit/system2_view.py) ---------- */
(function(){const s=document.createElement("style");s.textContent=`
.s2bar{display:flex;align-items:center;gap:8px}.s2bar i{display:block;height:8px;border-radius:4px;background:var(--acc)}
.s2cat{display:grid;grid-template-columns:90px 1fr 70px;gap:8px;align-items:center;margin:4px 0}
.s2cat .tr{background:var(--code);border-radius:5px;height:14px;position:relative;overflow:hidden}
.s2cat .tr b{position:absolute;left:0;top:0;bottom:0;background:var(--ok);opacity:.55}.s2cat .tr u{position:absolute;top:0;bottom:0;background:var(--bad);opacity:.8;text-decoration:none}
.s2m{border-collapse:separate;border-spacing:2px}.s2m td,.s2m th{padding:0;border:0}.s2m td.c{width:16px;height:16px;border-radius:3px}
.s2m td.p{background:var(--ok);opacity:.75}.s2m td.f{background:var(--bad)}.s2m td.n{background:var(--code)}
.s2m th{font-size:11px;color:var(--mute);font-weight:400;padding:0 6px 0 0;text-align:right;white-space:nowrap}.s2m th.h{text-align:center;padding:0;writing-mode:vertical-rl;transform:rotate(180deg);height:64px}
.s2ban{border:1px solid var(--bad);background:var(--badbg);color:var(--bad);border-radius:12px;padding:10px 14px;margin:0 0 12px}
.s2rule{border-left:3px solid var(--acc);padding:2px 10px;margin:6px 0;background:var(--accbg);border-radius:0 8px 8px 0}
`;document.head.appendChild(s)})();

function s2cell(ok){return `<td class="c ${ok===undefined?"n":ok?"p":"f"}" title="${ok===undefined?"not run":ok?"pass":"fail"}"></td>`}
function s2matrix(rows){
 // rows: [{cycle, decision, inc, cand}] ; columns are cases, in first-seen order
 const cases=[...new Set(rows.flatMap(r=>[...Object.keys(r.inc||{}),...Object.keys(r.cand||{})]))];
 if(!cases.length)return "";
 const head=`<tr><th></th>${cases.map(c=>`<th class="h" title="${esc(c)}">${esc(c.replace(/^c\d+-t\d+-/,""))}</th>`).join("")}</tr>`;
 const line=(label,m)=>`<tr><th>${esc(label)}</th>${cases.map(c=>s2cell(m?m[c]:undefined)).join("")}</tr>`;
 return `<div style="overflow:auto"><table class="s2m">${head}${rows.map(r=>line("cycle "+r.cycle+" incumbent",r.inc)+(r.cand?line("cycle "+r.cycle+" candidate · "+r.decision,r.cand):"")).join("")}</table></div>`}

function s2cats(cycles){
 const by={};
 cycles.flatMap(c=>c.tests||[]).forEach(t=>{const o=by[t.category]??={n:0,f:0,sev:0};o.n++;o.f+=t.success?0:1;o.sev=Math.max(o.sev,t.severity)});
 const names=Object.keys(by).sort((a,b)=>by[b].f/by[b].n-by[a].f/by[a].n||by[b].n-by[a].n);
 const mx=Math.max(1,...names.map(n=>by[n].n));
 return names.map(n=>{const o=by[n];return `<div class="s2cat"><span>${esc(n)}</span><div class="tr" title="${o.f} failed of ${o.n}"><b style="width:${100*(o.n-o.f)/mx}%"></b><u style="left:${100*(o.n-o.f)/mx}%;width:${100*o.f/mx}%"></u></div><span class="muted">${o.f}/${o.n} failed</span></div>`}).join("")||`<span class="muted">no tests yet</span>`}

function s2retrieval(c){
 const r=c.retrieval;if(!r)return "";
 const used=r.used,head=used?chip("retrieval used","ok"):chip("retrieval not used","bad");
 const reason={hit:"a stored correction matched the failure signature",memory_off:"memory is off: the correction cache was not consulted",empty_store:"correction cache is empty: nothing stored yet",no_store_configured:"no correction store configured for this run",no_match:"no admitted correction matched the failure signature (tried L3, then L2, then L1)"}[r.reason]||r.reason||"";
 const qs=(r.queries||[]).map(q=>chip([q.primitive,q.status,q.deviation].filter(Boolean).join(" | "))).join(" ");
 const got=(r.retrieved||[]).map(x=>`<div class="s2rule"><b>${esc(x.correction_id)}</b> ${chip("help "+(x.help_count||0)+" / hurt "+(x.hurt_count||0))} <span class="muted">stored fix for case ${esc(x.trigger_case||"")}</span><div>${esc(x.rule||"")}</div>${x.repair_diff?det("retrieved repair diff (from cache)",`<pre>${esc(x.repair_diff)}</pre>`):""}</div>`).join("");
 const cand=(r.candidates||[]).length?det("candidates considered ("+(r.candidates||[]).length+")",`<table><tr><th>Correction</th><th>Level</th><th>Score</th><th>Eligible</th><th>Rule</th></tr>${(r.candidates||[]).map(x=>`<tr><td><code>${esc(x.correction_id)}</code></td><td>${x.level?"L"+x.level:"-"}</td><td>${x.score}</td><td>${x.eligible?chip("yes","ok"):chip("no")}</td><td class="muted">${esc(x.rule||"")}</td></tr>`).join("")}</table>`):"";
 const wrote=(c.corrections_written||[]).length?`<div class="muted">stored after this cycle: ${c.corrections_written.map(x=>chip(x,"acc")).join(" ")}</div>`:"";
 return `<h4 style="margin:12px 0 4px">2b · Correction retrieval (signature cache)</h4><div>${head} <span class="muted">${esc(reason)}</span></div><div style="margin:4px 0">failure signature ${qs||chip("none")}</div>${got||`<div class="muted">no correction was handed to the generator this cycle.</div>`}${cand}${wrote}`}

function s2cycle(c){
 if(c.escalation)return `<div class="s2ban"><b>Escalate to a human.</b> ${esc(c.escalation.request)} <span class="muted">(stalled ${c.escalation.stalled_cycles} cycles on ${esc(c.escalation.signature)})</span></div>`;
 const dec=c.decision||"?",cls=dec==="accepted"?"ok":dec==="rejected"||dec==="budget_stop"?"bad":"";
 const tests=(c.tests||[]).map(t=>`<tr><td>${chip(t.category,"acc")}</td><td><span class="s2bar"><i style="width:${Math.round(60*t.severity)}px"></i>${t.severity}</span></td><td class="muted">${esc(JSON.stringify(t.params))}</td><td>seed ${t.seed}</td><td>${chip(t.success?"pass":"fail",okc(t.success))}</td></tr>`).join("");
 const cons=(c.constraints_new||[]).map(k=>`<div class="s2rule"><b>${esc(k.constraint_id)}</b> ${chip(k.failure_signature)} <span class="muted">${esc(k.when_to_apply)}</span><div>${esc(k.rule)}</div>${det("evidence",`<pre>${esc((k.evidence||[]).join("\n"))}</pre>`)}</div>`).join("");
 const g=c.gate;
 const gate=g?`<div>${chip("incumbent "+g.incumbent_passes+"/"+g.cases)}→${chip("candidate "+g.candidate_passes+"/"+g.cases,g.accepted?"ok":"bad")} <b>${esc(g.reason)}</b>${g.regressions.length?`<div class="muted">regressed on: ${g.regressions.map(x=>chip(x,"bad")).join("")}</div>`:""}${g.improvements.length?`<div class="muted">fixed: ${g.improvements.map(x=>chip(x,"ok")).join("")}</div>`:""}</div>`:"";
 const cand=c.candidate?`<div class="muted" style="margin:6px 0">candidate program <code>${esc(c.candidate.program)}</code> · ${(c.candidate.tokens||0).toLocaleString()} tokens</div>`:"";
 return `<div class="rail ${cls||""}"><details class="card" open><summary>Cycle ${c.cycle} ${chip(dec.replace("_"," "),cls)}${chip((c.tests||[]).filter(t=>!t.success).length+" of "+(c.tests||[]).length+" tests failed")}${(c.constraints_new||[]).length?chip((c.constraints_new||[]).length+" new constraint(s)","acc"):""}${c.retrieval?chip(c.retrieval.used?"cached fix retrieved":"no cached fix",c.retrieval.used?"ok":"bad"):""}</summary><div class="bd">
 <h4 style="margin:8px 0 4px">1 · Adversary tests the incumbent</h4><table><tr><th>Category</th><th>Severity</th><th>Parameters</th><th>Seed</th><th>Result</th></tr>${tests}</table>
 ${cons?`<h4 style="margin:12px 0 4px">2 · Diagnoser: failures become constraints</h4>${cons}`:""}
 ${s2retrieval(c)}
 ${g?`<h4 style="margin:12px 0 4px">3 · Generator proposes, gate decides</h4>${cand}${gate}`:""}</div></details></div>`}

function system2View(cycles){
 if(!cycles.length)return `<h2>System 2</h2><p class="muted">No <code>system2.jsonl</code> in this run yet (one JSON object per adversary cycle).</p>`;
 const real=cycles.filter(c=>c.tests),tests=real.flatMap(c=>c.tests),fails=tests.filter(t=>!t.success);
 const acc=real.filter(c=>c.decision==="accepted").length,rej=real.filter(c=>c.decision==="rejected").length;
 const tok=real.reduce((a,c)=>a+((c.candidate||{}).tokens||0),0),esc_=cycles.find(c=>c.escalation);
 const stat=(k,v,s="")=>`<div class="stat"><span class="muted">${k}</span><b>${v}</b><span class="muted">${s}</span></div>`;
 const mat=real.filter(c=>c.incumbent_results||c.candidate_results).map(c=>({cycle:c.cycle,decision:c.decision,inc:c.incumbent_results,cand:c.candidate_results}));
 return `<h2 style="margin:0 0 4px">System 2 · adversarial hardening</h2><p class="muted" style="margin:0 0 12px">Each cycle: the adversary tests the incumbent policy, the diagnoser turns failures into constraints, the generator proposes a candidate, and the gate accepts it only if it never does worse than the incumbent on any case seen.</p>
 ${esc_?s2cycle(esc_):""}
 <div class="grid">${stat("cycles",real.length)}${stat("tests run",tests.length,fails.length+" broke the incumbent")}${stat("candidates accepted",acc,rej+" rejected by the gate")}${stat("constraints",real.reduce((a,c)=>a+(c.constraints_new||[]).length,0))}${stat("generator tokens",tok.toLocaleString(),"≈ "+usd(tok))}${stat("correction retrievals",real.filter(c=>(c.retrieval||{}).used).length,real.filter(c=>c.retrieval&&!c.retrieval.used).length+" cycles without a cached fix")}</div>
 <div class="two" style="margin-top:12px"><div class="card pad"><h3 class="t">Where the adversary found failures <span class="muted" style="font-weight:400">· green passed, red failed</span></h3>${s2cats(real)}</div>
 <div class="card pad"><h3 class="t">Cases seen so far, incumbent vs candidate <span class="muted" style="font-weight:400">· green pass, red fail, grey not run</span></h3>${s2matrix(mat)||'<span class="muted">no candidate evaluated yet</span>'}</div></div>
 <h3>Cycles</h3>${real.map(s2cycle).join("")}`}
"""
