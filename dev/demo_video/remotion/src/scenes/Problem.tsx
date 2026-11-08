import React from "react";
import {AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {BLUE, FONT, GREEN, INK, Logo, MUTED, RED} from "./common";

/** Beat start/end in seconds. Re-time these to the narration; everything else follows. */
export const BEATS = {
  context: [0, 6], // VLM lacks physical context
  coverage: [6, 11], // tests never cover production
  synth: [11, 17], // human video + scene -> Synthesizer
  adversary: [17, 22], // crosshair finds the red dots -> Adversary
  title: [22, 27], // both join around the logo
} as const;
export const PROBLEM_SECONDS = BEATS.title[1];

const clamp = {extrapolateLeft: "clamp", extrapolateRight: "clamp"} as const;
const ease = Easing.inOut(Easing.cubic);

/** 0 -> 1 over [a, a + len] seconds. */
const useRamp = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const ramp = (a: number, len = 0.6) => interpolate(t, [a, a + len], [0, 1], {...clamp, easing: ease});
  /** visible during [a, b] with fades at both ends */
  const span = (a: number, b: number, f = 0.5) => Math.min(ramp(a, f), 1 - ramp(b - f, f));
  return {t, frame, fps, ramp, span};
};

const Headline: React.FC<{text: string; opacity: number}> = ({text, opacity}) => (
  <div style={{position: "absolute", top: 110, left: 0, right: 0, textAlign: "center", fontSize: 54, fontWeight: 700, color: INK, opacity}}>
    {text}
  </div>
);

const Label: React.FC<{children: React.ReactNode; color?: string; size?: number; style?: React.CSSProperties}> = ({children, color = MUTED, size = 30, style}) => (
  <div style={{fontSize: size, fontWeight: 600, color, textAlign: "center", ...style}}>{children}</div>
);

/* ---------- beat 1: VLM lacks physical context ---------- */
const VlmIcon = () => (
  <div style={{width: 260, height: 220, borderRadius: 28, border: `5px solid ${BLUE}`, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 16, background: "#f3f7fe"}}>
    <div style={{fontSize: 64, fontWeight: 800, color: BLUE, letterSpacing: "0.04em"}}>VLM</div>
    {[150, 110].map((w) => (
      <div key={w} style={{width: w, height: 12, borderRadius: 6, background: "#c9dbf7"}} />
    ))}
  </div>
);

const RobotArm: React.FC<{q: number}> = ({q}) => (
  <svg width={460} height={420} viewBox="0 0 460 420">
    {/* table */}
    <rect x="20" y="380" width="420" height="14" rx="7" fill="#d9dee3" />
    {/* base + links */}
    <rect x="40" y="330" width="110" height="50" rx="10" fill={INK} />
    <line x1="95" y1="330" x2="150" y2="140" stroke={INK} strokeWidth="26" strokeLinecap="round" />
    <line x1="150" y1="140" x2="300" y2="110" stroke={INK} strokeWidth="22" strokeLinecap="round" />
    <circle cx="150" cy="140" r="20" fill={BLUE} />
    <circle cx="95" cy="330" r="18" fill={BLUE} />
    {/* gripper */}
    <line x1="300" y1="110" x2="300" y2="170" stroke={INK} strokeWidth="14" strokeLinecap="round" />
    <path d="M278 170 h44 M278 170 v34 M322 170 v34" stroke={INK} strokeWidth="10" fill="none" strokeLinecap="round" />
    {/* bowl */}
    <path d="M240 330 q60 60 120 0 z" fill="#8aa4b8" />
    <rect x="232" y="324" width="136" height="10" rx="5" fill="#6f8aa0" />
    {/* question mark */}
    <text x="395" y="250" fontSize="120" fontWeight="800" fill={BLUE} fontFamily={FONT} textAnchor="middle" opacity={q}>?</text>
  </svg>
);

const BeatContext: React.FC = () => {
  const {ramp, span} = useRamp();
  const [a, b] = BEATS.context;
  const o = span(a, b);
  return (
    <AbsoluteFill style={{opacity: o}}>
      <Headline text="Vision-language models lack physical context" opacity={ramp(a + 0.2)} />
      <div style={{position: "absolute", top: 270, left: 0, right: 0, display: "flex", justifyContent: "center", alignItems: "center", gap: 120}}>
        <div style={{opacity: ramp(a + 0.4), transform: `translateX(${(1 - ramp(a + 0.4)) * -60}px)`}}>
          <VlmIcon />
        </div>
        <div style={{opacity: ramp(a + 1)}}>
          <RobotArm q={ramp(a + 1.8)} />
        </div>
      </div>
      <div style={{position: "absolute", top: 760, left: 0, right: 0, display: "flex", justifyContent: "center", gap: 90}}>
        <Label size={38} color={BLUE} style={{opacity: ramp(a + 2.4)}}>where to grasp?</Label>
        <Label size={38} color={BLUE} style={{opacity: ramp(a + 3.2)}}>how high to lift?</Label>
      </div>
    </AbsoluteFill>
  );
};

/* ---------- beat 2: tests never cover production ---------- */
const COLS = 9, ROWS = 5, GAP = 62;
const RED_DOTS = [
  [740, -40], [790, 120], [700, 260], [820, 300],
] as const;

const BeatCoverage: React.FC = () => {
  const {ramp, span} = useRamp();
  const [a, b] = BEATS.coverage;
  const o = span(a, b);
  const gw = (COLS - 1) * GAP, gh = (ROWS - 1) * GAP;
  return (
    <AbsoluteFill style={{opacity: o}}>
      <Headline text="No test covers every case" opacity={ramp(a + 0.2)} />
      <div style={{position: "absolute", left: 420, top: 330, width: 1100, height: 460}}>
        <div style={{position: "absolute", left: 0, top: 0, width: gw + 120, height: gh + 120, borderRadius: 26, border: "4px dashed #b7c3cc", opacity: ramp(a + 0.3)}} />
        <Label style={{position: "absolute", left: 0, top: gh + 140, width: gw + 120, opacity: ramp(a + 0.3)}}>tested in development</Label>
        {Array.from({length: COLS * ROWS}, (_, i) => {
          const c = i % COLS, r = Math.floor(i / COLS);
          const g = ramp(a + 0.5 + i * 0.045, 0.3);
          return (
            <div key={i} style={{position: "absolute", left: 60 + c * GAP - 14, top: 60 + r * GAP - 14, width: 28, height: 28, borderRadius: 14,
              background: g > 0.5 ? GREEN : "#d5dbe0", transform: `scale(${0.6 + 0.4 * g})`}} />
          );
        })}
        {RED_DOTS.map(([x, y], i) => {
          const p = ramp(a + 2.6 + i * 0.25, 0.35);
          return <div key={i} style={{position: "absolute", left: x - 18, top: y + 60 - 18, width: 36, height: 36, borderRadius: 18, background: RED, opacity: p, transform: `scale(${p})`}} />;
        })}
        <Label color={RED} size={36} style={{position: "absolute", left: 650, top: 420, width: 260, opacity: ramp(a + 3.4)}}>production</Label>
      </div>
    </AbsoluteFill>
  );
};

/* ---------- beats 3-5: synthesizer, adversary, title ---------- */
const Box: React.FC<{title: string; sub: string; color: string}> = ({title, sub, color}) => (
  <div style={{width: 400, padding: "30px 26px", borderRadius: 26, border: `5px solid ${color}`, background: "#fff", textAlign: "center", boxShadow: "0 10px 30px rgba(28,43,51,0.08)"}}>
    <div style={{fontSize: 52, fontWeight: 800, color}}>{title}</div>
    <div style={{fontSize: 28, fontWeight: 500, color: MUTED, marginTop: 8}}>{sub}</div>
  </div>
);

const Phone = () => (
  <svg width={120} height={200} viewBox="0 0 120 200">
    <rect x="6" y="6" width="108" height="188" rx="18" fill="#fff" stroke={INK} strokeWidth="8" />
    <rect x="18" y="30" width="84" height="130" rx="6" fill="#e7eef9" />
    <path d="M48 70 L80 95 L48 120 Z" fill={BLUE} />
    <circle cx="60" cy="176" r="6" fill={INK} />
  </svg>
);

const SceneIcon = () => (
  <svg width={190} height={150} viewBox="0 0 190 150">
    <rect x="6" y="6" width="178" height="138" rx="16" fill="#fff" stroke={INK} strokeWidth="8" />
    <rect x="20" y="96" width="150" height="10" rx="5" fill="#b7c3cc" />
    <path d="M40 96 q28 28 56 0 z" fill="#8aa4b8" />
    <ellipse cx="135" cy="92" rx="30" ry="7" fill="#c9d3da" />
    <text x="95" y="50" fontSize="26" fontWeight="700" fill={MUTED} fontFamily={FONT} textAnchor="middle">scene</text>
  </svg>
);

const Arrow: React.FC<{w: number; p: number}> = ({w, p}) => (
  <svg width={w} height={40} viewBox={`0 0 ${w} 40`}>
    <line x1="0" y1="20" x2={(w - 24) * p} y2="20" stroke={BLUE} strokeWidth="8" strokeLinecap="round" />
    {p > 0.95 && <path d={`M${w - 30} 4 L${w} 20 L${w - 30} 36 Z`} fill={BLUE} />}
  </svg>
);

const Crosshair: React.FC<{size: number}> = ({size}) => (
  <svg width={size} height={size} viewBox="0 0 100 100">
    <circle cx="50" cy="50" r="38" fill="none" stroke={BLUE} strokeWidth="6" />
    <line x1="50" y1="0" x2="50" y2="28" stroke={BLUE} strokeWidth="6" />
    <line x1="50" y1="72" x2="50" y2="100" stroke={BLUE} strokeWidth="6" />
    <line x1="0" y1="50" x2="28" y2="50" stroke={BLUE} strokeWidth="6" />
    <line x1="72" y1="50" x2="100" y2="50" stroke={BLUE} strokeWidth="6" />
  </svg>
);

// adversary targets (absolute stage coordinates)
const TARGETS = [
  [1330, 380], [1540, 330], [1450, 520], [1620, 470],
] as const;

const BeatSystems: React.FC = () => {
  const {t, fps, frame, ramp} = useRamp();
  const s3 = BEATS.synth[0], s4 = BEATS.adversary[0], s5 = BEATS.title[0];
  const visible = ramp(s3, 0.5);
  const join = ramp(s5, 1.0); // 0 -> 1 as boxes move to the final layout
  // synthesizer column
  const synIn = ramp(s3 + 0.2);
  const inputsFade = 1 - join;
  // crosshair path over the targets during beat 4
  const hopLen = 0.9;
  const hop = Math.min(TARGETS.length - 1, Math.max(0, Math.floor((t - s4 - 0.6) / hopLen)));
  const hopP = interpolate(t - s4 - 0.6 - hop * hopLen, [0, 0.5], [0, 1], {...clamp, easing: ease});
  const from = TARGETS[Math.max(0, hop - 1)], to = TARGETS[hop];
  const cx = hop === 0 ? to[0] : from[0] + (to[0] - from[0]) * hopP;
  const cy = hop === 0 ? to[1] : from[1] + (to[1] - from[1]) * hopP;
  const advIn = ramp(s4 + 0.2);
  const found = (i: number) => t > s4 + 0.6 + i * hopLen + 0.5;
  // final layout: boxes slide toward the logo in the middle
  const synX = interpolate(join, [0, 1], [430, 300]);
  const advX = interpolate(join, [0, 1], [1260, 1220]);
  const boxY = interpolate(join, [0, 1], [700, 520]);
  const pulse = 1 + 0.04 * Math.sin((frame / fps) * 6);
  return (
    <AbsoluteFill style={{opacity: visible}}>
      <Headline
        text={t < s4 ? "One human video and the scene become the prompt" : t < s5 ? "Targeted failure search finds where it breaks" : ""}
        opacity={t < s5 ? Math.min(ramp(t < s4 ? s3 + 0.2 : s4 + 0.1), 1 - ramp(s5 - 0.4, 0.4)) : 0}
      />
      {/* inputs */}
      <div style={{position: "absolute", left: 300, top: 300, display: "flex", alignItems: "center", gap: 40, opacity: synIn * inputsFade,
        transform: `translateX(${(1 - synIn) * -80}px)`}}>
        <div style={{display: "flex", flexDirection: "column", alignItems: "center", gap: 10}}><Phone /><Label size={26}>human video</Label></div>
        <div style={{display: "flex", flexDirection: "column", alignItems: "center", gap: 10}}><SceneIcon /><Label size={26}>scene context</Label></div>
      </div>
      <div style={{position: "absolute", left: 590, top: 560, transform: "rotate(90deg)", transformOrigin: "left center", opacity: synIn * inputsFade}}>
        <Arrow w={110} p={ramp(s3 + 1.0, 0.8)} />
      </div>
      {/* adversary targets */}
      {TARGETS.map(([x, y], i) => (
        <div key={i} style={{position: "absolute", left: x - 18, top: y - 18, width: 36, height: 36, borderRadius: 18, background: RED,
          opacity: advIn * (1 - join), transform: `scale(${found(i) ? 1.15 : 1})`, boxShadow: found(i) ? `0 0 0 10px rgba(217,58,58,0.18)` : "none"}} />
      ))}
      {t > s4 + 0.4 && t < s5 + 0.6 && (
        <div style={{position: "absolute", left: cx - 60, top: cy - 60, opacity: advIn * (1 - join)}}><Crosshair size={120} /></div>
      )}
      {/* boxes */}
      <div style={{position: "absolute", left: synX, top: boxY, opacity: ramp(s3 + 1.6), transform: `scale(${0.9 + 0.1 * ramp(s3 + 1.6)})`}}>
        <Box title="Synthesizer" sub="policy generator" color={BLUE} />
      </div>
      <div style={{position: "absolute", left: advX, top: boxY, opacity: ramp(s4 + 2.0), transform: `scale(${0.9 + 0.1 * ramp(s4 + 2.0)})`}}>
        <Box title="Adversary" sub="targeted failure search" color={RED} />
      </div>
      {/* title */}
      <div style={{position: "absolute", left: 0, right: 0, top: 470, display: "flex", justifyContent: "center", opacity: join}}>
        <div style={{transform: `scale(${pulse})`}}><Logo width={260} /></div>
      </div>
      <div style={{position: "absolute", left: 0, right: 0, top: 160, textAlign: "center", opacity: ramp(s5 + 0.8)}}>
        <div style={{fontSize: 72, fontWeight: 800, color: INK}}>Adversarial Agentic Task Synthesis</div>
      </div>
      <div style={{position: "absolute", left: 0, right: 0, top: 800, textAlign: "center", opacity: ramp(s5 + 1.6), fontSize: 40, fontWeight: 600, color: BLUE}}>
        Show once. Break smart.
      </div>
    </AbsoluteFill>
  );
};

export const Problem: React.FC = () => (
  <AbsoluteFill style={{backgroundColor: "#ffffff", fontFamily: FONT}}>
    <BeatContext />
    <BeatCoverage />
    <BeatSystems />
  </AbsoluteFill>
);
