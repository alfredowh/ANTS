"""Live orchestrator console: a stdlib HTTP server around the Phase A closed loop.

Static viewers in this repo (`dashboard.py`, `ants.studio.run`) all read a saved JSONL trace after
a run finished. This module is the live counterpart: a person clicks Run, confirms a gate ("ready
to run the policy development phase?"), and the loop's turns -- attacks, rewrites, gate verdicts --
stream into the browser as they happen.

Two modes, picked by `--mode`:
- "loop" (default): drives the real closed loop, `ants.orchestrator.loop.Loop`, against the mock
  Adversary backend (free, offline, already tested) with Synthesizer's repair step real (`muse exec`
  via `MuseOrchestrator`). Only consumes `orchestrator`'s and `adversary`'s public APIs (`Loop`,
  `LoopConfig`, `Adversary`, `AdversaryConfig`, `GenerateSynthesizer`, `MuseOrchestrator`) the same
  way `orchestrator/run.py` and the tests do -- nothing here edits those packages.
- "single": the original v1 scope, one Phase A repair step with no Adversary call at all. Kept for
  a cheaper/faster demo path. This mode shells out to `muse exec --json` directly instead of going
  through `muse_cli.py`, reading its stdout line by line instead of waiting for the whole subprocess
  to finish, so it has no dependency on `orchestrator/` at all.
"""

from __future__ import annotations

import dataclasses
import json
import queue
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from ants.studio.policy_wizard import WizardManager, launch_generation

REPO_ROOT = Path(__file__).resolve().parents[3]
PHASES_DOC = REPO_ROOT / "docs" / "orchestrator" / "phases.md"
STUDIO_DIR = Path(__file__).parent
VIEWS_DIR = STUDIO_DIR / "views"
STATIC_DIR = STUDIO_DIR / "static"
# Whitelist: every /static/<name> and /views/<name>_stub route this server will serve.
STATIC_FILES = {
    "console.css": STATIC_DIR / "console.css",
    "console.js": STATIC_DIR / "console.js",
    "wizard.js": STATIC_DIR / "wizard.js",
}
STUB_FILES = {
    "synthesizer_stub": VIEWS_DIR / "synthesizer_stub.html",
    "adversary_stub": VIEWS_DIR / "adversary_stub.html",
}


def _assemble_shell() -> str:
    """Build the one served page from views/shell.html + its view fragments."""
    shell = (VIEWS_DIR / "shell.html").read_text(encoding="utf-8")
    fragments = {
        "<!--__AGENT_CONSOLE__-->": (VIEWS_DIR / "agent_console.html").read_text(encoding="utf-8"),
        "<!--__PERCEPTION__-->": (VIEWS_DIR / "perception.html").read_text(encoding="utf-8"),
        "<!--__SYNTHESIZER__-->": (VIEWS_DIR / "synthesizer.html").read_text(encoding="utf-8"),
        "<!--__ADVERSARY__-->": (VIEWS_DIR / "adversary.html").read_text(encoding="utf-8"),
    }
    for marker, content in fragments.items():
        shell = shell.replace(marker, content)
    return shell


# Archived example only: a real simulator rollout's agentview keyframes (exp04_scene, E3 evidence
# arm, sample0). This console's own loop runs Adversary on the mock backend, which has no simulator
# or camera -- there is nothing live to show here yet. Kept as a labelled reference, not live data.
AGENTVIEW_ARCHIVE_BASE = REPO_ROOT / "data" / "runs" / "exp04_scene" / "E-E3" / "sample0"


def _find_agentview_keyframes() -> dict[str, Path]:
    """name ("000001-before-open-gripper") -> its agentview.png, in one archived sample run."""
    matches = sorted(AGENTVIEW_ARCHIVE_BASE.rglob("media/keyframes/*/agentview.png"))
    return {m.parent.name: m for m in matches}


# Archived cuRobo trajectory/collision-sphere viewer (exp09-11, the held-bowl-attached work), a
# separate pre-built static page -- reused by linking out to it, not rebuilt here.
def _latest_plan_viewer() -> Path | None:
    """Newest cuRobo plan viewer (exp11 preferred over exp10), by experiment number then mtime."""
    base = REPO_ROOT / "data" / "runs" / "curobo"
    candidates = sorted(base.glob("exp*/**/plan_viewer/index*.html"))
    if not candidates:
        return None

    def rank(p: Path) -> tuple[int, float]:
        import re

        m = re.search(r"exp(\d+)", str(p))
        return (int(m.group(1)) if m else 0, p.stat().st_mtime)

    return max(candidates, key=rank)


PLAN_VIEWER_PATH = _latest_plan_viewer()


def _find_sam3_overlays() -> dict[str, Path]:
    """name ("sam3-000001-camera-agentview") -> its overlay PNG, same archived sample run."""
    matches = sorted(AGENTVIEW_ARCHIVE_BASE.rglob("media/overlays/sam3-*.png"))
    return {m.stem: m for m in matches}


def _parse_why(reply_text: str) -> str:
    """The leading WHY note from a MuseOrchestrator reply, before its fenced code block."""
    lines: list[str] = []
    for line in reply_text.splitlines():
        if line.strip().startswith("```"):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _sam3_overlay_meta(png_path: Path) -> dict:
    """Top SAM3 candidate (label, score) from the overlay's sibling JSON, if present."""
    json_path = png_path.with_suffix(".json")
    if not json_path.exists():
        return {}
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    candidates = data.get("candidates") or []
    top = max(candidates, key=lambda c: c.get("score", 0), default=None)
    if top is None:
        return {}
    return {"label": top.get("label"), "score": round(top.get("score", 0), 2)}


def _split_keyframe_name(name: str) -> dict[str, str]:
    """ "000001-before-open-gripper" -> {index: "000001", phase: "before", call: "open gripper"}."""
    index, _, rest = name.partition("-")
    phase, _, call = rest.partition("-")
    return {"index": index, "phase": phase, "call": call.replace("-", " ")}


# Where AspireBackend.run_program() writes each real rollout (adversary/rollout/aspire_backend.py's
# AspireConfig.output_root default). cap_harness's own artifact writer appends one keyframe/overlay
# directory to disk as each primitive call finishes, WHILE the subprocess is still running -- see
# ASPIRE/src/cap_harness/artifacts.py's `_keyframe`/overlay writers. So a thread polling this
# directory tree genuinely observes a rollout in progress, not just its finished result.
ASPIRE_LIVE_ROOT = REPO_ROOT / "data" / "runs" / "aspire"


def watch_aspire_live(state: RunState, stop: threading.Event) -> None:
    """Tail the newest real rollout's keyframes/SAM3 overlays, broadcasting each as it appears."""
    started = time.time()
    current: Path | None = None
    seen_kf: set[str] = set()
    seen_ov: set[str] = set()
    while not stop.is_set():
        if ASPIRE_LIVE_ROOT.exists():
            # Only runs touched since this watcher started count as live; an older finished
            # run must never flip the Perception tab to "live" with stale frames.
            run_dirs = sorted(
                (
                    p
                    for p in ASPIRE_LIVE_ROOT.iterdir()
                    if p.is_dir() and p.stat().st_mtime >= started - 1.0
                ),
                key=lambda p: p.stat().st_mtime,
            )
            if run_dirs and run_dirs[-1] != current:
                current = run_dirs[-1]
                seen_kf, seen_ov = set(), set()
                state.broadcast({"kind": "perception_run", "run_id": current.name})
            if current is not None:
                kf_dir = current / "media" / "keyframes"
                if kf_dir.exists():
                    for kf in sorted(kf_dir.iterdir()):
                        img = kf / "agentview.png"
                        if kf.name not in seen_kf and img.exists():
                            seen_kf.add(kf.name)
                            state.broadcast(
                                {
                                    "kind": "perception_keyframe",
                                    "run_id": current.name,
                                    "src": f"/live/keyframe/{current.name}/{kf.name}",
                                    **_split_keyframe_name(kf.name),
                                }
                            )
                ov_dir = current / "media" / "overlays"
                if ov_dir.exists():
                    for ov in sorted(ov_dir.glob("sam3-*.png")):
                        if ov.stem not in seen_ov:
                            seen_ov.add(ov.stem)
                            state.broadcast(
                                {
                                    "kind": "perception_sam3",
                                    "run_id": current.name,
                                    "name": ov.stem,
                                    "src": f"/live/overlay/{current.name}/{ov.stem}",
                                    **_sam3_overlay_meta(ov),
                                }
                            )
        time.sleep(0.3)


def _live_asset_path(run_id: str, rest: str, *, overlay: bool) -> Path | None:
    """Resolve a /live/keyframe or /live/overlay request, refusing anything outside the root."""
    candidate = (
        ASPIRE_LIVE_ROOT / run_id / "media" / "overlays" / f"{rest}.png"
        if overlay
        else ASPIRE_LIVE_ROOT / run_id / "media" / "keyframes" / rest / "agentview.png"
    )
    try:
        resolved = candidate.resolve()
        resolved.relative_to(ASPIRE_LIVE_ROOT.resolve())
    except (OSError, ValueError):
        return None
    return resolved if resolved.exists() else None


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


def _attacks_jsonl_path(out_dir: Path, run_name: str) -> Path | None:
    """Resolve a /attacks/<run_name> request, refusing anything outside out_dir."""
    candidate = out_dir / run_name / "attacks.jsonl"
    try:
        resolved = candidate.resolve()
        resolved.relative_to(out_dir.resolve())
    except (OSError, ValueError):
        return None
    return resolved if resolved.exists() else None


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
    # Chat: at most one of these is meaningful at a time.
    # - awaiting_answer: set while Loop's ask_human callback is blocked waiting for a chat reply
    #   (Case 1 -- the escalation this run stalled on).
    # - queued_chat: a message that arrived while a run was active, to auto-fire as a one-shot
    #   the moment the run goes idle (Case 3, queue-and-auto-fire).
    awaiting_answer: queue.Queue[str] | None = None
    queued_chat: str | None = None

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
    """What the Run button drives in "loop" mode: the real closed loop, mock Adversary backend.

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
    # Tell the UI where this run is being saved before anything runs, so the folder is
    # findable even if the run later crashes.
    state.broadcast({"kind": "run_started", "run_dir": str(run_dir), "backend": cfg.backend})
    policy = Policy(
        "bowl_on_plate", 0, "put the bowl on the plate", incumbent.read_text(encoding="utf-8")
    )

    adv_kwargs: dict = {
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
        return GateAnswer(channel="text", text=text)

    loop = Loop(adv, synth, loop_cfg, on_attack=on_attack, ask_human=ask_human)

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
                        state.broadcast({"kind": "loop_event", "row": row})
                    pos = f.tell()
            time.sleep(0.3)

    threads = [threading.Thread(target=tail, daemon=True)]
    if cfg.backend == "cap_harness":
        threads.append(
            threading.Thread(target=watch_aspire_live, args=(state, stop_tail), daemon=True)
        )
    for t in threads:
        t.start()
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
        TOOLS_RIGHT if mode == "loop" else [t for t in TOOLS_RIGHT if t["role"] != "Adversary"]
    )
    agentview = _find_agentview_keyframes()
    agentview_list = [
        {"name": name, "src": f"/agentview/{name}", **_split_keyframe_name(name)}
        for name in sorted(agentview)
    ]
    sam3 = _find_sam3_overlays()
    sam3_list = [
        {"name": name, "src": f"/sam3/{name}", **_sam3_overlay_meta(sam3[name])}
        for name in sorted(sam3)
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
        "agentview_archive": {
            "frames": agentview_list,
            "source": str(AGENTVIEW_ARCHIVE_BASE.relative_to(REPO_ROOT)),
            # No live camera feed exists yet: Adversary runs on the mock backend (no simulator, no
            # camera). "live" stays False until a real rollout backend actually streams frames; a
            # future live source should just flip this and add a live frame URL, not change the
            # the shape the perception tab reads.
            "live": False,
        },
        "sam3_archive": {
            "frames": sam3_list,
            "source": str(AGENTVIEW_ARCHIVE_BASE.relative_to(REPO_ROOT)),
            "live": False,  # same reason: no live perception call happens in this console's loop
        },
        "plan_viewer": {
            "available": PLAN_VIEWER_PATH is not None,
            "live": False,  # same reason: no live cuRobo call happens in this console's loop
            "name": str(PLAN_VIEWER_PATH.relative_to(REPO_ROOT)) if PLAN_VIEWER_PATH else None,
        },
    }
    page = _assemble_shell().replace("/*__DATA__*/null", json.dumps(data))

    def _set_running(on: bool) -> bool:
        with state.lock:
            if on and state.running:
                return False
            state.running = on
            return True

    def _wizard_run_loop(program: Path, answers: dict) -> None:
        cfg = dataclasses.replace(
            loop_cfg or LoopRunConfig(),
            cycles=answers.get("adv_cycles", 3),
            stall_window=answers.get("adv_stall", 2),
            eta=1.0 if answers.get("strategy") == "uniform" else 0.2,
            synth_token_budget=answers["synth_budget"],
        )
        run_live_loop(state, program, cfg)

    wizard = WizardManager(
        state.broadcast,
        launcher=lambda a, folder, emit: launch_generation(
            a, folder, emit, run_loop=_wizard_run_loop
        ),
        set_running=_set_running,
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
            if path.startswith("/views/"):
                name = path[len("/views/") :]
                file_path = STUB_FILES.get(name)  # whitelist
                if file_path is None or not file_path.exists():
                    self.send_response(404)
                    self.end_headers()
                    return
                body = file_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/perception/planviewer":
                if PLAN_VIEWER_PATH is None or not PLAN_VIEWER_PATH.exists():
                    self.send_response(404)
                    self.end_headers()
                    return
                body = PLAN_VIEWER_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path.startswith("/live/keyframe/") or path.startswith("/live/overlay/"):
                overlay = path.startswith("/live/overlay/")
                prefix = "/live/overlay/" if overlay else "/live/keyframe/"
                run_id, _, rest = path[len(prefix) :].partition("/")
                image_path = _live_asset_path(run_id, rest, overlay=overlay)
                if image_path is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                body = image_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache")  # live: never cache a stale frame
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/runs":
                self._send_json({"runs": _list_runs(loop_cfg.out_dir) if loop_cfg else []})
                return
            if path.startswith("/attacks/"):
                run_name = path[len("/attacks/") :]
                attacks_path = _attacks_jsonl_path(loop_cfg.out_dir, run_name) if loop_cfg else None
                if attacks_path is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                body = attacks_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-cache")  # appended to live during a run
                self.end_headers()
                self.wfile.write(body)
                return
            if path.startswith("/agentview/") or path.startswith("/sam3/"):
                prefix, lookup = (
                    ("/agentview/", agentview)
                    if path.startswith("/agentview/")
                    else ("/sam3/", sam3)
                )
                name = path[len(prefix) :]
                image_path = lookup.get(name)  # whitelist: only names this run actually found
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
            if path == "/wizard":
                self._send_json(wizard.state())
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
            if path == "/wizard":
                self._handle_wizard()
                return
            if path == "/upload":
                self._handle_upload()
                return
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

            def fire_queued_chat() -> None:
                with state.lock:
                    msg, state.queued_chat = state.queued_chat, None
                if msg:
                    run_chat_oneshot(
                        state,
                        incumbent,
                        msg,
                        reasoning_effort=reasoning_effort,
                        max_model_steps=max_model_steps,
                    )

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
                fire_queued_chat()

            def drive_loop() -> None:
                try:
                    run_live_loop(state, incumbent, loop_cfg)
                finally:
                    with state.lock:
                        state.running = False
                    fire_queued_chat()

            target = drive_loop if (mode == "loop" and loop_cfg is not None) else drive_single
            threading.Thread(target=target, daemon=True).start()
            self._send_json({"ok": True})

        def _handle_wizard(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            action = body.get("action")
            if action == "start":
                self._send_json(wizard.start())
            elif action == "cancel":
                self._send_json(wizard.cancel())
            elif action == "message":
                self._send_json(wizard.message(str(body.get("message") or "")))
            else:
                self._send_json({"ok": False, "error": "unknown action"}, status=400)

        def _handle_upload(self) -> None:
            limit = wizard.skill["limits"]["upload_max_mb"] * 1024 * 1024
            length = int(self.headers.get("Content-Length", "0"))
            name = unquote(self.headers.get("X-Filename", ""))
            target = wizard.upload_target(name)
            if target is None:
                self._send_json(
                    {
                        "ok": False,
                        "error": "no video is being asked for, or the file type is not "
                        "an allowed video extension",
                    },
                    status=400,
                )
                return
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
            self._send_json(wizard.uploaded(target))

        def _handle_chat(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            message = (body.get("message") or "").strip()
            if not message:
                self._send_json({"ok": False, "error": "empty message"}, status=400)
                return
            with state.lock:
                # Case 1: a run is escalated and waiting on exactly this -- answer it.
                if state.awaiting_answer is not None:
                    answer_q = state.awaiting_answer
                    answer_q.put(message)
                    self._send_json({"ok": True, "case": "answer"})
                    return
                # Case 3: a run is active but not escalated -- queue, auto-fire once idle.
                if state.running:
                    state.queued_chat = message
                    self._send_json({"ok": True, "case": "queued"})
                    return
                state.running = True

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
