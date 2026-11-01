"""The one entry point the orchestrator calls. System 2 only reports: it never edits code,
accepts rewrites or escalates.

    adv = Adversary.from_config(AdversaryConfig())
    report = adv.attack(policy)            # one cycle -> AttackReport
    results = adv.replay(policy, cases)    # fixed cases: gate, acceptance, held-out
    cases = adv.discovered_failures()      # every failing perturbation so far
    status = adv.status(policy)            # stop rule for the current version
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ants.adversary.config import AdversaryConfig
from ants.adversary.diagnoser import classify, diagnose
from ants.adversary.history import AttackRecord, FailureHistory, policy_key
from ants.adversary.planner import TestPlanner
from ants.adversary.rollout import Backend, MockBackend, run_policy, to_feedback
from ants.contracts import AttackReport, Outcome, Perturbation, Policy, RolloutResult, to_dict


@dataclass(frozen=True)
class RobustnessStatus:
    robust: bool
    mode: str  # which stop rule decided
    counts: Mapping[str, tuple[int, int]]  # category -> (failures, successes) for this version
    mean: Mapping[str, float]  # posterior mean failure rate per category
    upper: Mapping[str, float]  # posterior stop_quantile per category

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)


class Adversary:
    def __init__(
        self,
        config: AdversaryConfig,
        backend: Backend,
        history: FailureHistory | None = None,
    ) -> None:
        self.config = config
        self.backend = backend
        self.history = history if history is not None else FailureHistory(config.history_path)
        self.planner = TestPlanner(
            categories=config.categories,
            bounds=config.bounds,
            strategy="uniform" if config.eta >= 1.0 else "thompson",
            seed=config.seed,
            eta=config.eta,
            min_severity=config.min_severity,
        )

    @classmethod
    def from_config(cls, config: AdversaryConfig) -> Adversary:
        if config.backend == "mock":
            return cls(config, MockBackend())
        if config.backend == "cap_harness":
            raise NotImplementedError(
                "the cap_harness backend waits on CaseSpec and EpisodeTrace in contracts"
            )
        raise ValueError(f"unknown backend {config.backend!r}")

    def _sync_planner(self, policy: Policy) -> None:
        counts = self.history.counts(
            policy_key(policy.policy_id, policy.version), self.config.categories
        )
        self.planner.failures = {c: n.failures for c, n in counts.items()}
        self.planner.passes = {c: n.successes for c, n in counts.items()}

    def attack(self, policy: Policy) -> AttackReport:
        """One cycle: choose a category and a perturbation, run it, diagnose a failure, record."""
        self._sync_planner(policy)
        attack_id = f"atk-{len(self.history):05d}"
        seed = self.config.seed * 1_000_003 + len(self.history)
        perturbation = dataclasses.replace(self.planner.propose(), seed=seed)
        result = run_policy(policy.code, self.backend, perturbation, seed, self.config.line_budget)

        failure = constraint = None
        if result.outcome is Outcome.FAILURE:
            fb = to_feedback(result)
            failure = classify(perturbation, fb)
            n_failures = sum(r.outcome is Outcome.FAILURE for r in self.history.records)
            constraint = diagnose(perturbation, fb, n_failures)
            constraint = dataclasses.replace(constraint, evidence=(attack_id, *constraint.evidence))

        self.history.append(
            AttackRecord(
                attack_id,
                policy_key(policy.policy_id, policy.version),
                perturbation,
                result.outcome,
                constraint.failure_signature if constraint else None,
                failure.mode if failure else None,
            )
        )
        selection = self.planner.last_selection
        return AttackReport(
            attack_id=attack_id,
            policy_id=policy.policy_id,
            version=policy.version,
            perturbation=perturbation,
            result=result,
            selector_draws=dict(selection.draws) if selection else {},
            failure=failure,
            constraint=constraint,
        )

    def replay(
        self, policy: Policy, cases: Sequence[Perturbation | None], seed: int = 0
    ) -> list[RolloutResult]:
        """Run fixed cases (None = nominal scene). Not recorded: replays are the gate's and the
        evaluation's business, and must not move the selector's beliefs."""
        return [
            run_policy(
                policy.code,
                self.backend,
                p,
                p.seed if p is not None and p.seed is not None else seed,
                self.config.line_budget,
            )
            for p in cases
        ]

    def discovered_failures(self) -> list[Perturbation]:
        return self.history.discovered_failures()

    def status(self, policy: Policy) -> RobustnessStatus:
        self._sync_planner(policy)
        cfg = self.config
        counts = self.planner.counts
        if cfg.stop_mode == "posterior":
            robust = self.planner.posterior_robust(cfg.tau, cfg.stop_quantile)
        else:
            robust = self.planner.confidently_robust(cfg.min_tests)
        return RobustnessStatus(
            robust=robust,
            mode=cfg.stop_mode,
            counts={c: (n.failures, n.successes) for c, n in counts.items()},
            mean=self.planner.selector.mean(counts),
            upper=self.planner.selector.upper(counts, cfg.stop_quantile),
        )
