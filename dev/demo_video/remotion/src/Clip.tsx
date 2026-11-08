import React from "react";
import {AbsoluteFill, Audio, Easing, Freeze, interpolate, OffthreadVideo, Sequence, staticFile, useCurrentFrame, useVideoConfig} from "remotion";

type Box = {x: number; y: number; width: number; height: number};
type Ev = {name: string; kind: string; t: number; box?: Box};
type Timeline = {width: number; height: number; fps: number; duration: number; events: Ev[]};
// "at" is an event name from timeline.json (or a number of seconds); "offset" shifts it.
type At = {at: string | number; offset?: number};
type CamKey = At & {zoom: number; ease?: number};
type Caption = {from: At; to: At; text: string; say?: string};
type Shots = {camera: CamKey[]; captions: Caption[]; cursor?: {move?: number; hide?: string[]}};
type VoiceLine = {caption: number; file: string; start: number; window: number; seconds: number};
type Voice = {lines: VoiceLine[]};
export type ClipProps = {name: string; shots: Shots; timeline: Timeline; voice?: Voice; voicePad?: number};

// Output time <-> source time. A section whose narration is longer than its window holds the
// recording's last frame of that section until the line ends (pad seconds of breathing room).
type Seg = {src0: number; src1: number; out0: number; out1: number};
export function sections(c: ClipProps): Seg[] {
  const pad = c.voicePad ?? 0.4;
  const lines = [...(c.voice?.lines ?? [])].sort((a, b) => a.start - b.start);
  const segs: Seg[] = [];
  let src = 0, out = 0;
  for (const l of lines) {
    if (l.start > src) { segs.push({src0: src, src1: l.start, out0: out, out1: out + l.start - src}); out += l.start - src; src = l.start; }
    const srcEnd = Math.min(l.start + l.window, c.timeline.duration);
    const len = Math.max(srcEnd - src, l.seconds + pad);
    segs.push({src0: src, src1: srcEnd, out0: out, out1: out + len});
    out += len; src = srcEnd;
  }
  if (src < c.timeline.duration) segs.push({src0: src, src1: c.timeline.duration, out0: out, out1: out + c.timeline.duration - src});
  return segs;
}
const toSrc = (segs: Seg[], t: number) => {
  const s = segs.find((x) => t < x.out1) ?? segs[segs.length - 1];
  return Math.min(s.src0 + (t - s.out0), s.src1 - 0.001);
};
const toOut = (segs: Seg[], src: number) => {
  const s = segs.find((x) => src < x.src1 + 1e-6) ?? segs[segs.length - 1];
  return s.out0 + (src - s.src0);
};

export const clipDuration = (c: ClipProps) => { const s = sections(c); return Math.ceil(s[s.length - 1].out1 * c.timeline.fps); };

const ev = (tl: Timeline, name: string) => {
  const e = tl.events.find((x) => x.name === name);
  if (!e) throw new Error(`no event "${name}" in timeline.json`);
  return e;
};
const time = (tl: Timeline, a: At) => (typeof a.at === "number" ? a.at : ev(tl, a.at).t) + (a.offset ?? 0);
const center = (tl: Timeline, a: At): [number, number] | null => {
  if (typeof a.at === "number") return null;
  const b = ev(tl, a.at).box;
  return b ? [b.x + b.width / 2, b.y + b.height / 2] : null;
};
const ease = Easing.bezier(0.65, 0, 0.35, 1);

function camera(tl: Timeline, keys: CamKey[], t: number) {
  const W = tl.width, H = tl.height;
  let s = 1, cx = W / 2, cy = H / 2;
  for (const k of keys) {
    const end = time(tl, k), dur = k.ease ?? 0.8;
    const p = interpolate(t, [end - dur, end], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease});
    if (p === 0) break;
    const [tx, ty] = center(tl, k) ?? [W / 2, H / 2];
    s += (k.zoom - s) * p; cx += (tx - cx) * p; cy += (ty - cy) * p;
  }
  const x = Math.min(0, Math.max(W - W * s, W / 2 - cx * s));
  const y = Math.min(0, Math.max(H - H * s, H / 2 - cy * s));
  return {s, x, y};
}

function cursor(tl: Timeline, shots: Shots, t: number) {
  const move = shots.cursor?.move ?? 0.7;
  const hide = new Set(shots.cursor?.hide ?? []);
  const pts = tl.events.filter((e) => e.box && !hide.has(e.name)).map((e) => ({t: e.t, p: center(tl, {at: e.name})!, click: e.kind === "click"}));
  let pos: [number, number] = [tl.width * 0.55, tl.height * 0.6];
  let click = -1;
  for (const q of pts) {
    const p = interpolate(t, [q.t - move, q.t], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease});
    pos = [pos[0] + (q.p[0] - pos[0]) * p, pos[1] + (q.p[1] - pos[1]) * p];
    if (q.click && t >= q.t && t < q.t + 0.6) click = (t - q.t) / 0.6;
  }
  return {pos, click};
}

export const Clip = (props: ClipProps) => {
  const {name, shots, timeline: tl, voice} = props;
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const segs = sections(props);
  const t = toSrc(segs, frame / fps);
  const cam = camera(tl, shots.camera, t);
  const cur = cursor(tl, shots, t);
  const cap = shots.captions.find((c) => t >= time(tl, c.from) && t < time(tl, c.to));
  // fade on output time, so a held section keeps its caption until the narration ends
  const outEnd = (src: number) => (segs.find((x) => src <= x.src1 + 1e-6) ?? segs[segs.length - 1]).out1;
  const tOut = frame / fps;
  const capOpacity = cap ? Math.min(1, (tOut - toOut(segs, time(tl, cap.from))) / 0.25, (outEnd(time(tl, cap.to)) - tOut) / 0.25) : 0;
  return (
    <AbsoluteFill style={{backgroundColor: "#0b0d12", overflow: "hidden"}}>
      <div style={{position: "absolute", width: tl.width, height: tl.height, transformOrigin: "0 0", transform: `translate(${cam.x}px, ${cam.y}px) scale(${cam.s})`}}>
        {segs.map((sg, i) => {
          const f0 = Math.round(sg.src0 * fps), f1 = Math.max(f0 + 1, Math.round(sg.src1 * fps));
          const o0 = Math.round(sg.out0 * fps), o1 = Math.round(sg.out1 * fps);
          const play = Math.min(f1 - f0, o1 - o0);
          const vid = {position: "absolute" as const, width: tl.width, height: tl.height};
          return (
            <React.Fragment key={i}>
              <Sequence from={o0} durationInFrames={Math.max(1, play)} layout="none">
                <OffthreadVideo src={staticFile(`${name}/raw.mp4`)} startFrom={f0} endAt={f1} style={vid} muted />
              </Sequence>
              {o1 - o0 > play && (
                <Sequence from={o0 + play} durationInFrames={o1 - o0 - play} layout="none">
                  <Freeze frame={f1 - 1}><OffthreadVideo src={staticFile(`${name}/raw.mp4`)} style={vid} muted /></Freeze>
                </Sequence>
              )}
            </React.Fragment>
          );
        })}
        {cur.click >= 0 && (
          <div style={{position: "absolute", left: cur.pos[0], top: cur.pos[1], width: 70, height: 70, marginLeft: -35, marginTop: -35, borderRadius: 35,
            border: "3px solid #2f6bff", opacity: 1 - cur.click, transform: `scale(${0.3 + cur.click})`}} />
        )}
        <svg width={28} height={34} viewBox="0 0 28 34" style={{position: "absolute", left: cur.pos[0] - 3, top: cur.pos[1] - 2,
          transform: `scale(${(cur.click >= 0 && cur.click < 0.3 ? 0.85 : 1) / Math.sqrt(cam.s)})`, transformOrigin: "3px 2px", filter: "drop-shadow(0 2px 3px rgba(0,0,0,.35))"}}>
          <path d="M3 2 L3 27 L9.5 21 L14 31 L18 29.2 L13.6 19.5 L22 19.5 Z" fill="#111" stroke="#fff" strokeWidth={2} strokeLinejoin="round" />
        </svg>
      </div>
      {cap && (
        <div style={{position: "absolute", left: 0, right: 0, bottom: 64, display: "flex", justifyContent: "center", opacity: capOpacity}}>
          <div style={{maxWidth: 1300, padding: "18px 34px", borderRadius: 16, background: "rgba(12,16,26,0.86)", color: "#fff",
            font: "500 38px/1.3 Inter, 'IBM Plex Sans', system-ui, sans-serif", textAlign: "center", boxShadow: "0 8px 30px rgba(0,0,0,.3)"}}>
            {cap.text}
          </div>
        </div>
      )}
      {(voice?.lines ?? []).map((l) => (
        <Sequence key={l.file} from={Math.round(toOut(segs, l.start) * fps)} layout="none">
          <Audio src={staticFile(`${name}/${l.file}`)} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
