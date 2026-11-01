"""Run one policy script in one episode, and turn the outcome into evidence for the diagnoser.

The policy runs with a whitelist of builtins, `import math` only, and the episode's API as its
only globals. Instead of a wall clock, a budget of executed lines stops runaway programs: it is
deterministic, so the same seed gives the same outcome on every OS. A crash is `Outcome.ERROR`,
never a task failure. This is a guard against mistakes in generated code, not a security
boundary; on the real simulator, ASPIRE's own sandbox runs the program.
"""

from __future__ import annotations

import builtins
import io
import math
import sys
import time
from collections.abc import Mapping
from contextlib import redirect_stdout
from typing import Any

from ants.adversary.rollout.backend import Backend
from ants.contracts import Event, Outcome, Perturbation, RolloutResult

_SAFE_BUILTINS = (
    "abs all any bool dict enumerate float int isinstance len list max min print range "
    "reversed round sorted str sum tuple zip ValueError ZeroDivisionError Exception"
).split()
_ALLOWED_IMPORTS = {"math": math}
DEFAULT_LINE_BUDGET = 500_000
_FILENAME = "<policy>"


class LineBudgetExceeded(Exception):
    pass


def _import(name: str, *args: Any, **kwargs: Any) -> Any:
    if name not in _ALLOWED_IMPORTS:
        raise ImportError(f"import of {name!r} is not allowed in a policy")
    return _ALLOWED_IMPORTS[name]


def _scope(api: Mapping[str, object]) -> dict[str, Any]:
    safe = {n: getattr(builtins, n) for n in _SAFE_BUILTINS}
    safe["__import__"] = _import
    return {"__builtins__": safe, "__name__": "__policy__", **api}


def run_policy(
    program: str,
    backend: Backend,
    perturbation: Perturbation | None,
    seed: int,
    line_budget: int = DEFAULT_LINE_BUDGET,
) -> RolloutResult:
    episode = backend.episode(perturbation, seed)
    scope = _scope(episode.api())
    lines = 0

    def tracer(frame, event, arg):  # noqa: ARG001
        nonlocal lines
        if frame.f_code.co_filename != _FILENAME:
            return None
        if event == "line":
            lines += 1
            if lines > line_budget:
                raise LineBudgetExceeded
        return tracer

    t0 = time.perf_counter()
    stdout = io.StringIO()
    error = None
    timed_out = False
    try:
        code = compile(program, _FILENAME, "exec")
        previous = sys.gettrace()
        sys.settrace(tracer)
        try:
            with redirect_stdout(stdout):
                exec(code, scope)  # noqa: S102 - the point of this module
        finally:
            sys.settrace(previous)
    except LineBudgetExceeded:
        timed_out = True
    except Exception as exc:  # generated code may raise anything
        error = f"{type(exc).__name__}: {exc}"

    events = list(episode.events)
    if timed_out:
        events.append(Event(float(len(events)), "terminated", detail={"reason": "timeout"}))
        outcome = Outcome.FAILURE
    elif error is not None:
        events.append(Event(float(len(events)), "terminated", detail={"reason": "program_error"}))
        outcome = Outcome.ERROR
    else:
        ok = episode.success()
        reason = "task_success" if ok else "program_completed"
        events.append(Event(float(len(events)), "terminated", detail={"reason": reason}))
        outcome = Outcome.SUCCESS if ok else Outcome.FAILURE

    calls = [e for e in events if e.kind == "call"]
    return RolloutResult(
        outcome=outcome,
        metrics={**episode.metrics(), "lines_executed": float(lines)},
        events=tuple(events),
        last_phase=str(calls[-1].detail.get("tool")) if calls else None,
        duration_s=round(time.perf_counter() - t0, 4),
        error=error,
    )


def to_feedback(result: RolloutResult, stdout_tail: str = "") -> dict[str, Any]:
    """The compact feedback dict the rule diagnoser reads (same shape as the cap_harness one)."""
    terminated = [e for e in result.events if e.kind == "terminated"]
    failed = [
        {
            "call_index": int(e.t),
            "tool": e.detail.get("tool"),
            "status": e.detail.get("status"),
            "steps_executed": e.detail.get("steps"),
        }
        for e in result.events
        if e.kind == "call" and not e.detail.get("ok", True)
    ]
    fb: dict[str, Any] = {
        "termination_reason": terminated[-1].detail.get("reason") if terminated else None,
        "failed_calls": failed[:12],
    }
    if result.error:
        fb["error"] = result.error
    if stdout_tail:
        fb["stdout_tail"] = stdout_tail[-1500:]
    return fb
