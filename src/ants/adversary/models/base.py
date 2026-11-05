"""The one interface planner and diagnoser use to talk to a reasoning model.

Nothing outside `models/` names a vendor or a model. Adapters map `Effort` to vendor modes
(Muse Spark: FAST -> Instant, DELIBERATE -> Thinking, PARALLEL -> Contemplating).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class Effort(StrEnum):
    FAST = "fast"
    DELIBERATE = "deliberate"  # step-by-step reasoning, one answer (diagnoser)
    PARALLEL = "parallel"  # several independent answers (proposer agents)


@dataclass(frozen=True)
class Message:
    role: str  # "system", "user" or "assistant"
    content: str
    images: tuple[str, ...] = ()  # file paths, e.g. keyframes


@dataclass(frozen=True)
class ModelResponse:
    texts: tuple[str, ...]  # one per requested sample
    model: str
    usage: Mapping[str, int] = field(default_factory=dict)  # tokens, for cost per cycle


class ModelError(RuntimeError):
    """Any failure to get a usable answer. Callers catch it and fall back to deterministic code."""


@runtime_checkable
class ReasoningModel(Protocol):
    name: str

    def complete(
        self,
        messages: Sequence[Message],
        effort: Effort = Effort.FAST,
        json_schema: Mapping[str, Any] | None = None,
        n: int = 1,
    ) -> ModelResponse:
        """Return `n` completions. Raise `ModelError` on any failure."""
        ...


def extract_json(text: str) -> Any:
    """The first JSON object in a model reply, after stripping reasoning blocks and code fences.

    Raises `ModelError` when there is none, so callers fall back instead of guessing.
    """
    import json
    import re

    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"```(?:json)?", "", cleaned)
    decoder = json.JSONDecoder()
    for start in (m.start() for m in re.finditer(r"\{", cleaned)):
        try:
            value, _ = decoder.raw_decode(cleaned[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ModelError("no JSON object in the model reply")
