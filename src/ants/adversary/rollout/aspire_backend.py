"""ASPIRE cap_harness backend: run one policy in perturbed LIBERO and read back the evidence.

Ported from System 1's rollout (`synthesizer` branch, `adversary/rollout.py`), reshaped for
System 2: it takes a `Perturbation` and returns a contracts `RolloutResult`, so the selector,
diagnosers, history and studio work unchanged.

How it runs. The harness lives in its own Linux venv outside `ants` (it pins numpy 1.26), so this
module imports nothing heavy: it writes the program to a file, builds the `cap-harness run`
command line and runs it as a subprocess. A nominal case calls `cap-harness` directly; a perturbed
case goes through System 1's launcher (`tools/aspire_launch.py`), which patches ASPIRE's LIBERO
loader so the perturbation is applied host-side after every reset and step. ASPIRE is not
modified, and the program never sees the perturbation or the success predicate.

Isolation. The program runs in ASPIRE's own process, not in ours: a crash or a hang there cannot
take the System 2 loop down, and the subprocess timeout bounds a primitive that never returns.
ASPIRE's program sandbox (an AST validator, `import math` only, restricted builtins) is an
in-process `exec`, so like our runner it is a guard against mistakes, NOT a security boundary.

Seeds and the split. LIBERO runs in `--init-mode seeded` (the default `saved` mode wraps seeds at
50). ASPIRE's partitions are dev 51-65, unseen-check 66-80 and held-out 1-50; ANTS uses dev as its
acceptance set. The backend maps the loop's attack seed onto the partition of its `split`, so an
acceptance backend can never run a held-out seed. Held-out evaluation builds its own backend with
`split=Split.HELD_OUT`.

Outcome mapping (from `outcome.json`): `task_success` -> SUCCESS; `program_ok` false -> ERROR
(the generated code crashed or was rejected); otherwise FAILURE. No run directory, a harness
crash or the wall clock -> ERROR, never a task failure.
"""

from __future__ import annotations

import itertools
import json
import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ants.adversary.perturbations import to_launcher_spec
from ants.contracts import Event, Outcome, Perturbation, RolloutResult, Split

ACCEPTANCE_SEEDS = tuple(range(51, 66))  # ASPIRE "dev"
UNSEEN_CHECK_SEEDS = tuple(range(66, 81))  # ASPIRE overfitting probe, measured once at the end
HELD_OUT_SEEDS = tuple(range(1, 51))
SEEDS_BY_SPLIT = {Split.ACCEPTANCE: ACCEPTANCE_SEEDS, Split.HELD_OUT: HELD_OUT_SEEDS}

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ASPIRE_ROOT = REPO_ROOT / "ASPIRE"  # git submodule since System 1's da9adec
MAX_KEYFRAMES = 8


@dataclass
class AspireConfig:
    """Where the ASPIRE checkout is and how to run it. Every field is logged with each rollout."""

    root: Path = field(
        default_factory=lambda: Path(os.environ.get("ANTS_ASPIRE_ROOT", DEFAULT_ASPIRE_ROOT))
    )
    launcher: Path = REPO_ROOT / "tools" / "aspire_launch.py"  # System 1's perturbation launcher
    output_root: Path = Path("data/runs/aspire")
    benchmark: str = "libero-pro"
    suite: str = "libero_goal_swap"
    task_id: int = 8  # bowl on plate; the launcher's body names are this task's
    split: Split = Split.ACCEPTANCE
    max_steps: int = 2000
    camera_width: int = 800
    camera_height: int = 512
    scene: Mapping[str, Any] = field(default_factory=dict)  # extra launcher keys, e.g. planner
    venv: str = ".venv-libero"

    def __post_init__(self) -> None:
        # The harness runs with cwd=root, so a relative root (`--aspire ASPIRE`) would point the
        # CLI and python paths at ASPIRE/ASPIRE/... Resolve the root only: the venv's python is a
        # symlink that must stay unresolved, or it runs outside the venv.
        self.root = Path(self.root).expanduser().resolve()

    @property
    def python(self) -> Path:
        return self.root / self.venv / "bin" / "python"

    @property
    def cli(self) -> Path:
        return self.root / self.venv / "bin" / "cap-harness"

    def env(self) -> dict[str, str]:
        return dict(
            os.environ,
            LIBERO_CONFIG_PATH=str(self.root / ".libero"),
            TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD="1",
            MUJOCO_GL="egl",
            PYOPENGL_PLATFORM="egl",
            EGL_PLATFORM="device",
            CUDA_VISIBLE_DEVICES=os.environ.get("CUDA_VISIBLE_DEVICES", "0"),
        )


class AspireBackend:
    """A program backend: it runs whole programs, so the runner hands over instead of exec-ing."""

    name = "cap_harness"

    def __init__(self, config: AspireConfig | None = None) -> None:
        self.config = config or AspireConfig()
        self._counter = itertools.count()

    # --- seeds and command line ----------------------------------------------------------
    def harness_seed(self, seed: int) -> int:
        seeds = SEEDS_BY_SPLIT[self.config.split]
        return seeds[seed % len(seeds)]

    def scene_spec(self, perturbation: Perturbation | None) -> dict[str, Any]:
        spec = dict(self.config.scene)
        if perturbation is not None:
            spec.update(to_launcher_spec([perturbation]))
        return spec

    def command(
        self, program: Path, run_root: Path, harness_seed: int, scene: Mapping[str, Any]
    ) -> list[str]:
        cfg = self.config
        if scene:
            if not cfg.launcher.exists():
                raise FileNotFoundError(
                    f"a perturbed run needs System 1's launcher at {cfg.launcher}"
                )
            spec = run_root / "scene.json"
            spec.write_text(json.dumps(scene, indent=1), encoding="utf-8")
            head = [str(cfg.python), str(cfg.launcher.resolve()), str(spec.resolve()), "--"]
        else:
            head = [str(cfg.cli)]
        return [
            *head,
            "run",
            "--benchmark", cfg.benchmark,
            "--suite", cfg.suite,
            "--task-id", str(cfg.task_id),
            "--seed", str(harness_seed),
            "--init-mode", "seeded",
            "--program", str(program.resolve()),
            "--output-root", str(run_root.resolve()),
            "--max-steps", str(cfg.max_steps),
            "--camera-width", str(cfg.camera_width),
            "--camera-height", str(cfg.camera_height),
        ]  # fmt: skip

    # --- one rollout ---------------------------------------------------------------------
    def run_program(
        self,
        program: str,
        perturbation: Perturbation | None,
        seed: int,
        timeout_s: float | None,
    ) -> RolloutResult:
        cfg = self.config
        hseed = self.harness_seed(seed)
        tag = perturbation.key if perturbation is not None else "nominal"
        stamp = time.strftime("%Y%m%d_%H%M%S")
        run_root = cfg.output_root / f"{stamp}_{next(self._counter):04d}_s{hseed}_{tag}"
        run_root.mkdir(parents=True, exist_ok=True)
        program_path = run_root / "program.py"
        program_path.write_text(program, encoding="utf-8")
        scene = self.scene_spec(perturbation)
        context = {
            "backend": self.name,
            "suite": cfg.suite,
            "task_id": cfg.task_id,
            "split": cfg.split.value,
            "attack_seed": seed,
            "harness_seed": hseed,
            "scene": scene,
            "run_root": str(run_root),
        }

        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                self.command(program_path, run_root, hseed, scene),
                cwd=cfg.root,
                env=cfg.env(),
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return _error(
                "wall_clock_timeout",
                f"WallClockExceeded: cap_harness ran longer than {timeout_s} s",
                time.perf_counter() - t0,
                context,
            )
        except OSError as exc:  # missing venv or checkout
            return _error("harness_error", f"{type(exc).__name__}: {exc}", 0.0, context)
        wall = time.perf_counter() - t0
        outcomes = sorted(run_root.rglob("outcome.json"), key=lambda p: p.stat().st_mtime)
        if not outcomes:
            stderr = (proc.stderr or "")[-2000:]
            return _error("harness_error", f"no outcome.json: {stderr}", wall, context)
        return read_run_dir(outcomes[-1].parent, wall_s=wall, context=context)


def _error(reason: str, message: str, wall_s: float, context: Mapping[str, Any]) -> RolloutResult:
    return RolloutResult(
        outcome=Outcome.ERROR,
        events=(Event(0.0, "terminated", detail={"reason": reason}),),
        duration_s=round(wall_s, 3),
        error=message,
        details={**context, "feedback": {"termination_reason": reason, "error": message}},
    )


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _call_event(index: int, call: Mapping[str, Any]) -> Event:
    out = call.get("outputs_summary") or {}
    ok = bool(call.get("ok"))
    status = out.get("status") or call.get("failure_code") or ("success" if ok else "failed")
    detail = {
        "tool": call.get("tool", "?"),
        "ok": ok,
        "status": str(status),
        "steps": out.get("steps_executed"),
        "duration_s": float(call.get("duration_s") or 0.0),
    }
    if not ok:
        detail["error"] = call.get("error_message")
        detail["final_position_error_m"] = out.get("final_errors")
    return Event(float(call.get("index", index)), "call", detail=detail)


def _final_gripper(steps_path: Path) -> dict[str, Any] | None:
    if not steps_path.exists():
        return None
    lines = steps_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return None
    state = json.loads(lines[-1]).get("robot_state") or {}
    pose = (state.get("end_effector_poses") or {}).get("primary") or {}
    pos = (pose.get("position") or {}).get("$array_inline")
    return {
        "position_robot_base": [round(v, 3) for v in pos] if pos else None,
        "gripper_position": (state.get("gripper_positions") or {}).get("primary"),
    }


def read_run_dir(
    run_dir: Path, wall_s: float = 0.0, context: Mapping[str, Any] | None = None
) -> RolloutResult:
    """Turn one cap_harness run directory into a RolloutResult (pure: reads files only)."""
    outcome = _load(run_dir / "outcome.json") or {}
    result = _load(run_dir / "source" / "program-result.json") or {}
    calls: Sequence[Mapping[str, Any]] = result.get("calls") or []
    events = [_call_event(i, c) for i, c in enumerate(calls)]
    reason = str(outcome.get("termination_reason") or "unknown")
    events.append(Event(float(len(events)), "terminated", detail={"reason": reason}))

    error = json.dumps(outcome["error"]) if outcome.get("error") else None
    if outcome.get("task_success"):
        verdict = Outcome.SUCCESS
    elif not outcome.get("program_ok", True):
        verdict = Outcome.ERROR
        error = error or "program_ok is false"
    else:
        verdict = Outcome.FAILURE

    feedback: dict[str, Any] = {"termination_reason": reason}
    if outcome.get("error"):
        feedback["error"] = outcome["error"]
    if result.get("stdout"):
        # Programs print their measurements first and their outcome last; keep both ends.
        feedback["stdout_head"] = result["stdout"][:2500]
        feedback["stdout_tail"] = result["stdout"][-1500:]
    if "result" in result:
        feedback["program_result"] = result["result"]
    final = _final_gripper(run_dir / "episode" / "steps.jsonl")
    if final:
        feedback["final_gripper"] = final

    videos = sorted((run_dir / "media" / "videos").glob("*.mp4"))
    keyframes = sorted((run_dir / "media" / "keyframes").glob("*"))
    tools = [str(c.get("tool")) for c in calls]
    metrics = {"primitive_calls": float(len(calls)), "wall_s": round(wall_s, 3)}
    for k, v in (outcome.get("timing") or {}).items():
        if isinstance(v, (int, float)):
            metrics[f"timing_{k}"] = float(v)
    return RolloutResult(
        outcome=verdict,
        metrics=metrics,
        events=tuple(events),
        last_phase=tools[-1] if tools else None,
        duration_s=round(wall_s, 3),
        error=error,
        video_path=str(videos[0]) if videos else None,
        keyframes=tuple(str(k) for k in keyframes[:MAX_KEYFRAMES]),
        details={**(context or {}), "run_dir": str(run_dir), "feedback": feedback},
    )
