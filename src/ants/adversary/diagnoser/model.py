"""Model diagnoser: Muse Spark (DELIBERATE) reasons over the evidence and the code and returns a
failure mode, a causal sentence tied to the code, a confidence and one rule for the generator.

The rule-based diagnosis is always computed first and passed in as a hint. The model's answer is
used only when it parses and its confidence reaches the floor; otherwise the rules answer, so
every failure gets a label. The failure signature always comes from the rules, because stall
counting and escalation must not depend on how a model phrases things.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from string import Template

from ants.adversary.diagnoser.rules import classify, diagnose
from ants.adversary.models import Effort, Message, ModelError, ReasoningModel, extract_json
from ants.contracts import BlameTarget, Constraint, Failure, FailureMode, Perturbation

PROMPT = Template(
    (Path(__file__).parents[1] / "prompts" / "diagnose.md").read_text(encoding="utf-8")
)


@dataclass(frozen=True)
class Diagnosis:
    failure: Failure
    constraint: Constraint
    source: str  # "model" or "rules: <reason>"
    code_sketch: str = ""
    usage: Mapping[str, int] = field(default_factory=dict)


@dataclass
class ModelDiagnoser:
    model: ReasoningModel
    confidence_floor: float = 0.5

    def diagnose(
        self,
        perturbation: Perturbation,
        fb: Mapping,
        index: int,
        program: str,
        task: str,
        events: list[dict] | None = None,
        metrics: Mapping[str, float] | None = None,
    ) -> Diagnosis:
        rule_failure = classify(perturbation, fb)
        rule_constraint = diagnose(perturbation, fb, index)
        prompt = PROMPT.substitute(
            task=task,
            perturbation=f"{perturbation.category} {dict(perturbation.params)} "
            f"(severity {perturbation.severity:.2f})",
            termination=fb.get("termination_reason"),
            failed_calls=json.dumps(fb.get("failed_calls") or [])[:1500],
            events=json.dumps(events or [])[:1500],
            metrics=json.dumps(dict(metrics or {})),
            program=program,
            rule_mode=rule_failure.mode,
            signature=rule_constraint.failure_signature,
            modes=", ".join(m.value for m in FailureMode),
        )
        try:
            resp = self.model.complete([Message("user", prompt)], Effort.DELIBERATE, json_schema={})
            reply = extract_json(resp.texts[0])
            confidence = float(reply.get("confidence", 0.0))
            rule = str(reply.get("rule", "")).strip()
            cause = str(reply.get("root_cause", "")).strip()
        except (ModelError, ValueError, TypeError, IndexError) as exc:
            return Diagnosis(rule_failure, rule_constraint, f"rules: {exc}")
        if not rule or not cause:
            return Diagnosis(
                rule_failure, rule_constraint, "rules: incomplete model answer", usage=resp.usage
            )
        if confidence < self.confidence_floor:
            return Diagnosis(
                rule_failure,
                rule_constraint,
                f"rules: model confidence {confidence:.2f}",
                usage=resp.usage,
            )
        target = str(reply.get("target", "program"))
        target = BlameTarget(target) if target in ("program", "perception") else BlameTarget.PROGRAM
        failure = Failure(
            mode=str(reply.get("mode") or rule_failure.mode)[:60],
            root_cause=cause[:400],
            confidence=min(max(confidence, 0.0), 1.0),
            source="model",
            target=target,
        )
        sketch = str(reply.get("code_sketch") or "").strip()
        constraint = dataclasses.replace(
            rule_constraint,
            when_to_apply=str(reply.get("when_to_apply") or rule_constraint.when_to_apply)[:300],
            rule=rule[:500],
            target=target,
            code_sketch=sketch[:800] or None,
        )
        return Diagnosis(failure, constraint, "model", sketch, resp.usage)
