"""Live orchestrator console: a stdlib HTTP server around the Phase A closed loop.

Static viewers in this repo (`dashboard.py`, `ants.studio.run`) all read a saved JSONL trace after
a run finished. This module is the live counterpart: a person clicks Run, confirms a gate ("ready
to run the policy development phase?"), and the loop's turns -- attacks, rewrites, gate verdicts --
stream into the browser as they happen.

Two modes, picked by `--mode`:
- "loop" (default): drives the real closed loop, `ants.orchestrator.loop.Loop`, against the mock
  System 2 backend (free, offline, already tested) with System 1's repair step real (`muse exec`
  via `MuseOrchestrator`). Only consumes `orchestrator`'s and `adversary`'s public APIs (`Loop`,
  `LoopConfig`, `Adversary`, `AdversaryConfig`, `GenerateSynthesizer`, `MuseOrchestrator`) the same
  way `orchestrator/run.py` and the tests do -- nothing here edits those packages.
- "single": the original v1 scope, one Phase A repair step with no System 2 call at all. Kept for
  a cheaper/faster demo path. This mode shells out to `muse exec --json` directly instead of going
  through `muse_cli.py`, reading its stdout line by line instead of waiting for the whole subprocess
  to finish, so it has no dependency on `orchestrator/` at all.
"""

from __future__ import annotations

import json
import queue
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[3]
PHASES_DOC = REPO_ROOT / "docs" / "orchestrator" / "phases.md"
TEMPLATE = Path(__file__).with_name("console_template.html")

# Archived example only: a real simulator rollout's agentview keyframes (exp04_scene, E3 evidence
# arm, sample0). This console's own loop runs System 2 on the mock backend, which has no simulator
# or camera -- there is nothing live to show here yet. Kept as a labelled reference, not live data.
AGENTVIEW_ARCHIVE_BASE = REPO_ROOT / "data" / "runs" / "exp04_scene" / "E-E3" / "sample0"


def _find_agentview_keyframes() -> dict[str, Path]:
    """name ("000001-before-open-gripper") -> its agentview.png, in one archived sample run."""
    matches = sorted(AGENTVIEW_ARCHIVE_BASE.rglob("media/keyframes/*/agentview.png"))
    return {m.parent.name: m for m in matches}


def _split_keyframe_name(name: str) -> dict[str, str]:
    """"000001-before-open-gripper" -> {index: "000001", phase: "before", call: "open gripper"}."""
    index, _, rest = name.partition("-")
    phase, _, call = rest.partition("-")
    return {"index": index, "phase": phase, "call": call.replace("-", " ")}

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


@dataclass
class LoopRunConfig:
    """What the Run button drives in "loop" mode: the real closed loop, mock System 2 backend.

    Defaults kept deliberately small (3 cycles, 1 nominal seed, W=2) so a click-through demo stays
    cheap and fast; pass the CLI flags for a fuller run.
    """

    cycles: int = 3
    categories: tuple[str, ...] | None = None  # None = AdversaryConfig's own default (all)
    rho: float = 0.8  # severity bound, Bounds(default=rho)
    eta: float = 0.2
    min_severity: float = 0.3
    adversary_model: str = (
        "mock"  # "mock" is free; "muse-spark" also spends tokens, unbudgeted here
    )
    n_agents: int = 4
    stop_mode: str = "min_tests"
    min_tests: int = 2
    tau: float = 0.1
    stall_window: int = 2  # W: cycles one failure signature may stall before escalation
    nominal_seeds: tuple[int, ...] = (51,)  # acceptance seeds for the nominal cases
    synth_token_budget: int = 200_000
    reasoning_effort: str = "high"
    max_model_steps: int = 20
    out_dir: Path = field(default_factory=lambda: REPO_ROOT / "data" / "console_runs")


def run_live_loop(state: RunState, incumbent: Path, cfg: LoopRunConfig) -> None:
    """Drive one real `Loop.run()` call, tailing `loop.jsonl` live and broadcasting each row."""
    from ants.adversary import Adversary, AdversaryConfig
    from ants.adversary.perturbations import Bounds
    from ants.contracts import Policy
    from ants.orchestrator.loop import Loop, LoopConfig
    from ants.orchestrator.synthesis import GenerateSynthesizer

    try:
        from ants.orchestrator.muse_orchestrator import MuseOrchestrator
    except ImportError as exc:
        state.broadcast({"kind": "error", "message": f"MuseOrchestrator unavailable: {exc}"})
        return

    run_dir = cfg.out_dir / time.strftime("run-%Y%m%dT%H%M%S")
    policy = Policy(
        "bowl_on_plate", 0, "put the bowl on the plate", incumbent.read_text(encoding="utf-8")
    )

    adv_kwargs: dict = {
        "model": cfg.adversary_model,
        "backend": "mock",
        "eta": cfg.eta,
        "bounds": Bounds(default=cfg.rho),
        "min_severity": cfg.min_severity,
        "n_agents": cfg.n_agents,
        "stop_mode": cfg.stop_mode,
        "min_tests": cfg.min_tests,
        "tau": cfg.tau,
        "history_path": run_dir / "history.jsonl",
    }
    if cfg.categories:
        adv_kwargs["categories"] = cfg.categories
    adv = Adversary.from_config(AdversaryConfig(**adv_kwargs))

    muse_orch = MuseOrchestrator(
        out_dir=run_dir / "muse",
        token_budget=cfg.synth_token_budget,
        reasoning_effort=cfg.reasoning_effort,
        max_model_steps=cfg.max_model_steps,
    )
    synth = GenerateSynthesizer(generate=muse_orch, workdir=run_dir / "work")

    loop_cfg = LoopConfig(
        cycles=cfg.cycles,
        stall_window=cfg.stall_window,
        nominal_seeds=cfg.nominal_seeds,
        out=run_dir,
    )

    def on_attack(report, attacked_policy) -> None:
        # fires right after System 2 attacks, before System 1's rewrite call (which blocks on the
        # real muse exec call) -- the only sub-cycle granularity Loop exposes, so the console can
        # show "System 2 just attacked" separately from "System 1 is now writing a repair".
        state.broadcast(
            {
                "kind": "attack_event",
                "attack_id": report.attack_id,
                "category": report.perturbation.category,
                "severity": report.perturbation.severity,
                "outcome": report.result.outcome.value,
                "policy_version": attacked_policy.version,
            }
        )

    loop = Loop(adv, synth, loop_cfg, on_attack=on_attack)

    log_path = run_dir / "loop.jsonl"
    stop_tail = threading.Event()

    def tail() -> None:
        pos = 0
        while not stop_tail.is_set():
            if log_path.exists():
                with log_path.open("r", encoding="utf-8") as f:
                    f.seek(pos)
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        state.broadcast({"kind": "loop_event", "row": row})
                    pos = f.tell()
            time.sleep(0.3)

    tailer = threading.Thread(target=tail, daemon=True)
    tailer.start()
    try:
        result = loop.run(policy)
        time.sleep(0.4)  # let the tailer pick up the final "end" row before it stops
        state.broadcast(
            {
                "kind": "done",
                "stopped": result.stopped,
                "stage": result.stage,
                "final_version": result.incumbent.version,
                "accepted_versions": result.accepted_versions,
                "escalation": result.escalation,
            }
        )
    except Exception as exc:  # noqa: BLE001 -- the loop never crashes the console, log instead
        state.broadcast({"kind": "error", "message": f"{type(exc).__name__}: {exc}"})
    finally:
        stop_tail.set()


def _scene2d_or_none(scene_path: Path | None) -> dict | None:
    if scene_path is None or not scene_path.exists():
        return None
    from ants.studio.scene2d import project_2d

    return project_2d(scene_path)


def make_handler(
    state: RunState,
    incumbent: Path,
    *,
    mode: str = "loop",
    reasoning_effort: str = "high",
    max_model_steps: int = 20,
    loop_cfg: LoopRunConfig | None = None,
    scene_generation_path: Path | None = None,
    scene_repair_path: Path | None = None,
):
    tools_right = (
        TOOLS_RIGHT if mode == "loop" else [t for t in TOOLS_RIGHT if t["role"] != "System 2"]
    )
    agentview = _find_agentview_keyframes()
    agentview_list = [
        {"name": name, "src": f"/agentview/{name}", **_split_keyframe_name(name)}
        for name in sorted(agentview)
    ]
    data = {
        "incumbent_name": incumbent.name,
        "incumbent_code": incumbent.read_text(encoding="utf-8"),
        "tools_left": TOOLS_LEFT,
        "tools_right": tools_right,
        "mode": mode,
        "scene2d": {
            "generation": _scene2d_or_none(scene_generation_path),
            "repair": _scene2d_or_none(scene_repair_path or scene_generation_path),
            "same_source": scene_repair_path is None,
        },
        "phases_summary": (
            "Phase A, full closed loop (mock System 2, real Muse Code rewrites)."
            if mode == "loop"
            else "Phase A, one repair step only -- deployment (Phase B) is out of scope."
        ),
        "loop_config": (
            {
                "cycles": loop_cfg.cycles,
                "rho": loop_cfg.rho,
                "eta": loop_cfg.eta,
                "stall_window": loop_cfg.stall_window,
                "nominal_seeds": list(loop_cfg.nominal_seeds),
                "min_tests": loop_cfg.min_tests,
                "synth_token_budget": loop_cfg.synth_token_budget,
                "reasoning_effort": loop_cfg.reasoning_effort,
                "max_model_steps": loop_cfg.max_model_steps,
                "adversary_model": loop_cfg.adversary_model,
            }
            if loop_cfg
            else None
        ),
        "agentview_archive": {
            "frames": agentview_list,
            "source": str(AGENTVIEW_ARCHIVE_BASE.relative_to(REPO_ROOT)),
        },
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
            if path.startswith("/agentview/"):
                name = path[len("/agentview/") :]
                image_path = agentview.get(name)  # whitelist: only names this run actually found
                if image_path is None or not image_path.exists():
                    self.send_response(404)
                    self.end_headers()
                    return
                body = image_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(body)
                return
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

            def drive_single() -> None:
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

            def drive_loop() -> None:
                try:
                    run_live_loop(state, incumbent, loop_cfg)
                finally:
                    with state.lock:
                        state.running = False

            target = drive_loop if (mode == "loop" and loop_cfg is not None) else drive_single
            threading.Thread(target=target, daemon=True).start()
            self._send_json({"ok": True})

    return Handler


def serve(
    *,
    incumbent: Path = REPO_ROOT / "examples" / "bowl_on_plate" / "policy.py",
    host: str = "127.0.0.1",
    port: int = 8765,
    mode: str = "loop",
    reasoning_effort: str = "high",
    max_model_steps: int = 20,
    loop_cfg: LoopRunConfig | None = None,
    scene_generation_path: Path | None = REPO_ROOT
    / "data"
    / "scenes"
    / "L1"
    / "contacts_scene.json",
    scene_repair_path: Path | None = None,
) -> None:
    state = RunState()
    handler = make_handler(
        state,
        incumbent,
        mode=mode,
        reasoning_effort=reasoning_effort,
        max_model_steps=max_model_steps,
        loop_cfg=loop_cfg if mode == "loop" else None,
        scene_generation_path=scene_generation_path,
        scene_repair_path=scene_repair_path,
    )
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"ANTS live console ({mode}): http://{host}:{port}  (incumbent: {incumbent})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
