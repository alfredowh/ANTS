import json
from pathlib import Path

import pytest

from ants.adversary import Adversary, AdversaryConfig
from ants.adversary.history import AttackRecord, FailureHistory, policy_key
from ants.adversary.rollout import MockBackend
from ants.contracts import AttackReport, Outcome, Perturbation, Policy

CODE = (Path(__file__).parents[2] / "examples" / "bowl_on_plate" / "policy.py").read_text(
    encoding="utf-8"
)
V0 = Policy("bowl_on_plate", 0, "put the bowl on the plate", CODE)


def _attacks(n=30, **cfg):
    adv = Adversary.from_config(AdversaryConfig(**cfg))
    return adv, [adv.attack(V0) for _ in range(n)]


def test_attack_reports_carry_diagnosis_and_evidence():
    adv, reports = _attacks()
    failures = [r for r in reports if r.result.outcome is Outcome.FAILURE]
    assert failures, "the v0 policy should break in the mock world"
    for r in failures:
        assert r.failure is not None and r.constraint is not None
        assert r.constraint.evidence[0] == r.attack_id
        assert r.constraint.failure_signature.startswith(r.perturbation.category + ":")
    assert all(r.failure is None for r in reports if r.result.outcome is Outcome.SUCCESS)
    assert len(adv.history) == 30
    assert all(set(r.selector_draws) == set(adv.config.categories) for r in reports)


def test_reports_round_trip_through_json():
    _, reports = _attacks(10)
    for r in reports:
        assert AttackReport.from_dict(json.loads(json.dumps(r.to_dict()))) == r


def test_attacks_are_reproducible():
    a = [r.to_dict() for r in _attacks(15, seed=4)[1]]
    b = [r.to_dict() for r in _attacks(15, seed=4)[1]]
    for x, y in zip(a, b, strict=True):
        x["result"].pop("duration_s"), y["result"].pop("duration_s")
    assert a == b


def test_adaptive_finds_more_failures_than_uniform_in_the_mock_world():
    # mechanism check only: the mock world's failure rates are our modelling choices
    def found(eta):
        return sum(
            r.failure is not None for s in range(3) for r in _attacks(30, seed=s, eta=eta)[1]
        )

    assert found(0.2) > found(1.0)


def test_discovered_failures_replay_as_failures_and_nominal_passes():
    adv, _ = _attacks()
    cases = adv.discovered_failures()
    assert cases and all(p.seed is not None for p in cases)
    assert all(r.outcome is Outcome.FAILURE for r in adv.replay(V0, cases))
    assert adv.replay(V0, [None])[0].outcome is Outcome.SUCCESS
    assert len(adv.history) == 30  # replays are not recorded


def test_counts_start_fresh_for_a_new_version():
    adv, _ = _attacks(10)
    v1 = Policy("bowl_on_plate", 1, V0.task, CODE, parent_version=0)
    assert all(c == (0, 0) for c in adv.status(v1).counts.values())


def test_stop_modes():
    h = FailureHistory()
    cats = AdversaryConfig().categories
    for i, c in enumerate(cats * 3):
        p = Perturbation(c, {}, 0.5, seed=i)
        h.append(AttackRecord(f"a{i}", policy_key("bowl_on_plate", 0), p, Outcome.SUCCESS))
    cheap = Adversary(AdversaryConfig(stop_mode="min_tests"), MockBackend(), h)
    strict = Adversary(AdversaryConfig(stop_mode="posterior"), MockBackend(), h)
    assert cheap.status(V0).robust and cheap.status(V0).mode == "min_tests"
    assert not strict.status(V0).robust  # 3 clean tests per category is far from 28


def test_config_and_backend_validation():
    with pytest.raises(ValueError):
        AdversaryConfig(stop_mode="never")
    assert Adversary.from_config(AdversaryConfig(backend="cap_harness")).backend.name == (
        "cap_harness"
    )
    with pytest.raises(ValueError):
        Adversary.from_config(AdversaryConfig(backend="gazebo"))


def test_history_persists_to_jsonl(tmp_path):
    path = tmp_path / "attacks.jsonl"
    adv, _ = _attacks(5, history_path=path)
    assert len(FailureHistory(path)) == 5
