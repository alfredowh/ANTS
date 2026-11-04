"""Live orchestrator console: a stdlib HTTP server around the Phase A closed loop.

Static viewers in this repo (`dashboard.py`, `ants.studio.run`) all read a saved JSONL trace after
a run finished. This module is the live counterpart: `/policy-dev` in the chat starts the pipeline
(`policy_dev.py`), and its stages, attacks, rewrites and gate verdicts stream into the browser as
they happen. It only consumes `orchestrator`'s and `adversary`'s public APIs (`Loop`, `LoopConfig`,
`Adversary`, `AdversaryConfig`, `GenerateSynthesizer`, `MuseOrchestrator`) the same way
`orchestrator/run.py` and the tests do -- nothing here edits those packages. A free-form chat
message is a one-shot `muse exec --json` call, read line by line (`stream_muse_exec`).
"""

from __future__ import annotations

import dataclasses
import json
import os
import queue
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from ants.studio import adversary_view, attempts_view, live_view, policy_dev

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDIO_DIR = Path(__file__).parent
VIEWS_DIR = STUDIO_DIR / "views"
STATIC_DIR = STUDIO_DIR / "static"
# Whitelist: every /static/<name> route this server will serve.
STATIC_FILES = {
    "console.css": STATIC_DIR / "console.css",
    "console.js": STATIC_DIR / "console.js",
    "wizard.js": STATIC_DIR / "wizard.js",
    "demo_media.js": STATIC_DIR / "demo_media.js",
    "attempts.js": STATIC_DIR / "attempts.js",
    "studio_switch.js": STATIC_DIR / "studio_switch.js",
    "flow.js": STATIC_DIR / "flow.js",
    "live.js": STATIC_DIR / "live.js",
    "live.css": STATIC_DIR / "live.css",
    "live_mirror.js": STATIC_DIR / "live_mirror.js",
    "flow.css": STATIC_DIR / "flow.css",
    "flow_blocks.json": REPO_ROOT / "docs" / "studio" / "process-flow-blocks.json",
}


def _assemble_shell() -> str:
    """Build the one served page from views/shell.html + its view fragments."""
    shell = (VIEWS_DIR / "shell.html").read_text(encoding="utf-8")
    fragments = {
        "<!--__AGENT_CONSOLE__-->": (VIEWS_DIR / "agent_console.html").read_text(encoding="utf-8"),
    }
    for marker, content in fragments.items():
        shell = shell.replace(marker, content)
    return shell


def _parse_why(reply_text: str) -> str:
    """The leading WHY note from a MuseOrchestrator reply, before its fenced code block."""
    lines: list[str] = []
    for line in reply_text.splitlines():
        if line.strip().startswith("```"):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _list_runs(out_dir: Path) -> list[dict]:
    """Stored runs under out_dir, newest first (read-only; names only plus cheap counts)."""
    if not out_dir.is_dir():
        return []
    runs = []
    for d in sorted((x for x in out_dir.iterdir() if x.is_dir()), reverse=True):

        def lines(name: str, d: Path = d) -> int:
            f = d / name
            if not f.is_file():
                return 0
            with f.open(encoding="utf-8") as fh:
                return sum(1 for _ in fh)

        runs.append(
            {"name": d.name, "cycles": lines("loop.jsonl"), "attacks": lines("attacks.jsonl")}
        )
    return runs


TOOLS_LEFT = [
    {
        "name": "localize_object",
        "role": "Synthesizer primitive",
        "desc": "perception lookup, returns a pose + point cloud",
    },
    {
        "name": "generate_grasps / select_grasp",
        "role": "Synthesizer primitive",
        "desc": "grasp candidates from the harness",
    },
    {
        "name": "move_to_pose",
        "role": "Synthesizer primitive",
        "desc": "motion planning to a target pose",
    },
    {
        "name": "close_gripper / open_gripper",
        "role": "Synthesizer primitive",
        "desc": "reports held / not held from contact",
    },
    {
        "name": "phase(name)",
        "role": "Synthesizer primitive",
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
        "role": "Adversary",
        "desc": "picks the perturbation category most likely to still break this policy",
    },
    {
        "name": "rollout runner",
        "role": "Adversary",
        "desc": "sandboxed execution, wall-clock timeout, crash = ERROR",
    },
    {
        "name": "diagnoser",
        "role": "Adversary",
        "desc": "mode, root cause, confidence, one imperative constraint",
    },
    {
        "name": "gate()",
        "role": "Orchestrator",
        "desc": "no worse on every case seen, better on at least one",
    },
    {
        "name": "escalation (W stalled cycles)",
        "role": "Orchestrator",
        "desc": "same failure signature stalls W cycles -> ask a human (W is in the loop config)",
    },
]


SESSIONS_DIR = REPO_ROOT / "data" / "console_sessions"
LEGACY_RUNS_DIR = REPO_ROOT / "data" / "console_runs"


def deploy_latest(session_dir: Path | None, incumbent: Path, deploy_dir: Path) -> dict:
    """Save the last main program to the deploy folder: the highest accepted version found in this
    session's runs (policies/v<N>.py), else the incumbent file. Writes <deploy_dir>/<ts>-v<N>.py
    and latest.py + latest.json. Never overwrites an older timestamped copy."""
    best: tuple[int, float, Path] | None = None
    if session_dir is not None:
        for f in (session_dir / "runs").glob("run-*/policies/v*.py"):
            digits = f.stem[1:]
            if digits.isdigit():
                key = (int(digits), f.stat().st_mtime, f)
                if best is None or key[:2] > best[:2]:
                    best = key
    src = best[2] if best else incumbent
    version = best[0] if best else 0
    return policy_dev.save_deployed(src, version, deploy_dir)


class Session:
    """One server/browser session = one folder holding everything relevant to it.

    data/console_sessions/<id>/ with session.json (id, started, cli config, incumbent), chat.jsonl
    (every chat message: role, case, ts), events.jsonl (every SSE event) and runs/run-<ts>/
    (the per-run folders the loop writes). Nothing secret is stored: the config is the CLI flags.
    """

    def __init__(self, base: Path, session_id: str | None = None, meta: dict | None = None) -> None:
        if session_id is None:
            session_id = time.strftime("sess-%Y%m%d-%H%M%S")
            n = 1
            while (base / session_id).exists():  # two resets within one second
                n += 1
                session_id = time.strftime("sess-%Y%m%d-%H%M%S") + f"-{n}"
        self.id = session_id
        self.dir = base / session_id
        self.runs_dir = self.dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._assistant_buf = ""
        info_path = self.dir / "session.json"
        if info_path.is_file():
            self.info = json.loads(info_path.read_text(encoding="utf-8"))
            self.info.setdefault("resumed", []).append(time.strftime("%Y-%m-%dT%H:%M:%S"))
        else:
            self.info = {
                "id": self.id,
                "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
                **(meta or {}),
            }
        info_path.write_text(json.dumps(self.info, indent=2, default=str), encoding="utf-8")

    def _append(self, name: str, row: dict) -> None:
        with self._lock, (self.dir / name).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")

    def log_event(self, event: dict) -> None:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._append("events.jsonl", {"ts": ts, **event})
        # the agent's streamed chat reply becomes one chat.jsonl row when it finishes
        kind = event.get("kind")
        if kind == "chat_muse_event":
            ev = event.get("event") or {}
            if ev.get("payload_type") == "run.output.delta":
                self._assistant_buf += (ev.get("payload") or {}).get("text", "")
        elif kind in ("chat_done", "chat_error"):
            text, self._assistant_buf = self._assistant_buf, ""
            if kind == "chat_error":
                text = text or str(event.get("message", ""))
            self.log_chat("assistant", text, "error" if kind == "chat_error" else "oneshot")

    def log_chat(self, role: str, text: str, case: str) -> None:
        self._append(
            "chat.jsonl",
            {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "role": role, "case": case, "text": text},
        )


def start_session(
    state: RunState,
    base: Path,
    loop_cfg: LoopRunConfig | None,
    meta: dict,
    session_id: str | None = None,
) -> Session:
    """Create (or resume) a session folder and point the loop's run output into it."""
    session = Session(base, session_id, meta)
    state.session = session
    if loop_cfg is not None:
        loop_cfg.out_dir = session.runs_dir
    return session


class StopRequested(Exception):
    """Raised inside the loop thread when the user pressed Stop."""


def kill_child_processes() -> int:
    """SIGTERM every descendant of this server process (muse exec, ASPIRE rollouts, wizard
    generation). Linux /proc based; elsewhere it does nothing and the loop still stops at the next
    attack boundary."""
    proc = Path("/proc")
    if not proc.is_dir():
        return 0
    children: dict[int, list[int]] = {}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8")
            ppid = int(stat.rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        children.setdefault(ppid, []).append(int(entry.name))
    todo, victims = [os.getpid()], []
    while todo:
        for pid in children.get(todo.pop(), []):
            victims.append(pid)
            todo.append(pid)
    killed = 0
    for pid in victims:
        try:
            os.kill(pid, signal.SIGTERM)
            killed += 1
        except OSError:
            pass
    return killed


@dataclass
class RunState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    running: bool = False
    stop_requested: threading.Event = field(default_factory=threading.Event)
    events: queue.Queue[dict] = field(default_factory=queue.Queue)
    subscribers: list[queue.Queue[dict]] = field(default_factory=list)
    # Chat: at most one of these is meaningful at a time.
    # - awaiting_answer: set while Loop's ask_human callback is blocked waiting for a chat reply
    #   (Case 1 -- the escalation this run stalled on).
    # - queued_chat: a message that arrived while a run was active, to auto-fire as a one-shot
    #   the moment the run goes idle (Case 3, queue-and-auto-fire).
    awaiting_answer: queue.Queue[str] | None = None
    queued_chat: str | None = None
    session: Session | None = None
    picked_video: Path | None = None  # chosen in the file dialog, shown before a run starts
    live: live_view.LiveView | None = None  # the rollout-in-progress panel (live_view.py)

    def broadcast(self, event: dict) -> None:
        if self.live is not None:
            self.live.observe(event)
        if self.session is not None:
            self.session.log_event(event)
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


def chat_prompt(incumbent: Path, message: str) -> str:
    """A free-form chat message, with the current incumbent program as context (not its full repair
    history/constraints -- those live inside one Loop run, not the console's standalone chat path).
    """
    return (
        "You are being asked a question about the robot program below, outside of any repair "
        "cycle -- this is not a request to rewrite it unless the question asks for a change.\n\n"
        "## Current incumbent program\n```python\n"
        + incumbent.read_text(encoding="utf-8")
        + "```\n\n## Question\n"
        + message
        + "\n"
    )


def run_chat_oneshot(
    state: RunState,
    incumbent: Path,
    message: str,
    *,
    reasoning_effort: str,
    max_model_steps: int,
) -> None:
    """Case 2/3 of the chat flow: a one-shot muse exec call, streamed as "chat_*" SSE events."""
    src = stream_muse_exec(
        chat_prompt(incumbent, message),
        reasoning_effort=reasoning_effort,
        max_model_steps=max_model_steps,
    )
    while True:
        item = src.get()
        kind = {"muse_event": "chat_muse_event", "done": "chat_done", "error": "chat_error"}.get(
            item.get("kind"), item.get("kind")
        )
        state.broadcast({**item, "kind": kind})
        if item.get("kind") in ("done", "error"):
            break


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
    """What `run_live_loop` drives: the real closed loop (`/policy-dev` overrides the run fields).

    Defaults kept deliberately small (3 cycles, 1 nominal seed, W=2) so a click-through demo stays
    cheap and fast; pass the CLI flags for a fuller run.
    """

    backend: str = "mock"  # "mock" (free, instant) or "cap_harness" (real ASPIRE/LIBERO rollouts)
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
    video_dir: Path | None = None  # where /policy-dev's file dialog opens (None: the skill file's)
    pipeline_token_budget: int | None = None  # /policy-dev total Muse cap (None: the skill file's)
    reasoning_effort: str = "high"
    max_model_steps: int = 20
    out_dir: Path = field(default_factory=lambda: REPO_ROOT / "data" / "console_runs")


def _adversary_from(cfg: LoopRunConfig, run_dir: Path):
    from ants.adversary import Adversary, AdversaryConfig
    from ants.adversary.perturbations import Bounds
    from ants.adversary.rollout.aspire_backend import AspireConfig

    kwargs: dict = {
        "model": cfg.adversary_model,
        "backend": cfg.backend,
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
        kwargs["categories"] = cfg.categories
    if (
        cfg.backend == "cap_harness"
    ):  # rollout videos in the run folder, where the Replay finds them
        kwargs["aspire"] = AspireConfig(output_root=run_dir / "aspire")
    return Adversary.from_config(AdversaryConfig(**kwargs))


def run_attacks_only(state: RunState, program: Path, cfg: LoopRunConfig, run_dir: Path, task: str):
    """Synthesizer off: attack a given script and report. No rewrites, no gate, no Muse tokens."""
    from ants.contracts import Policy
    from ants.studio.run import append_row, attack_row

    state.broadcast({"kind": "run_started", "run_dir": str(run_dir), "backend": cfg.backend})
    raw_adv = _adversary_from(cfg, run_dir)
    adv = policy_dev.ObservedAdversary(raw_adv, state.broadcast)
    policy = Policy("main_script", 0, task, program.read_text(encoding="utf-8"))
    adversary_view.write_run_meta(run_dir, raw_adv, policy, cfg)
    failures = 0
    stopped = "attacks_done"
    for _ in range(cfg.cycles):
        if state.stop_requested.is_set():
            stopped = "user_stop"
            break
        report = adv.attack(policy)
        append_row(run_dir / "attacks.jsonl", attack_row(adv, report, policy))
        failures += report.failure is not None
        state.broadcast(
            {
                "kind": "attack_event",
                "attack_id": report.attack_id,
                "category": report.perturbation.category,
                "severity": report.perturbation.severity,
                "outcome": report.result.outcome.value,
                "policy_version": policy.version,
            }
        )
    if state.stop_requested.is_set():
        stopped = "user_stop"
    state.broadcast(
        {
            "kind": "done",
            "stopped": stopped,
            "stage": f"{failures} failure(s) found, not repaired",
            "final_version": 0,
            "accepted_versions": [],
            "escalation": None,
        }
    )


def run_live_loop(
    state: RunState,
    incumbent: Path,
    cfg: LoopRunConfig,
    *,
    run_dir: Path | None = None,
    task: str = "put the bowl on the plate",
) -> None:
    """Drive one real `Loop.run()` call, tailing `loop.jsonl` live and broadcasting each row."""
    from ants.contracts import Policy
    from ants.orchestrator.loop import Loop, LoopConfig
    from ants.orchestrator.synthesis import GenerateSynthesizer

    try:
        from ants.orchestrator.muse_orchestrator import MuseOrchestrator
    except ImportError as exc:
        state.broadcast({"kind": "error", "message": f"MuseOrchestrator unavailable: {exc}"})
        return

    run_dir = run_dir or cfg.out_dir / time.strftime("run-%Y%m%dT%H%M%S")
    # Tell the UI where this run is being saved before anything runs, so the folder is
    # findable even if the run later crashes.
    state.broadcast({"kind": "run_started", "run_dir": str(run_dir), "backend": cfg.backend})
    policy = Policy("bowl_on_plate", 0, task, incumbent.read_text(encoding="utf-8"))

    adv = _adversary_from(cfg, run_dir)

    muse_orch = MuseOrchestrator(
        out_dir=run_dir / "muse",
        token_budget=cfg.synth_token_budget,
        reasoning_effort=cfg.reasoning_effort,
        max_model_steps=cfg.max_model_steps,
    )
    observed_adv = policy_dev.ObservedAdversary(adv, state.broadcast)
    synth = policy_dev.ObservedSynthesizer(
        GenerateSynthesizer(generate=muse_orch, workdir=run_dir / "work"),
        state.broadcast,
        observed_adv,
    )

    loop_cfg = LoopConfig(
        cycles=cfg.cycles,
        stall_window=cfg.stall_window,
        nominal_seeds=cfg.nominal_seeds,
        out=run_dir,
    )

    def on_attack(report, attacked_policy) -> None:
        if state.stop_requested.is_set():
            raise StopRequested
        # fires right after Adversary attacks, before Synthesizer's rewrite call (which blocks on
        # the real muse exec call) -- the only sub-cycle granularity Loop exposes, so the console
        # can
        # show "Adversary just attacked" separately from "Synthesizer is now writing a repair".
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
        # Also log this attack in Daniel's studio.run row shape (attacks.jsonl), so this run
        # becomes readable by his Replay-view data shape, not just this console's own loop.jsonl.
        try:
            from ants.studio.run import append_row, attack_row

            append_row(run_dir / "attacks.jsonl", attack_row(adv, report, attacked_policy))
        except Exception as exc:  # noqa: BLE001 -- logging must never break the loop
            state.broadcast({"kind": "error", "message": f"attacks.jsonl logging failed: {exc}"})

    def ask_human(escalation):
        from ants.orchestrator.human_gate import GateAnswer

        answer_q: queue.Queue[str] = queue.Queue()
        with state.lock:
            state.awaiting_answer = answer_q
        state.broadcast({"kind": "awaiting_answer", "escalation": dict(escalation)})
        text = answer_q.get()  # blocks the loop thread until /chat delivers a reply
        with state.lock:
            state.awaiting_answer = None
        if state.stop_requested.is_set():
            raise StopRequested
        return GateAnswer(channel="text", text=text)

    loop = Loop(observed_adv, synth, loop_cfg, on_attack=on_attack, ask_human=ask_human)
    adversary_view.write_run_meta(run_dir, adv, policy, cfg, gate_mode=loop_cfg.gate_mode)

    log_path = run_dir / "loop.jsonl"
    stop_tail = threading.Event()

    muse_cycle = 0  # MuseOrchestrator's own cycle counter: +1 on every rewrite call, same order

    def tail() -> None:
        nonlocal muse_cycle
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
                        if row.get("event") == "cycle" and "rewrite_tokens" in row:
                            muse_cycle += 1
                            cycle_dir = run_dir / "muse" / f"cycle{muse_cycle}"
                            detail: dict = {}
                            try:
                                detail["why"] = _parse_why(
                                    (cycle_dir / "reply.md").read_text(encoding="utf-8")
                                )
                            except OSError:
                                pass
                            try:
                                detail["usage"] = json.loads(
                                    (cycle_dir / "usage.json").read_text(encoding="utf-8")
                                )
                            except (OSError, json.JSONDecodeError):
                                pass
                            if detail:
                                row["rewrite_detail"] = detail
                        verdict = policy_dev.gate_verdict_event(row)
                        if verdict:
                            state.broadcast(verdict)
                        if state.stop_requested.is_set():
                            # Stop killed the rewrite, which Loop reads as a spent budget.
                            if row.get("decision") == "budget_stop":
                                row["decision"] = "user_stop"
                            if row.get("stopped") == "budget":
                                row["stopped"] = "user_stop"
                        state.broadcast({"kind": "loop_event", "row": row})
                    pos = f.tell()
            time.sleep(0.3)

    threading.Thread(target=tail, daemon=True).start()
    try:
        result = loop.run(policy)
        time.sleep(0.4)  # let the tailer pick up the final "end" row before it stops
        adversary_view.mark_finished(run_dir)
        state.broadcast(
            {
                "kind": "done",
                "stopped": "user_stop" if state.stop_requested.is_set() else result.stopped,
                "stage": result.stage,
                "final_version": result.incumbent.version,
                "accepted_versions": result.accepted_versions,
                "escalation": result.escalation,
            }
        )
    except Exception as exc:  # noqa: BLE001 -- the loop never crashes the console, log instead
        if state.stop_requested.is_set():
            time.sleep(0.4)
            state.broadcast(
                {
                    "kind": "done",
                    "stopped": "user_stop",
                    "stage": "stopped",
                    "final_version": None,
                    "accepted_versions": [],
                    "escalation": None,
                }
            )
        else:
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
    reasoning_effort: str = "high",
    max_model_steps: int = 20,
    loop_cfg: LoopRunConfig | None = None,
    scene_generation_path: Path | None = None,
    adversary_run: Path | None = None,
    sessions_dir: Path | None = None,
    session_id: str | None = None,
):
    def session_meta() -> dict:
        return {
            "incumbent": str(incumbent),
            "config": asdict(loop_cfg) if loop_cfg else None,
            "reasoning_effort": reasoning_effort,
            "max_model_steps": max_model_steps,
        }

    if sessions_dir is not None and state.session is None:
        start_session(state, sessions_dir, loop_cfg, session_meta(), session_id)

    def runs_dir() -> Path | None:
        if state.session is not None:
            return state.session.runs_dir
        return loop_cfg.out_dir if loop_cfg else None

    # what /policy-dev sends; --scene shows some other file, for reference only
    sent_scene = REPO_ROOT / policy_dev.load_skill()["scene_context"]["dump"]
    data = {
        "incumbent_name": incumbent.name,
        "incumbent_code": incumbent.read_text(encoding="utf-8"),
        "tools_left": TOOLS_LEFT,
        "tools_right": TOOLS_RIGHT,
        "scene2d": {
            "generation": _scene2d_or_none(scene_generation_path or sent_scene),
            "source": str(scene_generation_path or sent_scene.relative_to(REPO_ROOT)),
            "sent": scene_generation_path is None,
        },
        "loop_config": (
            {
                "backend": loop_cfg.backend,
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
    }
    page = _assemble_shell().replace("/*__DATA__*/null", json.dumps(data))

    def _fire_queued_chat() -> None:
        """Case 3 of the chat flow: a message queued during a run, sent once the run ended."""
        with state.lock:
            msg, state.queued_chat = state.queued_chat, None
            if not msg or state.running:
                state.queued_chat = msg
                return
            state.running = True
        try:
            run_chat_oneshot(
                state,
                incumbent,
                msg,
                reasoning_effort=reasoning_effort,
                max_model_steps=max_model_steps,
            )
        finally:
            with state.lock:
                state.running = False

    def _set_running(on: bool) -> bool:
        with state.lock:
            if on and state.running:
                return False
            state.running = on
        if not on:
            threading.Thread(target=_fire_queued_chat, daemon=True).start()
        return True

    skill = policy_dev.load_skill()
    if loop_cfg and loop_cfg.pipeline_token_budget:
        skill["settings"]["token_cap"]["default"] = loop_cfg.pipeline_token_budget

    def _pipeline_cfg(settings: dict, budget: int = 0) -> LoopRunConfig:
        return dataclasses.replace(
            loop_cfg or LoopRunConfig(),
            backend="cap_harness",
            adversary_model=skill["loop"]["proposer_model"],
            eta=settings["eta"],
            cycles=settings["attacks"],
            stall_window=skill["loop"]["stall_window"],
            nominal_seeds=policy_dev.nominal_seeds(settings, skill),
            synth_token_budget=budget,
        )

    def _pipeline_run_loop(
        program: Path, task: str, run_dir: Path, budget: int, settings: dict
    ) -> None:
        cfg = _pipeline_cfg(settings, budget)
        run_live_loop(state, program, cfg, run_dir=run_dir, task=task)

    def _pipeline_run_attacks(program: Path, task: str, run_dir: Path, settings: dict) -> None:
        run_attacks_only(state, program, _pipeline_cfg(settings), run_dir, task)

    pipeline = policy_dev.Manager(
        state.broadcast,
        set_running=_set_running,
        run_loop=_pipeline_run_loop,
        run_attacks=_pipeline_run_attacks,
        stop_requested=state.stop_requested.is_set,
        clear_stop=state.stop_requested.clear,
        runs_dir=lambda: state.session.runs_dir if state.session else LEGACY_RUNS_DIR,
        skill=skill,
    )

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
            if path.startswith("/static/"):
                name = path[len("/static/") :]
                file_path = STATIC_FILES.get(name)  # whitelist, no arbitrary filesystem access
                if file_path is None or not file_path.exists():
                    self.send_response(404)
                    self.end_headers()
                    return
                content_type = "text/css" if name.endswith(".css") else "application/javascript"
                body = file_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", f"{content_type}; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            # ---- Adversary view: Daniel's page for this session's latest run, plus its videos ----
            if path == "/adversary" or path.startswith("/adversary/"):
                self._serve_adversary(path[len("/adversary/") :])
                return
            # ---- end Adversary view ----
            if path == "/runs":
                cur = runs_dir()
                runs = _list_runs(cur) if cur else []
                legacy = [
                    {**r, "legacy": True}
                    for r in (_list_runs(LEGACY_RUNS_DIR) if cur != LEGACY_RUNS_DIR else [])
                ]
                self._send_json(
                    {
                        "runs": runs,
                        "legacy_runs": legacy,
                        "session": state.session.id if state.session else None,
                    }
                )
                return
            # ---- live simulator panel ----
            if path == "/live/status":
                live = state.live
                self._send_json(live.status(state.running) if live else {"active": False})
                return
            if path.startswith("/live/frame/") and path.endswith(".jpg"):
                body = state.live.frame(path[len("/live/frame/") : -4]) if state.live else None
                self.send_response(200 if body else 404)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body or b"")))
                self.end_headers()
                self.wfile.write(body or b"")
                return
            if path.startswith("/live/mirror/"):
                name = path[len("/live/mirror/") :]
                body = state.live.mirror(name) if state.live else None
                self.send_response(200 if body else 404)
                self.send_header(
                    "Content-Type",
                    "application/json" if name.endswith(".json") else "application/octet-stream",
                )
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body or b"")))
                self.end_headers()
                self.wfile.write(body or b"")
                return
            # ---- end live simulator panel ----
            # ---- human demo video and generation attempts of the current run ----
            current_run = Path(pipeline.current["run_dir"]) if pipeline.current else None
            if path == "/demo-video/status":
                overlay = current_run / "demo" / "overlay.mp4" if current_run else None
                self._send_json(
                    {
                        "raw": self._demo_raw() is not None,
                        "overlay": bool(overlay and overlay.is_file()),
                    }
                )
                return
            if path in ("/demo-video/raw", "/demo-video/overlay"):
                file = (
                    self._demo_raw()
                    if path.endswith("raw")
                    else (current_run / "demo" / "overlay.mp4" if current_run else None)
                )
                if file is None or not file.is_file():
                    self.send_response(404)
                    self.end_headers()
                    return
                self._send_ranged(file, "video/mp4")
                return
            if path == "/attempts":
                self._send_json({"attempts": attempts_view.attempts(current_run)})
                return
            if path.startswith("/attempts/media/"):
                rel = unquote(path[len("/attempts/media/") :])
                image = attempts_view.media_path(current_run, rel)
                if image is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self._send_ranged(image, attempts_view.MEDIA[image.suffix.lower()])
                return
            if path == "/session":
                self._send_json(
                    {
                        "id": state.session.id if state.session else None,
                        "dir": str(state.session.dir.relative_to(REPO_ROOT))
                        if state.session and state.session.dir.is_relative_to(REPO_ROOT)
                        else None,
                        "running": state.running,
                    }
                )
                return
            if path == "/":
                body = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/policy-dev":
                self._send_json(
                    {
                        "running": state.running,
                        "current": pipeline.current,
                        "settings": skill["settings"],
                        "budget": skill["budget"],
                    }
                )
                return
            if path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                # One persistent connection for the whole page session, not one per run: a loop
                # run's "done" used to close this stream, which would silently drop a Case-3
                # queued chat's events (broadcast with zero subscribers, since the per-run
                # connection had already closed before the auto-fired chat even started).
                sub = state.subscribe()
                try:
                    while True:
                        event = sub.get()
                        self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    state.unsubscribe(sub)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802 -- stdlib handler name
            path = urlparse(self.path).path
            if path == "/chat":
                self._handle_chat()
                return
            if path == "/session/new":
                self._handle_new_session()
                return
            if path == "/policy-dev":
                self._handle_policy_dev()
                return
            if path == "/pick-video":
                folder = (loop_cfg.video_dir if loop_cfg else None) or (
                    REPO_ROOT / skill["video"]["folder"]
                )
                picked = policy_dev.pick_file(folder, skill["video"]["extensions"])
                if picked.get("ok"):
                    state.picked_video = Path(picked["path"])
                self._send_json(picked)
                return
            if path == "/pick-script":
                self._send_json(
                    policy_dev.pick_file(
                        REPO_ROOT / "examples",
                        skill["settings"]["main_script"]["extensions"],
                        title="Choose the main robot script",
                        filter_name="Python",
                    )
                )
                return
            if path == "/upload":
                self._handle_upload()
                return
            if path == "/stop":
                with state.lock:
                    running = state.running
                    waiting = state.awaiting_answer
                if not running:
                    self._send_json({"ok": False, "error": "nothing is running"})
                    return
                state.stop_requested.set()
                if waiting is not None:
                    waiting.put("")  # unblock a pending escalation question
                killed = kill_child_processes()

                def keep_killing() -> None:
                    # the gate's next replay would otherwise start a new rollout after this kill
                    for _ in range(300):
                        with state.lock:
                            if not state.running:
                                return
                        kill_child_processes()
                        time.sleep(1)

                threading.Thread(target=keep_killing, daemon=True).start()
                state.broadcast({"kind": "stop_requested", "killed": killed})
                self._send_json({"ok": True, "killed": killed})
                return
            if path == "/clientlog":
                length = int(self.headers.get("Content-Length", "0"))
                try:
                    body = json.loads(self.rfile.read(min(length, 20000)) or b"{}")
                except ValueError:
                    body = {}
                row = {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    **{k: str(body.get(k))[:500] for k in ("message", "source", "line")},
                }
                if state.session:
                    with (state.session.dir / "client_errors.jsonl").open(
                        "a", encoding="utf-8"
                    ) as fh:
                        fh.write(json.dumps(row) + "\n")
                self._send_json({"ok": True})
                return
            if path == "/deploy":
                try:
                    info = deploy_latest(
                        state.session.dir if state.session else None,
                        incumbent,
                        REPO_ROOT / "data" / "deploy",
                    )
                except OSError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=500)
                    return
                info["dir"] = "data/deploy"
                self._send_json({"ok": True, **info})
                return
            self.send_response(404)
            self.end_headers()

        # ---- Adversary view ----
        def _demo_raw(self) -> Path | None:
            if pipeline.current and pipeline.current.get("video"):
                return Path(pipeline.current["video"])
            return state.picked_video

        def _send_ranged(self, file: Path, content_type: str) -> None:
            size = file.stat().st_size
            start, end = adversary_view.byte_range(self.headers.get("Range"), size)
            if start is None:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            partial = self.headers.get("Range") is not None
            self.send_response(206 if partial else 200)
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Cache-Control", "no-store")
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            try:
                with file.open("rb") as fh:
                    fh.seek(start)
                    left = end - start + 1
                    while left > 0:
                        chunk = fh.read(min(1 << 20, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _serve_adversary(self, rest: str) -> None:
            run_dir = adversary_view.latest_run(runs_dir()) or adversary_run
            if not rest:
                html = adversary_view.page(run_dir)
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            media = adversary_view.media_path(run_dir, unquote(rest))
            if media is None:
                self.send_response(404)
                self.end_headers()
                return
            size = media.stat().st_size
            start, end = adversary_view.byte_range(self.headers.get("Range"), size)
            if start is None:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            partial = self.headers.get("Range") is not None
            self.send_response(206 if partial else 200)
            self.send_header("Content-Type", adversary_view.media_type(media))
            self.send_header("Accept-Ranges", "bytes")  # his player seeks: the browser needs ranges
            self.send_header("Content-Length", str(end - start + 1))
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            try:
                with media.open("rb") as fh:
                    fh.seek(start)
                    left = end - start + 1
                    while left > 0:
                        chunk = fh.read(min(1 << 20, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the browser cancels ranges while seeking

        # ---- end Adversary view ----

        def _handle_new_session(self) -> None:
            if sessions_dir is None:
                self._send_json({"ok": False, "error": "sessions are not enabled"}, status=400)
                return
            with state.lock:
                if state.running or state.awaiting_answer is not None:
                    self._send_json(
                        {
                            "ok": False,
                            "error": "a run or chat reply is in progress; wait for it to finish "
                            "before starting a new session",
                        },
                        status=409,
                    )
                    return
                state.queued_chat = None
                state.picked_video = None
                pipeline.current = None
                start_session(state, sessions_dir, loop_cfg, session_meta())
            state.broadcast({"kind": "session_reset", "session": state.session.id})
            self._send_json({"ok": True, "session": state.session.id})

        def _handle_policy_dev(self) -> None:
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                self._send_json({"ok": False, "error": "expected JSON"}, status=415)
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            self._send_json(
                pipeline.start(
                    str(body.get("task") or "").strip(),
                    body.get("video") or None,
                    body.get("settings"),
                )
            )

        def _handle_upload(self) -> None:
            limit = skill["video"]["upload_max_mb"] * 1024 * 1024
            length = int(self.headers.get("Content-Length", "0"))
            name = unquote(self.headers.get("X-Filename", ""))
            safe = policy_dev.safe_upload_name(name, skill["video"]["extensions"])
            if safe is None or state.session is None:
                self._send_json(
                    {"ok": False, "error": "that file type is not an allowed video extension"},
                    status=400,
                )
                return
            target = state.session.dir / "uploads" / safe
            if length <= 0 or length > limit:
                self._send_json(
                    {"ok": False, "error": f"file must be 1 byte to {limit // 1024 // 1024} MB"},
                    status=413,
                )
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            remaining = length
            with target.open("wb") as fh:
                while remaining > 0:
                    chunk = self.rfile.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    fh.write(chunk)
                    remaining -= len(chunk)
            if remaining:
                target.unlink(missing_ok=True)
                self._send_json({"ok": False, "error": "upload was cut short"}, status=400)
                return
            self._send_json({"ok": True, "path": str(target), "name": target.name})

        def _handle_chat(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            message = (body.get("message") or "").strip()
            if not message:
                self._send_json({"ok": False, "error": "empty message"}, status=400)
                return
            with state.lock:
                session = state.session
                # Case 1: a run is escalated and waiting on exactly this -- answer it.
                if state.awaiting_answer is not None:
                    answer_q = state.awaiting_answer
                    answer_q.put(message)
                    if session:
                        session.log_chat("user", message, "answer")
                    self._send_json({"ok": True, "case": "answer"})
                    return
                # Case 3: a run is active but not escalated -- queue, auto-fire once idle.
                if state.running:
                    state.queued_chat = message
                    if session:
                        session.log_chat("user", message, "queued")
                    self._send_json({"ok": True, "case": "queued"})
                    return
                state.running = True
                if session:
                    session.log_chat("user", message, "oneshot")

            # Case 2: idle -- a one-shot Muse call, streamed as chat_* SSE events.
            def drive_chat() -> None:
                try:
                    run_chat_oneshot(
                        state,
                        incumbent,
                        message,
                        reasoning_effort=reasoning_effort,
                        max_model_steps=max_model_steps,
                    )
                finally:
                    with state.lock:
                        state.running = False

            threading.Thread(target=drive_chat, daemon=True).start()
            self._send_json({"ok": True, "case": "oneshot"})

    return Handler


def serve(
    *,
    incumbent: Path = REPO_ROOT / "examples" / "bowl_on_plate" / "policy.py",
    host: str = "127.0.0.1",
    port: int = 8765,
    reasoning_effort: str = "high",
    max_model_steps: int = 20,
    loop_cfg: LoopRunConfig | None = None,
    scene_generation_path: Path | None = None,
    adversary_run: Path | None = None,
    session_id: str | None = None,
    sessions_dir: Path | None = SESSIONS_DIR,
) -> None:
    state = RunState(live=live_view.enable())
    if session_id and sessions_dir and not (sessions_dir / session_id).is_dir():
        raise SystemExit(f"no such session: {sessions_dir / session_id}")
    handler = make_handler(
        state,
        incumbent,
        reasoning_effort=reasoning_effort,
        max_model_steps=max_model_steps,
        loop_cfg=loop_cfg,
        scene_generation_path=scene_generation_path,
        adversary_run=adversary_run,
        sessions_dir=sessions_dir,
        session_id=session_id,
    )
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"ANTS Studio: http://{host}:{port}  (incumbent: {incumbent})")
    if state.session:
        print(f"session: {state.session.dir}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
