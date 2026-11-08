import React from "react";
import {AbsoluteFill, Easing, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {BLUE, FONT, INK, Logo, MUTED} from "./common";

export type TitleCardProps = {line?: string; subtitle?: string};

/** White title card: logo, title, subtitle, then one line at ~2 s. Used for `logo` and `close`. */
export const TitleCard: React.FC<TitleCardProps> = ({line = "", subtitle = "Making Agentic Physical AI Production-Ready"}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const pop = spring({frame, fps, config: {damping: 14, mass: 0.8}});
  const fade = (start: number, len = 0.6) =>
    interpolate(frame, [start * fps, (start + len) * fps], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic)});
  const rise = (start: number) => (1 - fade(start)) * 24;
  const out = interpolate(frame, [durationInFrames - 0.5 * fps, durationInFrames], [1, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <AbsoluteFill style={{backgroundColor: "#ffffff", fontFamily: FONT, alignItems: "center", justifyContent: "center", opacity: out}}>
      <div style={{display: "flex", flexDirection: "column", alignItems: "center", gap: 34}}>
        <div style={{opacity: fade(0, 0.5), transform: `scale(${0.6 + 0.4 * pop})`}}>
          <Logo width={300} />
        </div>
        <div style={{opacity: fade(0.5), transform: `translateY(${rise(0.5)}px)`, fontSize: 76, fontWeight: 700, color: INK, letterSpacing: "-0.01em"}}>
          Adversarial Agentic Task Synthesis
        </div>
        <div style={{opacity: fade(0.9), transform: `translateY(${rise(0.9)}px)`, fontSize: 36, fontWeight: 500, color: MUTED}}>
          {subtitle}
        </div>
        {line && (
          <div style={{marginTop: 30, opacity: fade(2), transform: `translateY(${rise(2)}px)`, fontSize: 44, fontWeight: 600, color: BLUE}}>
            {line}
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};
