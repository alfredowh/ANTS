"""`/policy-dev <task>`: the whole pipeline from a human video to a hardened program.

    video -> hurobo extraction -> DemoSpec JSON -> prompt -> Synthesizer -> Adversary loop -> gate

Defaults and limits are plain data in `docs/studio/skills/policy-dev.json`. Every stage reuses the
existing tool: `hurobo/scripts/02_extract_demos.py`, `tools/hurobo_demospec.py`,
`ants.orchestrator.demo_vs_nodemo` and the live `Loop` (through a `run_loop` callback). All of it
is logged to `<run>/pipeline.jsonl` and streamed as SSE events (`pipeline_*`).

Nothing is faked and nothing falls back silently: a rejected clip stops the run and says why; a
program that never passes its nominal seed ends as `no_working_policy` and is never attacked.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_PATH = REPO_ROOT / "docs" / "studio" / "skills" / "policy-dev.json"
ATTEMPT_LINE = re.compile(r"^\[(\w+) s(\d+) a(\d+)\] success=(\w+) reason=(.*)$")
SIMULATOR_MARKERS = ("aspire_launch.py", "cap-harness\0run", "cap_harness.cli\0run")

Emit = Callable[[dict], None]


def load_skill(path: Path = SKILL_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def task_problem(task: str, skill: dict) -> str | None:
    """Why this task cannot run on the one scene we have, or None."""
    if not task.strip():
        return "Type the task after /policy-dev, for example: /policy-dev put the bowl on the plate"
    words = skill["scene"]["task_must_mention"]
    if not all(w in task.lower() for w in words):
        return (
            f"This pipeline only has the bowl-on-plate scene ({skill['scene']['suite']} task "
            f"{skill['scene']['task_id']}), and the task does not mention "
            f"{' and '.join(words)}: {task!r}. Nothing was started."
        )
    return None


def video_problem(video: Path | None, skill: dict) -> str | None:
    if video is None:
        return None
    if video.suffix.lower() not in skill["video"]["extensions"]:
        return f"{video.name} does not have an allowed video extension."
    if not video.is_file():
        return f"Video not found: {video}"
    return None


def safe_upload_name(name: str, extensions: Iterable[str]) -> str | None:
    """A plain file name with a whitelisted video extension, or None."""
    base = Path(name.replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base).lstrip(".")
    if not base or Path(base).suffix.lower() not in extensions:
        return None
    return base


def native_env(env: dict) -> dict:
    """The environment for a desktop program. A server started from VS Code's snap inherits snap
    library paths, which make the system's zenity die with a symbol lookup error."""
    drop = {
        "LD_LIBRARY_PATH", "GTK_PATH", "GTK_EXE_PREFIX", "GTK_IM_MODULE_FILE", "GIO_MODULE_DIR",
        "GDK_PIXBUF_MODULE_FILE", "GDK_PIXBUF_MODULEDIR", "LOCPATH", "GSETTINGS_SCHEMA_DIR",
    }  # fmt: skip
    out = {k: v for k, v in env.items() if k not in drop}
    if "XDG_DATA_DIRS_VSCODE_SNAP_ORIG" in out:
        out["XDG_DATA_DIRS"] = out["XDG_DATA_DIRS_VSCODE_SNAP_ORIG"]
    return out


def pick_video(
    folder: Path,
    extensions: Iterable[str],
    *,
    run: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    env: dict | None = None,
    timeout_s: float = 600,
) -> dict:
    """The server-side native file dialog, opened at `folder`. Browsers cannot open a picker at a
    chosen path. `fallback: True` means use the browser's picker (upload) instead."""
    env = os.environ if env is None else env
    if not which("zenity"):
        return {"ok": False, "fallback": True, "reason": "zenity is not installed on the server"}
    if not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")):
        return {"ok": False, "fallback": True, "reason": "the server has no DISPLAY"}
    patterns = " ".join(f"*{e}" for e in extensions)
    start = folder if folder.is_dir() else Path.home()
    cmd = [
        "zenity", "--file-selection", "--title=Choose the human demo video",
        f"--filename={start}{os.sep}", f"--file-filter=Videos | {patterns}",
    ]  # fmt: skip
    try:
        done = run(
            cmd, capture_output=True, text=True, timeout=timeout_s, env=native_env(dict(env))
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "fallback": True, "reason": f"the file dialog failed: {exc}"}
    if done.returncode == 1:
        return {"ok": False, "cancelled": True}
    if done.returncode != 0:
        reason = (done.stderr or "").strip()[-300:] or f"exit {done.returncode}"
        return {"ok": False, "fallback": True, "reason": f"the file dialog failed: {reason}"}
    path = Path(done.stdout.strip())
    if path.suffix.lower() not in extensions:
        return {"ok": False, "error": f"{path.name} does not have an allowed video extension."}
    return {"ok": True, "path": str(path), "name": path.name}


def extraction_commands(video: Path, out: Path, skill: dict, root: Path = REPO_ROOT) -> dict:
    """The two real commands: clip to hurobo demo (.npz), demo to DemoSpec JSON."""
    e = skill["extraction"]
    python = str(root / e["python"])
    cwd = root / e["cwd"]
    npz = out / "hurobo" / f"{video.stem}.npz"
    return {
        "cwd": cwd,
        "extract": [
            python,
            "scripts/02_extract_demos.py",
            str(video),
            "--setup",
            e["setup"],
            "--intrinsics",
            e["intrinsics"],
            "--cuts",
            e["cuts"],
            "--marker-size-m",
            str(e["marker_size_m"]),
            "--out",
            str(out / "hurobo"),
        ],  # fmt: skip
        "npz": npz,
        "demospec_json": out / "demospec.json",
        "demospec": [
            python,
            "-I",
            str(root / "tools" / "hurobo_demospec.py"),
            str(npz),
            "--setup",
            str(cwd / e["setup"]),
            "--out",
            str(out / "demospec.json"),
        ],  # fmt: skip
    }


def clip_verdict(summary_json: Path) -> tuple[bool, list[str]]:
    """hurobo's own quality gates for the one clip: (usable, reasons)."""
    try:
        reports = json.loads(summary_json.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, [f"no extraction summary: {exc}"]
    if not reports:
        return False, ["the extraction summary is empty"]
    return bool(reports[0].get("usable")), list(reports[0].get("reasons") or [])


def generation_command(
    task: str, demospec: Path, out: Path, budget: int, has_demo: bool, skill: dict,
    root: Path = REPO_ROOT,
) -> list[str]:  # fmt: skip
    """One sample, one arm, debugged in the same stock scene the Adversary attacks; no evaluation
    seeds here, because the loop does its own acceptance replay."""
    s, scene = skill["synthesizer"], skill["scene"]
    return [
        sys.executable, "-m", "ants.orchestrator.demo_vs_nodemo",
        "--aspire", str(Path(os.environ.get("ANTS_ASPIRE_ROOT", root / "ASPIRE"))),
        "--out", str(out),
        "--demospec", str(demospec),
        "--arms", s["arm_with_video"] if has_demo else s["arm_without_video"],
        "--temperatures", str(s["temperature"]),
        "--suite", scene["suite"], "--task-id", str(scene["task_id"]), "--task", task,
        "--debug-seed", str(scene["debug_seed"]), "--eval-seeds", "",
        "--scenes", scene["scene"], "--debug-scene", scene["scene"],
        "--repairs", str(s["repairs"]), "--token-budget", str(budget),
    ]  # fmt: skip


def passing_program(out: Path, arm: str) -> tuple[Path | None, dict]:
    """The latest attempt whose rollout really passed the nominal seed (from `record.json`), or
    None. The newest `program_attempt*.py` is NOT the answer: it may be a failing last repair."""
    sample = out / arm / "sample0"
    try:
        record = json.loads((sample / "record.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, {}
    for attempt in reversed(record.get("attempts", [])):
        if (attempt.get("trace") or {}).get("task_success"):
            program = sample / f"program_attempt{attempt['attempt']}.py"
            return (program if program.is_file() else None), record
    return None, record


def generation_tokens(out: Path) -> int:
    """New (uncached) tokens spent by the generation stage so far, from its event log."""
    total = 0
    try:
        lines = (out / "events.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        data = row.get("data") if isinstance(row.get("data"), dict) else row
        if row.get("kind") == "program" and not data.get("from_cache"):
            total += int(data.get("tokens") or 0)
    return total


def loop_budget(total: int, generation_spent: int, headroom: int) -> int:
    """What the rewrites may still spend; <= 0 means no rewrite is allowed."""
    return total - generation_spent - headroom


def build_prompt_preview(
    task: str, demo_summary: dict | None, out: Path, root: Path = REPO_ROOT
) -> dict:
    """The exact first prompt, saved before any spend (same function and inputs as generation)."""
    from ants.orchestrator.demo_vs_nodemo import EXAMPLE, EXAMPLE_TASK
    from ants.synthesizer.generator import build_messages

    aspire = Path(os.environ.get("ANTS_ASPIRE_ROOT", root / "ASPIRE"))
    api_ref = (aspire / "docs" / "api-reference.md").read_text(encoding="utf-8")
    example = (aspire / EXAMPLE).read_text(encoding="utf-8")
    messages = build_messages(api_ref, example, EXAMPLE_TASK, task, demo_summary)
    path = out / "prompt_messages.json"
    path.write_text(json.dumps(messages, indent=1), encoding="utf-8")
    return {
        "path": str(path),
        "chars": sum(len(str(m.get("content", ""))) for m in messages),
        "has_demo": demo_summary is not None,
    }


def other_simulator_jobs(proc: Path = Path("/proc"), own: int | None = None) -> list[str]:
    """Simulator runs already on this machine. Two at once give fake 'invalid depth' failures."""
    found = []
    own = os.getpid() if own is None else own
    if not proc.is_dir():
        return found
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == own:
            continue
        try:
            cmd = (entry / "cmdline").read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        if any(m in cmd for m in SIMULATOR_MARKERS):
            found.append(f"pid {entry.name}: {cmd.replace(chr(0), ' ').strip()[:160]}")
    return found


class Stopped(Exception):
    """The user pressed Stop."""


@dataclass
class Request:
    task: str
    video: Path | None
    run_dir: Path


class Pipeline:
    """One run, on the calling thread. `popen` and `run_loop` are injectable, so tests spend
    nothing."""

    def __init__(
        self,
        req: Request,
        skill: dict,
        emit: Emit,
        *,
        run_loop: Callable[[Path, str, Path, int], None],
        stop_requested: Callable[[], bool] = lambda: False,
        popen: Callable[..., Any] = subprocess.Popen,
        root: Path = REPO_ROOT,
        simulator_jobs: Callable[[], list[str]] = other_simulator_jobs,
        prompt_preview: Callable[..., dict] = build_prompt_preview,
    ) -> None:
        self.req, self.skill, self._emit = req, skill, emit
        self.run_loop, self.stop_requested = run_loop, stop_requested
        self.popen, self.root = popen, root
        self.simulator_jobs, self.prompt_preview = simulator_jobs, prompt_preview
        self.log_path = req.run_dir / "pipeline.jsonl"

    # -- logging ---------------------------------------------------------------------------
    def stage(self, stage: str, status: str, detail: str = "", **data: Any) -> None:
        row = {"stage": stage, "status": status, "detail": detail, **data}
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), **row}) + "\n")
        self._emit({"kind": "pipeline_stage", **row})

    def finish(self, stopped: str, stage: str, message: str = "") -> None:
        self.stage("finished", stopped, message)
        self._emit(
            {
                "kind": "done",
                "stopped": stopped,
                "stage": stage,
                "final_version": None,
                "accepted_versions": [],
                "escalation": None,
            }
        )

    def check_stop(self) -> None:
        if self.stop_requested():
            raise Stopped

    def run_cmd(self, stage: str, cmd: list[str], cwd: Path, log: Path, on_line=None) -> int:
        self.check_stop()
        self.stage(stage, "command", " ".join(cmd), cwd=str(cwd))
        with log.open("a", encoding="utf-8") as fh:
            proc = self.popen(
                cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )  # fmt: skip
            for line in proc.stdout:
                fh.write(line)
                text = line.rstrip()
                if text and not text.startswith(("W0000", "I0000", "INFO:", "WARNING:")):
                    self._emit({"kind": "pipeline_output", "stage": stage, "line": text})
                if on_line:
                    on_line(text)
            code = proc.wait()
        self.check_stop()
        return code

    # -- stages ----------------------------------------------------------------------------
    def preflight(self) -> bool:
        cmd = [
            sys.executable, "-m", "ants.orchestrator.preflight",
            "--aspire", str(Path(os.environ.get("ANTS_ASPIRE_ROOT", self.root / "ASPIRE"))),
            "--muse-code",
        ]  # fmt: skip
        self.stage("preflight", "running", "Checking simulator, services, GPU, disk, Muse access")
        code = self.run_cmd("preflight", cmd, self.root, self.req.run_dir / "preflight.log")
        jobs = self.simulator_jobs()
        if jobs:
            self.stage("preflight", "failed", "Another simulator is running: " + "; ".join(jobs))
            self.finish(
                "preflight_failed", "preflight",
                "Another simulator job is running. Two at once give fake depth failures, so "
                "nothing was started and no tokens were spent. Wait for it or stop it.",
            )  # fmt: skip
            return False
        if code != 0:
            self.stage("preflight", "failed", "See the lines above. No tokens were spent.")
            self.finish("preflight_failed", "preflight", "Preflight failed; nothing was spent.")
            return False
        self.stage("preflight", "ok", "Ready")
        return True

    def extract(self) -> Path | None:
        """Video to DemoSpec, or None after saying why."""
        out = self.req.run_dir / "demo"
        (out / "hurobo").mkdir(parents=True, exist_ok=True)
        c = extraction_commands(self.req.video, out, self.skill, self.root)
        e = self.skill["extraction"]
        self.stage(
            "extraction", "running",
            f"Reading {self.req.video.name}: hand and marker tracking "
            f"(marker size {e['marker_size_m'] * 100:g} cm, the measured value)",
        )  # fmt: skip
        log = out / "extraction.log"
        code = self.run_cmd("extraction", c["extract"], c["cwd"], log)
        usable, reasons = clip_verdict(out / "hurobo" / "summary.json")
        if code != 0 or not usable or not c["npz"].is_file():
            why = "; ".join(reasons) or f"the extractor exited {code}; see {log}"
            self.stage("extraction", "rejected", why)
            self.finish(
                "extraction_rejected", "extraction",
                f"This clip cannot be used: {why}. Only clips of the marker setup work. Choose "
                "another clip, or send /policy-dev <task> with no video for a no-demo run.",
            )  # fmt: skip
            return None
        self.stage("extraction", "ok", "All quality gates passed", demo=str(c["npz"]))
        code = self.run_cmd("demospec", c["demospec"], self.root, log)
        spec = c["demospec_json"]
        if code != 0 or not spec.is_file():
            self.stage("demospec", "failed", f"tools/hurobo_demospec.py exited {code}; see {log}")
            self.finish("demospec_failed", "demospec", "Could not build the DemoSpec.")
            return None
        return spec

    def generate(
        self, program_out: Path, demospec: Path, has_demo: bool
    ) -> tuple[Path | None, int]:
        budget = self.skill["budget"]
        cap = budget["generation_tokens"]
        cmd = generation_command(
            self.req.task, demospec, program_out, cap, has_demo, self.skill, self.root
        )

        def on_line(text: str) -> None:
            m = ATTEMPT_LINE.match(text)
            if m:
                self.stage(
                    "generation",
                    "attempt",
                    f"Attempt {m[3]} on seed {self.skill['scene']['debug_seed']}: "
                    f"{'passed' if m[4] == 'True' else 'failed'} ({m[5]})",
                    attempt=int(m[3]),
                    success=m[4] == "True",
                    tokens=generation_tokens(program_out),
                )

        self.stage(
            "generation", "running", f"Writing the program with Muse, cap {cap:,} new tokens"
        )
        code = self.run_cmd(
            "generation", cmd, self.root, self.req.run_dir / "generation.log", on_line
        )
        spent = generation_tokens(program_out)
        arm = self.skill["synthesizer"]["arm_with_video" if has_demo else "arm_without_video"]
        program, record = passing_program(program_out, arm)
        sent = program_out / arm / "sample0" / "messages_attempt0.json"
        saved = self.req.run_dir / "prompt_messages.json"
        if sent.is_file() and saved.is_file():
            same = json.loads(sent.read_text("utf-8")) == json.loads(saved.read_text("utf-8"))
            self.stage("prompt", "checked", f"Sent prompt equals the saved one: {same}", same=same)
        if code != 0:
            self.stage("generation", "failed", f"The generator exited {code}", tokens=spent)
            return None, spent
        if program is None:
            why = record.get("stopped") or "no attempt passed the nominal seed"
            self.stage("nominal", "failed", why, tokens=spent)
            return None, spent
        self.stage("nominal", "ok", f"{program.name} passed the nominal seed", program=str(program))
        return program, spent

    def run(self) -> None:
        req, skill = self.req, self.skill
        req.run_dir.mkdir(parents=True, exist_ok=True)
        budget = skill["budget"]
        self.stage(
            "start", "running",
            f"Task: {req.task}\nVideo: {req.video or 'none (no-demo run)'}\n"
            f"Muse cap: {budget['total_tokens']:,} tokens "
            f"(about ${budget['total_tokens'] / 1e6 * budget['usd_per_million_tokens']:.2f})\n"
            f"Folder: {req.run_dir}",
            run_dir=str(req.run_dir),
        )  # fmt: skip
        try:
            if not self.preflight():
                return
            demo_dir = req.run_dir / "demo"
            demo_dir.mkdir(parents=True, exist_ok=True)
            if req.video is not None:
                spec = self.extract()
                if spec is None:
                    return
                summary = json.loads(spec.read_text(encoding="utf-8"))["summary"]
                self.stage(
                    "demospec", "ok", json.dumps(summary, indent=1), path=str(spec),
                )  # fmt: skip
            else:
                # demo_vs_nodemo requires the argument but its no-demo arm never reads the content
                spec = demo_dir / "no_demo.json"
                spec.write_text(json.dumps({"summary": {}}), encoding="utf-8")
                summary = None
                self.stage("demospec", "skipped", "No video attached: this is a no-demo run")
            preview = self.prompt_preview(req.task, summary, req.run_dir, self.root)
            self.stage(
                "prompt", "ok",
                f"Prompt built, {preview['chars']:,} characters, "
                f"{'with' if preview['has_demo'] else 'without'} the demonstration",
                path=preview["path"],
            )  # fmt: skip
            program, spent = self.generate(req.run_dir / "generation", spec, req.video is not None)
            if program is None:
                self.finish(
                    "no_working_policy", "draft",
                    f"No program passed its nominal seed ({spent:,} tokens spent), so it was not "
                    "attacked. A person has to look at the attempts, or give one targeted demo.",
                )  # fmt: skip
                return
            left = loop_budget(budget["total_tokens"], spent, budget["one_call_headroom_tokens"])
            self.stage(
                "adversary", "running",
                f"Attacking {program.name}. Generation spent {spent:,} tokens; rewrites may "
                f"spend {max(left, 0):,}.",
                tokens=spent,
            )  # fmt: skip
            self.check_stop()
            self.run_loop(program, req.task, req.run_dir, max(left, 0))
            self.stage("adversary", "finished", "The loop ended", tokens=spent)
        except Stopped:
            self.finish("user_stop", "stopped", "Stopped by you.")


class Manager:
    """The single pipeline of this server."""

    def __init__(
        self,
        emit: Emit,
        *,
        set_running: Callable[[bool], bool],
        run_loop: Callable[[Path, str, Path, int], None],
        stop_requested: Callable[[], bool],
        clear_stop: Callable[[], None],
        runs_dir: Callable[[], Path],
        skill: dict | None = None,
        pipeline: Callable[..., Pipeline] = Pipeline,
    ) -> None:
        self.emit, self.set_running = emit, set_running
        self.run_loop, self.stop_requested, self.clear_stop = run_loop, stop_requested, clear_stop
        self.runs_dir = runs_dir
        self.skill = skill or load_skill()
        self.pipeline = pipeline
        self.current: dict | None = None

    def start(self, task: str, video: str | None) -> dict:
        path = Path(video) if video else None
        problem = task_problem(task, self.skill) or video_problem(path, self.skill)
        if problem:
            return {"ok": False, "error": problem}
        if not self.set_running(True):
            return {"ok": False, "error": "A run is already in progress; wait or press Stop."}
        self.clear_stop()
        run_dir = self.runs_dir() / time.strftime("run-%Y%m%dT%H%M%S")
        run_dir.mkdir(parents=True, exist_ok=True)
        self.current = {"task": task, "video": video, "run_dir": str(run_dir)}
        self.emit({"kind": "pipeline_start", **self.current})

        def work() -> None:
            try:
                self.pipeline(
                    Request(task, path, run_dir), self.skill, self.emit,
                    run_loop=self.run_loop, stop_requested=self.stop_requested,
                ).run()  # fmt: skip
            except Exception as exc:  # noqa: BLE001 -- surface any failure in the console
                self.emit({"kind": "error", "message": f"{type(exc).__name__}: {exc}"})
            finally:
                self.set_running(False)

        threading.Thread(target=work, daemon=True).start()
        return {"ok": True, **self.current}
