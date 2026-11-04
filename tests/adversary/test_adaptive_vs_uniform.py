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


def test_the_run_writes_a_labelled_figure(tmp_path):
    run(tmp_path, V0, attacks=5, seeds=[0, 1], base=AdversaryConfig())
    svg = (tmp_path / "figure.svg").read_text(encoding="utf-8")
    assert "Adaptive (η 0.2)" in svg and "Uniform (η 1.0)" in svg
    assert "MOCK WORLD, not a result" in svg
    page = (tmp_path / "figure.html").read_text(encoding="utf-8")
    assert "Table view" in page and 'data-theme="dark"' in page


def test_cap_harness_rollouts_land_in_the_run_directory(tmp_path, monkeypatch):
    from ants.adversary.experiments import adaptive_vs_uniform as avu

    seen = {}
    monkeypatch.setattr(avu, "run", lambda out, policy, attacks, seeds, base: seen.update(
        out=out, aspire=base.aspire) or [])  # fmt: skip
    monkeypatch.setattr(avu, "summarize", lambda *a, **k: "")
    out = tmp_path / "h1a"
    avu.main(["--backend", "cap_harness", "--aspire", str(tmp_path), "--out", str(out)])
    assert seen["aspire"].output_root == out / "aspire" and seen["aspire"].root == tmp_path


def test_severity_range_is_explicit_logged_and_matches_the_loop(tmp_path):
    import json

    assert main(["--attacks", "3", "--seeds", "0", "--out", str(tmp_path)]) == 0
    cfg = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))["config"]
    assert cfg["min_severity"] == 0.3 and "0.8" in str(cfg["bounds"])
    assert "Severity 0.3 to 0.8." in (tmp_path / "summary.md").read_text(encoding="utf-8")
    out = tmp_path / "narrow"
    main(["--attacks", "3", "--seeds", "0", "--severity-bound", "0.6", "--out", str(out)])
    for row in json.loads((out / "results.json").read_text(encoding="utf-8"))["runs"]:
        assert row["attacks"] == 3
    assert "0.6" in str(json.loads((out / "results.json").read_text(encoding="utf-8"))["config"])


def test_summary_reports_pooled_rates_with_a_wilson_interval_and_paired_seeds(tmp_path):
    from ants.adversary.experiments.adaptive_vs_uniform import wilson

    lo, hi = wilson(0, 120)
    assert lo == 0.0 and 0.02 < hi < 0.04  # zero of 120 still allows up to about 3%
    lo, hi = wilson(6, 100)
    assert lo < 0.06 < hi
    main(["--attacks", "4", "--seeds", "0", "1", "--out", str(tmp_path)])
    text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "95% CI (Wilson)" in text and "Paired by seed" in text
