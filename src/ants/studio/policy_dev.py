"""`/policy-dev <task>`: the whole pipeline from a human video to a hardened program.

    video -> hurobo extraction -> DemoSpec JSON -> prompt -> Synthesizer -> Adversary loop -> gate

Defaults and limits are plain data in `docs/studio/skills/policy-dev.json`. Every stage reuses the
existing tool: `hurobo/scripts/02_extract_demos.py`, `tools/hurobo_demospec.py`,
`ants.orchestrator.demo_vs_nodemo` and the live `Loop` (through a `run_loop` callback). All of it
is logged to `<run>/pipeline.jsonl` and `<run>/settings.json`.

SSE contract, also read by the process-flow view: every stage in `STAGES` is reported as
`{"kind": "pipeline_stage", "stage", "status": started|done|failed|skipped, "detail", "cycle"}`,
only when it really happens or is observed. Everything else (preflight, start, finished) is a
`pipeline_note`; tool output is `pipeline_output`.

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
STAGES = (
    "video", "extract", "demospec", "prompt", "generate", "nominal",
    "attack", "diagnose", "rewrite", "gate", "deploy",
)  # fmt: skip
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


def stage_event(
    stage: str, status: str, detail: str = "", cycle: int | None = None, **extra
) -> dict:
    if stage not in STAGES or status not in ("started", "done", "failed", "skipped"):
        raise ValueError(f"not in the event contract: {stage} {status}")
    return {
        "kind": "pipeline_stage", "stage": stage, "status": status, "detail": detail,
        "cycle": cycle, **extra,
    }  # fmt: skip


def parse_settings(raw: dict | None, skill: dict) -> tuple[dict, str | None]:
    """Dialog values to validated settings (defaults for anything absent), or an error message."""
    raw = raw or {}
    spec = skill["settings"]
    out: dict[str, Any] = {}
    for key, field in spec.items():
        value = raw.get(key, field["default"])
        if field["type"] == "bool":
            value = value is True or str(value).lower() in ("true", "1", "on")
        elif field["type"] == "int":
            try:
                value = int(value)
            except (TypeError, ValueError):
                return {}, f"{field['label']} must be a whole number."
            if not field["min"] <= value <= field["max"]:
                return {}, f"{field['label']} must be {field['min']:,} to {field['max']:,}."
        elif field["type"] == "choice":
            if value not in [c["value"] for c in field["choices"]]:
                return {}, f"{field['label']}: {value!r} is not an option."
        else:
            value = str(value or "").strip()
        out[key] = value
    if not out["synthesizer"] and not out["adversary"]:
        return {}, "Both modules are off, so there is nothing to run. Turn at least one on."
    if not out["synthesizer"]:
        script = Path(out["main_script"]) if out["main_script"] else None
        if script is None:
            return {}, "The Synthesizer is off: choose the main robot script to attack."
        if script.suffix.lower() not in spec["main_script"]["extensions"]:
            return {}, f"{script.name} is not a .py file."
        if not script.is_file():
            return {}, f"Main robot script not found: {script}"
    choice = next(c for c in spec["strategy"]["choices"] if c["value"] == out["strategy"])
    out["eta"] = choice["eta"]
    return out, None


def nominal_seeds(settings: dict, skill: dict) -> tuple[int, ...]:
    """Acceptance seeds only; `parse_settings` bounds the count to the 51-65 range."""
    first = skill["loop"]["acceptance_seed_first"]
    return tuple(range(first, first + settings["seeds"]))


def worst_case_note(settings: dict, skill: dict) -> str:
    """Honest estimate shown before the run and logged: what the settings could need vs the cap."""
    b = skill["budget"]
    cap = settings["token_cap"]
    usd = cap / 1e6 * b["usd_per_million_tokens"]
    if not settings["synthesizer"]:
        return "No Muse tokens: the Synthesizer is off, so nothing is generated or rewritten."
    calls = settings["max_retries"] + 1 + (settings["attacks"] if settings["adversary"] else 0)
    need = calls * b["tokens_per_call_estimate"]
    note = (
        f"Cap {cap:,} tokens, at most about ${usd:.2f}. Up to {calls} calls, about {need:,} tokens."
    )
    if need > cap - b["one_call_headroom_tokens"]:
        note += " That can pass the cap; the run then ends as a budget stop."
    return note


def save_deployed(src: Path, version: int, deploy_dir: Path) -> dict:
    """The deploy folder: a timestamped copy that is never overwritten, plus latest.py/.json."""
    deploy_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    code = src.read_text(encoding="utf-8")
    target = deploy_dir / f"{stamp}-v{version}.py"
    target.write_text(code, encoding="utf-8")
    (deploy_dir / "latest.py").write_text(code, encoding="utf-8")
    info = {"deployed": stamp, "version": version, "source": str(src), "file": target.name}
    (deploy_dir / "latest.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


class ObservedAdversary:
    """Reports what an `Adversary.attack()` call shows from outside. Selection, rollout and
    diagnosis all run inside that one call, so attack starts before it, and attack and diagnose end
    after it; no finer timing exists. Everything else passes through."""

    def __init__(self, adv: Any, emit: Emit) -> None:
        self._adv, self._emit = adv, emit
        self.cycle = -1

    def __getattr__(self, name: str) -> Any:
        return getattr(self._adv, name)

    def attack(self, policy: Any) -> Any:
        self.cycle += 1
        self._emit(stage_event("attack", "started", f"attacking v{policy.version}", self.cycle))
        try:
            report = self._adv.attack(policy)
        except Exception as exc:
            self._emit(stage_event("attack", "failed", f"{type(exc).__name__}", self.cycle))
            raise
        p = report.perturbation
        detail = f"{p.category} severity {p.severity:.2f}: {report.result.outcome.value}"
        self._emit(stage_event("attack", "done", detail, self.cycle))
        if report.failure is not None:
            self._emit(stage_event("diagnose", "done", report.failure.mode, self.cycle))
        return report


class ObservedSynthesizer:
    """Reports the rewrite and the gate replay that follows it. The gate's verdict comes from the
    loop log (`gate_verdict_event`)."""

    def __init__(self, synth: Any, emit: Emit, adversary: ObservedAdversary) -> None:
        self._synth, self._emit, self._adv = synth, emit, adversary

    def __getattr__(self, name: str) -> Any:
        return getattr(self._synth, name)

    def rewrite(self, incumbent: Any, feedback: Any, constraints: Any) -> Any:
        cycle = self._adv.cycle
        self._emit(stage_event("rewrite", "started", f"repairing v{incumbent.version}", cycle))
        candidate = self._synth.rewrite(incumbent, feedback, constraints)
        if candidate is None:
            self._emit(stage_event("rewrite", "failed", "no candidate", cycle))
            return None
        self._emit(stage_event("rewrite", "done", f"candidate v{candidate.version}", cycle))
        self._emit(stage_event("gate", "started", "replaying every case seen so far", cycle))
        return candidate


def gate_verdict_event(row: dict) -> dict | None:
    """The gate's verdict from one `loop.jsonl` row, if that row has one."""
    decision = row.get("decision")
    if row.get("event") != "cycle" or decision not in ("accepted", "rejected"):
        return None
    return stage_event("gate", "done", decision, row.get("cycle"), decision=decision)


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


def pick_file(
    folder: Path,
    extensions: Iterable[str],
    *,
    title: str = "Choose the human demo video",
    filter_name: str = "Videos",
    run: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    env: dict | None = None,
    timeout_s: float = 600,
) -> dict:
    """The server-side native file dialog, opened at `folder`. Browsers cannot open a picker at a
    chosen path. `fallback: True` means the dialog is unavailable."""
    env = os.environ if env is None else env
    if not which("zenity"):
        return {"ok": False, "fallback": True, "reason": "zenity is not installed on the server"}
    if not (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")):
        return {"ok": False, "fallback": True, "reason": "the server has no DISPLAY"}
    patterns = " ".join(f"*{e}" for e in extensions)
    start = folder if folder.is_dir() else Path.home()
    cmd = [
        "zenity", "--file-selection", f"--title={title}",
        f"--filename={start}{os.sep}", f"--file-filter={filter_name} | {patterns}",
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
        return {"ok": False, "error": f"{path.name} does not have an allowed extension."}
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
    task: str, demospec: Path, out: Path, budget: int, repairs: int, has_demo: bool, skill: dict,
    root: Path = REPO_ROOT,
) -> list[str]:  # fmt: skip
    """One sample, one arm, debugged in the same stock scene the Adversary attacks; no evaluation
    seeds here, because the loop does its own acceptance replay."""
    s, scene = skill["generation"], skill["scene"]
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
        "--repairs", str(repairs), "--token-budget", str(budget),
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
    settings: dict


class Pipeline:
    """One run, on the calling thread. `popen` and the callbacks are injectable, so tests spend
    nothing. `run_loop(program, task, run_dir, budget, settings)` is the closed loop;
    `run_attacks(program, task, run_dir, settings)` attacks without repair (Synthesizer off)."""

    def __init__(
        self,
        req: Request,
        skill: dict,
        emit: Emit,
        *,
        run_loop: Callable[..., None],
        run_attacks: Callable[..., None],
        stop_requested: Callable[[], bool] = lambda: False,
        popen: Callable[..., Any] = subprocess.Popen,
        root: Path = REPO_ROOT,
        simulator_jobs: Callable[[], list[str]] = other_simulator_jobs,
        prompt_preview: Callable[..., dict] = build_prompt_preview,
        deploy_dir: Path | None = None,
    ) -> None:
        self.req, self.skill, self._emit = req, skill, emit
        self.run_loop, self.run_attacks, self.stop_requested = run_loop, run_attacks, stop_requested
        self.popen, self.root = popen, root
        self.simulator_jobs, self.prompt_preview = simulator_jobs, prompt_preview
        self.deploy_dir = deploy_dir or root / "data" / "deploy"
        self.log_path = req.run_dir / "pipeline.jsonl"
        self._log_lock = threading.Lock()

    # -- logging ---------------------------------------------------------------------------
    def _log(self, row: dict) -> None:
        line = json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), **row}) + "\n"
        with self._log_lock, self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def stage(
        self, stage: str, status: str, detail: str = "", cycle: int | None = None, **extra: Any
    ) -> None:
        event = stage_event(stage, status, detail, cycle, **extra)
        self._log(event)
        self._emit(event)

    def note(self, name: str, status: str, detail: str = "", **extra: Any) -> None:
        event = {"kind": "pipeline_note", "note": name, "status": status, "detail": detail, **extra}
        self._log(event)
        self._emit(event)

    def finish(self, stopped: str, stage: str, message: str = "") -> None:
        self.note("finished", stopped, message)
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

    def run_cmd(self, stage: str, cmd: list[str], cwd: Path, log: Path) -> int:
        self.check_stop()
        self._log({"kind": "command", "stage": stage, "cmd": cmd, "cwd": str(cwd)})
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
            code = proc.wait()
        self.check_stop()
        return code

    # -- stages ----------------------------------------------------------------------------
    def preflight(self, simulator: bool) -> bool:
        cmd = [
            sys.executable, "-m", "ants.orchestrator.preflight",
            "--aspire", str(Path(os.environ.get("ANTS_ASPIRE_ROOT", self.root / "ASPIRE"))),
        ]  # fmt: skip
        if self.req.settings["synthesizer"]:
            cmd.append("--muse-code")
        self.note("preflight", "running", "Checking simulator, services, GPU, disk, Muse access")
        code = self.run_cmd("preflight", cmd, self.root, self.req.run_dir / "preflight.log")
        jobs = self.simulator_jobs() if simulator else []
        if jobs:
            self.finish(
                "preflight_failed", "preflight",
                "Another simulator job is running, and two at once give fake depth failures, so "
                "nothing was started and no tokens were spent: " + "; ".join(jobs),
            )  # fmt: skip
            return False
        if code != 0:
            self.finish("preflight_failed", "preflight", "Preflight failed; no tokens were spent.")
            return False
        self.note("preflight", "ok", "Ready")
        return True

    def extract(self) -> Path | None:
        """Video to DemoSpec, or None after saying why."""
        out = self.req.run_dir / "demo"
        (out / "hurobo").mkdir(parents=True, exist_ok=True)
        c = extraction_commands(self.req.video, out, self.skill, self.root)
        e = self.skill["extraction"]
        self.stage(
            "extract", "started",
            f"Reading {self.req.video.name}: hand and marker tracking "
            f"(marker size {e['marker_size_m'] * 100:g} cm, the measured value)",
        )  # fmt: skip
        log = out / "extraction.log"
        code = self.run_cmd("extract", c["extract"], c["cwd"], log)
        usable, reasons = clip_verdict(out / "hurobo" / "summary.json")
        if code != 0 or not usable or not c["npz"].is_file():
            why = "; ".join(reasons) or f"the extractor exited {code}; see {log}"
            self.stage("extract", "failed", why)
            self.finish(
                "extraction_rejected", "extract",
                f"This clip cannot be used: {why}. Only clips of the marker setup work. Choose "
                "another clip, or send /policy-dev <task> with no video for a no-demo run.",
            )  # fmt: skip
            return None
        self.stage("extract", "done", "All quality gates passed", demo=str(c["npz"]))
        self.stage("demospec", "started", "Building the DemoSpec")
        code = self.run_cmd("demospec", c["demospec"], self.root, log)
        spec = c["demospec_json"]
        if code != 0 or not spec.is_file():
            self.stage("demospec", "failed", f"tools/hurobo_demospec.py exited {code}; see {log}")
            self.finish("demospec_failed", "demospec", "Could not build the DemoSpec.")
            return None
        return spec

    def _report_generation(self, out: Path, seen: list[int]) -> None:
        """Turn new rows of the generator's event log into stages: `program` means a call ended and
        the rollout begins, `rollout` means the nominal seed finished, `feedback` means a repair
        call begins."""
        try:
            rows = (out / "events.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in rows[seen[0] :]:
            seen[0] += 1
            try:
                row = json.loads(line)
            except ValueError:
                continue
            kind, attempt = row.get("kind"), row.get("attempt")
            if kind == "program":
                tokens = generation_tokens(out)
                self.stage(
                    "generate", "done", f"Attempt {attempt}: {row.get('lines')} lines, "
                    f"{tokens:,} new tokens so far", attempt=attempt, tokens=tokens,
                )  # fmt: skip
                self.stage("nominal", "started", f"Attempt {attempt} on the nominal seed")
            elif kind == "rollout":
                ok = bool(row.get("success"))
                self.stage(
                    "nominal", "done" if ok else "failed",
                    f"Attempt {attempt}: {'passed' if ok else 'failed'} ({row.get('reason')})",
                    attempt=attempt, success=ok,
                )  # fmt: skip
            elif kind == "feedback":
                self.stage("generate", "started", f"Repair after attempt {attempt}")

    def generate(self, out: Path, demospec: Path, has_demo: bool) -> tuple[Path | None, int, dict]:
        cfg, headroom = self.req.settings, self.skill["budget"]["one_call_headroom_tokens"]
        cap = max(cfg["token_cap"] - headroom, 0)
        cmd = generation_command(
            self.req.task, demospec, out, cap, cfg["max_retries"], has_demo, self.skill, self.root
        )
        self.stage("generate", "started", f"Writing the program with Muse, up to {cap:,} tokens")
        seen, finished = [0], threading.Event()

        def watch() -> None:
            while not finished.wait(1.0):
                self._report_generation(out, seen)

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        try:
            code = self.run_cmd("generate", cmd, self.root, self.req.run_dir / "generation.log")
        finally:
            finished.set()
            watcher.join()
        self._report_generation(out, seen)
        spent = generation_tokens(out)
        g = self.skill["generation"]
        arm = g["arm_with_video"] if has_demo else g["arm_without_video"]
        program, record = passing_program(out, arm)
        sent = out / arm / "sample0" / "messages_attempt0.json"
        saved = self.req.run_dir / "prompt_messages.json"
        if sent.is_file() and saved.is_file():
            same = json.loads(sent.read_text("utf-8")) == json.loads(saved.read_text("utf-8"))
            self._log({"kind": "prompt_check", "sent_equals_saved": same})
        if code != 0:
            self.stage("generate", "failed", f"The generator exited {code}", tokens=spent)
        return program, spent, record

    def prepare_demo(self) -> tuple[Path, dict | None] | None:
        req = self.req
        demo_dir = req.run_dir / "demo"
        demo_dir.mkdir(parents=True, exist_ok=True)
        if req.video is None:
            # demo_vs_nodemo requires the argument but its no-demo arm never reads the content
            spec = demo_dir / "no_demo.json"
            spec.write_text(json.dumps({"summary": {}}), encoding="utf-8")
            for stage in ("video", "extract", "demospec"):
                self.stage(stage, "skipped", "No video attached: this is a no-demo run")
            return spec, None
        self.stage("video", "done", str(req.video))
        spec = self.extract()
        if spec is None:
            return None
        summary = json.loads(spec.read_text(encoding="utf-8"))["summary"]
        self.stage("demospec", "done", json.dumps(summary, indent=1), path=str(spec))
        return spec, summary

    def synthesize(self) -> tuple[Path, int] | None:
        """Video to a program that passed its nominal seed, or None after finishing the run."""
        req = self.req
        prepared = self.prepare_demo()
        if prepared is None:
            return None
        spec, summary = prepared
        self.stage("prompt", "started", "Building the prompt")
        preview = self.prompt_preview(req.task, summary, req.run_dir, self.root)
        self.stage(
            "prompt", "done",
            f"{preview['chars']:,} characters, "
            f"{'with' if preview['has_demo'] else 'without'} the demonstration",
            path=preview["path"],
        )  # fmt: skip
        out = req.run_dir / "generation"
        program, spent, record = self.generate(out, spec, req.video is not None)
        if program is not None:
            self.note("program", "ok", f"{program.name} passed the nominal seed", path=str(program))
            return program, spent
        if record.get("stopped"):
            self.finish(
                "budget", "draft",
                f"Budget stop during generation at {spent:,} tokens: {record['stopped']}. No "
                "attempt passed its nominal seed, so nothing was attacked.",
            )  # fmt: skip
        else:
            self.finish(
                "no_working_policy", "draft",
                f"No program passed its nominal seed ({spent:,} tokens spent), so it was not "
                "attacked. A person has to look at the attempts, or give one targeted demo.",
            )  # fmt: skip
        return None

    def deploy(self, program: Path, spent: int) -> None:
        self.stage("deploy", "started", "Saving the main program")
        info = save_deployed(program, 0, self.deploy_dir)
        path = self.deploy_dir / info["file"]
        self.stage("deploy", "done", str(path), path=str(path))
        self.finish(
            "deployed", "attackable",
            f"Saved to {path} (also latest.py). The Adversary is off, so it was not attacked. "
            f"{spent:,} new tokens spent.",
        )  # fmt: skip

    def run(self) -> None:
        req, cfg, skill = self.req, self.req.settings, self.skill
        req.run_dir.mkdir(parents=True, exist_ok=True)
        (req.run_dir / "settings.json").write_text(
            json.dumps({"task": req.task, "video": str(req.video or ""), **cfg}, indent=2),
            encoding="utf-8",
        )
        self.note(
            "start", "running",
            f"Task: {req.task}\nVideo: {req.video or 'none'}\n"
            f"{worst_case_note(cfg, skill)}\nFolder: {req.run_dir}",
            run_dir=str(req.run_dir), settings=cfg,
        )  # fmt: skip
        try:
            if not self.preflight(simulator=True):
                return
            if not cfg["synthesizer"]:
                for stage in ("video", "extract", "demospec", "prompt", "generate"):
                    self.stage(stage, "skipped", "The Synthesizer is off")
                program = req.run_dir / "main_script.py"
                shutil.copyfile(cfg["main_script"], program)
                self.check_stop()
                self.run_attacks(program, req.task, req.run_dir, cfg)
                return
            made = self.synthesize()
            if made is None:
                return
            program, spent = made
            self.check_stop()
            if not cfg["adversary"]:
                self.deploy(program, spent)
                return
            left = max(
                loop_budget(cfg["token_cap"], spent, skill["budget"]["one_call_headroom_tokens"]), 0
            )
            self.note(
                "adversary", "running",
                f"Attacking {program.name}. Generation spent {spent:,} tokens; rewrites may spend "
                f"{left:,}."
                + (" That is below one call, so a failure ends as a budget stop." if
                   left < skill["budget"]["tokens_per_call_estimate"] else ""),
                tokens=spent,
            )  # fmt: skip
            self.run_loop(program, req.task, req.run_dir, left, cfg)
        except Stopped:
            self.finish("user_stop", "stopped", "Stopped by you.")


class Manager:
    """The single pipeline of this server."""

    def __init__(
        self,
        emit: Emit,
        *,
        set_running: Callable[[bool], bool],
        run_loop: Callable[..., None],
        run_attacks: Callable[..., None],
        stop_requested: Callable[[], bool],
        clear_stop: Callable[[], None],
        runs_dir: Callable[[], Path],
        skill: dict | None = None,
        pipeline: Callable[..., Pipeline] = Pipeline,
    ) -> None:
        self.emit, self.set_running = emit, set_running
        self.run_loop, self.run_attacks = run_loop, run_attacks
        self.stop_requested, self.clear_stop = stop_requested, clear_stop
        self.runs_dir = runs_dir
        self.skill = skill or load_skill()
        self.pipeline = pipeline
        self.current: dict | None = None

    def start(self, task: str, video: str | None, raw_settings: dict | None = None) -> dict:
        path = Path(video) if video else None
        problem = task_problem(task, self.skill) or video_problem(path, self.skill)
        if problem:
            return {"ok": False, "error": problem}
        settings, problem = parse_settings(raw_settings, self.skill)
        if problem:
            return {"ok": False, "error": problem}
        if not self.set_running(True):
            return {"ok": False, "error": "A run is already in progress; wait or press Stop."}
        self.clear_stop()
        run_dir = self.runs_dir() / time.strftime("run-%Y%m%dT%H%M%S")
        run_dir.mkdir(parents=True, exist_ok=True)
        self.current = {"task": task, "video": video, "run_dir": str(run_dir), "settings": settings}
        self.emit({"kind": "pipeline_start", **self.current})

        def work() -> None:
            try:
                self.pipeline(
                    Request(task, path, run_dir, settings), self.skill, self.emit,
                    run_loop=self.run_loop, run_attacks=self.run_attacks,
                    stop_requested=self.stop_requested,
                ).run()  # fmt: skip
            except Exception as exc:  # noqa: BLE001 -- surface any failure in the console
                self.emit({"kind": "error", "message": f"{type(exc).__name__}: {exc}"})
            finally:
                self.set_running(False)

        threading.Thread(target=work, daemon=True).start()
        return {"ok": True, **self.current}
