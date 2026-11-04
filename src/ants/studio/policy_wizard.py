"""The `/policy-dev` wizard: a state machine over `docs/studio/skills/policy-dev.json`.

The skill file is plain data (questions, defaults, limits). This module only walks it, so the
wizard works without a model call. Every step and answer is appended to `wizard.jsonl` in the
wizard's own folder; uploads land next to it and are never executed.

Launching (`launch_generation`) reuses the existing generation path -- it does not reimplement it:
`ants.orchestrator.demo_vs_nodemo` (DemoSpec -> Muse program, develop-and-repair) as a subprocess,
and for "synthesizer + adversary" the live `Loop` through `console_server.run_live_loop`. It first
checks what that path needs and, when something is missing, says exactly what, instead of faking a
result.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

SKILL_PATH = Path(__file__).resolve().parents[3] / "docs" / "studio" / "skills" / "policy-dev.json"
REPO_ROOT = Path(__file__).resolve().parents[3]


def load_skill(path: Path = SKILL_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sessions_base(root: Path = REPO_ROOT) -> Path:
    """`data/console_sessions/` if it exists, else `data/console_uploads/`."""
    sessions = root / "data" / "console_sessions"
    return sessions if sessions.is_dir() else root / "data" / "console_uploads"


def list_demospecs(root: Path = REPO_ROOT) -> list[Path]:
    d = root / "data" / "demospecs"
    return sorted(d.glob("*.json")) if d.is_dir() else []


def safe_upload_name(name: str, extensions: list[str]) -> str | None:
    """A plain file name with a whitelisted video extension, or None."""
    base = Path(name.replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base).lstrip(".")
    if not base or Path(base).suffix.lower() not in extensions:
        return None
    return base


@dataclasses.dataclass
class Needs:
    """What the real generation path is missing; shown to the user as-is."""

    items: list[str]

    def __bool__(self) -> bool:
        return bool(self.items)


def check_generation_needs(answers: dict, root: Path = REPO_ROOT) -> Needs:
    items: list[str] = []
    if answers.get("demo") == "video" and answers.get("video"):
        items.append(
            "a video-to-DemoSpec extractor: today DemoSpecs come from hurobo marker tracks "
            "(tools/hurobo_demospec.py) or LIBERO demo files; SAM 3.1 video tracking is a stretch "
            "goal (decision D14). Pick 'demospec' and use an existing DemoSpec, or 'none'."
        )
    if answers.get("demo") == "demospec" and not answers.get("demospec"):
        items.append("a DemoSpec file under data/demospecs/")
    if not (root / "ASPIRE").is_dir() and not os.environ.get("ANTS_ASPIRE"):
        items.append("the ASPIRE checkout (ANTS/ASPIRE, or set ANTS_ASPIRE) with its simulator")
    env = root / ".env"
    has_key = bool(os.environ.get("META_API_KEY")) or (
        env.is_file() and "META_API_KEY" in env.read_text(encoding="utf-8")
    )
    if not has_key:
        items.append("META_API_KEY (in the environment or ANTS/.env) for the Muse generator")
    return Needs(items)


def generation_command(answers: dict, out: Path, root: Path = REPO_ROOT) -> list[str]:
    """The exact `demo_vs_nodemo` command for these answers (one sample, one arm)."""
    aspire = Path(os.environ.get("ANTS_ASPIRE", root / "ASPIRE"))
    has_demo = answers.get("demo") == "demospec" and answers.get("demospec")
    demospec = answers.get("demospec") or str(
        next(iter(list_demospecs(root)), root / "data" / "demospecs" / "hurobo_233832.json")
    )
    return [
        sys.executable,
        "-m",
        "ants.orchestrator.demo_vs_nodemo",
        "--aspire",
        str(aspire),
        "--out",
        str(out),
        "--demospec",
        str(demospec),
        "--arms",
        "demo" if has_demo else "nodemo",
        "--temperatures",
        "0.2",
        "--task",
        answers["task"],
        "--repairs",
        str(answers["synth_retries"]),
        "--token-budget",
        str(answers["synth_budget"]),
        "--eval-seeds",
        "",
    ]


def find_generated_program(out: Path) -> Path | None:
    programs = sorted(out.glob("*/program_attempt*.py"), key=lambda p: p.stat().st_mtime)
    return programs[-1] if programs else None


class Wizard:
    """One wizard session. `handle()` takes a user message and returns agent messages."""

    def __init__(self, skill: dict, folder: Path, demospecs: list[Path] | None = None) -> None:
        self.skill = skill
        self.folder = folder
        self.demospecs = demospecs if demospecs is not None else list_demospecs()
        self.steps: list[dict] = skill["steps"]
        self.answers: dict[str, Any] = {}
        self.status = "active"  # active | confirmed | cancelled
        self.pending_paid = False
        self.history: list[dict] = []
        self.current: dict | None = None
        folder.mkdir(parents=True, exist_ok=True)

    # -- logging / history ------------------------------------------------------------------
    def _log(self, event: str, **data: Any) -> None:
        row = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event, **data}
        with (self.folder / "wizard.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    def _say(self, text: str, out: list[dict], **extra: Any) -> None:
        msg = {"role": "agent", "text": text, "step": self.current["id"] if self.current else None}
        msg.update(extra)
        self.history.append(msg)
        out.append(msg)

    # -- step flow -------------------------------------------------------------------------
    def _applies(self, step: dict) -> bool:
        return all(self.answers.get(k) == v for k, v in (step.get("when") or {}).items())

    def _next_step(self) -> dict | None:
        done = {s["id"] for s in self.steps if s["id"] in self.answers}
        for s in self.steps:
            if s["id"] not in done and self._applies(s):
                return s
        return None

    def _question(self, step: dict) -> str:
        text = step["ask"]
        if step["type"] == "choice":
            lines = [f"  {i}. {c['label']}: {c['help']}" for i, c in enumerate(step["choices"], 1)]
            text += "\n" + "\n".join(lines)
        if step["type"] == "demospec":
            if self.demospecs:
                text += "\n" + "\n".join(
                    f"  {i}. {p.name}" for i, p in enumerate(self.demospecs, 1)
                )
            else:
                text += "\n  (no DemoSpec files found under data/demospecs/)"
        if step["type"] == "int":
            text += f" [{step['min']}-{step['max']}]"
        default = step.get("default")
        if default is not None:
            shown = default
            if step["type"] == "choice":
                shown = next(c["label"] for c in step["choices"] if c["value"] == default)
            text += f"\n(default: {shown}; say 'go with defaults' to accept this and the rest)"
        return text

    def _summary(self) -> str:
        a = self.answers
        lines = [
            f"Task: {a['task']}",
            f"Demonstration: {self._demo_label()}",
            "Run: "
            + ("Synthesizer + Adversary" if a["mode"] == "synth_adv" else "Synthesizer only"),
            f"Synthesizer: up to {a['synth_budget']:,} new tokens, "
            f"{a['synth_retries']} repair retries",
        ]
        if a["mode"] == "synth_adv":
            strat = (
                "Thompson sampling (eta 0.2)"
                if a["strategy"] == "thompson"
                else "uniform (eta 1.0)"
            )
            lines.append(
                f"Adversary: {a['adv_cycles']} attacks, escalate after {a['adv_stall']} stalled "
                f"cycles, {strat}, mock backend and mock proposer model"
            )
        cost = a["synth_budget"] / 1e6 * 13.5
        lines.append(
            f"Worst-case Muse cost for the Synthesizer: about ${cost:.2f} (at $13.5/M tokens)"
        )
        if a["synth_budget"] > self.skill["limits"]["paid_confirm_above_tokens"]:
            lines.append(
                "This is above 100,000 tokens: answer 'yes' to confirm you accept this paid spend."
            )
        return "\n".join(lines)

    def _demo_label(self) -> str:
        a = self.answers
        if a.get("demo") == "video":
            return f"video {a['video']}" if a.get("video") else "video (none attached)"
        if a.get("demo") == "demospec":
            return f"DemoSpec {Path(a['demospec']).name}" if a.get("demospec") else "DemoSpec"
        return "none (task text only)"

    def _advance(self, out: list[dict]) -> None:
        step = self._next_step()
        self.current = step
        if step is None:
            self.status = "confirmed"
            return
        if step.get("confirm"):
            self._say(
                "Summary\n" + self._summary() + "\n\n" + self._question(step), out, summary=True
            )
        else:
            self._say(self._question(step), out, accepts_upload=step["type"] == "upload")
        self._log("ask", step=step["id"])

    def start(self) -> list[dict]:
        out: list[dict] = []
        self._log("start", skill=self.skill["name"], version=self.skill["version"])
        self._say(
            "Policy development setup. I will ask a few questions; say 'go with defaults' at any "
            "step to accept the defaults, or /cancel to stop.",
            out,
        )
        self._advance(out)
        return out

    # -- answers ---------------------------------------------------------------------------
    def _parse(self, step: dict, text: str) -> tuple[Any, str | None]:
        t = text.strip()
        kind = step["type"]
        if kind == "text":
            return (t, None) if t else (None, "Please describe the task in a few words.")
        if kind == "choice":
            for i, c in enumerate(step["choices"], 1):
                if t.lower() in (str(i), c["label"].lower(), str(c["value"]).lower()):
                    return c["value"], None
            if step["id"] == "strategy" and t.lower() in ("random", "uniform"):
                return "uniform", None
            names = ", ".join(c["label"] for c in step["choices"])
            return None, f"Please answer with one of: {names} (or its number)."
        if kind == "int":
            digits = t.replace(",", "").replace("_", "").lower()
            mult = 1000 if digits.endswith("k") else 1
            try:
                n = int(float(digits.rstrip("k")) * mult)
            except ValueError:
                return None, f"Please give a whole number between {step['min']} and {step['max']}."
            if not step["min"] <= n <= step["max"]:
                return (
                    None,
                    f"{n:,} is outside the allowed range {step['min']:,} to {step['max']:,}.",
                )
            return n, None
        if kind == "demospec":
            if not self.demospecs:
                return None, "There are no DemoSpec files to choose from; pick 'none' instead."
            for i, p in enumerate(self.demospecs, 1):
                if t in (str(i), p.name, p.stem):
                    return str(p), None
            return None, "Please give the number or file name of one of the listed DemoSpecs."
        if kind == "upload":
            if t.lower() in ("skip", "none", "no"):
                return "", None
            return None, "Use the + button to attach a video, or say 'skip'."
        return None, "unsupported step"

    def _default(self, step: dict) -> Any:
        if step["type"] == "demospec":
            return str(self.demospecs[0]) if self.demospecs else None
        if step["type"] == "upload":
            return ""
        return step.get("default")

    def handle(self, text: str) -> list[dict]:
        out: list[dict] = []
        if self.status != "active":
            return out
        self.history.append({"role": "user", "text": text})
        self._log("answer", step=self.current["id"] if self.current else None, text=text)
        t = text.strip().lower()
        if t == "/cancel":
            return self.cancel()
        step = self.current
        if step is None:
            return out
        if t in self.skill["commands"]["defaults"] and not step.get("confirm"):
            while step is not None and not step.get("confirm"):
                value = self._default(step)
                if value is None:
                    self.current = step
                    self._say("That step has no default; " + self._question(step), out)
                    return out
                self.answers[step["id"]] = value
                self._log("default", step=step["id"], value=value)
                self.current = step
                step = self._next_step()
            self._advance(out)
            return out
        value, error = self._parse(step, text)
        if error:
            self._say(error, out)
            return out
        if step.get("confirm"):
            return self._confirm(value, out)
        self.answers[step["id"]] = value
        self._log("set", step=step["id"], value=value)
        self._advance(out)
        return out

    def _confirm(self, value: str, out: list[dict]) -> list[dict]:
        if value == "no":
            return self.cancel()
        self.answers["confirm"] = "yes"
        self.status = "confirmed"
        self._log("confirmed", answers=self.answers)
        self._say("Confirmed. Launching.", out)
        return out

    def attach_video(self, filename: str) -> list[dict]:
        out: list[dict] = []
        if self.status != "active" or not self.current or self.current["type"] != "upload":
            return out
        self.answers["video"] = filename
        self._log("upload", file=filename)
        self.history.append({"role": "user", "text": f"[attached {filename}]"})
        self._advance(out)
        return out

    def cancel(self) -> list[dict]:
        out: list[dict] = []
        if self.status == "active":
            self.status = "cancelled"
            self._log("cancelled")
            self._say("Wizard cancelled. Nothing was started.", out)
        return out

    def snapshot(self) -> dict:
        return {
            "status": self.status,
            "step": self.current["id"] if self.current else None,
            "awaiting_upload": bool(
                self.status == "active" and self.current and self.current["type"] == "upload"
            ),
            "answers": self.answers,
            "history": self.history,
            "folder": str(self.folder),
        }


Emit = Callable[[dict], None]


def launch_generation(
    answers: dict,
    folder: Path,
    emit: Emit,
    *,
    run_loop: Callable[[Path, dict], None] | None = None,
    popen: Callable[..., Any] = subprocess.Popen,
    root: Path = REPO_ROOT,
) -> bool:
    """Start the real generation for confirmed answers. Returns False (after emitting why) when
    the real path is missing something; nothing is faked."""
    needs = check_generation_needs(answers, root)
    if needs:
        emit(
            {
                "kind": "wizard_needs",
                "message": "Cannot launch yet. This needs: " + "; ".join(needs.items),
                "needs": needs.items,
            }
        )
        return False
    out = folder / "generation"
    cmd = generation_command(answers, out, root)
    emit({"kind": "wizard_launch", "command": cmd, "out": str(out)})
    proc = popen(
        cmd,
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    for line in proc.stdout:
        emit({"kind": "wizard_output", "line": line.rstrip()})
    code = proc.wait()
    emit({"kind": "wizard_generation_done", "returncode": code, "out": str(out)})
    if code != 0:
        return False
    program = find_generated_program(out)
    if answers["mode"] == "synth_adv":
        if program is None or run_loop is None:
            emit({"kind": "wizard_needs", "message": "No generated program found to attack."})
            return False
        run_loop(program, answers)
    return True


class WizardManager:
    """Holds the single active wizard for the server; thread-safe enough for one console."""

    def __init__(
        self,
        emit: Emit,
        *,
        base: Path | None = None,
        skill: dict | None = None,
        launcher: Callable[[dict, Path, Emit], bool] = launch_generation,
        set_running: Callable[[bool], bool] | None = None,
    ) -> None:
        self.emit = emit
        self.base = base or sessions_base()
        self.skill = skill or load_skill()
        self.launcher = launcher
        self.set_running = set_running
        self.wizard: Wizard | None = None
        self.lock = threading.Lock()

    def active(self) -> bool:
        return self.wizard is not None and self.wizard.status == "active"

    def start(self) -> dict:
        with self.lock:
            folder = self.base / time.strftime("wizard-%Y%m%dT%H%M%S")
            self.wizard = Wizard(self.skill, folder)
            self.wizard.start()
            return self.state()

    def message(self, text: str) -> dict:
        with self.lock:
            wiz = self.wizard
            if wiz is None or wiz.status != "active":
                return self.state()
            wiz.handle(text)
            if wiz.status == "confirmed":
                self._launch(wiz)
            return self.state()

    def cancel(self) -> dict:
        with self.lock:
            if self.wizard:
                self.wizard.cancel()
            return self.state()

    def upload_target(self, name: str) -> Path | None:
        wiz = self.wizard
        if wiz is None or wiz.status != "active" or not wiz.snapshot()["awaiting_upload"]:
            return None
        safe = safe_upload_name(name, self.skill["limits"]["video_extensions"])
        return wiz.folder / "uploads" / safe if safe else None

    def uploaded(self, path: Path) -> dict:
        with self.lock:
            if self.wizard:
                self.wizard.attach_video(path.name)
            return self.state()

    def _launch(self, wiz: Wizard) -> None:
        if self.set_running and not self.set_running(True):
            wiz.status = "active"
            wiz.answers.pop("confirm", None)
            wiz._say("A run is already in progress; answer 'yes' again once it has finished.", [])
            return

        def work() -> None:
            try:
                ok = self.launcher(dict(wiz.answers), wiz.folder, self.emit)
                wiz._log("launch_result", ok=ok)
            except Exception as exc:  # noqa: BLE001 -- surface any launch failure to the console
                self.emit({"kind": "wizard_needs", "message": f"Launch failed: {exc}"})
                wiz._log("launch_error", error=str(exc))
            finally:
                if self.set_running:
                    self.set_running(False)
                self.emit({"kind": "wizard_finished"})

        threading.Thread(target=work, daemon=True).start()

    def state(self) -> dict:
        if self.wizard is None:
            return {"status": "none", "history": []}
        return self.wizard.snapshot()
