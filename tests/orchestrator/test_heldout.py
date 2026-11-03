"""Held-out evaluation: separate cases, held-out split on the backend, logged per policy."""

import json

import pytest

from ants.adversary import AdversaryConfig
from ants.adversary.perturbations import Bounds
from ants.adversary.rollout import AspireConfig
from ants.contracts import Feedback, Split
from ants.orchestrator.heldout import (
    evaluate,
    held_out_adversary,
    held_out_cases,
    load_run_policies,
    main,
    run_held_out,
)
from ants.orchestrator.run import main as run_main

from .test_loop import V0, adversary


def test_cases_are_held_out_balanced_bounded_and_deterministic():
    cases = held_out_cases(12, ("physics", "camera", "pose"), Bounds(default=0.6))
    assert all(c.split is Split.HELD_OUT and c.held_out for c in cases)
    assert [c.seed for c in cases] == list(range(12))
    cats = [c.perturbations[0].category for c in cases]
    assert {cats.count(c) for c in set(cats)} == {4}
    assert all(c.perturbations[0].severity <= 0.6 + 1e-9 for c in cases)
    assert [c.to_dict() for c in cases] == [c.to_dict() for c in held_out_cases(
        12, ("physics", "camera", "pose"), Bounds(default=0.6))]  # fmt: skip


def test_a_held_out_failure_cannot_become_feedback():
    adv = adversary(("physics",))
    report = next(r for r in (adv.attack(V0) for _ in range(20)) if r.failure is not None)
    with pytest.raises(ValueError, match="held-out"):
        Feedback.from_report(report, held_out_cases(1)[0])


def test_the_cap_harness_backend_is_built_on_the_held_out_split(tmp_path):
    cfg = AdversaryConfig(backend="cap_harness", aspire=AspireConfig(root=tmp_path))
    adv = held_out_adversary(cfg, tmp_path)
    assert adv.backend.config.split is Split.HELD_OUT
    assert [adv.backend.harness_seed(i) for i in (0, 49)] == [1, 50]  # never 51-65
    assert adv.model is None  # evaluation spends no tokens


def test_evaluate_refuses_acceptance_cases():
    adv = held_out_adversary(AdversaryConfig(), None)
    case = held_out_cases(1)[0]
    acceptance = type(case)(**{**vars(case), "split": Split.ACCEPTANCE})
    with pytest.raises(ValueError):
        evaluate(adv, [V0], [acceptance])


def test_run_logs_every_outcome_per_policy(tmp_path):
    res = run_held_out(tmp_path, AdversaryConfig(categories=("physics",)), [V0], n=4)
    assert res["v0"]["cases"] == 4 and len(res["v0"]["outcomes"]) == 4
    doc = json.loads((tmp_path / "heldout.json").read_text(encoding="utf-8"))
    assert all(c["split"] == "held_out" for c in doc["cases"])
    assert "not results" in (tmp_path / "heldout.md").read_text(encoding="utf-8")


def test_after_a_loop_v0_and_final_are_evaluated(tmp_path):
    out = tmp_path / "run"
    argv = ["--cycles", "20", "--categories", "physics", "--min-severity", "0.6",
            "--out", str(out), "--eval-held-out", "6"]  # fmt: skip
    assert run_main(argv) == 0
    doc = json.loads((out / "heldout.json").read_text(encoding="utf-8"))
    assert set(doc["results"]) == {"v0", "v1"}
    assert [p.version for p in load_run_policies(out)] == [0, 1]
    assert main(["--run", str(out), "--n", "6"]) == 0  # standalone re-evaluation


def test_cap_harness_refuses_more_than_50_cases(tmp_path):
    with pytest.raises(SystemExit):
        main(["--run", str(tmp_path), "--n", "51", "--backend", "cap_harness"])
