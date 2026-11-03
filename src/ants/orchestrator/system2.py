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

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ants.adversary.diagnoser import diagnose, signature
from ants.adversary.perturbations import CATEGORIES, Bounds
from ants.adversary.planner import TestPlanner
from ants.contracts import CaseSpec, Constraint, Split, to_dict
from ants.evalkit.corrections import (
    CorrectionStore,
    make_correction,
    retrieve_corrections,
    signature_from_trace,
)
from ants.evalkit.runlog import RunLog, unified_diff
from ants.orchestrator.gate import regression_gate
from ants.orchestrator.human_gate import GateAnswer, answer_to_constraint


@dataclass
class CaseResult:
    success: bool
    feedback: dict = field(default_factory=dict)  # `aspire_harness.feedback()` of a failed episode
    run_dir: str | None = None


RunCase = Callable[[CaseSpec, Path], CaseResult]
#: (incumbent program, all constraints, failure feedbacks) -> (candidate program, tokens) or None
Generate = Callable[[Path, list[Constraint], list[dict]], "tuple[Path, int] | None"]
#: escalation request -> the person's answer, or None when nobody answered
AskHuman = Callable[[dict], "GateAnswer | None"]


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
    max_human_asks: int = 1  # how often a stall may be handed to a person before the loop stops
    min_tests_robust: int = 3
    strategy: str = "thompson"
    seed: int = 0
    bounds: Bounds = field(default_factory=Bounds)
    memory_mode: str = "off"  # off | matched(k): signature-keyed correction retrieval
    memory_k: int = 2
    correction_store: Path | None = None  # JSONL; written at gate acceptance, read on retrieval


@dataclass
class HardenResult:
    incumbent: Path
    stopped: str  # robust | cycles | budget | escalate
    constraints: list[Constraint]
    cycles: list[dict]
    escalation: dict | None = None


def harden(
    incumbent: Path,
    cfg: HardenConfig,
    run_case: RunCase,
    generate: Generate,
    log: RunLog,
    ask_human: AskHuman | None = None,
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
        add_case(CaseSpec(f"nominal-{seed}", cfg.suite, cfg.task_id, seed, Split.ACCEPTANCE))
    nominal_ok = all(results[f"nominal-{s}"] for s in cfg.nominal_seeds)
    log.event("system2_start", incumbent=str(incumbent), nominal_ok=nominal_ok, cfg=str(cfg))
    if not nominal_ok:
        return HardenResult(incumbent, "no_working_policy", constraints, rows)

    stopped, escalation, counter, asks = "cycles", None, 0, 0
    for cycle in range(cfg.cycles):
        tests, failures = [], []
        for i in range(cfg.tests_per_cycle):
            p = planner.propose()
            seed = cfg.acceptance_seeds[counter % len(cfg.acceptance_seeds)]
            counter += 1
            case = CaseSpec(
                f"c{cycle}-t{i}-{p.category}-s{seed}",
                cfg.suite, cfg.task_id, seed, Split.ACCEPTANCE, (p,),
            )  # fmt: skip
            res = add_case(case)
            planner.update(p.category, failed=not res.success)
            tests.append(
                {"case_id": case.case_id, "category": p.category, "severity": p.severity,
                 "params": p.params, "seed": seed, "success": res.success,
                 "run_dir": res.run_dir}
            )  # fmt: skip
            if not res.success:
                failures.append((p, res, case))
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
        for p, res, _case in failures:
            sig = signature(p, res.feedback)
            sigs.append(sig)
            if all(c.failure_signature != sig for c in constraints):
                c = diagnose(p, res.feedback, len(constraints))
                constraints.append(c)
                row["constraints_new"].append(to_dict(c))
        # Signature-keyed correction retrieval: past gate-accepted repairs for the
        # same failure signature, offered to the generator as extra constraints.
        retrieval = {
            "mode": cfg.memory_mode,
            "used": False,
            "reason": "memory_off" if cfg.memory_mode == "off" else "no_match",
            "queries": [signature_from_trace(r.feedback).as_dict() for _, r, _ in failures],
            "candidates": [],
            "retrieved": [],
        }
        prompt_constraints = list(constraints)
        retrieved_records: list[dict] = []
        if cfg.memory_mode == "matched" and cfg.correction_store is not None:
            store = CorrectionStore(cfg.correction_store)
            records = store.load()
            if not records:
                retrieval["reason"] = "empty_store"
            seen_ids: set[str] = set()
            for _, res, _ in failures:
                chosen, candidates = retrieve_corrections(records, res.feedback, cfg.memory_k)
                retrieval["candidates"].extend(candidates)
                for record in chosen:
                    if record["correction_id"] in seen_ids:
                        continue
                    seen_ids.add(record["correction_id"])
                    retrieved_records.append(record)
                    prompt_constraints.append(
                        Constraint(
                            constraint_id=f"mem:{record['correction_id']}",
                            failure_signature=record.get("failure_signature", ""),
                            when_to_apply=record.get("when_to_apply", ""),
                            rule=record["rule"]
                            + "\nPast accepted repair for this failure:\n"
                            + (record.get("repair_diff") or "")[:2000],
                            evidence=list(record.get("evidence", [])),
                        )
                    )
            if retrieved_records:
                retrieval["used"] = True
                retrieval["reason"] = "hit"
                retrieval["retrieved"] = [
                    {
                        "correction_id": r["correction_id"],
                        "signature": r.get("signature"),
                        "rule": r.get("rule", ""),
                        "repair_diff": (r.get("repair_diff") or "")[:2000],
                        "trigger_case": r.get("trigger_case", ""),
                        "help_count": r.get("help_count", 0),
                        "hurt_count": r.get("hurt_count", 0),
                    }
                    for r in retrieved_records
                ]
                for record in retrieved_records:
                    store.bump(record["correction_id"], retrieved_delta=1)
            log.event(
                "memory_retrieval",
                cycle=cycle,
                used=retrieval["used"],
                reason=retrieval["reason"],
                retrieved=[r["correction_id"] for r in retrieved_records],
            )
        elif cfg.memory_mode == "matched":
            retrieval["reason"] = "no_store_configured"
        row["retrieval"] = retrieval
        gen = generate(incumbent, prompt_constraints, [r.feedback for _, r, _ in failures])
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
        if gate.accepted and cfg.correction_store is not None:
            store = CorrectionStore(cfg.correction_store)
            try:
                diff = unified_diff(
                    incumbent.read_text(encoding="utf-8"),
                    candidate.read_text(encoding="utf-8"),
                    incumbent.name,
                    candidate.name,
                )
            except OSError:
                diff = ""
            written = []
            for (_p, res, case), sig in zip(failures, sigs, strict=False):
                if case.case_id not in gate.improvements:
                    continue
                constraint = next((c for c in constraints if c.failure_signature == sig), None)
                if constraint is None:
                    continue
                record = make_correction(
                    constraint,
                    res.feedback,
                    case.case_id,
                    incumbent.name,
                    candidate.name,
                    diff,
                    gate.__dict__,
                    epoch=cycle,
                )
                if all(r["correction_id"] != record["correction_id"] for r in store.load()):
                    store.append(record)
                    written.append(record["correction_id"])
            row["corrections_written"] = written
            for record in retrieved_records:
                store.bump(record["correction_id"], help_delta=1)
        elif gate.accepted:
            row["corrections_written"] = []
        if not gate.accepted and retrieved_records and cfg.correction_store is not None:
            store = CorrectionStore(cfg.correction_store)
            for record in retrieved_records:
                store.bump(record["correction_id"], hurt_delta=1)
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
            answer = ask_human(escalation) if ask_human and asks < cfg.max_human_asks else None
            asks += 1
            hint = answer_to_constraint(answer, escalation, len(constraints)) if answer else None
            if answer and not hint:
                log.event("human_answer_unused", channel=answer.channel, reason="not wired yet")
            if hint:
                constraints.append(hint)
                log.event("human_answer", channel=answer.channel, signature=worst)
                stalls = {}
                escalation = None
                continue
            stopped = "escalate"
            break
    log.event("system2_end", stopped=stopped, incumbent=str(incumbent))
    return HardenResult(incumbent, stopped, constraints, rows, escalation)
