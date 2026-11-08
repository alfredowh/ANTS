"""Long raw take of the Adversary tab (light theme, inside the console) on a logged run.

Default run: the closed-loop run on the real LIBERO simulator (2 attacks, Muse Spark off). Walks
Harden (attacks, outcome tiles, certification, attack log, usage), opens each attack in Replay
(videos playing, call timeline, robustness, why this attack), then Versions. Every section is held
3-5 s and its box logged, so zooms are chosen later. No model calls.

    uv run python dev/demo_video/record_adversary.py [run_dir]
    -> data/demo_video/clips/adversary/raw.mp4 + timeline.json
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent))
from record_repair import DSF, H, Recorder, W  # noqa: E402
from studio_replay import REPO  # noqa: E402

from ants.studio import console_server  # noqa: E402

RUN = REPO / "data/console_sessions/sess-20261104-213329/runs/run-20261104T214055"
OUT = REPO / "data" / "demo_video" / "clips" / "adversary"
PORT = 58962


class FrameRecorder(Recorder):
    """Boxes and clicks inside the Adversary iframe; boxes are in page (viewport) pixels."""

    frame = None

    def loc(self, selector: str):
        return self.frame.locator(selector).first

    def box(self, selector: str) -> dict:
        b = self.loc(selector).bounding_box()
        return {k: round(b[k]) for k in ("x", "y", "width", "height")}

    def mark(self, name: str, selector: str | None = None, kind: str = "mark") -> None:
        ev = {"name": name, "kind": kind, "t": round(self.now(), 3)}
        if selector:
            try:
                ev["box"] = self.box(selector)
            except Exception:
                print("no box:", name)
        self.events.append(ev)

    def click(self, name: str, selector: str, travel: float = 0.9) -> None:
        self.loc(selector).scroll_into_view_if_needed()
        self.wait(travel)
        self.mark(name, selector, kind="click")
        self.loc(selector).click()

    def show(self, name: str, selector: str, hold: float = 3.5) -> None:
        try:
            self.loc(selector).scroll_into_view_if_needed(timeout=2000)
        except Exception:
            print("missing:", name)
            return
        self.wait(0.6)
        self.mark(name, selector)
        self.wait(hold)


SECTION = "xpath=ancestor::*[self::section or self::div][1]"


def take(rec: FrameRecorder) -> None:
    rec.begin()
    rec.mark("wide")
    rec.wait(3)
    rec.show("run_title", "text=/hardening bowl-on-plate/")
    rec.show("loop_banner", "text=/LOOP STOPPED/i >> " + SECTION)
    rec.show("attacks_bar", "text=/^ATTACKS$/i >> " + SECTION)
    rec.show("outcome_tiles", "text=Rewrites accepted >> " + SECTION + " >> " + SECTION)
    rec.show("certification", "text=/^CERTIFICATION$/i >> " + SECTION, hold=5)
    rec.show("attack_log", "text=/^ATTACK LOG$/i >> " + SECTION, hold=4)
    rec.show("usage", "text=/^USAGE$/i >> " + SECTION)
    rec.click("tab_replay", "#tab-replay")
    rec.wait(2)
    for i in range(2):
        rec.show(f"attack_head_{i}", "text=/Attack #\\d/ >> nth=0")
        rec.show(f"videos_{i}", "text=/ROLLOUT VIDEO/i >> " + SECTION, hold=2)
        if rec.frame.locator("#pp").count():
            rec.click(f"play_{i}", "#pp")
        rec.wait(1)
        rec.show(f"timeline_{i}", "#tlarea", hold=6)
        rec.show(f"robustness_{i}", "text=/ROBUSTNESS OF/i >> " + SECTION, hold=4)
        rec.show(f"why_attack_{i}", "text=/WHY THIS ATTACK/i >> " + SECTION, hold=5)
        nxt = rec.frame.locator("text=/^#1$/").first
        if i == 0 and nxt.count():
            rec.click("open_attack_1", "text=/^#1$/")
            rec.wait(2)
    rec.click("tab_versions", "#tab-versions")
    rec.wait(2)
    rec.show("version_history", "text=/VERSION HISTORY/i >> " + SECTION, hold=4)
    rec.show("gate_decisions", "text=/GATE DECISIONS/i >> " + SECTION, hold=4)
    rec.click("tab_harden", "#tab-harden")
    rec.wait(2)
    rec.mark("wide_end")
    rec.wait(2)


def main() -> None:
    run = Path(sys.argv[1]) if len(sys.argv) > 1 else RUN
    threading.Thread(
        target=console_server.serve,
        kwargs={"port": PORT, "sessions_dir": None, "adversary_run": run},
        daemon=True,
    ).start()
    time.sleep(1.5)
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/google-chrome")
        page = browser.new_page(
            viewport={"width": W, "height": H}, color_scheme="light", device_scale_factor=DSF
        )
        page.goto(f"http://127.0.0.1:{PORT}")
        page.click("[data-view=adversary]")
        page.wait_for_timeout(3000)
        rec = FrameRecorder(page, OUT)
        rec.frame = next(f for f in page.frames if "/adversary/" in f.url)
        take(rec)
        rec.end(OUT)
        browser.close()


if __name__ == "__main__":
    main()
