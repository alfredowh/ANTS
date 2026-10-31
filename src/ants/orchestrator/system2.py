"""System 2 v0: harden a working policy with an adversarial test loop and a never-regress gate.

Start from an incumbent program that already succeeds on the nominal cases. Each cycle:

1. the planner proposes perturbed cases within the severity bound (acceptance seeds only);
2. the incumbent runs on them; every failure is diagnosed into a `Constraint`;
3. the generator is asked for a candidate with all constraints in its context;
4. the candidate runs on EVERY case seen so far (nominal and perturbed);
5. the per-case regression gate accepts it only if it never does worse than the incumbent.

The loop stops when every category is confidently robust, when the budget or cycle limit is
reached, or when the same failure signature stalls `stall_limit` times (escalation: ask a human
for one targeted demonstration). The simulator and the generator are passed in as callables, so
the loop is testable without a GPU or model tokens. Every cycle is appended to `system2.jsonl`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ants.adversary.diagnoser import diagnose, signature
from ants.adversary.perturbations import CATEGORIES, Bounds
from ants.adversary.planner import TestPlanner
from ants.contracts import CaseSpec, Constraint, to_json
from ants.evalkit.runlog import RunLog
from ants.orchestrator.gate import regression_gate


@dataclass
class CaseResult:
    success: bool
    feedback: dict = field(default_factory=dict)  # `rollout.feedback()` of a failed episode
    run_dir: str | None = None


RunCase = Callable[[CaseSpec, Path], CaseResult]
#: (incumbent program, all constraints, failure feedbacks) -> (candidate program, tokens) or None
Generate = Callable[[Path, list[Constraint], list[dict]], "tuple[Path, int] | None"]


@dataclass
class HardenConfig:
    suite: str = "libero_goal_swap"
    task_id: int = 8
    cycles: int = 4
    tests_per_cycle: int = 4
    nominal_seeds: tuple[int, ...] = (51, 52, 53)
    acceptance_seeds: tuple[int, ...] = tuple(range(51, 66))
    held_out_seeds: tuple[int, ...] = tuple(range(1, 51))
    stall_limit: int = 2
    min_tests_robust: int = 3
    strategy: str = "thompson"
    seed: int = 0
    bounds: Bounds = field(default_factory=Bounds)


@dataclass
class HardenResult:
    incumbent: Path
    stopped: str  # robust | cycles | budget | escalate
    constraints: list[Constraint]
    cycles: list[dict]
    escalation: dict | None = None


def harden(
    incumbent: Path, cfg: HardenConfig, run_case: RunCase, generate: Generate, log: RunLog
) -> HardenResult:
    if set(cfg.acceptance_seeds) & set(cfg.held_out_seeds):
        raise ValueError("acceptance and held-out seeds must be disjoint")
    planner = TestPlanner(CATEGORIES, cfg.bounds, cfg.strategy, cfg.seed)
    specs: dict[str, CaseSpec] = {}
    results: dict[str, bool] = {}
    constraints: list[Constraint] = []
    stalls: dict[str, int] = {}
    rows: list[dict] = []

    def add_case(case: CaseSpec) -> CaseResult:
        if case.seed not in cfg.acceptance_seeds:
            raise ValueError(f"seed {case.seed} is not an acceptance seed")
        specs[case.case_id] = case
        res = run_case(case, incumbent)
        results[case.case_id] = res.success
        return res

    for seed in cfg.nominal_seeds:
        add_case(CaseSpec(f"nominal-{seed}", cfg.suite, cfg.task_id, seed, "acceptance"))
    nominal_ok = all(results[f"nominal-{s}"] for s in cfg.nominal_seeds)
    log.event("system2_start", incumbent=str(incumbent), nominal_ok=nominal_ok, cfg=str(cfg))
    if not nominal_ok:
        return HardenResult(incumbent, "no_working_policy", constraints, rows)

    stopped, escalation, counter = "cycles", None, 0
    for cycle in range(cfg.cycles):
        tests, failures = [], []
        for i in range(cfg.tests_per_cycle):
            p = planner.propose()
            seed = cfg.acceptance_seeds[counter % len(cfg.acceptance_seeds)]
            counter += 1
            case = CaseSpec(
                f"c{cycle}-t{i}-{p.category}-s{seed}",
                cfg.suite, cfg.task_id, seed, "acceptance", [p],
            )  # fmt: skip
            res = add_case(case)
            planner.update(p.category, failed=not res.success)
            tests.append(
                {"case_id": case.case_id, "category": p.category, "severity": p.severity,
                 "params": p.params, "seed": seed, "success": res.success,
                 "run_dir": res.run_dir}
            )  # fmt: skip
            if not res.success:
                failures.append((p, res))
        row: dict = {"cycle": cycle, "tests": tests, "constraints_new": [], "candidate": None}
        if not failures:
            row["decision"] = "no_failure"
            rows.append(row)
            log.append_json("system2.jsonl", row)
            if planner.confidently_robust(cfg.min_tests_robust):
                stopped = "robust"
                break
            continue
        sigs = []
        for p, res in failures:
            sig = signature(p, res.feedback)
            sigs.append(sig)
            if all(c.failure_signature != sig for c in constraints):
                c = diagnose(p, res.feedback, len(constraints))
                constraints.append(c)
                row["constraints_new"].append(json.loads(to_json(c)))
        gen = generate(incumbent, constraints, [r.feedback for _, r in failures])
        if gen is None:
            row["decision"] = "budget_stop"
            rows.append(row)
            log.append_json("system2.jsonl", row)
            stopped = "budget"
            break
        candidate, tokens = gen
        cand_results = {cid: run_case(spec, candidate).success for cid, spec in specs.items()}
        gate = regression_gate(dict(results), cand_results)
        row["candidate"] = {"program": str(candidate), "tokens": tokens}
        row["gate"] = gate.__dict__
        row["incumbent_results"] = dict(results)
        row["candidate_results"] = cand_results
        if gate.accepted:
            incumbent, results = candidate, cand_results
            planner.reset()  # beliefs were about the old incumbent
            row["decision"] = "accepted"
            stalls = {}
        else:
            row["decision"] = "rejected"
            for sig in set(sigs):
                stalls[sig] = stalls.get(sig, 0) + 1
        row["stalls"] = dict(stalls)
        rows.append(row)
        log.append_json("system2.jsonl", row)
        log.event("system2_cycle", cycle=cycle, decision=row["decision"], reason=gate.reason)
        worst = max(stalls, key=stalls.get, default=None)
        if worst and stalls[worst] >= cfg.stall_limit:
            escalation = {
                "signature": worst,
                "stalled_cycles": stalls[worst],
                "request": f"one targeted demonstration for failure '{worst}'",
            }
            log.event("escalate", **escalation)
            log.append_json("system2.jsonl", {"cycle": cycle, "escalation": escalation})
            stopped = "escalate"
            break
    log.event("system2_end", stopped=stopped, incumbent=str(incumbent))
    return HardenResult(incumbent, stopped, constraints, rows, escalation)
