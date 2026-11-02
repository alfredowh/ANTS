import io
import json
import urllib.error

import pytest

from ants.adversary.models import (
    BudgetExceeded,
    Effort,
    Message,
    MetaModel,
    MockModel,
    ModelError,
    ReasoningModel,
    extract_json,
    get_model,
)
from ants.adversary.models import meta as meta_module


def test_get_mock_and_meta_satisfy_protocol():
    assert isinstance(get_model("mock"), ReasoningModel)
    assert isinstance(get_model("muse-spark"), MetaModel)


def test_other_providers_not_built_yet():
    with pytest.raises(NotImplementedError):
        get_model("openai:gpt-x")


def test_unknown_spec():
    with pytest.raises(ValueError):
        get_model("nope")


def test_mock_returns_n_deterministic_samples():
    model = MockModel(lambda msgs, effort, i: f"{effort}-{i}-{msgs[-1].content}")
    out = model.complete([Message("user", "hi")], Effort.PARALLEL, n=3)
    assert out.texts == ("parallel-0-hi", "parallel-1-hi", "parallel-2-hi")


def test_mock_failure_mode():
    with pytest.raises(ModelError):
        MockModel(fail=True).complete([Message("user", "hi")])


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1}',
        'Sure.\n```json\n{"a": 1}\n```',
        '<think>maybe {"b": 2}? no</think> final: {"a": 1}',
        'prefix {not json} then {"a": 1} suffix',
    ],
)
def test_extract_json(text):
    assert extract_json(text) == {"a": 1}


def test_extract_json_raises_without_object():
    with pytest.raises(ModelError):
        extract_json("no json here")


class FakeAPI:
    """Stands in for urllib.request.urlopen; records requests, returns chat completions."""

    def __init__(self, error: int | None = None):
        self.requests = []
        self.error = error

    def __call__(self, req, timeout):
        body = json.loads(req.data.decode("utf-8"))
        self.requests.append((req, body))
        if self.error:
            raise urllib.error.HTTPError(req.full_url, self.error, "err", {}, io.BytesIO(b"bad"))
        reply = {
            "choices": [{"message": {"content": f'{{"n": {len(self.requests)}}}'}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 400,
                "completion_tokens_details": {"reasoning_tokens": 300},
            },
        }
        return io.BytesIO(json.dumps(reply).encode("utf-8"))


@pytest.fixture
def api(monkeypatch, tmp_path):
    fake = FakeAPI()
    monkeypatch.setattr(meta_module.urllib.request, "urlopen", fake)
    monkeypatch.setenv("META_API_KEY", "test-key")
    model = MetaModel(cache_dir=tmp_path / "cache", ledger=tmp_path / "ledger.jsonl")
    return fake, model, tmp_path


def test_meta_request_shape_and_usage(api):
    fake, model, _ = api
    out = model.complete([Message("user", "hello")], Effort.DELIBERATE)
    req, body = fake.requests[0]
    assert req.full_url == "https://api.meta.ai/v1/chat/completions"
    assert req.get_header("Authorization") == "Bearer test-key"
    assert body["model"] == "muse-spark-1.3" and body["messages"][0]["content"] == "hello"
    assert out.texts == ('{"n": 1}',) and out.usage["reasoning_tokens"] == 300


def test_meta_cache_avoids_a_second_paid_call(api):
    fake, model, tmp_path = api
    model.complete([Message("user", "hello")])
    out = model.complete([Message("user", "hello")])
    assert len(fake.requests) == 1 and out.usage["cached_calls"] == 1
    ledger = [json.loads(x) for x in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert [e["from_cache"] for e in ledger] == [False, True]
    assert ledger[1]["prompt_tokens"] == 0


def test_meta_parallel_makes_n_independent_calls(api):
    fake, model, _ = api
    out = model.complete([Message("user", "attack")], Effort.PARALLEL, n=4)
    assert len(fake.requests) == 4 and len(out.texts) == 4
    assert out.usage["completion_tokens"] == 1600


def test_meta_budget_stops_before_spending(api):
    fake, model, _ = api
    model.token_budget = 600
    model.complete([Message("user", "one")])  # spends 500
    model.complete([Message("user", "two")])  # 500 < 600, allowed, now 1000
    with pytest.raises(BudgetExceeded):
        model.complete([Message("user", "three")])
    assert len(fake.requests) == 2


def test_meta_errors_become_model_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(meta_module.urllib.request, "urlopen", FakeAPI(error=400))
    monkeypatch.setenv("META_API_KEY", "k")
    model = MetaModel(cache_dir=tmp_path / "c", ledger=tmp_path / "l.jsonl")
    with pytest.raises(ModelError, match="HTTP 400"):
        model.complete([Message("user", "x")])
    monkeypatch.delenv("META_API_KEY")
    with pytest.raises(ModelError, match="not set"):
        model.complete([Message("user", "y")])


def test_meta_sends_images_as_data_urls(api):
    fake, model, tmp_path = api
    img = tmp_path / "k.png"
    img.write_bytes(b"\x89PNG fake")
    model.complete([Message("user", "look", images=(str(img),))])
    content = fake.requests[0][1]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "look"}
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_meta_budget_counts_only_this_runs_new_tokens(api, tmp_path):
    """Earlier runs in the shared ledger do not use up a new run's budget."""
    _, model, _ = api
    model.ledger.write_text(
        json.dumps({"prompt_tokens": 10**6, "completion_tokens": 0, "from_cache": False}) + "\n",
        encoding="utf-8",
    )
    model._spent = None
    model.token_budget = 600
    model.complete([Message("user", "fresh run")])
    assert model.run_spent == 500 and model.spent() > 10**6


def test_meta_default_budget_is_the_run_book_limit():
    assert meta_module.MetaModel().token_budget == 100_000
