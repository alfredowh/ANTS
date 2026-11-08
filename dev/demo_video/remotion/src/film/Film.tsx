import React from "react";
import {
  AbsoluteFill, Audio, Easing, Freeze, Img, interpolate, Loop, OffthreadVideo, Sequence, spring,
  staticFile, useCurrentFrame, useVideoConfig,
} from "remotion";
import {BLUE, FONT, INK, Logo, MUTED, RED} from "../scenes/common";
import {Problem} from "../scenes/Problem";
import {TitleCard} from "../scenes/TitleCard";
import {FLOWS, FlowScene, LoopScene, ResultScene} from "./Motion";

type Box = {x: number; y: number; width: number; height: number};
type Ev = {name: string; kind: string; t: number; box?: Box};
export type Scene = {
  id: string; kind: string; start: number; duration: number; caption?: string; voice?: string | null;
  card?: string; flow?: string; chips?: string[]; title?: string; image?: string; badge?: string; banner?: string;
  clip?: string; segs?: number[][]; rate?: number;
  insert?: {at: number; dur: number; per: number; clips: [string, string][]}; claim?: {text: string; from_end: number}; cam?: [string, number][]; pip?: Box; clicks?: string[];
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
    const p = interpolate(t, [at - 0.55, at], [0, 1], {...clamp, easing: ease});
    if (p === 0) break;
    const [tx, ty] = center(e.box);
    z += (zoom - z) * p; cx += (tx - cx) * p; cy += (ty - cy) * p;
  }
  z *= 1 + Math.min(0.06, 0.012 * t); // slow continuous push-in
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

  // floating 3D window: tilted and inset when wide, flat and full when zoomed in (readable)
  const flat = interpolate(z, [1, 1.55], [0, 1], clamp);
  const win = 0.86 + 0.14 * flat;
  const ry = interpolate(t, [0, s.duration], [-7, 5]) * (1 - flat);
  const rx = 5 * (1 - flat);
  const clicks = events.filter((e) => (e.kind === "click" || (s.clicks ?? []).includes(e.name)) && outOf(segs, e.t, rate) !== null);
  return (
    <AbsoluteFill style={{background: "radial-gradient(ellipse at 30% 20%, #ffffff 0%, #e9f0fb 55%, #d9e4f5 100%)", overflow: "hidden", perspective: 2600}}>
      {clicks.map((e) => (
        <Sequence key={e.name} from={Math.round((outOf(segs, e.t, rate) ?? 0) * fps)} layout="none"><Audio src={staticFile("film/sfx/click.wav")} volume={0.6} /></Sequence>
      ))}
      <div style={{position: "absolute", left: 0, top: 0, width: W, height: H, overflow: "hidden", borderRadius: 22 * (1 - flat),
        transform: `scale(${win}) rotateY(${ry}deg) rotateX(${rx}deg)`, transformOrigin: "50% 50%",
        boxShadow: `0 ${40 * (1 - flat)}px ${90 * (1 - flat)}px rgba(20,40,80,${0.28 * (1 - flat)})`, background: "#fff"}}>
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
      </div>
      {s.insert && <Insert ins={s.insert} total={s.duration} />}
      {s.claim && <Claim text={s.claim.text} at={s.duration - s.claim.from_end} />}
      {s.banner && <Banner text={s.banner} />}
    </AbsoluteFill>
  );
};

/** Real footage inside a tilted frame over the blurred screen: one clip, or a beat montage. */
const Insert: React.FC<{ins: NonNullable<Scene["insert"]>; total: number}> = ({ins, total}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const end = Math.min(total, ins.at + ins.dur);
  if (t < ins.at - 0.4 || t > end + 0.4) return null;
  const o = Math.min(interpolate(t, [ins.at - 0.3, ins.at], [0, 1], clamp), interpolate(t, [end - 0.25, end], [1, 0], clamp));
  const k = Math.min(ins.clips.length - 1, Math.max(0, Math.floor((t - ins.at) / ins.per)));
  const [src, label] = ins.clips[k];
  const local = Math.max(0, t - ins.at - k * ins.per);
  const pop = interpolate(local, [0, 0.18], [1.04, 1], clamp);
  const ry = interpolate(t, [ins.at, end], [6, -6]);
  return (
    <AbsoluteFill style={{opacity: o, backdropFilter: "blur(18px)", background: "rgba(232,239,250,0.55)", alignItems: "center", justifyContent: "center", perspective: 2400}}>
      {ins.clips.length > 1 && ins.clips.map((_, i) => (
        <Sequence key={i} from={Math.round((ins.at + i * ins.per) * fps)} layout="none"><Audio src={staticFile("film/sfx/tick.wav")} volume={0.5} /></Sequence>
      ))}
      <div style={{width: 1240, height: 794, borderRadius: 20, overflow: "hidden", transform: `rotateY(${ry}deg) rotateX(4deg) scale(${pop})`,
        boxShadow: "0 40px 90px rgba(20,40,80,0.35)", background: "#000"}}>
        <Sequence from={Math.round((ins.at + k * ins.per) * fps)} layout="none">
          <OffthreadVideo src={staticFile(src)} startFrom={Math.round(4 * fps)} muted style={{width: "100%", height: "100%", objectFit: "cover"}} />
        </Sequence>
      </div>
      {label && (
        <div style={{marginTop: 34, background: INK, color: "#fff", font: `700 44px ${FONT}`, padding: "12px 34px", borderRadius: 999}}>{label}</div>
      )}
    </AbsoluteFill>
  );
};

/** One big claim line over the shot, with a chime. */
const Claim: React.FC<{text: string; at: number}> = ({text, at}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = spring({frame: frame - Math.round(at * fps), fps, config: {damping: 14, mass: 0.6}});
  if (frame < at * fps) return null;
  return (
    <AbsoluteFill style={{alignItems: "center", justifyContent: "center", background: `rgba(255,255,255,${0.72 * Math.min(1, p)})`, backdropFilter: `blur(${10 * Math.min(1, p)}px)`}}>
      <Sequence from={Math.round(at * fps)} layout="none"><Audio src={staticFile("film/sfx/chime.wav")} volume={0.55} /></Sequence>
      <div style={{font: `800 118px ${FONT}`, color: INK, letterSpacing: "-0.02em", transform: `scale(${0.8 + 0.2 * p})`, opacity: Math.min(1, p)}}>{text}</div>
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

const SceneView: React.FC<{s: Scene}> = ({s}) => {
  switch (s.kind) {
    case "card": return <TitleCard line={s.card === "close" ? "Show once. Break smart." : ""} />;
    case "problem": return <Problem />;
    case "chips": return <ChipsScene s={s} />;
    case "demo": return <DemoScene s={s} />;
    case "image": return <ImageScene s={s} />;
    case "loop": return <LoopScene duration={s.duration} />;
    case "result": return <ResultScene duration={s.duration} />;
    case "flow": return <FlowScene flow={FLOWS[s.flow!]} duration={s.duration} />;
    default: return <ScreenScene s={s} />;
  }
};


/** Whip transition: each scene slides and blurs in, and out, so no cut is static. */
const Whip: React.FC<{len: number; dir: number; children: React.ReactNode}> = ({len, dir, children}) => {
  const frame = useCurrentFrame();
  const inP = interpolate(frame, [0, 9], [1, 0], {...clamp, easing: Easing.out(Easing.cubic)});
  const outP = interpolate(frame, [len - 8, len], [0, 1], {...clamp, easing: Easing.in(Easing.cubic)});
  const dx = (inP * 0.35 - outP * 0.35) * W * dir;
  const blur = 26 * Math.max(inP, outP);
  return <AbsoluteFill style={{transform: `translateX(${dx}px)`, filter: blur > 0.5 ? `blur(${blur}px)` : undefined}}>{children}</AbsoluteFill>;
};

export const Film: React.FC<{film: FilmData; withMusic?: boolean}> = ({film, withMusic = true}) => {
  const {fps} = useVideoConfig();
  return (
    <AbsoluteFill style={{background: "#fff"}}>
      {film.scenes.map((s, i) => {
        const from = Math.round(s.start * fps), len = Math.round(s.duration * fps);
        const prev = film.scenes[i - 1];
        const whoosh = i > 0 && prev.kind !== s.kind;
        return (
          <Sequence key={s.id} from={from} durationInFrames={len}>
            <Whip len={len} dir={i % 2 ? -1 : 1}><SceneView s={s} /></Whip>
            {s.voice && <Sequence from={Math.round(0.3 * fps)} layout="none"><Audio src={staticFile(s.voice)} /></Sequence>}
            {whoosh && <Audio src={staticFile("film/sfx/whoosh.wav")} volume={0.45} />}
            {s.kind === "card" && <Audio src={staticFile("film/sfx/sting.wav")} volume={0.5} />}
          </Sequence>
        );
      })}
      {withMusic && film.music && <Audio src={staticFile(film.music)} volume={0.14} />}
    </AbsoluteFill>
  );
};

export const filmFrames = (f: FilmData) => Math.ceil(f.duration * f.fps);
