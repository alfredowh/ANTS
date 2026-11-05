"""Synthetic experiment for signature-keyed correction retrieval (no simulator, no model).

World: v0 breaks on `size`; the naive repair v1 fixes size but breaks `pose` (the gate
rejects it); v2 breaks nothing. Three runs share one correction cache:

- train:   naive repair first, then the good one. The gate acceptance of v2 writes a
           Correction for the `move_to_pose|timeout` signature into the cache.
- matched: a fresh run whose generator uses a retrieved correction (`mem:` constraint)
           when one is offered, so it proposes v2 at the first attempt.
- off:     the same generator with memory off; it proposes v1 first and is rejected.

Open the result with the run viewer (System 2 tab shows, per cycle, whether a cached
fix was retrieved, the retrieved rule/diff, and why not when it was not):

    uv run python tools/correction_retrieval_mock.py data/runs/correction_retrieval_mock
    uv run python -m ants.evalkit.report data/runs/correction_retrieval_mock --open
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ants.evalkit.runlog import RunLog
from ants.orchestrator.system2 import CaseResult, HardenConfig, harden

FAIL = {"failed_calls": [{"tool": "move_to_pose", "status": "timeout", "steps_executed": 145}]}
PROGRAMS = {"v0": "size", "v1": "pose", "v2": "none"}


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, breaks in PROGRAMS.items():
        (out / f"{name}.py").write_text(f"breaks={breaks}\n", encoding="utf-8")
    store = out / "corrections.jsonl"

    def run_case(case, program):
        broken = program.read_text(encoding="utf-8").strip().split("=")[1].split(",")
        cats = [p.category for p in case.perturbations] or ["nominal"]
        ok = not any(c in broken for c in cats)
        return CaseResult(ok, {} if ok else FAIL)

    def write_config(name: str, note: str) -> None:
        (out / name).mkdir(parents=True, exist_ok=True)
        (out / name / "config.json").write_text(
            json.dumps({"note": note, "usd_per_mtok": 13.5}), encoding="utf-8"
        )

    base = dict(cycles=8, tests_per_cycle=8, min_tests_robust=1)

    calls = {"n": 0}

    def gen_train(inc, cons, fbs):
        calls["n"] += 1
        return out / ("v1.py" if calls["n"] == 1 else "v2.py"), 24_000

    write_config("train", "SYNTHETIC training run: writes the correction cache")
    train = harden(
        out / "v0.py",
        HardenConfig(**base, memory_mode="matched", memory_k=2, correction_store=store),
        run_case,
        gen_train,
        RunLog(out / "train"),
    )

    def make_gen_test():
        calls = {"n": 0}

        def gen_test(inc, cons, fbs):
            calls["n"] += 1
            retrieved = any(c.constraint_id.startswith("mem:") for c in cons)
            # A retrieved correction steers the first proposal to v2; without one the
            # naive v1 comes first and the good repair only follows its rejection.
            good = retrieved or calls["n"] > 1
            return out / ("v2.py" if good else "v1.py"), 24_000

        return gen_test

    results = {}
    for name, mode in (("matched", "matched"), ("off", "off")):
        write_config(name, f"SYNTHETIC test run: memory {mode}")
        results[name] = harden(
            out / "v0.py",
            HardenConfig(**base, memory_mode=mode, memory_k=2, correction_store=store),
            run_case,
            make_gen_test(),
            RunLog(out / name),
        )

    def cycles_with_retrieval(name: str) -> tuple[int, int]:
        rows = [
            json.loads(x)
            for x in (out / name / "system2.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        gen_rows = [r for r in rows if r.get("candidate")]
        hits = sum(1 for r in gen_rows if (r.get("retrieval") or {}).get("used"))
        return len(gen_rows), hits

    for name in ("train", "matched", "off"):
        n, hits = cycles_with_retrieval(name)
        print(f"{name}: generator cycles={n}, cycles with a retrieved correction={hits}")
    print(
        f"train stopped={train.stopped}; matched stopped={results['matched'].stopped}; "
        f"off stopped={results['off'].stopped}"
    )
    print(f"correction cache: {store}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/runs/correction_retrieval_mock"))
