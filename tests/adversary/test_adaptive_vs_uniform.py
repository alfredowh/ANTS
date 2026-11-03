"""H1a experiment pipeline on the mock world: paired seeds, logged, arms differ only in eta."""

import json
from pathlib import Path

from ants.adversary.config import AdversaryConfig
from ants.adversary.experiments.adaptive_vs_uniform import ARMS, main, run
from ants.contracts import Policy

CODE = (Path(__file__).parents[2] / "examples" / "bowl_on_plate" / "policy.py").read_text(
    encoding="utf-8"
)
V0 = Policy("bowl_on_plate", 0, "put the bowl on the plate", CODE)


def test_both_arms_run_on_the_same_seeds_and_are_logged(tmp_path):
    runs = run(tmp_path, V0, attacks=8, seeds=[0, 1], base=AdversaryConfig())
    assert [(r.arm, r.seed) for r in runs] == [
        ("adaptive", 0), ("uniform", 0), ("adaptive", 1), ("uniform", 1),
    ]  # fmt: skip
    assert {r.eta for r in runs} == set(ARMS.values())
    for r in runs:
        assert r.attacks == 8 and len(r.cumulative) == 8
        assert r.cumulative[-1] == r.failures == sum(r.failed.values())
        assert sum(r.picked.values()) == 8
    logged = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert logged["arms"] == ARMS and len(logged["runs"]) == 4
    assert "not results" in (tmp_path / "summary.md").read_text(encoding="utf-8")


def test_the_same_seed_reproduces_the_same_run(tmp_path):
    a = run(tmp_path / "a", V0, attacks=6, seeds=[3], base=AdversaryConfig())
    b = run(tmp_path / "b", V0, attacks=6, seeds=[3], base=AdversaryConfig())
    assert [r.to_dict() for r in a] == [r.to_dict() for r in b]


def test_cli(tmp_path, capsys):
    assert main(["--attacks", "4", "--seeds", "0", "--out", str(tmp_path)]) == 0
    assert "Failures / attack" in capsys.readouterr().out
