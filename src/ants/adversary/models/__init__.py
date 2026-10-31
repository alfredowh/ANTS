"""Reasoning-model interface and adapters. The only place a vendor or model name may appear."""

from ants.adversary.models.base import (
    Effort,
    Message,
    ModelError,
    ModelResponse,
    ReasoningModel,
)
from ants.adversary.models.mock import MockModel


def get_model(spec: str) -> ReasoningModel:
    """Build a model from a config string: "mock", "muse-spark" or "provider:model"."""
    if spec == "mock":
        return MockModel()
    if spec == "muse-spark" or ":" in spec:
        raise NotImplementedError(f"adapter for {spec!r} is not built yet (build order step 8)")
    raise ValueError(
        f"unknown model spec {spec!r}; expected 'mock', 'muse-spark' or 'provider:model'"
    )


__all__ = [
    "Effort",
    "Message",
    "MockModel",
    "ModelError",
    "ModelResponse",
    "ReasoningModel",
    "get_model",
]
