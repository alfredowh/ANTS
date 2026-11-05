"""The experiment tabs of the run viewer: About (summary, contents, abbreviations), Results (variant by
scene level) and Scene (top and side view of a scene with shapes, relations, the arm as cuRobo
spheres, the path of a run and its contact events).

Reads `D.config.experiment` (from `<run>/config.json`), `D.scenes` (from `<run>/scenes/*.json`) and
per sample `s.exp` (group, variant, level, summary) and `s.exp.overlay` (from `overlay.json`). The
JavaScript is spliced into `report.py`'s template, like `system2_view.py`.
"""

JS = r"""
/* ---------- experiment views (src/ants/evalkit/scene_view.py) ---------- */
(function(){const s=document.createElement("style");s.textContent=`
.xh{margin:0 0 4px;font-size:22px}.xlede{max-width:78ch;margin:0 0 10px}
.xg{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin:0 0 12px}.xg>.card{margin:0}
.xc{border-radius:10px;padding:8px 10px;cursor:pointer;display:flex;flex-direction:column;gap:1px;font-size:12px;border:1px solid var(--line);min-width:140px}
.xc b{font-size:13px}.xc.ok{background:var(--okbg);border-color:var(--ok)}.xc.bad{background:var(--badbg);border-color:var(--bad)}.xc.warn{background:var(--accbg);border-color:var(--acc)}
.xc:hover{filter:brightness(.97)}.xc.none{background:var(--code);cursor:default;color:var(--mute)}
table.xt td,table.xt th{padding:6px 8px}.xt td.v{font-weight:600;white-space:nowrap}
.xk{display:inline-block;min-width:44px;font:600 12px ui-monospace,Menlo,Consolas,monospace}
.xbar{height:8px;border-radius:4px;background:var(--acc);display:inline-block;vertical-align:middle;margin-right:6px}
.xbar.r{background:var(--bad)}
.xctl{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin:0 0 10px}.xctl label{display:inline-flex;gap:5px;align-items:center;font-size:13px}
.xmaps{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1fr);gap:12px;align-items:start}
@media(max-width:1000px){.xmaps{grid-template-columns:1fr}}
.xmap svg{width:100%;height:auto;display:block;background:var(--panel);border:1px solid var(--line);border-radius:12px}
.xmap svg text{fill:var(--ink);font-size:11px;font-family:inherit}.xmap svg text.m{fill:var(--mute)}
.xleg{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:12px;color:var(--mute);margin:6px 0}.xleg i{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-2px;margin-right:4px}
.xmini svg{width:100%;height:auto;display:block}
.xnote{border-left:4px solid var(--acc);background:var(--accbg);padding:8px 12px;border-radius:0 8px 8px 0;margin:0 0 10px}
.xnote.w{border-color:var(--bad);background:var(--badbg)}
`;document.head.appendChild(s)})();

const EXP=()=>(D.config&&D.config.experiment)||null;
const xCell=(g,v,l)=>D.samples.find(s=>s.exp&&s.exp.group===g&&s.exp.variant===v&&s.exp.level===l);
const xSum=s=>(s&&s.exp&&s.exp.summary)||{};
const xLv=()=>Object.keys((D.config&&D.config.levels)||D.scenes||{});
const xNum=n=>(n==null?"–":(+n).toLocaleString());

/* ---------- About ---------- */
function expAbout(){
 const E=EXP();if(!E)return "<p>This run has no experiment description.</p>";
 const gv=D.config.g_variants||{},ev=D.config.e_variants||{},vd=E.variants||{};
 const tok=D.samples.reduce((a,s)=>a+s.tokens_new,0);
 const done=D.samples.filter(s=>s.exp).length;
 const rows=(obj,g)=>Object.entries(obj).map(([k,n])=>`<tr><td class="v">${esc(k)}</td><td>${esc(typeof n==="string"?n:n[0])}</td><td>${esc((vd[k]||[])[1]||"")}</td></tr>`).join("");
 const lv=xLv().map(l=>{const L=D.config.levels[l]||{};return `<div class="card pad"><b>${esc(l)} · ${esc(L.title||"")}</b><div class="xmini">${sceneSVG(l,{small:true})}</div><p class="muted" style="margin:6px 0 0">${esc(L.desc||"")}</p></div>`}).join("");
 return `<h2 class="xh">${esc(E.title)}</h2>
 <p class="xlede">${esc(E.summary)}</p>
 <div class="xnote"><b>Question.</b> ${esc(E.question)}</div>
 <div class="bar">${chip(done+" runs finished","ok")}${chip(xNum(tok)+" new tokens")}${chip("≈ "+usd(tok),"acc")}${chip("model "+(D.config.model||"?"))}${chip("temperature "+(D.config.temperature||"?"))}${chip("one clip: 233859, seed "+(D.config.debug_seed||"?"))}</div>
 <h3>Contents</h3>
 <div class="xg"><div class="card pad"><h3 class="t">G · the first program (what the prompt says about the scene)</h3><table class="xt"><tr><th>id</th><th>name</th><th>the model is told</th></tr>${rows(gv)}</table></div>
 <div class="card pad"><h3 class="t">E · one repair (what the repair message adds)</h3><table class="xt"><tr><th>id</th><th>name</th><th>the model is told</th></tr>${rows(ev)}</table></div></div>
 <h3>Scene levels</h3><div class="xg">${lv}</div>
 <h3>How to read the results</h3><div class="card pad"><ul style="margin:0;padding-left:18px">${(E.how_to_read||[]).map(t=>`<li>${esc(t)}</li>`).join("")}</ul></div>
 <h3>Abbreviations</h3><div class="card pad"><table class="xt"><tr><th>term</th><th>meaning</th></tr>${(E.glossary||[]).map(g=>`<tr><td class="v">${esc(g[0])}</td><td>${esc(g[1])}</td></tr>`).join("")}</table></div>
 <h3>Limits of this run</h3><div class="xnote w"><ul style="margin:0;padding-left:18px">${(E.caveats||[]).map(t=>`<li>${esc(t)}</li>`).join("")}</ul></div>`}

/* ---------- Results ---------- */
function xCellHtml(s){
 if(!s)return `<div class="xc none">not run yet</div>`;
 const a=s.attempts[0];if(!a)return `<div class="xc none">${esc(s.stopped||"no attempt")}</div>`;
 const sm=xSum(s),stalls=(sm.failed_calls||[]).length,blk=sm.blocked_steps||0,cls=a.success?"ok":blk>0?"bad":"warn";
 return `<div class="xc ${cls}" onclick="show('${s.id}')" title="open the full trace"><b>${a.success?"✓ success":"✗ failed"}</b><span>${stalls} stalled call${stalls===1?"":"s"}</span><span>${blk} steps blocked</span><span class="muted">${xNum(sm.reasoning_tokens)} reasoning tok</span></div>`}
function expResults(){
 const E=EXP();if(!E)return "<p>No experiment description in this run.</p>";
 const gv=Object.keys(D.config.g_variants||{}),ev=Object.keys(D.config.e_variants||{}),L=xLv();
 const base=l=>xSum(xCell("G","S0",l));
 const gRows=gv.map(v=>`<tr><td class="v">${v}<div class="muted" style="font-weight:400">${esc(D.config.g_variants[v])}</div></td>${L.map(l=>`<td>${xCellHtml(xCell("G",v,l))}</td>`).join("")}</tr>`).join("");
 const eRows=ev.map(v=>{const s=xCell("E",v,"L1"),sm=xSum(s),a=s&&s.attempts[0];
  return `<tr class="${s?"row":""}" ${s?`onclick="show('${s.id}')"`:""}><td class="v">${v}<div class="muted" style="font-weight:400">${esc(D.config.e_variants[v])}</div></td>
  <td>${a?chip(a.success?"success":"failed",okc(a.success)):"<span class=muted>not run yet</span>"}</td><td>${a?(sm.failed_calls||[]).length:"–"}</td><td>${a?xNum(sm.blocked_steps):"–"}</td>
  <td>${a?(sm.mentions_rack?chip("names the rack","ok"):chip("no mention","")):"–"}</td><td>${a?xNum(sm.reasoning_tokens)+" / "+xNum(sm.completion_tokens):"–"}</td></tr>`}).join("");
 const sumRows=gv.map(v=>{const ss=L.map(l=>xCell("G",v,l)).filter(Boolean),n=ss.length;if(!n)return "";
  const ok=ss.filter(s=>s.attempts[0]&&s.attempts[0].success).length,st=ss.reduce((a,s)=>a+(xSum(s).failed_calls||[]).length,0),bl=ss.reduce((a,s)=>a+(xSum(s).blocked_steps||0),0),
   better=L.filter(l=>{const s=xCell("G",v,l),b=xCell("G","S0",l);return s&&b&&v!=="S0"&&(xSum(s).failed_calls||[]).length<(xSum(b).failed_calls||[]).length}).length,
   rt=ss.reduce((a,s)=>a+(xSum(s).reasoning_tokens||0),0)/n,mx=1500;
  return `<tr><td class="v">${v}</td><td>${ok} / ${n}</td><td>${st}</td><td><span class="xbar r" style="width:${Math.min(120,bl/10)}px"></span>${bl}</td><td>${v==="S0"?"baseline":better+" of "+n}</td><td><span class="xbar" style="width:${Math.min(120,rt/250)}px"></span>${xNum(Math.round(rt))}</td></tr>`}).join("");
 return `<h2 class="xh">Results</h2><p class="xlede">Each cell is one run (temperature ${esc(D.config.temperature||"0.2")}). Green: the task succeeded. Red: it failed and the hand was blocked by an object. Blue: it failed without a blocking contact (another cause). Click a cell for the prompt, reply, program, rollout and video.</p>
 <h3>G · the first program, by scene level</h3>
 <div class="card pad" style="overflow:auto"><table class="xt"><tr><th>variant</th>${L.map(l=>`<th>${l} · ${esc((D.config.levels[l]||{}).title||"")}</th>`).join("")}</tr>${gRows}</table></div>
 <h3>G · summary over the levels run so far</h3>
 <div class="card pad" style="overflow:auto"><table class="xt"><tr><th>variant</th><th>solved</th><th>stalled calls</th><th>steps blocked</th><th>levels with fewer stalls than S0</th><th>mean reasoning tokens</th></tr>${sumRows||"<tr><td colspan=6 class=muted>no G run finished yet</td></tr>"}</table>
 <p class="muted" style="margin:6px 0 0">With one run per cell this is a pattern to look at, not a test. Fewer stalls and fewer blocked steps than S0, in more than one level, is the signal worth trusting.</p></div>
 <h3>E · one repair of the failed attempt 2 (scene L1)</h3>
 <div class="card pad" style="overflow:auto"><table class="xt"><tr><th>variant</th><th>result</th><th>stalled calls</th><th>steps blocked</th><th>its WHY note names the rack</th><th>reasoning / output tokens</th></tr>${eRows}</table>
 <p class="muted" style="margin:6px 0 0">Reference: the failed program being repaired had 4 stalled calls and 477 blocked steps (hand on the wine rack).</p></div>${xA0()}${xA3()}`}

function xA0(){const a=D.a0;if(!a||!a.length)return "";
 const rows=a.map(x=>{const b=(x.blocking||[]).map(e=>chip(e.part+" → "+e.object+" · "+e.n_steps+" steps · "+e.fn_mean+" N","bad")).join("");
  return `<tr><td>${esc(x.clip)}</td><td>a${x.attempt}</td><td>${x.error?chip("replay failed","bad"):chip(x.success?"success":"failed",okc(x.success))}</td><td>${x.error?"–":(x.failed_calls||[]).length}</td><td>${x.error?"–":xNum(x.blocked_steps)}</td><td>${x.error?esc(x.error):(b||(((x.failed_calls||[]).length)?chip("stalled, no blocking contact (another cause)","acc"):"<span class=muted>no stall</span>"))}</td></tr>`}).join("");
 const st=a.filter(x=>!x.error&&(x.failed_calls||[]).length),bl=st.filter(x=>(x.blocking||[]).length);
 return `<h3>A0 · what blocked the stalls of the 15 exp03 programs (replayed with the contact log)</h3><div class="card pad" style="overflow:auto"><div class="xnote"><b>${bl.length} of ${st.length}</b> programs that stalled had a blocking contact with an object they never looked at (the wine rack or the wooden cabinet); ${st.length-bl.length} stalled without one.</div><table class="xt"><tr><th>clip</th><th>attempt</th><th>result</th><th>stalled calls</th><th>steps blocked</th><th>blocked by</th></tr>${rows}</table></div>`}
function xA3(){const a=D.a3;if(!a)return "";
 const lv=Object.keys(a).map(l=>{const rows=a[l];if(!Array.isArray(rows))return `<div class="card pad"><b>${esc(l)}</b><p class="muted">${esc(rows.error||"no data")}</p></div>`;
  return `<div class="card pad"><b>${esc(l)}${(D.config.levels&&D.config.levels[l])?" · "+esc(D.config.levels[l].title):""}</b><table class="xt"><tr><th>object</th><th>centre error</th><th>seen size (cm)</th><th>true size (cm)</th></tr>${rows.map(r=>r.ok?`<tr><td>${esc(r.object)}</td><td>${chip(r.centre_err_xy_cm+" cm",r.centre_err_xy_cm>10?"bad":r.centre_err_xy_cm>3?"acc":"ok")}</td><td class="mono">${r.seen_size_cm.join(" × ")}</td><td class="mono">${r.truth_size_cm.join(" × ")}</td></tr>`:`<tr><td>${esc(r.object)}</td><td colspan=3>${chip("not found","bad")}</td></tr>`).join("")}</table></div>`}).join("");
 return `<h3>A3 · does ASPIRE's own perception find the objects? (SAM 3 text mask + depth, agent-view camera, compared with the simulator)</h3><p class="muted">Centre error is in the horizontal plane. The camera sees only the visible side, so a few cm is expected. Green: under 3 cm, blue: 3 to 10 cm, red: over 10 cm.</p><div class="xg" style="grid-template-columns:repeat(auto-fit,minmax(460px,1fr))">${lv}</div>`}


function expChips(s){const sm=xSum(s),a=s.attempts[0],ev=(sm.blocking||[]);
 return chip((s.exp.group==="G"?"G · first program":"E · repair")+" · "+s.exp.variant,"acc")+chip("scene "+s.exp.level)+(a?chip(a.success?"success":"failed",okc(a.success)):"")+chip((sm.failed_calls||[]).length+" stalled calls")+chip((sm.blocked_steps||0)+" steps blocked",sm.blocked_steps?"bad":"")+chip((sm.reasoning_tokens||0).toLocaleString()+" reasoning tokens")
 +ev.map(e=>chip(e.part+" on "+e.object+" · "+e.n_steps+" steps · "+e.fn_mean+" N","bad")).join("")}

/* ---------- Scene ---------- */
const XV={lvl:"",run:"",step:0,shape:"detail",lay:{rel:true,arm:true,path:true,ref:true,contact:true}};
const XC={bg:"var(--panel)"};
function xv(){const L=xLv();if(!XV.lvl||!L.includes(XV.lvl))XV.lvl=L[0]||"";return (D.scenes||{})[XV.lvl]}
function xOverlay(){const s=smp(XV.run);return s&&s.exp&&s.exp.overlay}
const TX={x0:0.1,x1:1.0,y0:-0.45,y1:0.5,S:620,M:20};
const tx=(y)=>TX.M+(TX.y1-y)*TX.S,ty=(x)=>TX.M+(TX.x1-x)*TX.S;
const SZ={z0:-0.03,z1:0.52,S:620,M:20};
const sx=(x)=>SZ.M+(x-TX.x0)*SZ.S,sz=(z)=>SZ.M+(SZ.z1-z)*SZ.S;
function xFlagged(){const o=xOverlay();return new Set(((o&&o.events)||[]).filter(e=>e.blocking).map(e=>e.object))}
function xArmFrame(){const o=xOverlay();if(!o||!o.arm||!o.arm.length)return null;let f=o.arm[0];for(const a of o.arm){if(a.step<=XV.step)f=a}return f}
function sceneSVG(lvl,opt={}){
 const S=(D.scenes||{})[lvl];if(!S)return "<div class='muted'>no scene data</div>";
 const small=!!opt.small,V=S.view,flag=small?new Set():xFlagged(),detail=XV.shape==="detail"||small;
 const top=[],side=[];
 const col=o=>o.task?"var(--acc)":o.label==="wine rack"?"var(--s2)":"var(--mute)";
 for(const o of V.objects){
  const c=col(o),f=flag.has(o.label),st=f?"var(--bad)":c,sw=f?3:1.2;
  if(o.profile&&detail){
   const r=Math.max(...o.profile.rings.map(q=>q[1])),ax=o.profile.axis;
   top.push(`<circle cx="${tx(ax[1])}" cy="${ty(ax[0])}" r="${r*TX.S}" fill="${c}" fill-opacity=".14" stroke="${st}" stroke-width="${sw}"><title>${esc(o.label)}: round, outer radius ${(r*100).toFixed(1)} cm</title></circle><circle cx="${tx(ax[1])}" cy="${ty(ax[0])}" r="2.5" fill="${st}"/>`);
   const z0=o.aabb[0][2],pts=[];o.profile.rings.forEach(q=>pts.push([ax[0]+q[1],z0+q[0]]));[...o.profile.rings].reverse().forEach(q=>pts.push([ax[0]-q[1],z0+q[0]]));
   side.push(`<polygon points="${pts.map(p=>sx(p[0])+","+sz(p[1])).join(" ")}" fill="${c}" fill-opacity=".2" stroke="${st}" stroke-width="${sw}"><title>${esc(o.label)} (radius profile)</title></polygon>`);
  }else{
   const bx=detail&&o.boxes.length>1&&o.boxes.length<=12?o.boxes:[o.aabb];
   bx.forEach(b=>{top.push(`<rect x="${tx(b[1][1])}" y="${ty(b[1][0])}" width="${(b[1][1]-b[0][1])*TX.S}" height="${(b[1][0]-b[0][0])*TX.S}" fill="${c}" fill-opacity="${bx.length>1?.18:.16}" stroke="${st}" stroke-width="${bx.length>1?Math.max(.8,sw-1):sw}"><title>${esc(o.label)}</title></rect>`);
    side.push(`<rect x="${sx(b[0][0])}" y="${sz(b[1][2])}" width="${(b[1][0]-b[0][0])*SZ.S}" height="${Math.max(1.2,(b[1][2]-b[0][2])*SZ.S)}" fill="${c}" fill-opacity="${bx.length>1?.22:.16}" stroke="${st}" stroke-width="${bx.length>1?Math.max(.8,sw-1):sw}"><title>${esc(o.label)}</title></rect>`)});
  }
  if(!small){const a=o.aabb,cx=(a[0][1]+a[1][1])/2,cy=(a[0][0]+a[1][0])/2;top.push(`<text x="${tx(cx)}" y="${ty(a[1][0])-4}" text-anchor="middle">${esc(o.label)}</text>`);side.push(`<text x="${sx(cy)}" y="${sz(a[1][2])-4}" text-anchor="middle">${esc(o.label)}</text>`)}
 }
 const cen=l=>{const o=V.objects.find(q=>q.label===l);if(!o)return null;const a=o.aabb;return [(a[0][0]+a[1][0])/2,(a[0][1]+a[1][1])/2,(a[0][2]+a[1][2])/2]};
 if(!small&&XV.lay.rel){for(const r of V.relations){if(r.kind==="supported_by"||(r.kind!=="touching"&&r.gap_m>0.05))continue;const a=cen(r.a),b=cen(r.b);if(!a||!b)continue;const t=r.kind==="touching";
   top.push(`<line x1="${tx(a[1])}" y1="${ty(a[0])}" x2="${tx(b[1])}" y2="${ty(b[0])}" stroke="${t?"var(--bad)":"var(--mute)"}" stroke-width="${t?2.4:1}" stroke-dasharray="${t?"":"4 3"}" opacity=".8"><title>${esc(r.a)} – ${esc(r.b)}: ${r.kind}, gap ${(Math.max(0,r.gap_m)*1000).toFixed(0)} mm</title></line><text class="m" x="${(tx(a[1])+tx(b[1]))/2+3}" y="${(ty(a[0])+ty(b[0]))/2-3}">${(Math.max(0,r.gap_m)*1000).toFixed(0)} mm</text>`)}}
 if(!small&&XV.lay.ref&&S.reference_path){const p=S.reference_path;top.push(`<polyline points="${p.map(q=>tx(q[1])+","+ty(q[0])).join(" ")}" fill="none" stroke="var(--ok)" stroke-width="1.6" stroke-dasharray="6 4" opacity=".8"><title>path of the successful program (exp03 clip 233859 attempt 4)</title></polyline>`);side.push(`<polyline points="${p.map(q=>sx(q[0])+","+sz(q[2])).join(" ")}" fill="none" stroke="var(--ok)" stroke-width="1.6" stroke-dasharray="6 4" opacity=".8"/>`)}
 const ov=small?null:xOverlay();
 if(ov){
  if(XV.lay.path&&ov.path){const p=ov.path;let segT="",segS="";for(let i=1;i<p.length;i++){const a=p[i-1],b=p[i],c=b[4]>0.04?"var(--bad)":"var(--acc)";segT+=`<line x1="${tx(a[2])}" y1="${ty(a[1])}" x2="${tx(b[2])}" y2="${ty(b[1])}" stroke="${c}" stroke-width="2" opacity=".75"/>`;segS+=`<line x1="${sx(a[1])}" y1="${sz(a[3])}" x2="${sx(b[1])}" y2="${sz(b[3])}" stroke="${c}" stroke-width="2" opacity=".75"/>`}top.push(segT);side.push(segS);
   const cur=p.reduce((m,q)=>Math.abs(q[0]-XV.step)<Math.abs(m[0]-XV.step)?q:m,p[0]);top.push(`<circle cx="${tx(cur[2])}" cy="${ty(cur[1])}" r="6" fill="none" stroke="var(--ink)" stroke-width="2"/>`);side.push(`<circle cx="${sx(cur[1])}" cy="${sz(cur[3])}" r="6" fill="none" stroke="var(--ink)" stroke-width="2"/>`)}
  if(XV.lay.arm){const f=xArmFrame();if(f)for(const q of f.spheres){const hand=/hand|finger/.test(q[4]);const c=hand?"var(--s2)":"var(--s1)";
    top.push(`<circle cx="${tx(q[1])}" cy="${ty(q[0])}" r="${q[3]*TX.S}" fill="${c}" fill-opacity=".22" stroke="${c}" stroke-width=".6"/>`);side.push(`<circle cx="${sx(q[0])}" cy="${sz(q[2])}" r="${q[3]*SZ.S}" fill="${c}" fill-opacity=".22" stroke="${c}" stroke-width=".6"/>`)}}
  if(XV.lay.contact)for(const e of (ov.events||[])){if(!e.blocking)continue;const on=XV.step>=e.steps[0]&&XV.step<=e.steps[1];const p=e.point,lab=`${e.part} → ${e.object} · ${e.n_steps} steps · ${e.fn_mean} N`;
   top.push(`<circle cx="${tx(p[1])}" cy="${ty(p[0])}" r="${on?9:6}" fill="var(--bad)" fill-opacity="${on?.85:.35}" stroke="var(--bad)"><title>${esc(lab)}</title></circle><text x="${tx(p[1])+11}" y="${ty(p[0])+4}" style="fill:var(--bad)">${esc(lab)}</text>`);
   side.push(`<circle cx="${sx(p[0])}" cy="${sz(p[2])}" r="${on?9:6}" fill="var(--bad)" fill-opacity="${on?.85:.35}" stroke="var(--bad)"><title>${esc(lab)}</title></circle>`)}
 }
 const base=S.base?`<rect x="${tx(0.05)}" y="${ty(0.12)}" width="${0.1*TX.S}" height="${0.1*TX.S}" fill="var(--ink)" fill-opacity=".25"/><text class="m" x="${tx(0.0)}" y="${ty(0.0)+14}" text-anchor="middle">robot base</text>`:"";
 const tbl=`<rect x="${sx(TX.x0)}" y="${sz(-0.012)}" width="${(TX.x1-TX.x0)*SZ.S}" height="${6}" fill="var(--line)"/>`;
 const gridT=[0.2,0.4,0.6,0.8].map(x=>`<line x1="${TX.M}" x2="${TX.M+(TX.y1-TX.y0)*TX.S}" y1="${ty(x)}" y2="${ty(x)}" stroke="var(--line)" stroke-dasharray="2 4"/><text class="m" x="${TX.M+2}" y="${ty(x)-3}">x ${x} m</text>`).join("");
 const W=TX.M*2+(TX.y1-TX.y0)*TX.S,H=TX.M*2+(TX.x1-TX.x0)*TX.S,W2=SZ.M*2+(TX.x1-TX.x0)*SZ.S,H2=SZ.M*2+(SZ.z1-SZ.z0)*SZ.S;
 const t=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="top view of ${esc(lvl)}">${small?"":gridT}${base}${top.join("")}<text class="m" x="${W-8}" y="${H-6}" text-anchor="end">top view · x forward (up), y left (left)</text></svg>`;
 if(small)return t;
 const sd=`<svg viewBox="0 0 ${W2} ${H2}" role="img" aria-label="side view of ${esc(lvl)}">${tbl}${[0.1,0.2,0.3,0.4,0.5].map(z=>`<line x1="${SZ.M}" x2="${W2-SZ.M}" y1="${sz(z)}" y2="${sz(z)}" stroke="var(--line)" stroke-dasharray="2 4"/><text class="m" x="${SZ.M+2}" y="${sz(z)-3}">z ${z} m</text>`).join("")}${side.join("")}<text class="m" x="${W2-8}" y="${H2-6}" text-anchor="end">side view · x forward (right), z up</text></svg>`;
 return `<div class="xmaps"><div class="xmap">${t}</div><div class="xmap">${sd}</div></div>`}

function xvSet(k,v){if(k==="lvl"){XV.lvl=v;XV.run="";XV.step=0}else if(k==="run"){XV.run=v;XV.step=0}else if(k==="shape")XV.shape=v;else XV.lay[k]=v;show("scene",true)}
function xvStep(v){XV.step=+v;$("#xm").innerHTML=sceneSVG(XV.lvl);const o=xOverlay(),el=$("#xstep");if(el)el.textContent=xStepText(o)}
function xStepText(o){if(!o)return "";const p=(o.path||[]).reduce((m,q)=>Math.abs(q[0]-XV.step)<Math.abs(m[0]-XV.step)?q:m,(o.path||[[0,0,0,0,0,0]])[0]);const ev=(o.events||[]).filter(e=>e.blocking&&XV.step>=e.steps[0]&&XV.step<=e.steps[1]);
 return `step ${XV.step} · TCP (${p[1].toFixed(3)}, ${p[2].toFixed(3)}, ${p[3].toFixed(3)}) m · tracking error ${p[4]} rad · gripper ${p[5]}`+(ev.length?` · IN BLOCKING CONTACT: ${ev.map(e=>e.part+" → "+e.object+" ("+e.fn_mean+" N)").join(", ")}`:"")}
function expScene(){
 const S=xv();if(!S)return "<p>No scene data in this run.</p>";
 const runs=D.samples.filter(s=>s.exp&&s.exp.level===XV.lvl&&s.exp.overlay);
 if(XV.run&&!runs.find(s=>s.id===XV.run))XV.run="";
 const o=xOverlay(),maxStep=o&&o.path&&o.path.length?o.path[o.path.length-1][0]:0;
 const sel=(k,opts,cur)=>`<select onchange="xvSet('${k}',this.value)">${opts.map(([v,t])=>`<option value="${esc(v)}" ${v===cur?"selected":""}>${esc(t)}</option>`).join("")}</select>`;
 const chk=(k,t)=>`<label><input type="checkbox" ${XV.lay[k]?"checked":""} onchange="xvSet('${k}',this.checked)"> ${t}</label>`;
 const V=S.view;
 const objs=V.objects.map(q=>{const a=q.aabb,z=[0,1,2].map(i=>((a[1][i]-a[0][i])*100).toFixed(0));return `<tr><td class="v">${esc(q.label)}</td><td class="mono">${[0,1,2].map(i=>((a[0][i]+a[1][i])/2).toFixed(3)).join(", ")}</td><td>${z.join(" × ")} cm</td><td>${q.profile?"round, radius "+(Math.max(...q.profile.rings.map(r=>r[1]))*100).toFixed(1)+" cm":q.boxes.length+" box"+(q.boxes.length>1?"es":"")}</td><td>${q.movable?"movable":"fixed"}</td></tr>`}).join("");
 const rels=V.relations.filter(r=>r.kind!=="supported_by").map(r=>`<tr><td>${esc(r.a)}</td><td>${esc(r.b)}</td><td>${chip(r.kind,r.kind==="touching"?"bad":"")}</td><td>${(Math.max(0,r.gap_m)*1000).toFixed(0)} mm</td></tr>`).join("");
 return `<h2 class="xh">Scene · ${esc(XV.lvl)} ${esc(S.title||"")}</h2><p class="xlede">${esc(S.desc||"")}</p>
 <div class="xctl"><label>level ${sel("lvl",xLv().map(l=>[l,l+" · "+((D.config.levels||{})[l]||{}).title]),XV.lvl)}</label>
 <label>run to overlay ${sel("run",[["","none"],...runs.map(s=>[s.id,s.id+" · "+(s.attempts[0]&&s.attempts[0].success?"success":"failed")])],XV.run)}</label>
 <label>shapes ${sel("shape",[["detail","detail (radius profile, box sets)"],["box","one box per object"]],XV.shape)}</label>
 ${chk("rel","relations")}${chk("ref","reference path")}${chk("path","run path")}${chk("arm","arm spheres")}${chk("contact","blocking contacts")}</div>
 ${o?`<div class="ctl"><button onclick="XV.step=Math.max(0,XV.step-6);xvStep(XV.step);$('#xr').value=XV.step">◀</button><input id="xr" type="range" min="0" max="${maxStep}" value="${XV.step}" oninput="xvStep(this.value)"><button onclick="XV.step=Math.min(${maxStep},XV.step+6);xvStep(XV.step);$('#xr').value=XV.step">▶</button></div><div id="xstep" class="mono" style="margin:0 0 8px">${xStepText(o)}</div>`:`<div class="xnote">Pick a run to overlay its path, the arm as spheres and its contact events.</div>`}
 <div id="xm">${sceneSVG(XV.lvl)}</div>
 <div class="xleg"><span><i style="background:var(--acc)"></i>task object</span><span><i style="background:var(--s2)"></i>wine rack / hand spheres</span><span><i style="background:var(--mute)"></i>other object</span><span><i style="background:var(--bad)"></i>blocking contact · red outline = object that blocked the hand</span><span><i style="background:var(--ok)"></i>reference path (successful program)</span><span><i style="background:var(--acc);opacity:.6"></i>run path (red where a joint is more than 0.04 rad off target)</span><span><i style="background:var(--s1);opacity:.4"></i>arm links (61 cuRobo spheres)</span></div>
 <div class="two"><div class="card pad"><h3 class="t">Objects (robot_base frame)</h3><div style="overflow:auto"><table class="xt"><tr><th>object</th><th>centre x, y, z (m)</th><th>size</th><th>shape</th><th></th></tr>${objs}</table></div></div>
 <div class="card pad"><h3 class="t">Relations (exact gaps from the simulator, up to 12 cm)</h3><div style="overflow:auto;max-height:320px"><table class="xt"><tr><th>a</th><th>b</th><th>relation</th><th>gap</th></tr>${rels}</table></div></div></div>
 <p class="muted">Arm spheres are drawn with standard Panda kinematics from the logged joint angles (checked against the logged end-effector position: a constant 9.65 cm offset from the hand frame) and cuRobo's collision sphere set; they illustrate where the arm is and are not used by any program.</p>`}
"""
