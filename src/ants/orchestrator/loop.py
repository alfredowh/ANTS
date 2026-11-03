"""The closed loop: System 2 breaks the incumbent, System 1 rewrites it, the gate keeps or drops it.

Ported from System 1's `harden()` (branch `synthesizer`, `orchestrator/system2.py`) onto the
System 2 `Adversary` and the shared contracts. One cycle is one attack (paper, Algorithm 1):

1. System 2 attacks the incumbent (it chooses the category and the perturbation).
2. On a task failure the attack becomes an acceptance `CaseSpec` and a `Feedback`; its constraint
   joins the context for good if its failure signature is new.
3. System 1 writes a candidate (`Synthesizer.rewrite`).
4. The candidate replays every case seen so far: the nominal acceptance cases plus F_n, the
   failures found. The gate compares outcomes with the incumbent's.
5. Accepted: the candidate becomes the incumbent; System 2's beliefs restart automatically,
   because its history is keyed by policy version. Rejected: the signature's stall count grows.
6. Stop when System 2 says the incumbent is robust (its configured stop mode), at the cycle or
   budget limit, or escalate when one signature stalls for `stall_window` cycles (W = 3).

Split. Every case the loop builds is an acceptance case, and `Feedback` refuses a held-out one;
held-out evaluation runs elsewhere (`evalkit/`) through `Adversary.replay` and never reaches
System 1.

Costs. The incumbent's outcomes are reused from when it ran each case, so a gate check replays
only the candidate. That is exact for deterministic backends (the mock world, seeded LIBERO); for
a policy with `deterministic=False` the gate should use several rollouts per case (not built).

Everything is logged under `out/`: `loop.jsonl` (one line per cycle, every input of every
decision), `policies/v<N>.py` (each accepted version), `summary.json`.
"""

from __future__ import annotations

import difflib
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ants.adversary import Adversary
from ants.contracts import (
    AttackReport,
    CaseSpec,
    Constraint,
    Feedback,
    Outcome,
    Perturbation,
    Policy,
    RolloutResult,
    Split,
    to_dict,
)
from ants.orchestrator.gate import GateDecision, gate
from ants.orchestrator.human_gate import GateAnswer, answer_to_constraint
from ants.orchestrator.synthesis import Synthesizer
from ants.orchestrator.workflow import workflow_info

#: escalation request -> a person's answer, or None when nobody answered
AskHuman = Callable[[Mapping[str, Any]], "GateAnswer | None"]
#: called after every attack with the report and the policy it attacked (observability only)
OnAttack = Callable[[AttackReport, Policy], None]

#: the names `docs/orchestrator/phases.md` documents for the repair model; a test keeps them in sync
STOP_REASONS = ("robust", "cycles", "budget", "escalate", "no_working_policy")
DECISIONS = ("no_failure", "accepted", "rejected", "budget_stop")
EVENTS = ("start", "cycle", "escalate", "human_answer", "no_working_policy", "end")


@dataclass
class LoopConfig:
    cycles: int = 20  # attacks
    suite: str = "libero_goal_swap"
    task_id: int = 8
    nominal_seeds: tuple[int, ...] = (51, 52, 53)  # acceptance seeds of the nominal cases
    gate_mode: str = "strict"  # "off" only for the without-gate ablation arm
    stall_window: int = 3  # W: cycles one failure signature may stall before escalation
    max_human_asks: int = 1
    # Muse price used to turn token counts into $ (observed about $13.5 per million tokens,
    # see docs/architecture.md, open decision 6). Logged with the run; not a billing record.
    usd_per_million_tokens: float = 13.5
    out: Path | None = None  # run directory; None logs nothing to disk


@dataclass
class LoopResult:
    incumbent: Policy
    stopped: str  # robust | cycles | budget | escalate | no_working_policy
    stage: str  # attackable | incumbent | certified
    constraints: list[Constraint]
    cycles: list[dict[str, Any]]
    escalation: dict[str, Any] | None = None
    accepted_versions: list[int] = field(default_factory=list)


class Loop:
    def __init__(
        self,
        adversary: Adversary,
        synthesizer: Synthesizer,
        config: LoopConfig | None = None,
        ask_human: AskHuman | None = None,
        on_attack: OnAttack | None = None,
    ) -> None:
        self.adv = adversary
        self.on_attack = on_attack
        self.synth = synthesizer
        self.cfg = config or LoopConfig()
        self.ask_human = ask_human
        self.cases: dict[str, CaseSpec] = {}
        self.outcomes: dict[str, Outcome] = {}  # the incumbent's outcome per case
        self.constraints: list[Constraint] = []
        self.stalls: dict[str, int] = {}

    # --- logging -------------------------------------------------------------------------
    def _log(self, name: str, row: Mapping[str, Any]) -> None:
        if self.cfg.out is None:
            return
        self.cfg.out.mkdir(parents=True, exist_ok=True)
        with (self.cfg.out / name).open("a", encoding="utf-8") as f:
            f.write(json.dumps(to_dict(dict(row)), default=str) + "\n")

    def _save_policy(self, policy: Policy) -> None:
        if self.cfg.out is None:
            return
        folder = self.cfg.out / "policies"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"v{policy.version}.py").write_text(policy.code, encoding="utf-8")
        (folder / f"v{policy.version}.json").write_text(
            json.dumps(policy.to_dict(), indent=1, default=str), encoding="utf-8"
        )

    # --- cost ----------------------------------------------------------------------------
    def _usd(self, tokens: int) -> float:
        return round(tokens * self.cfg.usd_per_million_tokens / 1e6, 4)

    def _cost(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Rewrite tokens and $ in total and per rewrite (System 1's counts)."""
        spent = [r["rewrite_tokens"] for r in rows if "rewrite_tokens" in r]
        total = sum(spent)
        return {
            "rewrite_tokens": total,
            "rewrites": len(spent),
            "rewrite_cost_usd": self._usd(total),
            "cost_per_rewrite_usd": self._usd(total / len(spent)) if spent else 0.0,
            "usd_per_million_tokens": self.cfg.usd_per_million_tokens,
        }

    # --- cases ---------------------------------------------------------------------------
    def _run(self, policy: Policy, case: CaseSpec) -> RolloutResult:
        p: Perturbation | None = case.perturbations[0] if case.perturbations else None
        return self.adv.replay(policy, [p], seed=case.seed)[0]

    def _nominal_cases(self) -> list[CaseSpec]:
        c = self.cfg
        return [
            CaseSpec(f"nominal-{s}", c.suite, c.task_id, s, Split.ACCEPTANCE)
            for s in c.nominal_seeds
        ]

    def _constraint_for(self, constraint: Constraint) -> Constraint:
        """The one constraint per signature: reuse the first one, so the context stays short."""
        for c in self.constraints:
            if c.failure_signature == constraint.failure_signature:
                return c
        self.constraints.append(constraint)
        return constraint

    # --- the loop ------------------------------------------------------------------------
    def run(self, policy: Policy) -> LoopResult:
        cfg = self.cfg
        start = {
            "event": "start",
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "policy": {"id": policy.policy_id, "version": policy.version},
            "loop": {k: v for k, v in vars(cfg).items() if k != "out"},
            "adversary": {
                k: v for k, v in vars(self.adv.config).items() if k not in ("aspire", "bounds")
            },
            "backend": self.adv.backend.name,
            "workflow": workflow_info(),
        }
        self._log("loop.jsonl", start)
        incumbent, stage = policy, "draft"
        self._save_policy(incumbent)
        for case in self._nominal_cases():
            self.cases[case.case_id] = case
            self.outcomes[case.case_id] = self._run(incumbent, case).outcome
        if any(o is not Outcome.SUCCESS for o in self.outcomes.values()):
            escalation = {
                "signature": "nominal",
                "request": "the policy fails its nominal cases: one more demonstration",
                "outcomes": {k: v.value for k, v in self.outcomes.items()},
            }
            self._log("loop.jsonl", {"event": "no_working_policy", **escalation})
            return self._finish(incumbent, "no_working_policy", stage, [], escalation, [])
        stage = "attackable"

        rows: list[dict[str, Any]] = []
        accepted: list[int] = []
        stopped, escalation, asks = "cycles", None, 0
        for cycle in range(cfg.cycles):
            report = self.adv.attack(incumbent)
            if self.on_attack is not None:
                self.on_attack(report, incumbent)
            p = report.perturbation
            row: dict[str, Any] = {
                "event": "cycle",
                "cycle": cycle,
                "attack_id": report.attack_id,
                "policy_version": incumbent.version,
                "category": p.category,
                "severity": p.severity,
                "params": dict(p.params),
                "seed": p.seed,
                "outcome": report.result.outcome.value,
                "selector_draws": dict(report.selector_draws),
            }
            if report.result.outcome is not Outcome.FAILURE:
                # An incumbent crash under attack is logged but never fed back as a task failure.
                status = self.adv.status(incumbent)
                row["decision"] = "no_failure"
                row["robust"] = status.robust
                rows.append(row)
                self._log("loop.jsonl", row)
                if status.robust:
                    stopped, stage = "robust", "certified"
                    break
                continue

            case = CaseSpec(
                report.attack_id,
                cfg.suite,
                cfg.task_id,
                p.seed if p.seed is not None else 0,
                Split.ACCEPTANCE,
                (p,),
            )
            self.cases[case.case_id] = case
            self.outcomes[case.case_id] = report.result.outcome
            constraint = self._constraint_for(report.constraint)
            feedback = Feedback.from_report(report, case)
            sig = constraint.failure_signature
            row.update(
                signature=sig,
                failure=to_dict(report.failure),
                constraint=to_dict(constraint),
                constraints_active=len(self.constraints),
            )

            candidate = self.synth.rewrite(incumbent, [feedback], list(self.constraints))
            if candidate is None:
                row["decision"] = "budget_stop"
                rows.append(row)
                self._log("loop.jsonl", row)
                stopped = "budget"
                break
            cand = {cid: self._run(candidate, c).outcome for cid, c in self.cases.items()}
            decision: GateDecision = gate(self.outcomes, cand, cfg.gate_mode)
            row["candidate_version"] = candidate.version
            if "tokens" in candidate.metadata:  # what this rewrite cost (System 1's count)
                row["rewrite_tokens"] = candidate.metadata["tokens"]
                row["rewrite_cost_usd"] = self._usd(candidate.metadata["tokens"])
            row["diff"] = "".join(
                difflib.unified_diff(
                    incumbent.code.splitlines(keepends=True),
                    candidate.code.splitlines(keepends=True),
                    f"v{incumbent.version}.py",
                    f"v{candidate.version}.py",
                    n=1,
                )
            )
            row["gate"] = decision.to_dict()
            if decision.accepted:
                incumbent, self.outcomes, stage = candidate, cand, "incumbent"
                self.stalls = {}
                accepted.append(candidate.version)
                self._save_policy(candidate)
                row["decision"] = "accepted"
            else:
                self.stalls[sig] = self.stalls.get(sig, 0) + 1
                row["decision"] = "rejected"
            row["stalls"] = dict(self.stalls)
            rows.append(row)
            self._log("loop.jsonl", row)

            if self.stalls.get(sig, 0) >= cfg.stall_window:
                escalation = {
                    "signature": sig,
                    "stalled_cycles": self.stalls[sig],
                    "request": f"one targeted demonstration for failure '{sig}'",
                    "constraint": constraint.rule,
                }
                self._log("loop.jsonl", {"event": "escalate", "cycle": cycle, **escalation})
                answer = None
                if self.ask_human is not None and asks < cfg.max_human_asks:
                    answer = self.ask_human(escalation)
                    asks += 1
                hint = (
                    answer_to_constraint(answer, escalation, len(self.constraints))
                    if answer
                    else None
                )
                if hint is not None:
                    self.constraints.append(hint)
                    self._log(
                        "loop.jsonl",
                        {"event": "human_answer", "cycle": cycle, "constraint": to_dict(hint)},
                    )
                    self.stalls, escalation = {}, None
                    continue
                stopped = "escalate"
                break
        return self._finish(incumbent, stopped, stage, rows, escalation, accepted)

    def _finish(
        self,
        incumbent: Policy,
        stopped: str,
        stage: str,
        rows: list[dict[str, Any]],
        escalation: dict[str, Any] | None,
        accepted: list[int],
    ) -> LoopResult:
        result = LoopResult(
            incumbent, stopped, stage, list(self.constraints), rows, escalation, accepted
        )
        summary = {
            "event": "end",
            "stopped": stopped,
            "stage": stage,
            "final_version": incumbent.version,
            "accepted_versions": accepted,
            "cycles_run": len(rows),
            "failures_found": sum(r.get("outcome") == Outcome.FAILURE.value for r in rows),
            "constraints": [c.to_dict() for c in self.constraints],
            "escalation": escalation,
            "cases": len(self.cases),
            **self._cost(rows),
        }
        self._log("loop.jsonl", summary)
        if self.cfg.out is not None:
            (self.cfg.out / "summary.json").write_text(
                json.dumps(summary, indent=1, default=str), encoding="utf-8"
            )
        return result
