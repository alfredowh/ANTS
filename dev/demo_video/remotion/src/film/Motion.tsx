import React from "react";
import {AbsoluteFill, Audio, Easing, interpolate, Sequence, spring, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import {BLUE, FONT, GREEN, INK, MUTED, RED} from "../scenes/common";

const clamp = {extrapolateLeft: "clamp", extrapolateRight: "clamp"} as const;
const ease = Easing.bezier(0.65, 0, 0.35, 1);
const GREY = "#c9d2db";

/* ---------- tiny icon set (24x24 strokes) ---------- */
const ICONS: Record<string, string> = {
  text: "M4 6h16M4 12h16M4 18h10",
  video: "M3 6h12v12H3zM15 10l6-3v10l-6-3",
  bolt: "M13 2L4 14h7l-1 8 9-12h-7z",
  search: "M10 4a6 6 0 1 1 0 12a6 6 0 1 1 0-12M15 15l6 6",
  rule: "M5 4h14v16H5zM8 9h8M8 13h8M8 17h5",
  code: "M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16",
  shield: "M12 2l8 4v6c0 5-4 9-8 10c-4-1-8-5-8-10V6z",
  person: "M12 4a4 4 0 1 1 0 8a4 4 0 1 1 0-8M4 21c0-4 4-7 8-7s8 3 8 7",
  robot: "M5 20h14M8 20v-5l4-6 5 3M17 12l3-2M12 9l-2-3",
  warn: "M12 3l10 18H2zM12 10v5M12 18v.5",
  cube: "M12 2l9 5v10l-9 5-9-5V7zM3 7l9 5 9-5M12 12v10",
  doc: "M6 2h9l5 5v15H6zM14 2v6h6",
  rocket: "M12 2c4 3 5 8 4 13l-4 3-4-3c-1-5 0-10 4-13zM8 15l-3 4M16 15l3 4M12 9v.5",
};
const Icon: React.FC<{name: string; size: number; color: string; width?: number}> = ({name, size, color, width = 2}) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={width} strokeLinecap="round" strokeLinejoin="round">
    <path d={ICONS[name]} />
  </svg>
);

/* ---------- 1. result: two rows of ten runs filling live ---------- */
export const ResultScene: React.FC<{duration: number}> = ({duration}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const rows = [
    {label: "Text only", icon: "text", pass: 0, color: RED, start: 1.2},
    {label: "Human video", icon: "video", pass: 7, color: GREEN, start: 3.2},
  ];
  const head = interpolate(frame, [0, 14], [0, 1], clamp);
  return (
    <AbsoluteFill style={{background: "#fff", fontFamily: FONT, alignItems: "center", justifyContent: "center"}}>
      {rows.flatMap((r) => Array.from({length: 10}, (_, i) => (
        <Sequence key={`${r.label}${i}`} from={Math.round((r.start + (i + 0.5) * 0.16) * fps)} layout="none">
          <Audio src={staticFile("film/sfx/tick.wav")} volume={i < r.pass ? 0.45 : 0.18} />
        </Sequence>
      )))}
      <div style={{opacity: head, font: `600 40px ${FONT}`, color: MUTED, marginBottom: 70, letterSpacing: "0.02em"}}>
        New object sizes · 10 runs each
      </div>
      <div style={{display: "grid", gap: 64}}>
        {rows.map((r, ri) => {
          const shown = interpolate(t, [r.start, r.start + 1.6], [0, 10], clamp);
          const count = Math.min(r.pass, Math.floor(shown));
          const rowIn = spring({frame: frame - r.start * fps + 12, fps, config: {damping: 200}});
          return (
            <div key={r.label} style={{display: "flex", alignItems: "center", gap: 44, opacity: rowIn, transform: `translateX(${(1 - rowIn) * -40}px)`}}>
              <div style={{width: 400, display: "flex", alignItems: "center", gap: 18, color: INK, font: `600 46px ${FONT}`, whiteSpace: "nowrap"}}>
                <Icon name={r.icon} size={52} color={ri ? BLUE : MUTED} />{r.label}
              </div>
              <div style={{display: "flex", gap: 22}}>
                {Array.from({length: 10}, (_, i) => {
                  const on = shown > i + 0.5;
                  const pass = i < r.pass;
                  const pop = interpolate(shown, [i, i + 0.6], [0.4, 1], clamp);
                  return (
                    <div key={i} style={{width: 66, height: 66, borderRadius: 33, transform: `scale(${pop})`,
                      background: on ? (pass ? GREEN : "#fff") : "#eef2f6", border: `4px solid ${on ? (pass ? GREEN : RED) : "#e1e7ee"}`,
                      display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", font: `700 34px ${FONT}`}}>
                      {on && !pass && <span style={{color: RED}}>✕</span>}
                      {on && pass && "✓"}
                    </div>
                  );
                })}
              </div>
              <div style={{width: 200, font: `700 84px ${FONT}`, color: r.color, fontVariantNumeric: "tabular-nums", opacity: shown > 0.5 ? 1 : 0}}>
                {count}<span style={{fontSize: 46, color: MUTED}}>/10</span>
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

/* ---------- 2. gate loop: a pulse travels the loop; the gate rejects once, then keeps ---------- */
export const LoopScene: React.FC<{duration: number}> = ({duration}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const steps = [
    {label: "Attack", sub: "breaks the policy", icon: "bolt", color: RED},
    {label: "Explain", sub: "why it failed", icon: "search", color: RED},
    {label: "Rule", sub: "for the generator", icon: "rule", color: BLUE},
    {label: "Rewrite", sub: "new version", icon: "code", color: BLUE},
    {label: "Gate", sub: "nothing got worse?", icon: "shield", color: INK},
  ];
  const n = steps.length, R = 300, cx = 760, cy = 560;
  const lap = Math.max(4, (duration - 6) / 2); // two laps, then the person appears
  const pos = (k: number) => {
    const a = -Math.PI / 2 + (k * 2 * Math.PI) / n;
    return [cx + R * Math.cos(a), cy + R * Math.sin(a)];
  };
  const prog = interpolate(t, [0.8, 0.8 + 2 * lap], [0, 2], clamp); // laps travelled
  const ang = -Math.PI / 2 + (prog % 1) * 2 * Math.PI;
  const dot = [cx + R * Math.cos(ang), cy + R * Math.sin(ang)];
  const atGate = (lapIndex: number) => interpolate(prog, [lapIndex + 0.8, lapIndex + 0.86, lapIndex + 0.98, lapIndex + 1.0], [0, 1, 1, lapIndex === 1 ? 1 : 0], clamp);
  const reject = atGate(0), keep = atGate(1);
  const personIn = spring({frame: frame - (0.8 + 2 * lap) * fps, fps, config: {damping: 200}});
  const ring = interpolate(prog, [0, 2], [0, 1], clamp);
  const gateAt = (lapIndex: number) => (0.8 + (lapIndex + 0.82) * lap) * fps;
  return (
    <AbsoluteFill style={{background: "#fff", fontFamily: FONT}}>
      <svg width={1920} height={1080} style={{position: "absolute"}}>
        <circle cx={cx} cy={cy} r={R} fill="none" stroke="#e3e9ef" strokeWidth={10} />
        <circle cx={cx} cy={cy} r={R} fill="none" stroke={BLUE} strokeWidth={10} strokeLinecap="round" opacity={0.35}
          strokeDasharray={2 * Math.PI * R} strokeDashoffset={2 * Math.PI * R * (1 - Math.min(1, prog))} transform={`rotate(-90 ${cx} ${cy})`} />
        <circle cx={dot[0]} cy={dot[1]} r={16} fill={BLUE} opacity={prog > 0 && prog < 2 ? 1 : 0} />
        <circle cx={dot[0]} cy={dot[1]} r={30} fill={BLUE} opacity={prog > 0 && prog < 2 ? 0.18 : 0} />
        {personIn > 0 && <path d={`M ${pos(2)[0] + 120} ${pos(2)[1] - 10} Q 1250 760 1380 640`} stroke={MUTED} strokeWidth={4} strokeDasharray="12 10" fill="none" opacity={personIn} />}
      </svg>
      {steps.map((s, k) => {
        const [x, y] = pos(k);
        const near = Math.abs(((prog % 1) * n - k + n + 0.5) % n - 0.5) < 0.45 && prog < 2;
        const sIn = spring({frame: frame - k * 4, fps, config: {damping: 200}});
        return (
          <div key={s.label} style={{position: "absolute", left: x - 140, top: y - 78, width: 280, height: 156, borderRadius: 22,
            background: "#fff", border: `4px solid ${near ? s.color : GREY}`, boxShadow: near ? `0 10px 30px ${s.color}33` : "none",
            display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 6,
            opacity: sIn, transform: `scale(${(0.85 + 0.15 * sIn) * (near ? 1.06 : 1)})`}}>
            <Icon name={s.icon} size={44} color={s.color} />
            <div style={{font: `700 36px ${FONT}`, color: INK}}>{s.label}</div>
            <div style={{font: `500 24px ${FONT}`, color: MUTED}}>{s.sub}</div>
          </div>
        );
      })}
      <Sequence from={Math.round(gateAt(0))} layout="none"><Audio src={staticFile("film/sfx/thud.wav")} volume={0.6} /></Sequence>
      <Sequence from={Math.round(gateAt(1))} layout="none"><Audio src={staticFile("film/sfx/chime.wav")} volume={0.5} /></Sequence>
      {/* gate verdicts */}
      {[{v: reject, text: "Rejected: a passing case broke", color: RED, mark: "✕"}, {v: keep, text: "Kept: better, nothing worse", color: GREEN, mark: "✓"}].map((g) => (
        <div key={g.text} style={{position: "absolute", left: pos(4)[0] - 400, top: pos(4)[1] - 190, opacity: g.v, transform: `translateY(${(1 - g.v) * 12}px)`,
          display: "flex", alignItems: "center", gap: 14, background: "#fff", border: `3px solid ${g.color}`, color: g.color, borderRadius: 999,
          padding: "10px 24px", font: `700 30px ${FONT}`}}>
          <span style={{fontSize: 36}}>{g.mark}</span>{g.text}
        </div>
      ))}
      {/* the person */}
      <div style={{position: "absolute", left: 1270, top: 380, width: 580, opacity: personIn, transform: `translateX(${(1 - personIn) * 40}px)`,
        border: `4px solid ${INK}`, borderRadius: 24, padding: "26px 30px", background: "#fff"}}>
        <div style={{display: "flex", alignItems: "center", gap: 16, font: `700 36px ${FONT}`, color: INK}}>
          <Icon name="person" size={50} color={INK} />A person helps
        </div>
        <div style={{font: `500 26px ${FONT}`, color: MUTED, margin: "10px 0 18px"}}>when the same failure comes back</div>
        <div style={{display: "flex", gap: 14}}>
          {[["text", "Text answer"], ["video", "New demo video"]].map(([ic, l], i) => {
            const p = spring({frame: frame - (1.2 + 2 * lap + i * 0.4) * fps, fps, config: {damping: 200}});
            return (
              <div key={l} style={{display: "flex", alignItems: "center", gap: 10, border: `3px solid ${BLUE}`, color: BLUE, borderRadius: 999,
                padding: "8px 18px", font: `600 26px ${FONT}`, opacity: p, whiteSpace: "nowrap"}}>
                <Icon name={ic} size={30} color={BLUE} />{l}
              </div>
            );
          })}
        </div>
      </div>
      <div style={{position: "absolute", left: 0, right: 0, top: 70, textAlign: "center", font: `700 52px ${FONT}`, color: INK,
        opacity: interpolate(frame, [0, 14], [0, 1], clamp)}}>
        Every failure becomes a fix, or it is rejected
      </div>
      <div style={{position: "absolute", left: cx - 120, top: cy - 40, width: 240, textAlign: "center", font: `700 30px ${FONT}`, color: MUTED}}>
        lap {Math.min(2, Math.floor(prog) + 1)}
      </div>
    </AbsoluteFill>
  );
};

/* ---------- 3. flows built from the architecture ---------- */
type FNode = {id: string; label: string; sub?: string; icon: string; x: number; y: number; color: string; dashed?: boolean};
type FEdge = {from: string; to: string; bend?: number; label?: string};
export type Flow = {title: string; nodes: FNode[]; edges: FEdge[]};

export const FLOWS: Record<string, Flow> = {
  deploy: {
    title: "Deployment: learn from failures in production",
    nodes: [
      {id: "robot", label: "Robot", sub: "runs the policy", icon: "robot", x: 260, y: 560, color: INK},
      {id: "fail", label: "Failure", sub: "in production", icon: "warn", x: 620, y: 560, color: RED},
      {id: "sim", label: "Reproduce", sub: "in simulation", icon: "cube", x: 980, y: 560, color: INK},
      {id: "synth", label: "Synthesizer", sub: "new or recovery policy", icon: "code", x: 1340, y: 440, color: BLUE},
      {id: "adv", label: "Adversary", sub: "optional hardening", icon: "bolt", x: 1340, y: 720, color: RED, dashed: true},
      {id: "gate", label: "Gate", sub: "nothing got worse", icon: "shield", x: 1680, y: 560, color: INK},
    ],
    edges: [
      {from: "robot", to: "fail"}, {from: "fail", to: "sim"}, {from: "sim", to: "synth"}, {from: "synth", to: "adv"},
      {from: "synth", to: "gate"}, {from: "adv", to: "gate"}, {from: "gate", to: "robot", bend: -760, label: "back to the robot"},
    ],
  },
  newtask: {
    title: "New task, new robot: the loop starts again",
    nodes: [
      {id: "task", label: "New task", sub: "or new robot", icon: "robot", x: 240, y: 400, color: INK},
      {id: "video", label: "Human video", sub: "one demonstration", icon: "video", x: 240, y: 720, color: INK},
      {id: "author", label: "Task prompt", sub: "reusable template", icon: "doc", x: 640, y: 560, color: BLUE},
      {id: "synth", label: "Synthesizer", sub: "writes the policy", icon: "code", x: 1040, y: 560, color: BLUE},
      {id: "adv", label: "Adversary", sub: "hardens it", icon: "bolt", x: 1400, y: 560, color: RED},
      {id: "deploy", label: "Deploy", sub: "skill transfers", icon: "rocket", x: 1720, y: 560, color: INK},
    ],
    edges: [
      {from: "task", to: "author"}, {from: "video", to: "author"}, {from: "author", to: "synth"}, {from: "synth", to: "adv"},
      {from: "adv", to: "deploy"}, {from: "deploy", to: "task", bend: -380, label: "next task"},
    ],
  },
};

const NW = 290, NH = 150;
export const FlowScene: React.FC<{flow: Flow; duration: number}> = ({flow, duration}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const by = Object.fromEntries(flow.nodes.map((n) => [n.id, n]));
  const step = Math.max(0.7, (duration - 3) / (flow.edges.length + 1));
  const nodeTime = (id: string) => {
    const i = flow.edges.findIndex((e) => e.to === id);
    return i < 0 ? 0.3 : 0.6 + (i + 1) * step;
  };
  const curve = (e: FEdge) => {
    const a = by[e.from], b = by[e.to];
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2 + (e.bend ?? 0);
    return {a, b, mx, my, d: `M ${a.x} ${a.y} Q ${mx} ${my} ${b.x} ${b.y}`};
  };
  const at = (e: FEdge, p: number) => {
    const {a, b, mx, my} = curve(e);
    const q = 1 - p;
    return [q * q * a.x + 2 * q * p * mx + p * p * b.x, q * q * a.y + 2 * q * p * my + p * p * b.y];
  };
  return (
    <AbsoluteFill style={{background: "#fff", fontFamily: FONT}}>
      <div style={{position: "absolute", left: 0, right: 0, top: 80, textAlign: "center", font: `700 52px ${FONT}`, color: INK,
        opacity: interpolate(frame, [0, 14], [0, 1], clamp)}}>{flow.title}</div>
      <svg width={1920} height={1080} style={{position: "absolute"}}>
        <defs>
          <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0L10 5L0 10z" fill={MUTED} />
          </marker>
        </defs>
        {flow.edges.map((e, i) => {
          const start = 0.6 + i * step;
          const p = interpolate(t, [start, start + step * 0.8], [0, 1], {...clamp, easing: ease});
          const {d, mx, my} = curve(e);
          const len = Math.hypot(by[e.to].x - by[e.from].x, by[e.to].y - by[e.from].y) + Math.abs(e.bend ?? 0) * 1.2;
          const pulse = ((t - start) % 1.6) / 1.6;
          const [px, py] = at(e, Math.max(0, Math.min(1, p < 1 ? p : pulse)));
          return (
            <g key={i}>
              <path d={d} fill="none" stroke={GREY} strokeWidth={5} strokeDasharray={len} strokeDashoffset={len * (1 - p)}
                markerEnd={p > 0.98 ? "url(#arr)" : undefined} />
              {p > 0 && <circle cx={px} cy={py} r={11} fill={BLUE} opacity={p < 1 ? 1 : 0.55} />}
              {e.label && p > 0.9 && <text x={mx} y={my + (e.bend ?? 0) * -0.42} textAnchor="middle" fontFamily={FONT} fontSize={28} fill={MUTED}>{e.label}</text>}
            </g>
          );
        })}
      </svg>
      {flow.nodes.map((n) => {
        const p = spring({frame: frame - nodeTime(n.id) * fps, fps, config: {damping: 200}});
        return (
          <div key={n.id} style={{position: "absolute", left: n.x - NW / 2, top: n.y - NH / 2, width: NW, height: NH, borderRadius: 22,
            background: "#fff", border: `4px ${n.dashed ? "dashed" : "solid"} ${n.color}`, display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center", gap: 6, opacity: p, transform: `scale(${0.8 + 0.2 * p})`,
            boxShadow: `0 8px 24px ${n.color}1f`}}>
            <Icon name={n.icon} size={44} color={n.color} />
            <div style={{font: `700 34px ${FONT}`, color: INK}}>{n.label}</div>
            {n.sub && <div style={{font: `500 23px ${FONT}`, color: MUTED}}>{n.sub}</div>}
          </div>
        );
      })}
    </AbsoluteFill>
  );
};
