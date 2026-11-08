import {Film, filmFrames, FilmData} from "./film/Film";
import filmData from "../public/film/film.json";
import {Composition} from "remotion";
import {Clip, clipDuration, ClipProps} from "./Clip";
import repairShots from "./shots/repair.json";
import repairTimeline from "../public/repair/timeline.json";
import repairVoice from "../public/repair/voice.json";
import {TitleCard} from "./scenes/TitleCard";
import {Problem, PROBLEM_SECONDS} from "./scenes/Problem";

// One <Composition> per clip. Edit src/shots/<clip>.json; Studio reloads on save.
const clips: ClipProps[] = [{name: "repair", shots: repairShots, timeline: repairTimeline, voice: repairVoice} as ClipProps];

export const Root = () => (
  <>
    {clips.map((c) => (
      <Composition
        key={c.name}
        id={c.name}
        component={Clip}
        defaultProps={c}
        fps={c.timeline.fps}
        width={c.timeline.width}
        height={c.timeline.height}
        durationInFrames={clipDuration(c)}
      />
    ))}
    <Composition id="logo" component={TitleCard} defaultProps={{line: ""}} fps={30} width={1920} height={1080} durationInFrames={150} />
    <Composition id="problem" component={Problem} fps={30} width={1920} height={1080} durationInFrames={PROBLEM_SECONDS * 30} />
    <Composition id="film" component={Film} defaultProps={{film: filmData as unknown as FilmData}} fps={30} width={1920} height={1080} durationInFrames={filmFrames(filmData as unknown as FilmData)} />
    <Composition id="close" component={TitleCard} defaultProps={{line: "Show once. Break smart."}} fps={30} width={1920} height={1080} durationInFrames={150} />
  </>
);
