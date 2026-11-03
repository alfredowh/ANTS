"""Reasoning-model interface and adapters. The only place a vendor or model name may appear."""

from pathlib import Path

from ants.adversary.models.base import (
    Effort,
    Message,
    ModelError,
    ModelResponse,
    ReasoningModel,
    extract_json,
)
from ants.adversary.models.meta import BudgetExceeded, EffortSetting, MetaModel, load_dotenv
from ants.adversary.models.mock import MockModel


def get_model(spec: str) -> ReasoningModel:
    """Build a model from a config string: "mock", "muse-spark" or "provider:model"."""
    if spec == "mock":
        return MockModel()
    if spec == "muse-spark":
        load_dotenv(Path(".env"))
        return MetaModel()
    if ":" in spec:
        raise NotImplementedError(f"adapter for {spec!r} is not built yet")
    raise ValueError(
        f"unknown model spec {spec!r}; expected 'mock', 'muse-spark' or 'provider:model'"
    )


__all__ = [
    "BudgetExceeded",
    "Effort",
    "EffortSetting",
    "Message",
    "MetaModel",
    "MockModel",
    "ModelError",
    "ModelResponse",
    "ReasoningModel",
    "extract_json",
    "get_model",
    "load_dotenv",
]
