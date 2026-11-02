"""Experiment: does one demonstration help the generator write a working program?

Arms differ only in the demonstration section of the prompt (Q1 in
docs/synthesizer/discussion.md). Per arm and sample: write a program, run it on a debug seed,
repair it from text feedback up to N times, then evaluate the final program unchanged on the
acceptance seeds (no model calls at evaluation time).

    uv run python -m ants.orchestrator.demo_vs_nodemo --aspire ../ASPIRE \
        --demospec data/demospecs/hurobo_233832.json --out data/runs/demo_vs_nodemo_01

All model calls are cached and logged; --token-budget is a hard cap on new tokens per run.
Every program, reply, prompt, feedback, program diff and event is written to the run directory;
view it with `uv run python -m ants.evalkit.report <run dir>`.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from ants.adversary.rollout import CapHarness, feedback
from ants.contracts import CaseSpec, to_json
from ants.evalkit.contacts import analyse, evidence_text
from ants.evalkit.runlog import RunLog, unified_diff
from ants.synthesizer.generator import build_messages, extract_code, repair_message
from ants.synthesizer.llm import BudgetExceeded, ChatClient, load_dotenv

EXAMPLE = "examples/libero/object_swap_seed1.py"
EXAMPLE_TASK = "pick up the alphabet soup and place it in the basket"
# hurobo E1 real size vs stock LIBERO bowl and plate (smoke-2026-10-31.md)
REAL_SIZE = {"akita_black_bowl_1_main": 1.227, "plate_1_main": 1.855}


def run_sample(
    arm: str,
    sample: int,
    temperature: float,
    args: argparse.Namespace,
    client: ChatClient,
    harnesses: dict[str, CapHarness],
    demo_summary: dict | None,
    log: RunLog,
) -> dict:
    out = args.out / arm / f"sample{sample}"
    out.mkdir(parents=True, exist_ok=True)
    rel = f"{arm}/sample{sample}"
    api_ref = (args.aspire / "docs" / "api-reference.md").read_text(encoding="utf-8")
    example = (args.aspire / EXAMPLE).read_text(encoding="utf-8")
    scene_text = None
    if args.scene_text_file:
        scene_text = args.scene_text_file.read_text(encoding="utf-8").strip()
    messages = build_messages(
        api_ref, example, EXAMPLE_TASK, args.task, demo_summary, scene_context=scene_text
    )
    record: dict = {"arm": arm, "sample": sample, "temperature": temperature, "attempts": []}
    debug_case = CaseSpec(
        f"debug-{args.debug_seed}", args.suite, args.task_id, args.debug_seed, "acceptance"
    )
    log.event("sample_start", arm=arm, sample=sample, temperature=temperature)
    program = previous_text = None
    for attempt in range(args.repairs + 1):
        role = "initial" if attempt == 0 else "repair"
        try:
            reply = client.chat(
                messages, temperature=temperature, tag=f"{arm}/s{sample}/a{attempt}"
            )
        except BudgetExceeded as err:
            record["stopped"] = str(err)
            log.event("budget_stop", arm=arm, sample=sample, attempt=attempt, reason=str(err))
            break
        tokens = reply.prompt_tokens + reply.completion_tokens
        log.write_json(f"{rel}/messages_attempt{attempt}.json", messages)
        log.write(f"{rel}/reply_attempt{attempt}.md", reply.text)
        log.write_json(f"{rel}/api_response_attempt{attempt}.json", reply.raw)
        text = extract_code(reply.text)
        program = log.write(f"{rel}/program_attempt{attempt}.py", text)
        diff = ""
        if previous_text is not None:
            diff = unified_diff(previous_text, text, f"attempt{attempt - 1}", f"attempt{attempt}")
            log.write(f"{rel}/diff_attempt{attempt}.diff", diff)
        previous_text = text
        log.event(
            "program", arm=arm, sample=sample, attempt=attempt, role=role, tokens=tokens,
            reasoning_tokens=reply.reasoning_tokens,
            from_cache=reply.from_cache, lines=len(text.splitlines()),
            diff_lines=len(diff.splitlines()),
        )  # fmt: skip
        harness = harnesses[args.debug_scene]
        contacts = out / f"debug_attempt{attempt}" / "contacts.jsonl"
        if args.contacts:
            harness.scene = {**(harness.scene or {}), "contacts": {"path": str(contacts)}}
        trace = harness.run(
            debug_case, program, out / f"debug_attempt{attempt}", f"{arm}-s{sample}-a{attempt}"
        )
        analysis = None
        if args.contacts and trace.run_dir:
            try:
                dump = json.loads(contacts.with_name("contacts_scene.json").read_text("utf-8"))
                analysis = analyse(
                    contacts, Path(trace.run_dir), dump, tuple(dump["bodies"]["robot0_base"]["pos"])
                )
            except Exception as err:  # keep the run going; the evidence is optional
                log.event("contact_analysis_failed", arm=arm, attempt=attempt, error=str(err)[:200])
        record["attempts"].append(
            {"attempt": attempt, "role": role, "tokens": tokens,
             "from_cache": reply.from_cache, "trace": json.loads(to_json(trace)),
             "blocking": [(e["part"], e["object"], e["n_steps"]) for e in analysis["blocking"]]
             if analysis else None,
             "clean_success": bool(trace.task_success and analysis and not analysis["blocking"])}
        )  # fmt: skip
        log.event(
            "rollout", arm=arm, sample=sample, attempt=attempt, seed=args.debug_seed,
            success=trace.task_success, reason=trace.termination_reason, wall_s=trace.wall_s,
        )  # fmt: skip
        print(
            f"[{arm} s{sample} a{attempt}] success={trace.task_success} "
            f"reason={trace.termination_reason}",
            flush=True,
        )
        if trace.task_success or attempt == args.repairs or not trace.run_dir:
            break
        fb = feedback(Path(trace.run_dir))
        log.write_json(f"{rel}/feedback_attempt{attempt}.json", fb)
        log.event("feedback", arm=arm, sample=sample, attempt=attempt, keys=sorted(fb))
        repair = repair_message(fb, args.explain)
        if args.evidence == "e3" and analysis:
            base_z = dump["bodies"]["robot0_base"]["pos"][2]
            parts = ["Evidence from the simulator for this failed run:",
                     evidence_text(analysis, dump, base_z, 3)]  # fmt: skip
            if scene_text:
                parts += ["", scene_text]
            repair = {**repair, "content": repair["content"] + "\n\n" + "\n".join(parts)}
            log.write(f"{rel}/evidence_attempt{attempt}.txt", "\n".join(parts))
        messages = [*messages, {"role": "assistant", "content": reply.text}, repair]
    record["evaluation"] = []
    if program is not None:
        for scene, harness in harnesses.items():
            for seed in args.eval_seeds:
                case = CaseSpec(
                    f"eval-{scene}-{seed}", args.suite, args.task_id, seed, "acceptance"
                )
                trace = harness.run(
                    case, program, out / f"eval_{scene}_seed{seed}", f"{arm}-s{sample}-final"
                )
                record["evaluation"].append({"scene": scene, **json.loads(to_json(trace))})
                log.event(
                    "eval", arm=arm, sample=sample, scene=scene, seed=seed,
                    success=trace.task_success, reason=trace.termination_reason,
                )  # fmt: skip
                print(
                    f"[{arm} s{sample} eval {scene} {seed}] success={trace.task_success}",
                    flush=True,
                )
    log.write_json(f"{rel}/record.json", record)
    log.event("sample_end", arm=arm, sample=sample, spent_total=client.spent())
    return record


def reevaluate(args: argparse.Namespace, harnesses: dict[str, CapHarness], log: RunLog) -> list:
    """Re-score the final program of every finished sample in the chosen scenes (no model calls)."""
    records = []
    for rec_path in sorted(args.out.glob("*/sample*/record.json")):
        record = json.loads(rec_path.read_text(encoding="utf-8"))
        sample_dir = rec_path.parent
        last = record["attempts"][-1]["attempt"]
        program = sample_dir / f"program_attempt{last}.py"
        scenes = [s for s in harnesses if s != "stock" or args.scenes == "stock"]
        record["evaluation"] = [e for e in record["evaluation"] if e.get("scene") not in scenes]
        for scene in scenes:
            for seed in args.eval_seeds:
                case = CaseSpec(
                    f"eval-{scene}-{seed}", args.suite, args.task_id, seed, "acceptance"
                )
                tag = f"{record['arm']}-s{record['sample']}-final"
                trace = harnesses[scene].run(
                    case, program, sample_dir / f"eval_{scene}_seed{seed}", tag
                )
                record["evaluation"].append({"scene": scene, **json.loads(to_json(trace))})
                log.event(
                    "reeval", arm=record["arm"], sample=record["sample"], scene=scene, seed=seed,
                    success=trace.task_success, reason=trace.termination_reason,
                )  # fmt: skip
                print(f"[{record['arm']} s{record['sample']} reeval {scene} {seed}] "
                      f"success={trace.task_success}", flush=True)  # fmt: skip
        rec_path.write_text(json.dumps(record, indent=1), encoding="utf-8")
        records.append(record)
    return records


def summarise(records: list[dict]) -> str:
    scenes = sorted({e.get("scene", "stock") for r in records for e in r.get("evaluation", [])})
    head = "| Arm | Sample | T | Debug attempts | Solved debug seed |"
    head += "".join(f" Eval {s} |" for s in scenes) + " Tokens (uncached) |"
    lines = [head, "|" + "---|" * (5 + len(scenes) + 1)]
    for r in records:
        evals = r.get("evaluation", [])
        solved = any(a["trace"]["task_success"] for a in r["attempts"])
        tokens = sum(a["tokens"] for a in r["attempts"] if not a["from_cache"])
        cells = []
        for s in scenes:
            es = [e for e in evals if e.get("scene", "stock") == s]
            cells.append(f"{sum(1 for e in es if e['task_success'])}/{len(es)}")
        lines.append(
            f"| {r['arm']} | {r['sample']} | {r['temperature']} | {len(r['attempts'])} "
            f"| {'yes' if solved else 'no'} | " + " | ".join(cells) + f" | {tokens} |"
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
    p.add_argument("--temperatures", default="0.2,0.7,0.5,1.0", help="one sample per temperature")
    p.add_argument("--suite", default="libero_goal_swap")
    p.add_argument("--task-id", type=int, default=8)
    p.add_argument("--task", default="put the bowl on the plate")
    p.add_argument("--debug-seed", type=int, default=51)
    p.add_argument("--eval-seeds", default="51,52,53,54,55", help="empty string: no evaluation")
    p.add_argument("--repairs", type=int, default=4)
    p.add_argument(
        "--explain", action="store_true",
        help="repair replies start with a 'WHY:' rationale (the API returns no reasoning text)",
    )  # fmt: skip
    p.add_argument(
        "--scene-text-file", type=Path, default=None,
        help="scene description (e.g. S4) added to the first prompt and to every repair",
    )  # fmt: skip
    p.add_argument(
        "--evidence", default="none", choices=["none", "e3"],
        help="e3: repair message adds the contact log, the scene text and the stall readings",
    )  # fmt: skip
    p.add_argument(
        "--contacts", action="store_true",
        help="log simulator contacts per attempt (evaluation only unless --evidence is set)",
    )  # fmt: skip
    p.add_argument(
        "--planner", default="default", choices=["default", "curobo-sam3", "curobo-sim"],
        help="curobo-sam3: cuRobo on the depth cloud, robot masked by SAM 3; curobo-sim: robot "
        "masked by the simulator (digital twin)",
    )  # fmt: skip
    p.add_argument(
        "--ontop-area", type=float, default=None,
        help="'bowl on plate' passes when this share of the bowl footprint lies inside the plate",
    )  # fmt: skip
    p.add_argument("--model", default="muse-wonder-1.0")
    p.add_argument(
        "--token-budget", type=int, default=600_000,
        help="hard cap on NEW (uncached) tokens in this run; earlier ledger spend is not counted",
    )  # fmt: skip
    p.add_argument("--usd-per-mtok", type=float, default=13.5, help="for the cost estimate only")
    p.add_argument(
        "--scenes",
        default="stock,scaled",
        help="scenes each final program is evaluated in",
    )
    p.add_argument(
        "--debug-scene", default="stock", choices=["stock", "scaled"],
        help="scene where programs are debugged and repaired (scaled: grown on-top tolerance)",
    )  # fmt: skip
    p.add_argument("--scale-json", default=json.dumps(REAL_SIZE), help="body name -> scale factor")
    p.add_argument(
        "--eval-only", action="store_true",
        help="no generation: re-score the final programs of an existing --out run in --scenes",
    )  # fmt: skip
    args = p.parse_args(argv)
    args.eval_seeds = [int(s) for s in args.eval_seeds.split(",") if s.strip()]
    args.aspire = args.aspire.resolve()
    args.out = args.out.resolve()
    load_dotenv(Path(".env"))

    client = ChatClient(args.model, Path("data/llm_cache"), Path("data/llm_ledger.jsonl"), 10**12)
    base_spent = client.spent()
    client.token_budget = base_spent + args.token_budget
    launcher = Path(__file__).resolve().parents[3] / "tools" / "aspire_launch.py"
    extra: dict = {}
    if args.planner != "default":
        extra["planner"] = {"mode": args.planner, "exclude_radius_m": 0.12}
    if args.ontop_area is not None:
        extra["ontop"] = {"rule": "area", "min_fraction": args.ontop_area}
    if args.evidence != "none":
        args.contacts = True
    harnesses = {}
    for scene in args.scenes.split(","):
        if scene == "stock":
            harnesses[scene] = CapHarness(args.aspire)
        elif scene == "scaled":
            harnesses[scene] = CapHarness(
                args.aspire,
                launcher=launcher,
                scene={"scale": {"bodies": json.loads(args.scale_json)}, **extra},
            )
        else:
            raise SystemExit(f"unknown scene {scene!r} (stock, scaled)")
    harnesses.setdefault("stock", CapHarness(args.aspire))
    if args.debug_scene not in harnesses:
        raise SystemExit(f"--debug-scene {args.debug_scene!r} must be one of --scenes")
    log = RunLog(args.out)
    if args.eval_only:
        records = reevaluate(args, harnesses, log)
        (args.out / "summary.md").write_text(summarise(records), encoding="utf-8")
        print(summarise(records))
        return 0
    demo = json.loads(args.demospec.read_text(encoding="utf-8"))["summary"]
    log.write_json(
        "config.json",
        {k: str(v) for k, v in vars(args).items()}
        | {"started": time.strftime("%Y-%m-%dT%H:%M:%S"), "ledger_spent_at_start": base_spent,
           "scenes": {k: h.scene for k, h in harnesses.items()}},
    )  # fmt: skip
    log.event(
        "run_start", token_budget=args.token_budget, usd_per_mtok=args.usd_per_mtok,
        model=args.model, ledger_spent_at_start=base_spent,
    )  # fmt: skip
    records = []
    temps = [float(t) for t in args.temperatures.split(",")]
    for sample, temp in enumerate(temps):
        for arm in args.arms.split(","):
            if any(r.get("stopped") for r in records):
                break  # the budget is used up; do not start new samples
            done = args.out / arm / f"sample{sample}" / "record.json"
            prior = json.loads(done.read_text(encoding="utf-8")) if done.exists() else None
            if prior is not None and not prior.get("stopped"):
                records.append(prior)  # resumed run: a finished sample is kept, not redone
                continue
            records.append(
                run_sample(
                    arm, sample, temp, args, client, harnesses, demo if arm == "demo" else None, log
                )
            )
            (args.out / "summary.md").write_text(summarise(records), encoding="utf-8")
    new_tokens = client.spent() - base_spent
    log.event(
        "run_end", new_tokens=new_tokens, usd_est=round(new_tokens / 1e6 * args.usd_per_mtok, 2)
    )
    print(summarise(records))
    print(
        f"new tokens this run: {new_tokens} (cap {args.token_budget}); "
        f"ledger total {client.spent()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
