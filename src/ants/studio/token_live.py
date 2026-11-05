"""What the token tracker shows while a model call is still running.

Real counts exist only when a call has ended: generation calls do not stream, and `muse exec`
output is read after the process exits. So this never produces a token count that could pass for a
real one. It knows which call is running and for how long, plus two rough sizes where the text is
really known: the first prompt, and the output of a streamed chat reply (about 4 characters per
token). `session_tokens` stays the only source of the real total.
"""

from __future__ import annotations

import threading
import time

CHARS_PER_TOKEN = 4
LABELS = {
    "generate": "Muse Wonder writing",
    "rewrite": "Muse Wonder rewriting",
    "chat": "chat reply",
}


class InFlight:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._call: dict | None = None
        self._first_prompt_chars: int | None = None

    def observe(self, event: dict) -> None:
        kind = event.get("kind")
        with self._lock:
            if kind == "pipeline_stage":
                self._stage(event)
            elif kind == "chat_muse_event":
                self._chat(event.get("event") or {})
            elif kind in ("chat_done", "chat_error"):
                if self._call and self._call["stage"] == "chat":
                    self._call = None
            elif kind in ("done", "error", "stop_requested", "session_reset"):
                self._call = None

    def _stage(self, event: dict) -> None:
        stage, status = event.get("stage"), event.get("status")
        if stage == "prompt" and status == "done":
            self._first_prompt_chars = event.get("chars")
        elif stage in ("generate", "rewrite"):
            if status == "started":
                self._call = {"stage": stage, "started": time.time()}
                if stage == "generate" and self._first_prompt_chars:
                    self._call["input_chars"] = self._first_prompt_chars
                    self._first_prompt_chars = None  # a repair's prompt size is not known here
            else:
                self._call = None

    def _chat(self, ev: dict) -> None:
        if self._call is None or self._call["stage"] != "chat":
            self._call = {"stage": "chat", "started": time.time(), "output_chars": 0}
        if ev.get("payload_type") == "run.output.delta":
            self._call["output_chars"] += len((ev.get("payload") or {}).get("text", ""))

    def snapshot(self, now: float | None = None) -> dict | None:
        """The running call, or None. `~` fields are rough sizes, never part of the real total."""
        with self._lock:
            call = dict(self._call) if self._call else None
        if call is None:
            return None
        out: dict = {
            "stage": call["stage"],
            "label": LABELS[call["stage"]],
            "elapsed_s": max(0, int((now or time.time()) - call["started"])),
        }
        if call.get("input_chars"):
            out["approx_input_tokens"] = call["input_chars"] // CHARS_PER_TOKEN
        if call.get("output_chars"):
            out["approx_output_tokens"] = call["output_chars"] // CHARS_PER_TOKEN
        return out
