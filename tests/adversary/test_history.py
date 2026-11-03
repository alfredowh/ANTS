from ants.adversary.history import AttackRecord, FailureHistory, policy_key
from ants.contracts import Outcome, Perturbation

P1 = Perturbation("physics", {"friction_scale": 0.5}, 0.7, seed=1)
P2 = Perturbation("camera", {"dy_m": 0.03}, 0.6, seed=2)
V1, V2 = policy_key("bowl", 1), policy_key("bowl", 2)


def _rec(i, policy, p, outcome, sig=None):
    return AttackRecord(f"a{i}", policy, p, outcome, sig)


def test_counts_are_per_version_and_ignore_program_errors():
    h = FailureHistory()
    h.append(_rec(0, V1, P1, Outcome.FAILURE, "physics:close_gripper:failed"))
    h.append(_rec(1, V1, P2, Outcome.SUCCESS))
    h.append(_rec(2, V1, P2, Outcome.ERROR))
    h.append(_rec(3, V2, P1, Outcome.SUCCESS))
    v1 = h.counts(V1, ["physics", "camera"])
    assert (v1["physics"].failures, v1["camera"].successes, v1["camera"].failures) == (1, 1, 0)
    assert h.counts(V2, ["physics"])["physics"].successes == 1


def test_discovered_failures_are_unique_across_versions():
    h = FailureHistory()
    for i, pol in enumerate((V1, V2, V2)):
        h.append(_rec(i, pol, P1, Outcome.FAILURE))
    h.append(_rec(9, V1, P2, Outcome.SUCCESS))
    assert h.discovered_failures() == [P1]


def test_jsonl_log_round_trips(tmp_path):
    path = tmp_path / "history.jsonl"
    h = FailureHistory(path)
    h.append(_rec(0, V1, P1, Outcome.FAILURE, "physics:close_gripper:failed"))
    h.append(_rec(1, V1, P2, Outcome.SUCCESS))
    again = FailureHistory(path)
    assert again.records == h.records and len(again) == 2


def test_recent_returns_the_latest_attacks_in_a_category():
    h = FailureHistory()
    for i in range(7):
        h.append(_rec(i, V1, P1, Outcome.SUCCESS))
    assert [r.attack_id for r in h.recent(V1, "physics", 3)] == ["a4", "a5", "a6"]
