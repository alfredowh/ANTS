"""Experiment: does one demonstration help the generator write a working program?

Arms differ only in the demonstration section of the prompt (Q1 in
docs/synthesizer/discussion.md). Per arm and sample: write a program, run it on a debug seed,
repair it from text feedback up to N times, then evaluate the final program unchanged on the
acceptance seeds (no model calls at evaluation time).

    uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ../ASPIRE \
        --demospec data/demospecs/hurobo_233832.json --out data/runs/demo_vs_nodemo_01

All model calls are cached and logged; --token-budget is a hard cap.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from ants.adversary.rollout import CapHarness, feedback
from ants.contracts import CaseSpec, to_json
from ants.synthesizer.generator import build_messages, extract_code, repair_message
from ants.synthesizer.llm import BudgetExceeded, ChatClient, load_dotenv

EXAMPLE = "examples/libero/object_swap_seed1.py"
EXAMPLE_TASK = "pick up the alphabet soup and place it in the basket"


def run_sample(
    arm: str,
    sample: int,
    temperature: float,
    args: argparse.Namespace,
    client: ChatClient,
    harness: CapHarness,
    demo_summary: dict | None,
) -> dict:
    out = args.out / arm / f"sample{sample}"
    out.mkdir(parents=True, exist_ok=True)
    api_ref = (args.aspire / "docs" / "api-reference.md").read_text(encoding="utf-8")
    example = (args.aspire / EXAMPLE).read_text(encoding="utf-8")
    messages = build_messages(api_ref, example, EXAMPLE_TASK, args.task, demo_summary)
    record: dict = {"arm": arm, "sample": sample, "temperature": temperature, "attempts": []}
    debug_case = CaseSpec(
        f"debug-{args.debug_seed}", args.suite, args.task_id, args.debug_seed, "acceptance"
    )
    program = None
    for attempt in range(args.repairs + 1):
        try:
            reply = client.chat(
                messages, temperature=temperature, tag=f"{arm}/s{sample}/a{attempt}"
            )
        except BudgetExceeded as err:
            record["stopped"] = str(err)
            break
        program = out / f"program_attempt{attempt}.py"
        program.write_text(extract_code(reply.text), encoding="utf-8")
        trace = harness.run(
            debug_case, program, out / f"debug_attempt{attempt}", f"{arm}-s{sample}-a{attempt}"
        )
        record["attempts"].append(
            {"attempt": attempt, "tokens": reply.prompt_tokens + reply.completion_tokens,
             "from_cache": reply.from_cache, "trace": json.loads(to_json(trace))}
        )  # fmt: skip
        print(
            f"[{arm} s{sample} a{attempt}] success={trace.task_success} "
            f"reason={trace.termination_reason}",
            flush=True,
        )
        if trace.task_success or attempt == args.repairs or not trace.run_dir:
            break
        messages = [
            *messages,
            {"role": "assistant", "content": reply.text},
            repair_message(feedback(Path(trace.run_dir))),
        ]
    record["evaluation"] = []
    if program is not None:
        for seed in args.eval_seeds:
            case = CaseSpec(f"eval-{seed}", args.suite, args.task_id, seed, "acceptance")
            trace = harness.run(case, program, out / f"eval_seed{seed}", f"{arm}-s{sample}-final")
            record["evaluation"].append(json.loads(to_json(trace)))
            print(f"[{arm} s{sample} eval {seed}] success={trace.task_success}", flush=True)
    (out / "record.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    return record


def summarise(records: list[dict]) -> str:
    lines = [
        "| Arm | Sample | Debug attempts | Solved debug seed | Eval success | Tokens (uncached) |",
        "|---|---|---|---|---|---|",
    ]
    for r in records:
        evals = r.get("evaluation", [])
        ok = sum(1 for e in evals if e["task_success"])
        solved = any(a["trace"]["task_success"] for a in r["attempts"])
        tokens = sum(a["tokens"] for a in r["attempts"] if not a["from_cache"])
        lines.append(
            f"| {r['arm']} | {r['sample']} | {len(r['attempts'])} | {'yes' if solved else 'no'} "
            f"| {ok}/{len(evals)} | {tokens} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--aspire", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--demospec", type=Path, required=True)
    p.add_argument("--arms", default="nodemo,demo")
    p.add_argument("--temperatures", default="0.2,0.7", help="one sample per temperature")
    p.add_argument("--suite", default="libero_goal_swap")
    p.add_argument("--task-id", type=int, default=8)
    p.add_argument("--task", default="put the bowl on the plate")
    p.add_argument("--debug-seed", type=int, default=51)
    p.add_argument("--eval-seeds", default="51,52,53,54,55")
    p.add_argument("--repairs", type=int, default=2)
    p.add_argument("--model", default="muse-wonder-1.0")
    p.add_argument("--token-budget", type=int, default=600_000)
    args = p.parse_args(argv)
    args.eval_seeds = [int(s) for s in args.eval_seeds.split(",")]
    args.aspire = args.aspire.resolve()
    args.out = args.out.resolve()
    load_dotenv(Path(".env"))

    client = ChatClient(
        args.model, Path("data/llm_cache"), Path("data/llm_ledger.jsonl"), args.token_budget
    )
    harness = CapHarness(args.aspire)
    demo = json.loads(args.demospec.read_text(encoding="utf-8"))["summary"]
    (args.out).mkdir(parents=True, exist_ok=True)
    (args.out / "config.json").write_text(
        json.dumps(
            {k: str(v) for k, v in vars(args).items()}
            | {"started": time.strftime("%Y-%m-%dT%H:%M:%S")},
            indent=1,
        ),
        encoding="utf-8",
    )
    records = []
    temps = [float(t) for t in args.temperatures.split(",")]
    for sample, temp in enumerate(temps):
        for arm in args.arms.split(","):
            records.append(
                run_sample(
                    arm, sample, temp, args, client, harness, demo if arm == "demo" else None
                )
            )
            (args.out / "summary.md").write_text(summarise(records), encoding="utf-8")
    print(summarise(records))
    print(f"tokens spent (ledger, uncached): {client.spent()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
