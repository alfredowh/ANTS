import React from "react";
import {
  AbsoluteFill, Audio, Easing, Freeze, Img, interpolate, Loop, OffthreadVideo, Sequence, spring,
  staticFile, useCurrentFrame, useVideoConfig,
} from "remotion";
import {BLUE, FONT, INK, Logo, MUTED, RED} from "../scenes/common";
import {Problem} from "../scenes/Problem";
import {TitleCard} from "../scenes/TitleCard";

type Box = {x: number; y: number; width: number; height: number};
type Ev = {name: string; kind: string; t: number; box?: Box};
export type Scene = {
  id: string; kind: string; start: number; duration: number; caption?: string; voice?: string | null;
  card?: string; chips?: string[]; title?: string; image?: string; badge?: string; banner?: string;
  clip?: string; segs?: number[][]; rate?: number; cam?: [string, number][]; pip?: Box; clicks?: string[];
  timeline?: {width: number; height: number; events: Ev[]};
};
export type FilmData = {fps: number; width: number; height: number; duration: number; scenes: Scene[]; music?: string};

const W = 1920, H = 1080;
const ease = Easing.bezier(0.65, 0, 0.35, 1);
const clamp = {extrapolateLeft: "clamp", extrapolateRight: "clamp"} as const;
const center = (b: Box): [number, number] => [b.x + b.width / 2, b.y + b.height / 2];

/* ---------- screen takes: segments, camera, cursor, overlay of the hand-tracking clip ---------- */
function outOf(segs: number[][], src: number, rate = 1): number | null {
  let acc = 0;
  for (const [a, b] of segs) {
    if (src >= a && src <= b) return (acc + (src - a)) / rate;
    acc += b - a;
  }
  return null;
}

const ScreenScene: React.FC<{s: Scene}> = ({s}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const segs = s.segs!;
  const rate = s.rate ?? 1;
  const events = s.timeline!.events;
  const byName = (n: string) => events.find((e) => e.name === n);

  // camera: keys at their event times (output clock); each eases in over 0.8 s
  let z = 1, cx = W / 2, cy = H / 2;
  for (const [name, zoom] of s.cam ?? []) {
    const e = byName(name);
    const at = e ? outOf(segs, e.t, rate) : null;
    if (at === null || !e?.box) continue;
    const p = interpolate(t, [at - 0.8, at], [0, 1], {...clamp, easing: ease});
    if (p === 0) break;
    const [tx, ty] = center(e.box);
    z += (zoom - z) * p; cx += (tx - cx) * p; cy += (ty - cy) * p;
  }
  const x = Math.min(0, Math.max(W - W * z, W / 2 - cx * z));
  const y = Math.min(0, Math.max(H - H * z, H / 2 - cy * z));

  // cursor: glides to every element shown inside the segments; ripple on clicks
  let pos: [number, number] = [W * 0.55, H * 0.62], click = -1;
  for (const e of events) {
    const at = outOf(segs, e.t, rate);
    if (at === null || !e.box) continue;
    const p = interpolate(t, [at - 0.7, at], [0, 1], {...clamp, easing: ease});
    const [tx, ty] = center(e.box);
    pos = [pos[0] + (tx - pos[0]) * p, pos[1] + (ty - pos[1]) * p];
    const isClick = e.kind === "click" || (s.clicks ?? []).includes(e.name);
    if (isClick && t >= at && t < at + 0.6) click = (t - at) / 0.6;
  }

  let acc = 0;
  const parts = segs.map(([a, b], i) => {
    const from = Math.round((acc / rate) * fps), len = Math.max(1, Math.round(((b - a) / rate) * fps));
    acc += b - a;
    return (
      <Sequence key={i} from={from} durationInFrames={len} layout="none">
        <OffthreadVideo src={staticFile(`${s.clip}/raw.mp4`)} startFrom={Math.round(a * fps)} playbackRate={rate} muted style={{position: "absolute", width: W, height: H}} />
      </Sequence>
    );
  });
  const footage = acc / rate, lb = segs[segs.length - 1][1];
  const holdFrom = Math.round(footage * fps), holdLen = Math.round(s.duration * fps) - holdFrom;

  return (
    <AbsoluteFill style={{backgroundColor: "#fff", overflow: "hidden"}}>
      <div style={{position: "absolute", width: W, height: H, transformOrigin: "0 0", transform: `translate(${x}px, ${y}px) scale(${z})`}}>
        {parts}
        {holdLen > 0 && (
          <Sequence from={holdFrom} durationInFrames={holdLen} layout="none">
            <Freeze frame={Math.max(0, Math.round(lb * fps) - 1)}>
              <OffthreadVideo src={staticFile(`${s.clip}/raw.mp4`)} muted style={{position: "absolute", width: W, height: H}} />
            </Freeze>
          </Sequence>
        )}
        {s.pip && (
          <div style={{position: "absolute", left: s.pip.x, top: s.pip.y, width: s.pip.width, height: s.pip.height, overflow: "hidden", background: "#000"}}>
            <Loop durationInFrames={Math.round(11 * fps)}>
              <OffthreadVideo src={staticFile("assets/demo_overlay.mp4")} muted style={{width: "100%", height: "100%", objectFit: "cover"}} />
            </Loop>
          </div>
        )}
        {click >= 0 && (
          <div style={{position: "absolute", left: pos[0] - 35, top: pos[1] - 35, width: 70, height: 70, borderRadius: 35,
            border: "3px solid #2f6bff", opacity: 1 - click, transform: `scale(${0.3 + click})`}} />
        )}
        <svg width={28} height={34} viewBox="0 0 28 34" style={{position: "absolute", left: pos[0] - 3, top: pos[1] - 2,
          transform: `scale(${1 / Math.sqrt(z)})`, transformOrigin: "3px 2px", filter: "drop-shadow(0 2px 3px rgba(0,0,0,.35))"}}>
          <path d="M3 2 L3 27 L9.5 21 L14 31 L18 29.2 L13.6 19.5 L22 19.5 Z" fill="#111" stroke="#fff" strokeWidth={2} strokeLinejoin="round" />
        </svg>
      </div>
      {s.banner && <Banner text={s.banner} />}
    </AbsoluteFill>
  );
};

const Banner: React.FC<{text: string}> = ({text}) => {
  const frame = useCurrentFrame();
  const o = interpolate(frame, [30, 45], [0, 1], clamp);
  return (
    <div style={{position: "absolute", top: 60, left: 0, right: 0, display: "flex", justifyContent: "center", opacity: o}}>
      <div style={{background: BLUE, color: "#fff", font: `600 44px ${FONT}`, padding: "18px 40px", borderRadius: 14}}>{text}</div>
    </div>
  );
};

/* ---------- non-screen scenes ---------- */
const ChipsScene: React.FC<{s: Scene}> = ({s}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return (
    <AbsoluteFill style={{background: "#fff", alignItems: "center", justifyContent: "center", fontFamily: FONT, gap: 50}}>
      <div style={{font: `700 64px ${FONT}`, color: INK, opacity: interpolate(frame, [0, 15], [0, 1], clamp)}}>{s.title}</div>
      <div style={{display: "flex", gap: 30}}>
        {(s.chips ?? []).map((c, i) => {
          const p = spring({frame: frame - 15 - i * 12, fps, config: {damping: 200}});
          return (
            <div key={c} style={{border: `3px solid ${BLUE}`, color: BLUE, font: `600 40px ${FONT}`, padding: "18px 38px",
              borderRadius: 999, opacity: p, transform: `translateY(${(1 - p) * 30}px)`}}>{c}</div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const DemoScene: React.FC<{s: Scene}> = ({s}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const cut = Math.round(5.5 * fps);
  const o = interpolate(frame, [cut, cut + 20], [0, 1], clamp);
  const label = (text: string, op: number) => (
    <div style={{position: "absolute", top: 50, left: 60, background: "rgba(12,16,24,0.78)", color: "#fff",
      font: `600 34px ${FONT}`, padding: "10px 24px", borderRadius: 10, opacity: op}}>{text}</div>
  );
  return (
    <AbsoluteFill style={{background: "#000"}}>
      <OffthreadVideo src={staticFile("assets/demo_raw.mp4")} muted style={{width: W, height: H, objectFit: "cover"}} />
      <AbsoluteFill style={{opacity: o}}>
        <Sequence from={cut} layout="none">
          <Loop durationInFrames={Math.round(11 * fps)}>
            <OffthreadVideo src={staticFile("assets/demo_overlay.mp4")} muted style={{width: W, height: H, objectFit: "cover"}} />
          </Loop>
        </Sequence>
      </AbsoluteFill>
      {label("Raw phone clip", 1 - o)}
      {label("Hand, objects and gripper path tracked", o)}
    </AbsoluteFill>
  );
};

const ImageScene: React.FC<{s: Scene}> = ({s}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const z = interpolate(frame, [0, s.duration * fps], [1, 1.07], clamp);
  return (
    <AbsoluteFill style={{background: "#fff", alignItems: "center", justifyContent: "center"}}>
      <Img src={staticFile(s.image!)} style={{width: "82%", maxHeight: "80%", objectFit: "contain", transform: `scale(${z})`}} />
      {s.badge && (
        <div style={{position: "absolute", top: 50, right: 60, border: `3px solid ${BLUE}`, color: BLUE, font: `700 34px ${FONT}`,
          padding: "8px 26px", borderRadius: 999, letterSpacing: "0.04em"}}>{s.badge.toUpperCase()}</div>
      )}
    </AbsoluteFill>
  );
};

const LoopScene: React.FC<{s: Scene}> = ({s}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const steps = ["Attack breaks the policy", "Adversary explains why", "Rule for the generator", "Policy rewritten", "Gate: keep only if nothing got worse"];
  const R = 330, cx0 = W / 2 - 180, cy0 = H / 2 + 10;
  const per = Math.max(1.6, (s.duration - 4) / steps.length);
  const human = interpolate(frame, [(steps.length * per) * fps, (steps.length * per + 0.6) * fps], [0, 1], clamp);
  return (
    <AbsoluteFill style={{background: "#fff", fontFamily: FONT}}>
      <svg width={W} height={H} style={{position: "absolute"}}>
        <circle cx={cx0} cy={cy0} r={R} fill="none" stroke="#d5dde6" strokeWidth={4} strokeDasharray="12 10" />
      </svg>
      {steps.map((txt, i) => {
        const a = -Math.PI / 2 + (i * 2 * Math.PI) / steps.length;
        const p = spring({frame: frame - i * per * fps, fps, config: {damping: 200}});
        const gate = i === steps.length - 1;
        return (
          <div key={txt} style={{position: "absolute", left: cx0 + R * Math.cos(a) - 170, top: cy0 + R * Math.sin(a) - 48, width: 340,
            minHeight: 96, display: "flex", alignItems: "center", justifyContent: "center", textAlign: "center", padding: "10px 16px",
            background: "#fff", border: `3px solid ${gate ? INK : i === 0 ? RED : BLUE}`, borderRadius: 16,
            color: gate ? INK : i === 0 ? RED : BLUE, font: `600 30px ${FONT}`, opacity: p, transform: `scale(${0.85 + 0.15 * p})`}}>{txt}</div>
        );
      })}
      <div style={{position: "absolute", left: cx0 + R + 260, top: cy0 - 90, width: 420, opacity: human, border: `3px dashed ${MUTED}`,
        borderRadius: 16, padding: "20px 24px", color: INK, font: `500 30px/1.35 ${FONT}`}}>
        Same failure comes back 3 times?<br /><b>ants asks a person.</b> The answer becomes a new rule.
      </div>
    </AbsoluteFill>
  );
};

const Caption: React.FC<{text: string; duration: number}> = ({text, duration}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const o = Math.min(interpolate(frame, [8, 20], [0, 1], clamp), interpolate(frame, [duration * fps - 12, duration * fps], [1, 0], clamp));
  return (
    <div style={{position: "absolute", left: 0, right: 0, bottom: 56, display: "flex", justifyContent: "center", opacity: o}}>
      <div style={{maxWidth: 1400, padding: "16px 32px", borderRadius: 14, background: "rgba(12,16,26,0.86)", color: "#fff",
        font: `500 36px/1.3 ${FONT}`, textAlign: "center"}}>{text}</div>
    </div>
  );
};

const SceneView: React.FC<{s: Scene}> = ({s}) => {
  switch (s.kind) {
    case "card": return <TitleCard line={s.card === "close" ? "Show once. Break smart." : ""} />;
    case "problem": return <Problem />;
    case "chips": return <ChipsScene s={s} />;
    case "demo": return <DemoScene s={s} />;
    case "image": return <ImageScene s={s} />;
    case "loop": return <LoopScene s={s} />;
    default: return <ScreenScene s={s} />;
  }
};

const NO_CAPTION = new Set(["card", "problem", "chips"]);

export const Film: React.FC<{film: FilmData}> = ({film}) => {
  const {fps} = useVideoConfig();
  return (
    <AbsoluteFill style={{background: "#fff"}}>
      {film.scenes.map((s) => {
        const from = Math.round(s.start * fps), len = Math.round(s.duration * fps);
        return (
          <Sequence key={s.id} from={from} durationInFrames={len}>
            <SceneView s={s} />
            {s.caption && !NO_CAPTION.has(s.kind) && <Caption text={s.caption} duration={s.duration} />}
            {s.voice && <Sequence from={Math.round(0.3 * fps)} layout="none"><Audio src={staticFile(s.voice)} /></Sequence>}
          </Sequence>
        );
      })}
      {film.music && <Audio src={staticFile(film.music)} volume={0.08} />}
    </AbsoluteFill>
  );
};

export const filmFrames = (f: FilmData) => Math.ceil(f.duration * f.fps);
