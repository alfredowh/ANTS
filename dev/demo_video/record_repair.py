"""Clip 1: one /policy-dev run repairs its own program (5 attempts, 4 failures, then a pass).

Replays the logged run data/runs/exp03_explain/clip_233859 in ANTS Studio, drives the page with
Playwright, and writes into data/demo_video/clips/repair/:

    raw.mp4        the screen, 1920x1080, 30 fps, no cursor or zoom
    timeline.json  every action: time (s), element box (px), kind; Remotion turns it into the
                   cursor, clicks and zoom (dev/demo_video/remotion)

    uv run python dev/demo_video/record_repair.py
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from studio_replay import REPO, Replay, start  # noqa: E402

SOURCE = REPO / "data" / "runs" / "exp03_explain" / "clip_233859" / ""
# HOLD stretches every pause (long raw takes); CLIP names the output folder
HOLD = float(os.environ.get("HOLD", "1"))
# DSF records at that device pixel ratio (2 = 3840x2160 video); boxes stay in CSS pixels
DSF = int(os.environ.get("DSF", "2"))
OUT = REPO / "data" / "demo_video" / "clips" / os.environ.get("CLIP", "repair")
PORT = 58932
W, H, FPS = 1920, 1080, 30


class Recorder:
    def __init__(self, page: Page, out: Path) -> None:
        self.page, self.frames_dir = page, out / "frames"
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        for f in self.frames_dir.glob("*.jpg"):
            f.unlink()
        self.frames: list[tuple[float, Path]] = []
        self.events: list[dict] = []
        self.t0: float | None = None
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._frame)

    def _frame(self, p: dict) -> None:
        ts = p["metadata"]["timestamp"]
        if self.t0 is None:
            self.t0 = ts
        path = self.frames_dir / f"{len(self.frames):05d}.jpg"
        path.write_bytes(base64.b64decode(p["data"]))
        self.frames.append((ts - self.t0, path))
        self.cdp.send("Page.screencastFrameAck", {"sessionId": p["sessionId"]})

    def begin(self) -> None:
        self.cdp.send(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": 92,
                "maxWidth": W * DSF,
                "maxHeight": H * DSF,
                "everyNthFrame": 1,
            },
        )
        self.wall0 = time.monotonic()
        self.wait(0.3)

    def now(self) -> float:
        return time.monotonic() - self.wall0

    def wait(self, s: float) -> None:
        self.page.wait_for_timeout(int(s * HOLD * 1000))

    def box(self, selector: str) -> dict:
        b = self.page.locator(selector).first.bounding_box()
        return {k: round(b[k]) for k in ("x", "y", "width", "height")}

    def mark(self, name: str, selector: str | None = None, kind: str = "mark") -> None:
        ev = {"name": name, "kind": kind, "t": round(self.now(), 3)}
        if selector:
            ev["box"] = self.box(selector)
        self.events.append(ev)

    def click(self, name: str, selector: str, travel: float = 0.9) -> None:
        """Pause for the (virtual) cursor to travel, then click for real."""
        self.page.locator(selector).first.scroll_into_view_if_needed()
        self.wait(travel)
        self.mark(name, selector, kind="click")
        self.page.locator(selector).first.click()

    def scroll_to(self, selector: str, block: str = "start") -> None:
        self.page.locator(selector).first.evaluate(
            f"e => e.scrollIntoView({{behavior: 'smooth', block: '{block}'}})"
        )
        self.wait(0.9)

    def end(self, out: Path) -> None:
        self.wait(0.5)
        self.cdp.send("Page.stopScreencast")
        total = self.now()
        # concat list: each frame held until the next one (screencast only sends changes)
        lines = []
        for i, (t, path) in enumerate(self.frames):
            nxt = self.frames[i + 1][0] if i + 1 < len(self.frames) else total
            lines += [f"file '{path.name}'", f"duration {max(nxt - t, 1 / FPS):.4f}"]
        lines.append(f"file '{self.frames[-1][1].name}'")
        (self.frames_dir / "list.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", "list.txt", "-vf", f"fps={FPS},scale={W * DSF}:{H * DSF}", "-c:v", "libx264",
             "-crf", "16", "-pix_fmt", "yuv420p", str(out / "raw.mp4")],
            cwd=self.frames_dir, check=True,
        )  # fmt: skip
        timeline = {"width": W, "height": H, "fps": FPS, "pixel_ratio": DSF,
                    "duration": round(total, 3), "source_run": str(SOURCE.relative_to(REPO)),
                    "events": self.events}  # fmt: skip
        (out / "timeline.json").write_text(json.dumps(timeline, indent=1), encoding="utf-8")
        print(f"{out / 'raw.mp4'}  {total:.1f} s, {len(self.frames)} frames, "
              f"{len(self.events)} events")  # fmt: skip


def reveal(rec: Recorder, replay: Replay, attempt: int) -> str:
    replay.show_through_attempt(attempt)
    rec.page.evaluate("window.attemptsEvent({kind: 'pipeline_stage', stage: 'generate'})")
    sel = f"#attempt-turn-demo-{attempt}"
    rec.page.wait_for_selector(sel)
    rec.wait(0.2)
    return sel


def collapse(rec: Recorder, sel: str) -> None:
    rec.page.evaluate(f"document.querySelectorAll('{sel} details').forEach(d => d.open = false)")


def script(rec: Recorder, replay: Replay) -> None:
    page = rec.page
    rec.begin()
    rec.mark("wide")
    rec.wait(1.5)
    rec.click("click_policy_dev_chip", "text=/policy-dev")  # fills the input; nothing is sent
    rec.wait(0.8)
    page.locator("textarea, input[type=text]").first.fill("")
    rec.mark("start_run")

    # attempt 0: initial program fails
    a0 = reveal(rec, replay, 0)
    rec.scroll_to(a0)
    rec.mark("a0_result", f"{a0} .chipx")
    rec.wait(2.0)
    collapse(rec, a0)

    # attempt 1: first repair, show why + diff
    a1 = reveal(rec, replay, 1)
    rec.scroll_to(a1)
    rec.mark("a1_head", f"{a1} .att > b")
    rec.wait(1.2)
    rec.mark("a1_why", f"{a1} details:nth-of-type(1) pre")
    rec.wait(3.0)
    rec.mark("a1_diff", f"{a1} details:nth-of-type(2) summary")
    rec.scroll_to(f"{a1} details:nth-of-type(2) pre", block="center")
    rec.mark("a1_diff_body", f"{a1} details:nth-of-type(2) pre")
    rec.wait(2.5)
    rec.click("a1_open_feedback", f"{a1} details:last-of-type summary")
    rec.wait(0.6)
    rec.scroll_to(f"{a1} details:last-of-type pre", block="center")
    rec.mark("a1_feedback", f"{a1} details:last-of-type pre")
    rec.wait(2.5)
    collapse(rec, a1)

    # attempts 2, 3: still failing, quick
    for k in (2, 3):
        a = reveal(rec, replay, k)
        rec.scroll_to(a)
        rec.mark(f"a{k}_result", f"{a} .chipx")
        rec.wait(1.3)
        collapse(rec, a)

    # attempt 4: passes
    a4 = reveal(rec, replay, 4)
    rec.scroll_to(a4)
    rec.mark("a4_result", f"{a4} .chipx")
    rec.wait(2.5)
    rec.page.wait_for_function(f"document.querySelector('{a4} img.att-gif')?.naturalWidth > 0")
    rec.scroll_to(f"{a4} img.att-gif", block="center")
    rec.mark("a4_rollout", f"{a4} img.att-gif")
    rec.wait(5.0)
    rec.mark("wide_end")
    rec.wait(2.0)
    rec.end(OUT)


def main() -> None:
    replay = Replay(SOURCE, REPO / "data" / "demo_video" / "replay_run")
    replay.show_through_attempt(-1)
    start(replay, PORT, "put the bowl on the plate")
    time.sleep(1.5)
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/google-chrome")
        page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=DSF)
        page.goto(f"http://127.0.0.1:{PORT}")
        page.click("[data-view=synthesizer]")
        page.wait_for_timeout(2000)
        script(Recorder(page, OUT), replay)
        browser.close()


if __name__ == "__main__":
    main()
