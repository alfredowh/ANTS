"""Render a studio run directory as one self-contained HTML page.

    uv run python -m ants.studio.build data/runs/<name>

Everything shown comes from the run's logs. A System 2 run (`ants.studio.run`) has no rewrites or
gate verdicts; a closed-loop run (`ants.orchestrator.run`) also has `loop.jsonl` and `policies/`,
which add the Versions view, per-attack gate verdicts and diffs. Parts that are missing from the
logs are shown as not available, never filled in.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

TEMPLATE = Path(__file__).with_name("template.html")
OBSERVED_USD_PER_MTOK = 13.5  # System 1's logged Muse cost; an estimate for Muse Spark


def _phases(events: list[dict]) -> list[str]:
    """A task phase per primitive call, from the order of calls (no simulator time in the mock)."""
    out, closed, released = [], False, False
    for e in events:
        tool = e.get("tool")
        if tool == "open_gripper" and not closed:
            out.append("Setup")
        elif tool == "localize_object" and not closed:
            out.append("Locate")
        elif tool == "close_gripper":
            closed = True
            out.append("Grasp")
        elif tool == "open_gripper" and closed:
            released = True
            out.append("Place")
        elif released:
            out.append("Retreat")
        else:
            out.append("Transport" if closed else "Approach")
    return out


def _divergence(calls: list[dict], nominal: list[dict]) -> int | None:
    """Index of the first call that differs from the nominal run (tool or success)."""
    for i, c in enumerate(calls):
        if i >= len(nominal):
            return i
        n = nominal[i]
        if c.get("tool") != n.get("tool") or bool(c.get("ok")) != bool(n.get("ok")):
            return i
    return len(calls) if len(calls) != len(nominal) else None


def _attack(row: dict, index: int, nominal_calls: list[dict]) -> dict[str, Any]:
    rep, notes = row["report"], row.get("notes", {})
    p, res = rep["perturbation"], rep["result"]
    events = [{"kind": e["kind"], **e.get("detail", {})} for e in res.get("events", [])]
    calls = [e for e in events if e["kind"] == "call"]
    others = []
    call_i = 0
    for e in events:
        if e["kind"] == "call":
            call_i += 1
        else:
            others.append({**e, "at": call_i})
    failure, constraint = rep.get("failure"), rep.get("constraint")
    diag = notes.get("diagnosis", {})
    usage = [notes.get("proposal", {}).get("usage", {}), diag.get("usage", {})]
    tokens = sum(u.get("prompt_tokens", 0) + u.get("completion_tokens", 0) for u in usage)
    phases = _phases(calls)
    first_fail = next((i for i, c in enumerate(calls) if not c.get("ok", True)), None)
    return {
        "id": rep["attack_id"],
        "n": index + 1,
        "category": p["category"],
        "params": p["params"],
        "severity": p["severity"],
        "seed": p.get("seed"),
        "rationale": p.get("rationale", ""),
        "outcome": res["outcome"],
        "error": res.get("error"),
        "duration_s": res.get("duration_s"),
        "metrics": res.get("metrics", {}),
        "draws": rep.get("selector_draws", {}),
        "explored": notes.get("selection", {}).get("explored", False),
        "proposal": notes.get("proposal", {}),
        "calls": [
            {
                "tool": c.get("tool"),
                "ok": c.get("ok", True),
                "status": c.get("status"),
                "phase": phases[i],
                "query": c.get("query"),
                "error_m": c.get("error_m"),
            }
            for i, c in enumerate(calls)
        ],  # fmt: skip
        "events": others,
        "first_fail": first_fail,
        "divergence": _divergence(calls, nominal_calls),
        "signature": constraint["failure_signature"] if constraint else None,
        "mode": failure["mode"] if failure else None,
        "root_cause": failure["root_cause"] if failure else None,
        "confidence": failure["confidence"] if failure else None,
        "diag_source": diag.get("source"),
        "rule_mode": diag.get("rule_mode"),
        "code_sketch": (constraint or {}).get("code_sketch") or diag.get("code_sketch") or "",
        "rule": constraint["rule"] if constraint else None,
        "when": constraint["when_to_apply"] if constraint else None,
        "evidence": (constraint or {}).get("evidence", []),
        "line": _line(failure["root_cause"]) if failure else None,
        "explanation": row.get("explanation", ""),
        "explanation_source": row.get("explanation_source", "none"),
        "status": row.get("status_after", {}),
        "tokens": tokens,
    }


def _line(text: str) -> int | None:
    m = re.search(r"\blines? (\d+)", text or "", flags=re.IGNORECASE)
    return int(m.group(1)) if m else None


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def collect_loop(run_dir: Path) -> dict[str, Any] | None:
    """Versions, gate verdicts and escalations of a closed-loop run (None for a System 2 run)."""
    rows = _jsonl(run_dir / "loop.jsonl")
    if not rows:
        return None
    cycles = [r for r in rows if r.get("event") == "cycle"]
    end = next((r for r in reversed(rows) if r.get("event") == "end"), {})
    start = next((r for r in rows if r.get("event") == "start"), {})
    versions = []
    for meta_path in sorted((run_dir / "policies").glob("v*.json"), key=lambda q: int(q.stem[1:])):
        pol = json.loads(meta_path.read_text(encoding="utf-8"))
        v = pol["version"]
        made = next(
            (c for c in cycles if c.get("decision") == "accepted" and c["candidate_version"] == v),
            None,
        )
        versions.append(
            {
                "version": v,
                "parent": pol.get("parent_version"),
                "code": meta_path.with_suffix(".py").read_text(encoding="utf-8"),
                "accepted_at": made["attack_id"] if made else None,
                "constraint": (made or {}).get("constraint"),
                "diff": (made or {}).get("diff", ""),
                "gate": (made or {}).get("gate"),
            }
        )
    by_attack = {
        c["attack_id"]: {
            k: c.get(k)
            for k in (
                "policy_version",
                "decision",
                "candidate_version",
                "gate",
                "diff",
                "stalls",
                "constraints_active",
            )
        }
        for c in cycles
    }
    events = [
        r for r in rows if r.get("event") in ("escalate", "human_answer", "no_working_policy")
    ]
    return {
        "config": start.get("loop", {}),
        "stopped": end.get("stopped"),
        "stage": end.get("stage"),
        "final_version": end.get("final_version"),
        "accepted_versions": end.get("accepted_versions", []),
        "constraints": end.get("constraints", []),
        "escalation": end.get("escalation"),
        "events": events,
        "versions": versions,
        "by_attack": by_attack,
        "decisions": [
            {
                "attack_id": c["attack_id"],
                "cycle": c["cycle"],
                "category": c["category"],
                "signature": c.get("signature"),
                "policy_version": c["policy_version"],
                "candidate_version": c.get("candidate_version"),
                "decision": c.get("decision"),
                "reason": (c.get("gate") or {}).get("reason"),
                "regressions": (c.get("gate") or {}).get("regressions", []),
                "improvements": (c.get("gate") or {}).get("improvements", []),
                "cases": (c.get("gate") or {}).get("cases"),
                "stalls": c.get("stalls", {}),
            }
            for c in cycles
            if c.get("decision") not in (None, "no_failure")
        ],
    }


def collect(run_dir: Path) -> dict[str, Any]:
    meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    rows = _jsonl(run_dir / "attacks.jsonl")
    loop = collect_loop(run_dir)
    nominal_calls = [e for e in meta.get("nominal", {}).get("events", []) if e["kind"] == "call"]
    attacks = [_attack(r, i, nominal_calls) for i, r in enumerate(rows)]
    for a in attacks:
        a["version"] = meta["policy"]["version"]
        if loop and a["id"] in loop["by_attack"]:
            a["version"] = loop["by_attack"][a["id"]]["policy_version"]
            a["loop"] = loop["by_attack"][a["id"]]
    tokens = sum(a["tokens"] for a in attacks)
    program = (run_dir / "policy.py").read_text(encoding="utf-8")
    return {
        "run": meta,
        "program": program,
        "attacks": attacks,
        "loop": loop,
        "status": attacks[-1]["status"] if attacks else {},
        "usage": {
            "rollouts": len(attacks) + 1,
            "sim_seconds": round(sum(a["duration_s"] or 0.0 for a in attacks), 2),
            "tokens": tokens,
            "usd_estimate": round(tokens / 1e6 * OBSERVED_USD_PER_MTOK, 2),
            "usd_rate": OBSERVED_USD_PER_MTOK,
        },
    }


def build(run_dir: Path) -> Path:
    data = json.dumps(collect(run_dir), default=str).replace("</", "<\\/")
    page = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", data)
    out = run_dir / "studio.html"
    out.write_text(page, encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m ants.studio.build <run_dir>")
        return 2
    print(build(Path(args[0])).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
