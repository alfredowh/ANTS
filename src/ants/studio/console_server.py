"""Live orchestrator console: a stdlib HTTP server around one `muse exec` repair step.

Static viewers in this repo (`dashboard.py`, `ants.studio.run`) all read a saved JSONL trace after
a run finished. This module is the live counterpart for one Phase A repair step: a person clicks
Run, confirms a gate ("ready to run the policy development phase?"), and the Muse Code task
lifecycle streams into the browser as it happens.

Deliberately does not import or edit `ants.orchestrator.muse_cli` / `muse_orchestrator`: those are
Daniel's package. This module only shells out to the same `muse exec --json` CLI those modules use,
reading its stdout line by line instead of waiting for the whole subprocess to finish, so the
console has no cross-package write coupling. Everything downstream (Phase A rules, the gate, the
regression check) still lives in `orchestrator/`; one click here only runs *one* repair step, not
the loop -- see docs/orchestrator/plan-muse-code-orchestrator.md for why that is the right scope
for v1.
"""

from __future__ import annotations

import json
import queue
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[3]
PHASES_DOC = REPO_ROOT / "docs" / "orchestrator" / "phases.md"
TEMPLATE = Path(__file__).with_name("console_template.html")

TOOLS_LEFT = [
    {
        "name": "localize_object",
        "role": "System 1 primitive",
        "desc": "perception lookup, returns a pose + point cloud",
    },
    {
        "name": "generate_grasps / select_grasp",
        "role": "System 1 primitive",
        "desc": "grasp candidates from the harness",
    },
    {
        "name": "move_to_pose",
        "role": "System 1 primitive",
        "desc": "motion planning to a target pose",
    },
    {
        "name": "close_gripper / open_gripper",
        "role": "System 1 primitive",
        "desc": "reports held / not held from contact",
    },
    {
        "name": "phase(name)",
        "role": "System 1 primitive",
        "desc": "records the program's current phase for replay",
    },
    {
        "name": "muse exec --json",
        "role": "generator backend",
        "desc": "Muse Code CLI, headless JSONL event stream",
    },
]

TOOLS_RIGHT = [
    {
        "name": "Thompson selector",
        "role": "System 2",
        "desc": "picks the perturbation category most likely to still break this policy",
    },
    {
        "name": "rollout runner",
        "role": "System 2",
        "desc": "sandboxed execution, wall-clock timeout, crash = ERROR",
    },
    {
        "name": "diagnoser",
        "role": "System 2",
        "desc": "mode, root cause, confidence, one imperative constraint",
    },
    {
        "name": "gate()",
        "role": "Orchestrator",
        "desc": "no worse on every case seen, better on at least one",
    },
    {
        "name": "escalation (W=3)",
        "role": "Orchestrator",
        "desc": "same failure signature stalls 3 cycles -> ask a human",
    },
]


@dataclass
class RunState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    running: bool = False
    events: queue.Queue[dict] = field(default_factory=queue.Queue)
    subscribers: list[queue.Queue[dict]] = field(default_factory=list)

    def broadcast(self, event: dict) -> None:
        with self.lock:
            subs = list(self.subscribers)
        for sub in subs:
            sub.put(event)

    def subscribe(self) -> queue.Queue[dict]:
        q: queue.Queue[dict] = queue.Queue()
        with self.lock:
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[dict]) -> None:
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)


def build_prompt(incumbent: Path) -> str:
    return (
        PHASES_DOC.read_text(encoding="utf-8")
        + "\n\n## Incumbent program\n```python\n"
        + incumbent.read_text(encoding="utf-8")
        + "```\n\nNo constraints or feedback yet: this is the first repair step shown in the live"
        " console. Read the program, say in your WHY what single assumption it hard-codes that a"
        " harder scenario would break, and return the same program improved against that one"
        " assumption.\n"
    )


def stream_muse_exec(
    prompt: str,
    *,
    reasoning_effort: str = "high",
    max_model_steps: int | None = 20,
    muse_bin: str = "muse",
    timeout_s: float = 300.0,
) -> queue.Queue[dict]:
    """Run `muse exec --json` in a background thread, yielding parsed JSONL events as they arrive.

    Returns a queue the caller reads from; the final item is always one of
    {"kind": "done", ...} or {"kind": "error", "message": ...}.
    """
    out: queue.Queue[dict] = queue.Queue()

    def worker() -> None:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(prompt)
            prompt_path = Path(handle.name)
        command = [
            muse_bin, "exec", "--json",
            "--prompt-file", str(prompt_path),
            "--reasoning-effort", reasoning_effort,
            "--approval-mode", "never",
        ]  # fmt: skip
        if max_model_steps is not None:
            command += ["--max-model-steps", str(max_model_steps)]
        events: list[dict] = []
        try:
            proc = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                events.append(event)
                out.put({"kind": "muse_event", "event": event})
            stderr = proc.stderr.read() if proc.stderr else ""
            code = proc.wait(timeout=timeout_s)
            if code != 0:
                out.put({"kind": "error", "message": f"muse exec exited {code}: {stderr[-2000:]}"})
                return
        except Exception as exc:  # noqa: BLE001 -- the loop never crashes on the model, log instead
            out.put({"kind": "error", "message": f"{type(exc).__name__}: {exc}"})
            return
        finally:
            prompt_path.unlink(missing_ok=True)

        terminal = next(
            (e for e in events if e.get("payload_type") == "run.terminal.completed"), None
        )
        if terminal is None or terminal["payload"].get("terminal") != "completed":
            out.put({"kind": "error", "message": "muse exec produced no completed terminal event"})
            return
        usage_event = next((e for e in events if e.get("payload_type") == "run.usage"), None)
        model_usage = (
            usage_event["payload"]["models"][0]
            if usage_event and usage_event["payload"].get("models")
            else {}
        )
        out.put(
            {
                "kind": "done",
                "text": terminal["payload"].get("text", ""),
                "usage": {
                    "input_tokens": int(model_usage.get("input_tokens", 0)),
                    "output_tokens": int(model_usage.get("output_tokens", 0)),
                    "reasoning_tokens": int(model_usage.get("reasoning_tokens", 0)),
                    "cached_tokens": int(model_usage.get("cached_tokens", 0)),
                },
            }
        )

    threading.Thread(target=worker, daemon=True).start()
    return out


def make_handler(state: RunState, incumbent: Path, reasoning_effort: str, max_model_steps: int):
    data = {
        "incumbent_name": incumbent.name,
        "incumbent_code": incumbent.read_text(encoding="utf-8"),
        "tools_left": TOOLS_LEFT,
        "tools_right": TOOLS_RIGHT,
        "phases_summary": "Phase A only -- deployment (Phase B) is out of scope for this console.",
    }
    page = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", json.dumps(data))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002 -- stdlib signature
            pass

        def _send_json(self, obj: dict, status: int = 200) -> None:
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 -- stdlib handler name
            path = urlparse(self.path).path
            if path == "/":
                body = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                sub = state.subscribe()
                try:
                    while True:
                        event = sub.get()
                        self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                        self.wfile.flush()
                        if event.get("kind") in ("done", "error"):
                            break
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    state.unsubscribe(sub)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802 -- stdlib handler name
            path = urlparse(self.path).path
            if path != "/run":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            if not body.get("confirmed"):
                self._send_json(
                    {
                        "ok": False,
                        "error": "gate not confirmed: ready to run the policy development phase?",
                    },
                    status=400,
                )
                return
            with state.lock:
                if state.running:
                    self._send_json(
                        {"ok": False, "error": "a run is already in progress"}, status=409
                    )
                    return
                state.running = True

            def drive() -> None:
                prompt = build_prompt(incumbent)
                src = stream_muse_exec(
                    prompt, reasoning_effort=reasoning_effort, max_model_steps=max_model_steps
                )
                while True:
                    item = src.get()
                    state.broadcast(item)
                    if item.get("kind") in ("done", "error"):
                        break
                with state.lock:
                    state.running = False

            threading.Thread(target=drive, daemon=True).start()
            self._send_json({"ok": True})

    return Handler


def serve(
    *,
    incumbent: Path = REPO_ROOT / "examples" / "bowl_on_plate" / "policy.py",
    host: str = "127.0.0.1",
    port: int = 8765,
    reasoning_effort: str = "high",
    max_model_steps: int = 20,
) -> None:
    state = RunState()
    handler = make_handler(state, incumbent, reasoning_effort, max_model_steps)
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"ANTS live console: http://{host}:{port}  (incumbent: {incumbent})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
