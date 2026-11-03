"""Experiment: which description of the scene helps the generator, and which contact evidence helps a repair?

G: the FIRST program is written with a different scene section in the prompt (S0 none, S1 object
positions only, S2 + extents, S3 + relation graph, S4 combination of shapes, graph and hand, SP the
same as S4 with the wine rack's position wrong on purpose). Each is tried in scene levels L1 to L3.
E: ONE repair of a failed program (exp03, clip 233859, attempt 2) with different evidence in the
repair message (E0 as in exp03, E1 + contact log, E2 + scene, E3 + stall readings, EP placebo).

    uv run python -m ants.orchestrator.scene_context_exp --aspire ASPIRE --out data/runs/exp04_scene --prep
    uv run python -m ants.orchestrator.scene_context_exp --aspire ASPIRE --out data/runs/exp04_scene --dry-run
    uv run python -m ants.orchestrator.scene_context_exp --aspire ASPIRE --out data/runs/exp04_scene

The scene given to the model is simulator truth ("oracle"), not a perceived scene. Everything is
cached and logged; `--token-budget` is a hard cap on NEW tokens. View: `ants.evalkit.report`.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from ants.adversary.collision_world import describe, load_world, view
from ants.contracts import CaseSpec, Split, to_dict
from ants.evalkit.aspire_harness import CapHarness, feedback
from ants.evalkit.contacts import analyse, evidence_text, shifted_evidence
from ants.evalkit.runlog import RunLog, unified_diff
from ants.orchestrator.demo_vs_nodemo import EXAMPLE, EXAMPLE_TASK, REAL_SIZE
from ants.synthesizer.generator import build_messages, extract_code
from ants.synthesizer.llm import BudgetExceeded, ChatClient, load_dotenv

# Placebo: the text puts the wine rack where it stands in ANOTHER level (wrong on purpose).
PLACEBO_SHIFT = {"L1": (0.38, 0.40), "L2": (-0.38, -0.40), "L3": (-0.38, -0.40)}
EXP03 = Path("data/runs/exp03_explain/clip_233859/demo/sample0")
EVIDENCE = Path("data/evidence/exp03_233859_a2_v2")
G_VARIANTS = {
    "S0": ("none", None),
    "S1": ("positions only", "positions"),
    "S2": ("+ extents", "extents"),
    "S3": ("+ relation graph", "graph"),
    "S4": ("combination", "combo"),
    "SP": ("placebo (rack misplaced)", "combo"),
}
E_VARIANTS = {
    "E0": "feedback as in exp03",
    "E1": "+ contact log",
    "E2": "+ contact log + scene",
    "E3": "+ contact log + scene + stall readings",
    "EP": "placebo: E2 with the rack and contact misplaced",
}
EXPERIMENT = {
    "title": "Scene context for the generator (exp04)",
    "summary": (
        "A robot program for 'put the bowl on the plate' stalled when the gripper hand pressed on a "
        "wine rack that the program never looked at (exp03, clip 233859, attempt 2; the simulator's "
        "contact log shows it, and removing the rack's collision made all calls succeed). This run "
        "asks which description of the scene, given to the model, helps most: in the FIRST program (G) "
        "and in ONE repair after a stall (E). The scene given is simulator truth, so this measures how "
        "useful a representation is, not whether perception can produce it."
    ),
    "question": "Which representation of the scene (positions, extents, relation graph, shapes) makes the model write programs that keep the hand clear, and does contact evidence improve a repair?",
    "variants": {
        "S0": [
            "none",
            "The prompt of exp03 (task, demonstration, API reference, example): no scene section. The baseline; its replies are reused from exp03.",
        ],
        "S1": [
            "positions only",
            "Adds a list of the objects and the centre of each, in the robot_base frame.",
        ],
        "S2": ["+ extents", "S1 plus the size (x, y, z) of each object."],
        "S3": [
            "+ relation graph",
            "S2 plus the relations between objects: which touch, and the nearest distance (mm) between close pairs, from the simulator.",
        ],
        "S4": [
            "combination",
            "S3 with shapes: a radius-by-height profile for the round bowl and plate, the individual boxes of the wine rack, and a description of the gripper hand (about 21 x 10 cm, underside 3 cm above the TCP).",
        ],
        "SP": [
            "placebo",
            "S4 with the wine rack listed where it stands in a different level (wrong on purpose). Same length and format.",
        ],
        "E0": [
            "feedback as in exp03",
            "The repair message of exp03 for attempt 2: the program's own report and the failed calls. The reply is reused from exp03.",
        ],
        "E1": [
            "+ contact log",
            "E0 plus the simulator's contact log: which gripper part pressed on which object, for how many steps, with what force, at which point.",
        ],
        "E2": ["+ scene", "E1 plus the S4 scene description."],
        "E3": [
            "+ stall readings",
            "E2 plus the TCP height while blocked next to the contact height, and a note that no other part was blocked and no joint was at its limit.",
        ],
        "EP": [
            "placebo",
            "E3 with the rack and the contact point moved to another position (wrong on purpose).",
        ],
    },
    "glossary": [
        ["G", "experiment on the first program: only the scene section of the prompt changes"],
        ["E", "experiment on one repair: only the evidence in the repair message changes"],
        [
            "S0 to S4, SP",
            "G variants: none, positions, + extents, + relation graph, combination, placebo",
        ],
        [
            "E0 to E3, EP",
            "E variants: exp03 feedback, + contact log, + scene, + stall readings, placebo",
        ],
        [
            "L1 to L3",
            "scene levels: standard scene, then harder scenes built from the working path",
        ],
        [
            "P0, P1, P5",
            "shape levels: one box per object, radius profile for round objects, spheres (bubbles)",
        ],
        [
            "TCP",
            "tool centre point: the point between the fingertips, the position programs command",
        ],
        ["robot_base frame", "x forward, y left, z up, metres, origin at the robot base"],
        ["oracle", "taken from the simulator, not estimated from camera images"],
        [
            "placebo",
            "same format but wrong content, to see whether the model uses content or just extra text",
        ],
        ["stall", "a move_to_pose call that timed out; the arm did not reach its target"],
        [
            "blocking contact",
            "contact between a robot part and an object that is not the grasped bowl, lasting at least 10 steps with at least 5 N",
        ],
        [
            "tokens",
            "prompt + output tokens; reasoning tokens are the part of the output spent thinking",
        ],
    ],
    "how_to_read": [
        "Results: one row per variant, one column per scene level. A green cell means the task succeeded; the numbers are stalled calls and steps of blocking contact.",
        "Scene: top-down and side view of a level, with object shapes, relations, the arm as cuRobo's 61 spheres, the path of a chosen run and the contact events.",
        "Samples (left): the full prompt, reply, program and rollout of every run.",
    ],
    "caveats": [
        "One run per cell at temperature 0.2: a difference between two cells can be luck. Read the pattern across rows and levels, not one cell.",
        "The scene text is oracle (simulator) geometry. A perceived scene will be less exact.",
        "Hardened levels are not proven solvable; if every variant fails there, that level says little.",
        "Only the wine rack's relation to the hand is checked automatically; other failure causes show up as 'no blocking contact'.",
    ],
}


def load_levels(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def scene_spec(level: dict, contacts: Path) -> dict:
    spec: dict = {"scale": {"bodies": REAL_SIZE}, "contacts": {"path": str(contacts)}}
    pose = {k: level[k] for k in ("offsets_m", "body_offsets_m") if level.get(k)}
    if pose:
        spec["pose"] = pose
    return spec


def prep_levels(args: argparse.Namespace, levels: dict) -> None:
    """Run a do-nothing program in every level so the launcher dumps the settled scene."""
    noop = Path("data/scenes/noop_program.py").resolve()
    for name, level in levels.items():
        out = Path("data/scenes").resolve() / name
        harness = CapHarness(
            args.aspire,
            launcher=Path("tools/aspire_launch.py").resolve(),
            scene=scene_spec(level, out / "contacts.jsonl"),
        )
        harness.run(
            CaseSpec(f"dump-{name}", args.suite, args.task_id, args.debug_seed, Split.ACCEPTANCE),
            noop,
            out / "run",
            "dump",
        )
        world = load_world(json.loads((out / "contacts_scene.json").read_text(encoding="utf-8")))
        print(name, "->", out, "objects:", [o.label for o in world.objects])


def scene_for(name: str) -> dict:
    return json.loads(
        (Path("data/scenes") / name / "contacts_scene.json").read_text(encoding="utf-8")
    )


def g_scene_text(variant: str, level: str) -> str | None:
    kind = G_VARIANTS[variant][1]
    if kind is None:
        return None
    world = load_world(scene_for(level))
    if variant == "SP":
        world = world.shifted("wine rack", *PLACEBO_SHIFT[level])
    return describe(world, kind)


def e_messages(variant: str) -> list[dict]:
    base = json.loads((EXP03 / "messages_attempt3.json").read_text(encoding="utf-8"))
    if variant == "E0":
        return base
    scene = scene_for("L1")
    base_z = scene["bodies"]["robot0_base"]["pos"][2]
    analysis = analyse(
        EVIDENCE / "contacts.jsonl",
        next((EVIDENCE / "run").rglob("outcome.json")).parent,
        json.loads((EVIDENCE / "contacts_scene.json").read_text(encoding="utf-8")),
        tuple(scene["bodies"]["robot0_base"]["pos"]),
    )
    world = load_world(scene)
    if variant == "EP":
        analysis = shifted_evidence(analysis, *PLACEBO_SHIFT["L1"])
        world = world.shifted("wine rack", *PLACEBO_SHIFT["L1"])
    level = 3 if variant in ("E3", "EP") else 1
    parts = [
        "Evidence from the simulator for this failed run:",
        evidence_text(analysis, scene, base_z, level),
    ]
    if variant != "E1":
        parts += ["", describe(world, "combo")]
    last = dict(base[-1])
    last["content"] = last["content"] + "\n\n" + "\n".join(parts)
    return [*base[:-1], last]


def write_attempt(
    sample_dir: Path, rel: str, log: RunLog, messages: list[dict], reply, prev: str | None
) -> tuple[Path, str]:
    log.write_json(f"{rel}/messages_attempt0.json", messages)
    log.write(f"{rel}/reply_attempt0.md", reply.text)
    log.write_json(f"{rel}/api_response_attempt0.json", reply.raw)
    text = extract_code(reply.text)
    program = log.write(f"{rel}/program_attempt0.py", text)
    if prev is not None:
        log.write(
            f"{rel}/diff_attempt0.diff", unified_diff(prev, text, "exp03 attempt 2", "this run")
        )
    return program, text


def run_case(
    args,
    client,
    log,
    group: str,
    variant: str,
    level_name: str,
    level: dict,
    sample: int,
    messages: list[dict],
    prev: str | None,
) -> dict:
    arm = f"{group}-{variant}"
    rel = f"{arm}/sample{sample}"
    sample_dir = args.out / rel
    sample_dir.mkdir(parents=True, exist_ok=True)
    rec_path = sample_dir / "record.json"
    if rec_path.exists():
        prior = json.loads(rec_path.read_text(encoding="utf-8"))
        if not prior.get("stopped"):
            return prior
    record: dict = {
        "arm": arm,
        "sample": sample,
        "temperature": args.temperature,
        "attempts": [],
        "evaluation": [],
    }
    record["exp"] = {"group": group, "variant": variant, "level": level_name}
    try:
        reply = client.chat(messages, temperature=args.temperature, tag=f"{arm}/{level_name}")
    except BudgetExceeded as err:
        record["stopped"] = str(err)
        log.event("budget_stop", arm=arm, level=level_name, reason=str(err))
        return record
    program, text = write_attempt(sample_dir, rel, log, messages, reply, prev)
    contacts = sample_dir / "contacts.jsonl"
    harness = CapHarness(
        args.aspire,
        launcher=Path("tools/aspire_launch.py").resolve(),
        scene=scene_spec(level, contacts),
    )
    case = CaseSpec(
        f"debug-{args.debug_seed}", args.suite, args.task_id, args.debug_seed, Split.ACCEPTANCE
    )
    for _try in range(3):  # a local-service timeout or crash is retried, never fatal
        try:
            trace = harness.run(case, program, sample_dir / "debug_attempt0", f"{arm}-{level_name}")
        except Exception as err:
            log.event("harness_exception", arm=arm, level=level_name, error=str(err)[:300])
            continue
        if trace.termination_reason != "harness_error":
            break
        log.event("harness_retry", arm=arm, level=level_name, error=(trace.error or "")[:300])
    else:
        raise RuntimeError(f"harness failed 3 times for {arm} {level_name}")
    tokens = reply.prompt_tokens + reply.completion_tokens
    role = "initial" if group == "G" else "repair"
    record["attempts"].append(
        {
            "attempt": 0,
            "role": role,
            "tokens": tokens,
            "from_cache": reply.from_cache,
            "trace": to_dict(trace),
        }
    )
    summary: dict = {}
    try:
        summary = _analyse_case(trace, contacts, sample_dir, level_name, rel, log)
    except Exception as err:  # keep the run; record that the contact analysis failed
        summary = {"analysis_error": f"{type(err).__name__}: {err}"[:300]}
    head = reply.text.split("```", 1)[0]
    reasoning_text = text if group == "G" else head
    summary["mentions_rack"] = bool(re.search(r"rack", reasoning_text, re.I))
    summary["reasoning_tokens"] = reply.reasoning_tokens
    summary["completion_tokens"] = reply.completion_tokens
    record["exp"]["summary"] = summary
    log.write_json(f"{rel}/record.json", record)
    log.event(
        "case", arm=arm, level=level_name, success=trace.task_success, reason=trace.termination_reason,
        failed_calls=len(summary.get("failed_calls", [])), blocked_steps=summary.get("blocked_steps"),
        tokens=tokens, reasoning_tokens=reply.reasoning_tokens, from_cache=reply.from_cache,
    )  # fmt: skip
    print(
        f"[{arm} {level_name}] success={trace.task_success} stalls={len(summary.get('failed_calls', []))} blocked_steps={summary.get('blocked_steps')} tokens={tokens} (cached={reply.from_cache})",
        flush=True,
    )
    return record


def _analyse_case(
    trace, contacts: Path, sample_dir: Path, level_name: str, rel: str, log: RunLog
) -> dict:
    if not (trace.run_dir and contacts.exists()):
        return {}
    dump = sample_dir / "contacts_scene.json"
    scene = json.loads(dump.read_text(encoding="utf-8")) if dump.exists() else scene_for(level_name)
    a = analyse(contacts, Path(trace.run_dir), scene, tuple(scene["bodies"]["robot0_base"]["pos"]))
    (sample_dir / "overlay.json").write_text(json.dumps(a.pop("overlay")), encoding="utf-8")
    if not trace.task_success:
        log.write_json(f"{rel}/feedback_attempt0.json", feedback(Path(trace.run_dir)))
    return a


def write_scenes(args, levels: dict) -> None:
    traj = json.loads(Path("data/scenes/success_trajectory.json").read_text(encoding="utf-8"))
    for name, level in levels.items():
        scene = scene_for(name)
        world = load_world(scene)
        data = {
            "name": name,
            "title": level["title"],
            "desc": level["desc"],
            "base": scene["bodies"]["robot0_base"]["pos"],
            "view": view(world),
            "reference_path": traj["points"],
        }
        (args.out / "scenes").mkdir(parents=True, exist_ok=True)
        (args.out / "scenes" / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--aspire", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--demospec", type=Path, default=Path("data/demospecs/hurobo_233859.json"))
    p.add_argument("--levels-file", type=Path, default=Path("data/scenes/levels.json"))
    p.add_argument("--levels", default="L1,L2,L3")
    p.add_argument("--g-variants", default="S0,S1,S2,S3,S4,SP")
    p.add_argument("--e-variants", default="E0,E1,E2,E3,EP")
    p.add_argument("--groups", default="G,E")
    p.add_argument("--suite", default="libero_goal_swap")
    p.add_argument("--task-id", type=int, default=8)
    p.add_argument("--task", default="put the bowl on the plate")
    p.add_argument("--debug-seed", type=int, default=51)
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--model", default="muse-wonder-1.0")
    p.add_argument(
        "--token-budget", type=int, default=900_000, help="hard cap on NEW tokens in this run"
    )
    p.add_argument("--usd-per-mtok", type=float, default=13.5, help="for the cost estimate only")
    p.add_argument(
        "--prep", action="store_true", help="dump the settled scene of every level, then stop"
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="write the prompts and stop; no model call, no simulation",
    )
    args = p.parse_args(argv)
    args.aspire, args.out = args.aspire.resolve(), args.out.resolve()
    load_dotenv(Path(".env"))
    levels = load_levels(args.levels_file)
    if args.prep:
        prep_levels(args, levels)
        return 0
    names = args.levels.split(",")
    log = RunLog(args.out)
    api_ref = (args.aspire / "docs" / "api-reference.md").read_text(encoding="utf-8")
    example = (args.aspire / EXAMPLE).read_text(encoding="utf-8")
    demo = json.loads(args.demospec.read_text(encoding="utf-8"))["summary"]
    prev_program = (EXP03 / "program_attempt2.py").read_text(encoding="utf-8")
    jobs: list[tuple] = []
    for lv in names:
        for v in args.g_variants.split(","):
            if "G" in args.groups.split(","):
                text = g_scene_text(v, lv)
                msgs = build_messages(
                    api_ref, example, EXAMPLE_TASK, args.task, demo, scene_context=text
                )
                jobs.append(("G", v, lv, names.index(lv), msgs, None))
    if "E" in args.groups.split(","):
        for v in args.e_variants.split(","):
            jobs.append(("E", v, "L1", 0, e_messages(v), prev_program))
    if args.dry_run:
        (args.out / "prompts").mkdir(parents=True, exist_ok=True)
        for g, v, lv, _, msgs, _ in jobs:
            text = msgs[-1]["content"] if g == "E" else msgs[1]["content"]
            (args.out / "prompts" / f"{g}-{v}-{lv}.txt").write_text(text, encoding="utf-8")
            print(f"{g}-{v}-{lv}: {len(text.split())} words in the changing part")
        return 0
    client = ChatClient(args.model, Path("data/llm_cache"), Path("data/llm_ledger.jsonl"), 10**12)
    base_spent = client.spent()
    client.token_budget = base_spent + args.token_budget
    config = {k: str(v) for k, v in vars(args).items()} | {
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "ledger_spent_at_start": base_spent,
        "usd_per_mtok": args.usd_per_mtok, "experiment": EXPERIMENT,
        "levels": levels, "g_variants": {k: v[0] for k, v in G_VARIANTS.items()}, "e_variants": E_VARIANTS,
        "debug_scene": "scaled",
    }  # fmt: skip
    log.write_json("config.json", config)
    write_scenes(args, levels)
    log.event(
        "run_start",
        token_budget=args.token_budget,
        model=args.model,
        ledger_spent_at_start=base_spent,
    )
    for g, v, lv, idx, msgs, prev in jobs:
        rec = run_case(args, client, log, g, v, lv, levels[lv], idx, msgs, prev)
        if rec.get("stopped"):
            break
    new = client.spent() - base_spent
    log.event("run_end", new_tokens=new, usd_est=round(new / 1e6 * args.usd_per_mtok, 2))
    print(f"new tokens this run: {new} (cap {args.token_budget}); ledger total {client.spent()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
