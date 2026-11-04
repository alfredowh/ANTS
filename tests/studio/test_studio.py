import json
from pathlib import Path

from ants.studio.build import _divergence, _line, _phases, collect
from ants.studio.run import run

POLICY = Path(__file__).parents[2] / "examples" / "bowl_on_plate" / "policy.py"


def test_run_writes_logs_and_a_self_contained_page(tmp_path):
    page = run(tmp_path / "r", attacks=6, policy_path=POLICY)
    rows = (tmp_path / "r" / "attacks.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 6 and page.name == "studio.html"
    html = page.read_text(encoding="utf-8")
    assert "/*__DATA__*/" not in html and "</script>" in html
    data = collect(tmp_path / "r")
    assert len(data["attacks"]) == 6 and data["program"].startswith("import math")
    assert data["run"]["nominal"]["outcome"] == "success"
    for a in data["attacks"]:
        assert a["calls"] and set(a["draws"]) == set(data["run"]["config"]["categories"])
        if a["outcome"] == "failure":
            assert a["signature"] and a["rule"] and a["explanation_source"] == "template"


def test_page_data_cannot_close_the_script_tag(tmp_path):
    run(tmp_path / "r", attacks=1, policy_path=POLICY)
    (tmp_path / "r" / "policy.py").write_text("x = '</script><b>'\n", encoding="utf-8")
    from ants.studio.build import build

    html = build(tmp_path / "r").read_text(encoding="utf-8")
    assert html.count("</script>") == 1


def test_phases_follow_the_call_order():
    calls = [{"tool": t} for t in ("open_gripper", "localize_object", "move_to_pose",
             "close_gripper", "move_to_pose", "open_gripper", "move_to_pose")]  # fmt: skip
    assert _phases(calls) == [
        "Setup", "Locate", "Approach", "Grasp", "Transport", "Place", "Retreat"
    ]  # fmt: skip


def test_divergence_is_the_first_call_that_differs_from_nominal():
    nominal = [{"tool": "a", "ok": True}, {"tool": "b", "ok": True}]
    assert _divergence(nominal, nominal) is None
    assert _divergence([{"tool": "a", "ok": True}, {"tool": "b", "ok": False}], nominal) == 1
    assert _divergence([{"tool": "a", "ok": True}], nominal) == 1


def test_root_cause_line_is_parsed():
    assert _line("Line 229 retries only three times") == 229
    assert _line("no line mentioned") is None
    assert json.dumps(_line("see lines 12-14")) == "12"


def test_rerunning_into_the_same_folder_starts_fresh(tmp_path):
    run(tmp_path / "r", attacks=3, policy_path=POLICY)
    run(tmp_path / "r", attacks=3, policy_path=POLICY)
    ids = [a["id"] for a in collect(tmp_path / "r")["attacks"]]
    assert ids == ["atk-00000", "atk-00001", "atk-00002"]


def _loop_run(tmp_path):
    from ants.adversary import AdversaryConfig
    from ants.adversary.perturbations import Bounds
    from ants.contracts import Policy
    from ants.orchestrator import LoopConfig
    from ants.orchestrator.run import run_loop

    adv = AdversaryConfig(categories=("physics", "camera"), min_severity=0.6, bounds=Bounds(0.8))
    policy = Policy("bowl_on_plate", 0, "put the bowl on the plate", POLICY.read_text("utf-8"))
    return run_loop(tmp_path / "loop", adv, LoopConfig(cycles=20), policy)


def test_a_loop_run_has_versions_gate_verdicts_and_diffs(tmp_path):
    res, page = _loop_run(tmp_path)
    data = collect(tmp_path / "loop")
    loop = data["loop"]
    assert loop["accepted_versions"] == res.accepted_versions == [1]
    assert [v["version"] for v in loop["versions"]] == [0, 1]
    v1 = loop["versions"][1]
    assert v1["accepted_at"] and "pinch_height = 0.4 * bowl_h" in v1["code"]
    assert v1["constraint"]["failure_signature"].startswith("physics:")
    assert {d["decision"] for d in loop["decisions"]} >= {"accepted", "rejected"}
    assert loop["stopped"] == "escalate" and loop["escalation"]["signature"].startswith("camera:")
    # every attack row is tagged with the version it attacked and, for failures, the gate verdict
    assert len(data["attacks"]) == len(res.cycles)
    assert {a["version"] for a in data["attacks"]} == {0, 1}
    gated = [a for a in data["attacks"] if a.get("loop", {}).get("gate")]
    assert gated and all(a["loop"]["decision"] in ("accepted", "rejected") for a in gated)
    html = page.read_text(encoding="utf-8")
    assert html.count("</script>") == 1 and '"versions"' in html


def test_a_system2_run_has_no_loop_section(tmp_path):
    run(tmp_path / "r", attacks=2, policy_path=POLICY)
    assert collect(tmp_path / "r")["loop"] is None


def test_videos_link_relative_to_the_run_folder_even_when_recorded_elsewhere(tmp_path):
    # A run made on the GPU machine and copied here: logged paths point at /workspace/...
    run_dir = tmp_path / "libero_studio"
    run(run_dir, attacks=2, policy_path=POLICY)
    attack_vid = run_dir / "aspire" / "20261104_0002_s52_abc" / "x" / "media" / "videos" / "a.mp4"
    nominal_vid = (
        run_dir / "aspire" / "20261104_0001_s51_nominal" / "y" / "media" / "videos" / "n.mp4"
    )
    for v in (attack_vid, nominal_vid):
        v.parent.mkdir(parents=True)
        v.write_bytes(b"")
    rows = (run_dir / "attacks.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(rows[0])
    gpu_path = (
        "/workspace/ANTS/data/runs/libero_studio/" + attack_vid.relative_to(run_dir).as_posix()
    )
    first["report"]["result"]["video_path"] = gpu_path
    rows[0] = json.dumps(first)
    (run_dir / "attacks.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")

    data = collect(run_dir)
    assert data["attacks"][0]["video"] == attack_vid.relative_to(run_dir).as_posix()
    assert data["attacks"][1]["video"] is None  # the mock world records no video
    # Older runs did not log the nominal video: it is found by its folder name.
    assert data["nominal_video"] == nominal_vid.relative_to(run_dir).as_posix()
