import React from "react";
import {AbsoluteFill, Easing, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from "remotion";

/** Intro: the official hackathon image, unchanged (prize/date area left empty), with simple motion:
 *  title lines rise in one by one, the Meta logo fades in, dots and lines reveal from the star's node,
 *  slow push-in, fade out. Every layer is a strip of the same image; nothing is redrawn. */
const BG = "rgb(30,45,52)";
const S = 1080; // image size on screen (square), centred in 1920x1080
const SRC = "assets/hackathon_clean.png"; // 1080x1080, original pixels upscaled
const NODE = {x: 845, y: 691}; // centre of the blue star, image pixels
const clamp = {extrapolateLeft: "clamp", extrapolateRight: "clamp"} as const;

// [top, bottom, left, right] in image pixels
const TITLE = [[95, 190], [200, 312], [313, 405]];
const LOGO = [95, 160, 800, 990];
const LOWER_TOP = 406;

const Strip: React.FC<{t: number; b: number; l?: number; r?: number; style?: React.CSSProperties}> = ({t, b, l = 0, r = S, style}) => (
  <div style={{position: "absolute", left: l, top: t, width: r - l, height: b - t, overflow: "hidden", ...style}}>
    <Img src={staticFile(SRC)} style={{position: "absolute", left: -l, top: -t, width: S, height: S}} />
  </div>
);

export const HackathonIntro: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const push = interpolate(frame, [0, durationInFrames], [1, 1.04]);
  const out = interpolate(frame, [durationInFrames - 0.6 * fps, durationInFrames], [1, 0], clamp);
  const reveal = interpolate(frame, [1.1 * fps, 3.2 * fps], [0, 1], {...clamp, easing: Easing.out(Easing.cubic)});
  const r = reveal * 1150; // reveal radius from the node
  const mask = `radial-gradient(circle at ${NODE.x}px ${NODE.y - LOWER_TOP}px, #000 ${Math.max(0, r - 160)}px, transparent ${r}px)`;
  return (
    <AbsoluteFill style={{background: BG, opacity: out}}>
      <div style={{position: "absolute", left: (1920 - S) / 2, top: 0, width: S, height: S, transform: `scale(${push})`, transformOrigin: `${NODE.x}px ${NODE.y}px`}}>
        <Strip t={LOWER_TOP} b={S} style={{WebkitMaskImage: mask, maskImage: mask}} />
        {TITLE.map(([t, b], i) => {
          const p = spring({frame: frame - 6 - i * 8, fps, config: {damping: 200}});
          return <Strip key={i} t={t} b={b} style={{opacity: p, transform: `translateY(${(1 - p) * 34}px)`}} />;
        })}
        <Strip t={LOGO[0]} b={LOGO[1]} l={LOGO[2]} r={LOGO[3]} style={{opacity: interpolate(frame, [28, 42], [0, 1], clamp)}} />
      </div>
    </AbsoluteFill>
  );
};
