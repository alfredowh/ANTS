"""Run one program on one test case with ASPIRE's cap-harness and read back an EpisodeTrace.

The harness lives outside the ants package (its own Linux venv); this module only builds the
command line and parses the run directory, so it imports nothing heavy.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from ants.adversary.perturbations import to_launcher_spec
from ants.contracts import CallRecord, CaseSpec, EpisodeTrace


@dataclass
class CapHarness:
    """Location and settings of an ASPIRE checkout."""

    root: Path
    max_steps: int = 2000
    camera_width: int = 800
    camera_height: int = 512
    timeout_s: float = 900.0
    launcher: Path | None = None  # tools/aspire_launch.py; needed when `scene` is set
    scene: dict | None = None  # perturbation spec (see the launcher), e.g. {"scale": {...}}

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

    def command(self, case: CaseSpec, program: Path, output_root: Path) -> list[str]:
        scene = {**(self.scene or {}), **to_launcher_spec(case.perturbations)}
        if scene:
            if self.launcher is None:
                raise ValueError("a scene needs the launcher (tools/aspire_launch.py)")
            output_root.mkdir(parents=True, exist_ok=True)
            spec = output_root / "scene.json"
            spec.write_text(json.dumps(scene, indent=1), encoding="utf-8")
            head = [str(self.root / ".venv-libero" / "bin" / "python"), str(self.launcher),
                    str(spec), "--"]  # fmt: skip
        else:
            head = [str(self.root / ".venv-libero" / "bin" / "cap-harness")]
        return [
            *head,
            "run",
            "--benchmark", "libero-pro",
            "--suite", case.suite,
            "--task-id", str(case.task_id),
            "--seed", str(case.seed),
            "--init-mode", "seeded",  # the default "saved" mode wraps seeds at 50
            "--program", str(program),
            "--output-root", str(output_root),
            "--max-steps", str(self.max_steps),
            "--camera-width", str(self.camera_width),
            "--camera-height", str(self.camera_height),
        ]  # fmt: skip

    def run(self, case: CaseSpec, program: Path, output_root: Path, policy_id: str) -> EpisodeTrace:
        t0 = time.time()
        proc = subprocess.run(
            self.command(case, program, output_root),
            cwd=self.root,
            env=self.env(),
            capture_output=True,
            text=True,
            timeout=self.timeout_s,
        )
        outcomes = sorted(output_root.rglob("outcome.json"), key=lambda p: p.stat().st_mtime)
        if not outcomes:
            return EpisodeTrace(
                case.case_id, policy_id, False, False, "harness_error",
                error=proc.stderr[-2000:], wall_s=round(time.time() - t0, 1),
            )  # fmt: skip
        trace = read_run_dir(outcomes[-1].parent, case.case_id, policy_id)
        trace.wall_s = round(time.time() - t0, 1)
        return trace


def read_run_dir(run_dir: Path, case_id: str, policy_id: str) -> EpisodeTrace:
    outcome = json.loads((run_dir / "outcome.json").read_text(encoding="utf-8"))
    calls = []
    result_path = run_dir / "source" / "program-result.json"
    if result_path.exists():
        for c in json.loads(result_path.read_text(encoding="utf-8")).get("calls", []):
            out = c.get("outputs_summary") or {}
            calls.append(
                CallRecord(
                    c.get("tool", "?"),
                    bool(c.get("ok")),
                    c.get("failure_code") or (out.get("status") if not c.get("ok") else None),
                    float(c.get("duration_s") or 0.0),
                )
            )
    return EpisodeTrace(
        case_id=case_id,
        policy_id=policy_id,
        program_ok=bool(outcome.get("program_ok")),
        task_success=bool(outcome.get("task_success")),
        termination_reason=str(outcome.get("termination_reason")),
        calls=calls,
        error=json.dumps(outcome.get("error")) if outcome.get("error") else None,
        run_dir=str(run_dir),
    )


def feedback(run_dir: Path, max_calls: int = 12) -> dict:
    """A compact text description of a failed episode for the generator (no images)."""
    out: dict = {}
    outcome = json.loads((run_dir / "outcome.json").read_text(encoding="utf-8"))
    out["termination_reason"] = outcome.get("termination_reason")
    if outcome.get("error"):
        out["error"] = outcome["error"]
    result_path = run_dir / "source" / "program-result.json"
    if result_path.exists():
        res = json.loads(result_path.read_text(encoding="utf-8"))
        out["program_result"] = res.get("result")
        out["stdout_tail"] = (res.get("stdout") or "")[-1500:]
        failed = []
        for c in res.get("calls", []):
            if c.get("ok"):
                continue
            o = c.get("outputs_summary") or {}
            failed.append(
                {
                    "call_index": c.get("index"),
                    "tool": c.get("tool"),
                    "status": o.get("status") or c.get("failure_code"),
                    "error": c.get("error_message"),
                    "final_position_error_m": o.get("final_errors"),
                    "steps_executed": o.get("steps_executed"),
                }
            )
        out["failed_calls"] = failed[:max_calls]
    steps = run_dir / "episode" / "steps.jsonl"
    if steps.exists():
        lines = steps.read_text(encoding="utf-8").splitlines()
        if lines:
            state = json.loads(lines[-1]).get("robot_state") or {}
            pose = (state.get("end_effector_poses") or {}).get("primary") or {}
            pos = (pose.get("position") or {}).get("$array_inline")
            out["final_gripper"] = {
                "position_robot_base": [round(v, 3) for v in pos] if pos else None,
                "gripper_position": (state.get("gripper_positions") or {}).get("primary"),
            }
    return out
