"""System 2 configuration. Every field is logged with the run (gate, bounds and budget explicit)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ants.adversary.perturbations import CATEGORIES, Bounds
from ants.adversary.rollout.runner import DEFAULT_LINE_BUDGET


@dataclass
class AdversaryConfig:
    model: str = "mock"  # "muse-spark" enables the model proposer, diagnoser and explainer
    n_agents: int = 4  # parallel proposer agents (PARALLEL effort)
    confidence_floor: float = 0.5  # below it the rule diagnosis is used
    backend: str = "mock"  # "mock" now; "cap_harness" once System 1's contracts land
    categories: tuple[str, ...] = CATEGORIES
    eta: float = 0.2  # uniform share of picks; 1.0 is the uniform baseline
    bounds: Bounds = field(default_factory=Bounds)  # per-category severity limit (rho caps on top)
    min_severity: float = 0.3
    stop_mode: str = "min_tests"  # "min_tests" for demo runs, "posterior" for reported numbers
    min_tests: int = 3
    tau: float = 0.1
    stop_quantile: float = 0.95
    seed: int = 0
    line_budget: int = DEFAULT_LINE_BUDGET
    history_path: Path | None = None

    def __post_init__(self) -> None:
        if self.stop_mode not in ("min_tests", "posterior"):
            raise ValueError("stop_mode must be 'min_tests' or 'posterior'")
