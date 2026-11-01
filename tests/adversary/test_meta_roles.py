"""Proposer, model diagnoser and explainer with a scripted model: no network, no tokens."""

import json
import random
from pathlib import Path

from ants.adversary import Adversary, AdversaryConfig
from ants.adversary.diagnoser.model import ModelDiagnoser
from ants.adversary.models import Effort, MockModel
from ants.adversary.perturbations import DEFAULT_SPACE
from ants.adversary.planner.proposer import Proposer, novelty
from ants.adversary.rollout import MockBackend
from ants.contracts import Perturbation, Policy

CODE = (Path(__file__).parents[2] / "examples" / "bowl_on_plate" / "policy.py").read_text(
    encoding="utf-8"
)
V0 = Policy("bowl_on_plate", 0, "put the bowl on the plate", CODE)
TIMEOUT = {"failed_calls": [{"tool": "move_to_pose", "status": "timeout"}]}
ATTACK = Perturbation("actuation", {"noise_std": 0.012, "latency_steps": 2.0}, 0.6)

HARD = {
    "dx_m": 0.08, "dy_m": 0.05, "friction_scale": 0.3, "mass_scale": 3.0, "bowl_scale": 1.25,
    "plate_scale": 1.9, "noise_std": 0.02, "latency_steps": 3, "fovy_delta_deg": 4.0,
    "diffuse_scale": 0.3,
}  # fmt: skip


def agent(scale):
    params = {
        k: v * scale if k not in ("friction_scale", "diffuse_scale") else v for k, v in HARD.items()
    }
    return json.dumps({"params": params, "assumption": f"a{scale}", "rationale": f"r{scale}"})


def scripted(msgs, effort, i):
    if effort is Effort.PARALLEL:
        return ["not json", agent(0.5), agent(10.0), agent(0.6)][i % 4]
    if effort is Effort.DELIBERATE:
        return json.dumps({
            "mode": "timeout", "root_cause": "Line 229 gives up after 3 tries under noise.",
            "confidence": 0.8, "target": "program", "when_to_apply": "when moves land off target",
            "rule": "Read back the pose and retry with a larger tolerance.", "code_sketch": "x = 1",
        })  # fmt: skip
    return "The arm shook, missed the rim and gave up. The fix makes it check and retry."


def test_proposer_validates_every_reply_and_picks_the_most_novel():
    prop = Proposer(MockModel(scripted), DEFAULT_SPACE, n_agents=4)
    previous = [
        (Perturbation("actuation", {"noise_std": 0.006, "latency_steps": 1.0}, 0.3), "success")
    ]
    out = prop.propose("actuation", CODE, V0.task, previous, 0.6, random.Random(0), seed=3)
    assert out.source == "model" and len(out.candidates) == 3  # the junk reply is dropped
    assert all(c.perturbation.severity <= 0.6 + 1e-9 for c in out.candidates)  # x10 got clamped
    assert out.perturbation.seed == 3
    best = max(out.candidates, key=lambda c: c.novelty)
    assert out.perturbation == best.perturbation and out.assumption == best.assumption


def test_proposer_falls_back_on_errors_and_junk():
    for model in (MockModel(fail=True), MockModel(lambda m, e, i: "no json")):
        out = Proposer(model, DEFAULT_SPACE).propose(
            "physics", CODE, V0.task, [], 0.6, random.Random(0), seed=1
        )
        assert out.source.startswith("fallback") and out.perturbation.severity <= 0.6 + 1e-9


def test_novelty_is_distance_to_the_closest_previous_attack():
    a = Perturbation("physics", {"friction_scale": 0.3, "mass_scale": 1.0}, 1.0)
    b = Perturbation("physics", {"friction_scale": 1.0, "mass_scale": 1.0}, 0.0)
    assert novelty(a, [], DEFAULT_SPACE) == float("inf")
    assert novelty(a, [a], DEFAULT_SPACE) == 0.0
    assert novelty(a, [b], DEFAULT_SPACE) == 1.0


def test_model_diagnosis_used_above_the_floor_with_the_rule_signature():
    d = ModelDiagnoser(MockModel(scripted)).diagnose(ATTACK, TIMEOUT, 4, CODE, V0.task)
    assert d.source == "model" and d.failure.source == "model"
    assert d.constraint.failure_signature == "actuation:move_to_pose:timeout"
    assert d.constraint.rule.startswith("Read back") and d.constraint.code_sketch == "x = 1"
    assert d.constraint.constraint_id == "c004"


def test_rules_answer_when_the_model_is_unsure_or_broken():
    unsure = MockModel(
        lambda m, e, i: json.dumps({"rule": "x", "root_cause": "y", "confidence": 0.2})
    )
    for model in (unsure, MockModel(fail=True), MockModel(lambda m, e, i: "??")):
        d = ModelDiagnoser(model).diagnose(ATTACK, TIMEOUT, 0, CODE, V0.task)
        assert d.source.startswith("rules") and d.failure.source == "rules"


def test_adversary_with_a_model_logs_why_each_attack_was_chosen():
    adv = Adversary(AdversaryConfig(seed=0), MockBackend(), model=MockModel(scripted))
    reports = [adv.attack(V0) for _ in range(6)]
    notes = [r.notes for r in adv.history.records]
    assert all(n["proposal"]["source"] == "model" for n in notes)
    assert all(len(n["proposal"]["candidates"]) == 3 for n in notes)
    failed = [r for r in reports if r.failure]
    assert failed, "hard proposals should break the v0 policy in the mock world"
    rec = {r.attack_id: r for r in adv.history.records}
    assert all(rec[r.attack_id].notes["diagnosis"]["source"] == "model" for r in failed)
    text, source = adv.explain(failed[0], V0)
    assert source == "model" and "retry" in text
    assert adv.explain(next((r for r in reports if not r.failure), failed[0]), V0)[1] in (
        "none",
        "model",
    )
