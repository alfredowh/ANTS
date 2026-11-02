"""Run book: every command that runs an ANTS experiment or tool, from one JSON catalog.

`docs/runbook/commands.json` is the single source. This module checks it, builds the exact command
line for any command (defaults or overrides), and writes the redundant copies so a session limit
or a different agent never loses the list:

    uv run python -m ants.evalkit.runbook list                # experiments and their commands
    uv run python -m ants.evalkit.runbook show exp04          # question, modules, commands
    uv run python -m ants.evalkit.runbook cmd exp04.run --set=--groups=G --off=--token-budget
    uv run python -m ants.evalkit.runbook check               # catalog is consistent
    uv run python -m ants.evalkit.runbook build               # regenerate html, md, todo block

`build` writes docs/runbook.html (the UI), docs/runbook/commands-full.md (every flag),
docs/synthesizer/experiment-commands.md (the essential commands) and the block between the
`runbook:start` / `runbook:end` markers in docs/todo.md. Nothing here runs an experiment.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "docs" / "runbook" / "commands.json"
TEMPLATE = Path(__file__).with_name("runbook_template.html")
START, END = "<!-- runbook:start -->", "<!-- runbook:end -->"
SAFE = re.compile(r"^[A-Za-z0-9_@%+=:,./-]+$")


def load(path: Path = CATALOG) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check(data: dict, root: Path = ROOT) -> list[str]:
    """Problems in the catalog: duplicate ids, dangling references, missing doc files."""
    bad: list[str] = []
    modules = {m["id"] for m in data["modules"]}
    commands = [c["id"] for c in data["commands"]]
    for kind, ids in (("module", [m["id"] for m in data["modules"]]), ("command", commands),
                      ("experiment", [e["id"] for e in data["experiments"]])):  # fmt: skip
        bad += [f"duplicate {kind} id {i}" for i in {i for i in ids if ids.count(i) > 1}]
    for a, b in data["flow"]:
        bad += [f"flow edge uses unknown module {m}" for m in (a, b) if m not in modules]
    for e in data["experiments"]:
        bad += [f"{e['id']}: unknown module {m}" for m in e["modules"] if m not in modules]
        bad += [f"{e['id']}: unknown command {c}" for c in e["commands"] if c not in commands]
    docs = [m.get("doc") for m in data["modules"]] + [x.get("doc") for x in data["experiments"]]
    docs += [c.get("doc") for c in data["commands"]]
    bad += [
        f"missing doc file {d}" for d in sorted({d for d in docs if d}) if not (root / d).exists()
    ]
    for c in data["commands"]:
        bad += [f"{c['id']}: unknown module {m}" for m in c["modules"] if m not in modules]
        if c["runner"] not in data["runners"]:
            bad.append(f"{c['id']}: unknown runner {c['runner']}")
        for a in c["args"]:
            if a["kind"] not in ("value", "switch", "env"):
                bad.append(f"{c['id']}: bad arg kind for {a['flag']}")
    return bad


def _q(value: str, raw: bool = False) -> str:
    return value if raw or SAFE.match(value) else shlex.quote(value)


def command_text(data: dict, cmd: dict, on: dict[str, bool] | None = None,
                 values: dict[str, str] | None = None, multiline: bool = True) -> str:  # fmt: skip
    """The shell command for `cmd`; each flag keeps its default state unless overridden."""
    on, values = on or {}, values or {}
    runner = data["runners"][cmd["runner"]]
    head, env, flags = [], [], []
    if cmd.get("where"):
        head.append(cmd["where"])
    if cmd.get("env"):
        env.append(cmd["env"])
    for a in cmd["args"]:
        if not on.get(a["flag"], a["on"]):
            continue
        v = values.get(a["flag"], a.get("value", ""))
        if a["kind"] == "env":
            env.append(f"{a['flag']}{_q(v)}")
        elif a["kind"] == "switch":
            flags.append(a["flag"])
        else:
            flags.append(f"{a['flag']} {_q(v, a.get('raw', False))}")
    main = " ".join(p for p in [*env, runner["prefix"], cmd["base"]] if p)
    sep = " \\\n    " if multiline else " "
    body = sep.join([main, *flags])
    return " && ".join([*head, body]) if head else body


def _by_id(items: list[dict]) -> dict[str, dict]:
    return {i["id"]: i for i in items}


def full_markdown(data: dict) -> str:
    cmds = _by_id(data["commands"])
    out = [
        "# ANTS run book: every command and every flag",
        "",
        f"Generated from `docs/runbook/commands.json` on {data['updated']} by "
        "`uv run python -m ants.evalkit.runbook build`. Do not edit by hand; edit the JSON.",
        "",
        "Run from the ANTS repo root unless the command starts with `cd`. Services must be up "
        "(`setup` section) before any simulation. Commands marked **paid** spend Muse tokens: "
        "check `--token-budget` first. GitHub and VS Code show a copy button on every code block.",
        "",
        "Interactive version: `docs/runbook.html`. Essential commands only: "
        "[experiment-commands.md](../synthesizer/experiment-commands.md).",
        "",
    ]
    for e in data["experiments"]:
        out += [f"## {e['title']}", "", f"*{e['status']}.* {e['question']}", ""]
        out += [
            f"- Docs: `{e['doc']}`" + (f" · run dir: `{e['run_dir']}`" if e.get("run_dir") else "")
        ]
        out += [f"- Inputs: {'; '.join(e['inputs'])}", f"- Outputs: {'; '.join(e['outputs'])}"]
        if e.get("cost"):
            out += [f"- Cost: {e['cost']}"]
        out += [f"- Result so far: {e['result']}", ""]
        for cid in e["commands"]:
            c = cmds[cid]
            out += [f"### `{cid}`: {c['title']}" + (" (paid)" if c.get("paid") else ""), "",
                    c["description"], "", "```bash", command_text(data, c), "```", ""]  # fmt: skip
            if c["args"]:
                out += ["| Flag | Default | On | Meaning |", "|---|---|---|---|"]
                for a in c["args"]:
                    v = "" if a["kind"] == "switch" else f"`{a.get('value', '')}`"
                    ch = f" Choices: {', '.join(a['choices'])}." if a.get("choices") else ""
                    out.append(
                        f"| `{a['flag']}` | {v} | {'yes' if a['on'] else 'no'} | {a['desc']}{ch} |"
                    )
                out.append("")
            for x in c["examples"]:
                out += [f"{x['title']}:", "", "```bash", x["cmd"], "```", ""]
    return "\n".join(out).rstrip() + "\n"


def essential_markdown(data: dict) -> str:
    cmds = _by_id(data["commands"])
    out = [
        "# Experiment commands (essential)",
        "",
        "The one command that reproduces each experiment, plus setup. All flags, examples and "
        "arguments: [commands-full.md](../runbook/commands-full.md). "
        "Interactive: `docs/runbook.html`. "
        "Generated by `uv run python -m ants.evalkit.runbook build` from "
        "`docs/runbook/commands.json`.",
        "",
        "Rule of thumb: start the services, run with a small `--token-budget`, view the run, then "
        "scale up. A run resumes if you repeat the same `--out`.",
        "",
    ]
    for e in data["experiments"]:
        out += [f"## {e['title']}", "", f"{e['question']} Details: `{e['doc']}`.", ""]
        for cid in e["commands"][:2] if e["kind"] != "setup" else e["commands"][:4]:
            c = cmds[cid]
            out += [f"**{c['title']}**" + (" (spends Muse tokens)" if c.get("paid") else ""), "",
                    "```bash", command_text(data, c), "```", ""]  # fmt: skip
    return "\n".join(out).rstrip() + "\n"


def todo_block(data: dict) -> str:
    cmds = _by_id(data["commands"])
    out = [START, "", "## Run book (generated, redundant on purpose)", "",
           "If a session limit hits, copy a command from here and keep going. Full flag tables: "
           "[runbook/commands-full.md](runbook/commands-full.md). "
        f"UI: [ANTS Run Book]({data['artifact_url']}) "
        "or `docs/runbook.html`. "
           "Agent access notes: [runbook/agent-access.md](runbook/agent-access.md). "
           f"Catalog updated {data['updated']}.", ""]  # fmt: skip
    for e in data["experiments"]:
        out += [f"**{e['title']}** ({e['status']})", ""]
        for cid in e["commands"][:2] if e["kind"] != "setup" else e["commands"][:3]:
            c = cmds[cid]
            out += ["```bash", command_text(data, c), "```", ""]
    return "\n".join([*out, END])


def write_todo(data: dict, path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    block = todo_block(data)
    if START in text:
        text = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, text, flags=re.S)
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    path.write_text(text, encoding="utf-8")


def html(data: dict, local: bool = True) -> str:
    """The UI as one file. `local` adds the document wrapper the Artifact tool adds itself."""
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/", payload)
    wrapper = (
        '<!doctype html>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    )
    return (wrapper if local else "") + page


def build(data: dict, root: Path = ROOT, artifact_out: Path | None = None) -> list[Path]:
    targets = {
        root / "docs" / "runbook.html": html(data),
        root / "docs" / "runbook" / "commands-full.md": full_markdown(data),
        root / "docs" / "synthesizer" / "experiment-commands.md": essential_markdown(data),
    }
    for path, text in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    write_todo(data, root / "docs" / "todo.md")
    written = [*targets, root / "docs" / "todo.md"]
    if artifact_out:
        artifact_out.write_text(html(data, local=False), encoding="utf-8")
        written.append(artifact_out)
    return written


def _listing(data: dict) -> str:
    lines = []
    for e in data["experiments"]:
        lines.append(f"{e['id']:<14} {e['status']:<22} {e['title']}")
        lines += [f"    {c}" for c in e["commands"]]
    return "\n".join(lines)


def _show(data: dict, key: str) -> str:
    exp = _by_id(data["experiments"]).get(key)
    if not exp:
        raise SystemExit(f"unknown experiment {key!r}; try `list`")
    mods = _by_id(data["modules"])
    lines = [exp["title"], f"  status: {exp['status']}", f"  question: {exp['question']}",
             f"  doc: {exp['doc']}", f"  run dir: {exp.get('run_dir')}",
             f"  inputs: {'; '.join(exp['inputs'])}", f"  outputs: {'; '.join(exp['outputs'])}",
             f"  result: {exp['result']}", "  modules:"]  # fmt: skip
    lines += [f"    {m}: {mods[m]['path']}" for m in exp["modules"]]
    lines += ["  commands:"] + [f"    {c}" for c in exp["commands"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("check")
    sub.add_parser("build").add_argument(
        "--artifact-out", type=Path, help="also write the Artifact-tool fragment"
    )
    sub.add_parser("show").add_argument("experiment")
    c = sub.add_parser("cmd")
    c.add_argument("id")
    c.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="FLAG=VALUE",
        help="turn a flag on with a value",
    )
    c.add_argument("--off", action="append", default=[], metavar="FLAG", help="turn a flag off")
    c.add_argument("--one-line", action="store_true")
    args = p.parse_args(argv)
    data = load()
    if args.cmd == "list":
        print(_listing(data))
    elif args.cmd == "show":
        print(_show(data, args.experiment))
    elif args.cmd == "check":
        problems = check(data)
        print("\n".join(problems) or "catalog ok")
        return 1 if problems else 0
    elif args.cmd == "build":
        problems = check(data)
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        for path in build(data, artifact_out=args.artifact_out):
            print(f"wrote {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    else:
        cmd = _by_id(data["commands"]).get(args.id)
        if not cmd:
            raise SystemExit(f"unknown command {args.id!r}; try `list`")
        on = {f: False for f in args.off}
        values = {}
        for item in args.set:
            flag, _, value = item.partition("=")
            on[flag], values[flag] = True, value
        print(command_text(data, cmd, on, values, multiline=not args.one_line))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
