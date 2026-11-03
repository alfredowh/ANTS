"""Thin wrapper around `muse exec`, Meta's own agentic CLI, run headlessly as a subprocess.

Unlike the Meta Model API (`ants.synthesizer.llm.ChatClient`), `muse exec --json` emits a JSONL
event stream that includes a real reasoning-token count per call and the full tool/task lifecycle
trace, not just a short prompted "WHY:" note. This module only runs one prompt and parses that
stream; nothing here decides what to ask or what to do with the reply.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

MUSE_MODEL = "muse-wonder-1.0"


class MuseCliError(RuntimeError):
    """`muse exec` exited non-zero, produced no terminal event, or did not complete."""


@dataclass
class MuseRunResult:
    text: str
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    cached_tokens: int
    events: list[dict] = field(default_factory=list)  # raw JSONL events, for the dashboard trace

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def run_muse(
    prompt: str,
    *,
    reasoning_effort: str = "high",
    max_model_steps: int | None = None,
    timeout_s: float = 300.0,
    muse_bin: str = "muse",
) -> MuseRunResult:
    """Run one headless `muse exec` turn and return its final text and token usage.

    No workspace is registered and no file/shell tools are granted: the prompt goes in as text and
    the reply comes back as text, the same blast radius as a Meta Model API call. A non-zero exit,
    a missing terminal event, or a terminal status other than "completed" raises `MuseCliError`.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as handle:
        handle.write(prompt)
        prompt_path = Path(handle.name)
    try:
        command = [
            muse_bin, "exec", "--json",
            "--prompt-file", str(prompt_path),
            "--reasoning-effort", reasoning_effort,
            "--approval-mode", "never",
        ]  # fmt: skip
        if max_model_steps is not None:
            command += ["--max-model-steps", str(max_model_steps)]
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired as exc:
            raise MuseCliError(f"muse exec exceeded {timeout_s}s") from exc
    finally:
        prompt_path.unlink(missing_ok=True)

    if proc.returncode != 0:
        raise MuseCliError(f"muse exec exited {proc.returncode}: {proc.stderr[-2000:]}")

    events: list[dict] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    terminal = next((e for e in events if e.get("payload_type") == "run.terminal.completed"), None)
    if terminal is None:
        raise MuseCliError(f"muse exec produced no terminal event: {proc.stderr[-2000:]}")
    if terminal["payload"].get("terminal") != "completed":
        raise MuseCliError(f"muse exec did not complete: {terminal['payload']}")

    usage = next((e for e in events if e.get("payload_type") == "run.usage"), None)
    model_usage = usage["payload"]["models"][0] if usage and usage["payload"].get("models") else {}

    return MuseRunResult(
        text=terminal["payload"].get("text", ""),
        input_tokens=int(model_usage.get("input_tokens", 0)),
        output_tokens=int(model_usage.get("output_tokens", 0)),
        reasoning_tokens=int(model_usage.get("reasoning_tokens", 0)),
        cached_tokens=int(model_usage.get("cached_tokens", 0)),
        events=events,
    )
