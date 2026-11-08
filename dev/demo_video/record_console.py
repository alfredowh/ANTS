"""Long raw takes of the live ants Studio console (no model calls, no tokens):

    prompt   type the task, attach the phone clip, open the settings dialog, hold on each field,
             cancel (no run starts)
    deploy   type /deploy and send it (copies the incumbent program to data/deploy/)

Each take holds 3-5 s on every element and logs every element box in timeline.json, so the
final cut, zoom and timing are chosen later in Remotion without recording again.

    uv run python dev/demo_video/record_console.py prompt deploy
    -> data/demo_video/clips/<take>/raw.mp4 + timeline.json
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

CLIPS = REPO / "data" / "demo_video" / "clips"
CLIP = REPO / "hurobo" / "data" / "raw" / "e1" / "clips" / "20261016_233859.mp4"
PORT = 58961
TASK = "put the bowl on the plate"


def take_prompt(rec: Recorder) -> None:
    page = rec.page
    rec.begin()
    rec.mark("wide")
    rec.wait(3)
    rec.click("chip_policy_dev", "text=/policy-dev")
    rec.wait(1)
    page.locator("#chat-input, textarea").first.press("End")
    page.keyboard.type(TASK, delay=70)
    rec.mark("typed_task", "#chat-input, textarea")
    rec.wait(2.5)
    rec.click("attach_clip", "#chat-attach")
    page.wait_for_timeout(2500)
    rec.mark("clip_chip", "text=20261016_233859")
    rec.wait(3)
    if page.locator("text=Human demonstration").first.is_visible():
        rec.mark("demo_panel", "text=Human demonstration")
        rec.wait(4)
    else:
        print("demo panel not visible")
    rec.click("send", "text=Send")
    page.wait_for_selector("#set-run", timeout=10000)
    rec.wait(1)
    dialog = "#set-run >> xpath=ancestor::*[contains(@class,'modal') or @role='dialog'][1]"
    rec.mark("settings_dialog", dialog)
    rec.wait(3)
    labels = page.locator(".modal label, [role=dialog] label")
    for i in range(min(labels.count(), 12)):
        el = labels.nth(i)
        try:
            el.scroll_into_view_if_needed(timeout=1000)
            b = el.bounding_box()
        except Exception:
            continue
        if b:
            box = {k: round(b[k]) for k in ("x", "y", "width", "height")}
            ev = {"name": f"setting_{i}", "kind": "mark", "t": round(rec.now(), 3)}
            rec.events.append({**ev, "text": el.inner_text()[:60], "box": box})
            rec.wait(2.5)
    rec.mark("run_button", "#set-run")
    rec.wait(2.5)
    rec.click("cancel", "#set-cancel")
    rec.wait(3)
    rec.mark("wide_end")
    rec.wait(2)


def take_deploy(rec: Recorder) -> None:
    page = rec.page
    rec.begin()
    rec.mark("wide")
    rec.wait(3)
    rec.click("chip_deploy", "text=/deploy")
    rec.wait(1.5)
    rec.mark("typed_deploy", "#chat-input, textarea")
    rec.wait(2)
    rec.click("send", "text=Send")
    page.wait_for_timeout(2500)
    reply = page.locator(".wizard-turn").last
    if reply.count() and reply.is_visible():
        rec.mark("deploy_reply", ".wizard-turn >> nth=-1")
    rec.wait(5)
    rec.mark("wide_end")
    rec.wait(2)


TAKES = {"prompt": take_prompt, "deploy": take_deploy}


def answer_pick(route) -> None:
    """Answer /pick-video as the native file dialog would, so no dialog opens on the desktop."""
    route.fulfill(json={"ok": True, "path": str(CLIP), "name": CLIP.name})


def main(names: list[str]) -> None:
    threading.Thread(
        target=console_server.serve, kwargs={"port": PORT, "sessions_dir": None}, daemon=True
    ).start()
    time.sleep(1.5)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/google-chrome")
        for name in names:
            page = browser.new_page(
                viewport={"width": W, "height": H}, color_scheme="light", device_scale_factor=DSF
            )
            page.route("**/pick-video", answer_pick)
            page.goto(f"http://127.0.0.1:{PORT}")
            page.click("[data-view=synthesizer]")
            page.wait_for_timeout(1500)
            out = CLIPS / name
            out.mkdir(parents=True, exist_ok=True)
            rec = Recorder(page, out)
            TAKES[name](rec)
            rec.end(out)
            page.close()
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:] or list(TAKES))
