"""Deterministic offline model, so the full loop runs in tests without network or GPU."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ants.adversary.models.base import Effort, Message, ModelError, ModelResponse

Responder = Callable[[Sequence[Message], Effort, int], str]


class MockModel:
    """Answers with `responder(messages, effort, sample_index)`, or `"{}"` by default.

    `fail=True` raises `ModelError` on every call, to exercise the fallback paths.
    """

    name = "mock"

    def __init__(self, responder: Responder | None = None, fail: bool = False) -> None:
        self._responder = responder or (lambda _m, _e, _i: "{}")
        self._fail = fail
        self.calls: list[tuple[tuple[Message, ...], Effort, int]] = []

    def complete(
        self,
        messages: Sequence[Message],
        effort: Effort = Effort.FAST,
        json_schema: Mapping[str, Any] | None = None,
        n: int = 1,
    ) -> ModelResponse:
        self.calls.append((tuple(messages), effort, n))
        if self._fail:
            raise ModelError("mock model configured to fail")
        texts = tuple(self._responder(messages, effort, i) for i in range(n))
        return ModelResponse(texts=texts, model=self.name, usage={"calls": 1})
