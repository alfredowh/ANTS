import pytest

from ants.contracts import Outcome
from ants.orchestrator import gate

S, F, E = Outcome.SUCCESS, Outcome.FAILURE, Outcome.ERROR


def test_accepts_a_pure_improvement():
    d = gate({"a": S, "b": F}, {"a": S, "b": S})
    assert d.accepted and d.improvements == ("b",) and d.mode == "strict"


def test_any_regression_rejects_even_with_improvements():
    d = gate({"a": S, "b": F}, {"a": F, "b": S})
    assert not d.accepted and d.regressions == ("a",)


def test_a_candidate_crash_where_the_incumbent_passed_is_a_regression():
    assert gate({"a": S, "b": F}, {"a": E, "b": S}).regressions == ("a",)


def test_an_incumbent_crash_is_not_a_pass():
    assert gate({"a": E}, {"a": S}).accepted
    d = gate({"a": E}, {"a": F})  # error -> failure is neither better nor worse
    assert not d.accepted and d.reason == "no improvement over the incumbent"


def test_a_missing_result_counts_as_not_passed():
    d = gate({"a": S, "b": F}, {"b": S})
    assert not d.accepted and d.regressions == ("a",)
    assert d.outcomes["a"] == ("success", "missing")


def test_identical_outcomes_are_rejected():
    assert not gate({"a": S, "b": F}, {"a": S, "b": F}).accepted


def test_off_mode_accepts_and_says_so():
    d = gate({"a": S}, {"a": F}, mode="off")
    assert d.accepted and d.mode == "off" and d.regressions == ("a",)
    with pytest.raises(ValueError):
        gate({}, {}, mode="lenient")


def test_decision_is_json_ready():
    d = gate({"a": F}, {"a": S}).to_dict()
    assert d["accepted"] and d["outcomes"]["a"] == ["failure", "success"]
