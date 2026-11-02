"""The closed loop offline: mock world (System 2 backend) and patch fixture (System 1 stand-in)."""

import json
from pathlib import Path

from ants.adversary import Adversary, AdversaryConfig
from ants.adversary.perturbations import Bounds
from ants.contracts import Policy, Split
from ants.orchestrator import GateAnswer, Loop, LoopConfig, PatchSynthesizer

V0_CODE = (Path(__file__).parents[2] / "examples" / "bowl_on_plate" / "policy.py").read_text(
    encoding="utf-8"
)
V0 = Policy("bowl_on_plate", 0, "put the bowl on the plate", V0_CODE)


def adversary(categories):
    """Severity 0.6-0.8: in the mock world every physics and camera attack then breaks v0."""
    cfg = AdversaryConfig(categories=categories, min_severity=0.6, bounds=Bounds(default=0.8))
    return Adversary.from_config(cfg)


def loop(categories, synth=None, **cfg):
    adv = adversary(categories)
    return Loop(adv, synth or PatchSynthesizer(), LoopConfig(**cfg))


def test_a_fix_is_accepted_and_the_policy_is_certified(tmp_path):
    res = loop(("physics",), cycles=30, out=tmp_path).run(V0)
    assert res.accepted_versions == [1] and res.incumbent.version == 1
    assert res.stopped == "robust" and res.stage == "certified"
    assert "pinch_height = 0.4 * bowl_h" in res.incumbent.code
    assert res.constraints[0].failure_signature.startswith("physics:")
    accepted = next(r for r in res.cycles if r["decision"] == "accepted")
    assert accepted["gate"]["cases"] == 4  # 3 nominal acceptance cases + the failure found
    assert accepted["gate"]["improvements"] == [accepted["attack_id"]]
    assert "-        pinch_height = 0.82 * bowl_h" in accepted["diff"]
    assert res.incumbent.parent_version == 0


def test_an_unfixable_failure_stalls_and_escalates():
    res = loop(("camera",), cycles=30, stall_window=3).run(V0)
    assert res.stopped == "escalate" and res.incumbent.version == 0
    assert res.stage == "attackable" and res.escalation["stalled_cycles"] == 3
    assert res.escalation["signature"].startswith("camera:")
    assert [r["decision"] for r in res.cycles if "decision" in r].count("rejected") == 3


def test_a_human_text_answer_becomes_a_constraint_and_the_loop_goes_on(tmp_path):
    asked = []

    def ask(request):
        asked.append(request)
        return GateAnswer("text", "Re-localize from depth after the camera moves.")

    adv = adversary(("camera",))
    cfg = LoopConfig(cycles=30, max_human_asks=1, out=tmp_path)
    res = Loop(adv, PatchSynthesizer(), cfg, ask_human=ask).run(V0)
    assert len(asked) == 1 and res.stopped == "escalate"  # asked once, then escalates for good
    human = [c for c in res.constraints if c.constraint_id.startswith("h")]
    assert human and human[0].rule.startswith("Re-localize")
    events = [json.loads(x)["event"] for x in (tmp_path / "loop.jsonl").read_text().splitlines()]
    assert events.count("escalate") == 2 and "human_answer" in events


def test_gate_off_accepts_a_candidate_that_fixes_nothing():
    res = loop(("camera",), cycles=6, gate_mode="off").run(V0)
    assert res.accepted_versions and all(
        r["gate"]["mode"] == "off" for r in res.cycles if "gate" in r
    )


def test_budget_stop():
    res = loop(("physics",), PatchSynthesizer(budget=0), cycles=30).run(V0)
    assert res.stopped == "budget" and res.incumbent.version == 0


def test_a_policy_that_fails_its_nominal_cases_is_not_attacked():
    broken = Policy("p", 0, "t", "x = 1 / 0\n")
    res = loop(("physics",), cycles=5).run(broken)
    assert res.stopped == "no_working_policy" and res.cycles == []
    assert res.escalation["signature"] == "nominal"


def test_only_acceptance_cases_reach_system_1():
    seen = []

    class Spy(PatchSynthesizer):
        def rewrite(self, incumbent, feedback, constraints):
            seen.extend(feedback)
            return super().rewrite(incumbent, feedback, constraints)

    loop(("physics", "actuation", "camera"), Spy(), cycles=25).run(V0)
    assert seen and all(fb.test_case.split is Split.ACCEPTANCE for fb in seen)


def test_run_is_logged_and_reproducible(tmp_path):
    a = loop(("physics", "actuation", "camera"), cycles=25, out=tmp_path / "a").run(V0)
    b = loop(("physics", "actuation", "camera"), cycles=25, out=tmp_path / "b").run(V0)
    assert [r["decision"] for r in a.cycles] == [r["decision"] for r in b.cycles]
    lines = [json.loads(x) for x in (tmp_path / "a" / "loop.jsonl").read_text().splitlines()]
    assert lines[0]["event"] == "start" and lines[-1]["event"] == "end"
    assert lines[0]["loop"]["gate_mode"] == "strict" and lines[0]["backend"] == "mock"
    assert (tmp_path / "a" / "policies" / "v0.py").exists()
    for v in a.accepted_versions:
        assert (tmp_path / "a" / "policies" / f"v{v}.py").exists()
    summary = json.loads((tmp_path / "a" / "summary.json").read_text())
    assert summary["final_version"] == a.incumbent.version
