"""Failure explainer: one short plain-language paragraph for people, from Muse Spark (FAST).

The diagnosis is written for the program generator; this is written for a line engineer and for
the demo. It never influences any decision. Without a model it falls back to a template.
"""

from __future__ import annotations

import json
from pathlib import Path
from string import Template

from ants.adversary.models import Effort, Message, ModelError, ReasoningModel
from ants.contracts import AttackReport

PROMPT = Template((Path(__file__).parent / "prompts" / "explain.md").read_text(encoding="utf-8"))


def _template(report: AttackReport) -> str:
    p, c = report.perturbation, report.constraint
    cause = report.failure.root_cause if report.failure else ""
    values = ", ".join(f"{k.replace('_', ' ')} {v:.3g}" for k, v in p.params.items())
    return (
        f"The scene was changed ({p.category}: {values}). "
        f"The program did not finish the task: {cause} "
        f"Fix: {c.rule if c else 'none'}"
    ).strip()


def explain(report: AttackReport, model: ReasoningModel | None, task: str) -> tuple[str, str]:
    """(text, source) for a failed attack; source is "model" or "template"."""
    if report.failure is None or report.constraint is None:
        return "", "none"
    if model is None:
        return _template(report), "template"
    events = [
        {"kind": e.kind, **{k: v for k, v in e.detail.items() if k in ("tool", "status", "reason")}}
        for e in report.result.events
        if e.kind != "call" or not e.detail.get("ok", True)
    ]
    prompt = PROMPT.substitute(
        task=task,
        perturbation=f"{report.perturbation.category} {dict(report.perturbation.params)}",
        termination=next(
            (
                e.detail.get("reason")
                for e in reversed(report.result.events)
                if e.kind == "terminated"
            ),
            "unknown",
        ),
        failed_calls=json.dumps([e for e in events if "tool" in e])[:800],
        events=json.dumps([e for e in events if "tool" not in e])[:800],
        root_cause=report.failure.root_cause,
        rule=report.constraint.rule,
    )
    try:
        text = model.complete([Message("user", prompt)], Effort.FAST).texts[0].strip()
    except (ModelError, IndexError):
        return _template(report), "template"
    return (text, "model") if text else (_template(report), "template")
