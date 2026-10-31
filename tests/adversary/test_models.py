import pytest

from ants.adversary.models import (
    Effort,
    Message,
    MockModel,
    ModelError,
    ReasoningModel,
    get_model,
)


def test_get_mock_satisfies_protocol():
    assert isinstance(get_model("mock"), ReasoningModel)


@pytest.mark.parametrize("spec", ["muse-spark", "openai:gpt-x"])
def test_real_adapters_not_built_yet(spec):
    with pytest.raises(NotImplementedError):
        get_model(spec)


def test_unknown_spec():
    with pytest.raises(ValueError):
        get_model("nope")


def test_mock_returns_n_deterministic_samples():
    model = MockModel(lambda msgs, effort, i: f"{effort}-{i}-{msgs[-1].content}")
    out = model.complete([Message("user", "hi")], Effort.PARALLEL, n=3)
    assert out.texts == ("parallel-0-hi", "parallel-1-hi", "parallel-2-hi")
    assert model.calls[0][1] is Effort.PARALLEL


def test_mock_failure_mode():
    with pytest.raises(ModelError):
        MockModel(fail=True).complete([Message("user", "hi")])
