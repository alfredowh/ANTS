"""cap_harness backend without ASPIRE: a fake subprocess writes a run directory in its format."""

import json
import subprocess
from pathlib import Path

import pytest

from ants.adversary import Adversary, AdversaryConfig
from ants.adversary.rollout import AspireBackend, AspireConfig, read_run_dir, to_feedback
from ants.adversary.rollout.aspire_backend import ACCEPTANCE_SEEDS, HELD_OUT_SEEDS
from ants.contracts import Outcome, Perturbation, Policy, Split

POSE = Perturbation("pose", {"dx_m": 0.05, "dy_m": 0.0}, 0.4, seed=3)


def write_run(run_dir: Path, *, success=False, program_ok=True, calls=(), stdout="", error=None):
    (run_dir / "source").mkdir(parents=True)
    (run_dir / "episode").mkdir()
    (run_dir / "media" / "videos").mkdir(parents=True)
    (run_dir / "media" / "videos" / "agentview.mp4").write_bytes(b"")
    outcome = {
        "program_ok": program_ok,
        "task_success": success,
        "termination_reason": "task_succeeded" if success else "program_completed",
        "error": error,
    }
    (run_dir / "outcome.json").write_text(json.dumps(outcome), encoding="utf-8")
    result = {"calls": list(calls), "stdout": stdout, "result": {"placed": success}}
    (run_dir / "source" / "program-result.json").write_text(json.dumps(result), encoding="utf-8")
    state = {
        "robot_state": {
            "end_effector_poses": {"primary": {"position": {"$array_inline": [0.5, 0.1, 0.2]}}},
            "gripper_positions": {"primary": 0.0},
        }
    }
    (run_dir / "episode" / "steps.jsonl").write_text(json.dumps(state) + "\n", encoding="utf-8")


TIMEOUT_CALL = {
    "index": 4,
    "tool": "move_to_pose",
    "ok": False,
    "duration_s": 3.0,
    "outputs_summary": {"status": "timeout", "steps_executed": 260, "final_errors": [0.03]},
}
OK_CALL = {"index": 0, "tool": "localize_object", "ok": True, "outputs_summary": {}}


class FakeHarness:
    """Stands in for subprocess.run: records the command and writes the run directory."""

    def __init__(self, **run_kwargs):
        self.run_kwargs = run_kwargs
        self.commands = []

    def __call__(self, cmd, **kwargs):
        self.commands.append(cmd)
        root = Path(cmd[cmd.index("--output-root") + 1])
        write_run(root / "libero-pro" / "task" / "run-1", **self.run_kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")


@pytest.fixture
def backend(tmp_path):
    launcher = tmp_path / "aspire_launch.py"
    launcher.write_text("", encoding="utf-8")
    cfg = AspireConfig(root=tmp_path / "ASPIRE", launcher=launcher, output_root=tmp_path / "runs")
    return AspireBackend(cfg)


def test_acceptance_backend_never_runs_a_held_out_seed(backend):
    seeds = {backend.harness_seed(s) for s in range(1000)}
    assert seeds == set(ACCEPTANCE_SEEDS) and not seeds & set(HELD_OUT_SEEDS)
    held = AspireBackend(AspireConfig(split=Split.HELD_OUT))
    assert {held.harness_seed(s) for s in range(1000)} == set(HELD_OUT_SEEDS)


def test_nominal_runs_cap_harness_and_perturbed_runs_the_launcher(backend, tmp_path):
    prog = tmp_path / "p.py"
    nominal = backend.command(prog, tmp_path, 51, {})
    assert nominal[0].endswith("cap-harness") and nominal[1] == "run"
    assert nominal[nominal.index("--init-mode") + 1] == "seeded"
    scene = backend.scene_spec(POSE)
    perturbed = backend.command(prog, tmp_path, 51, scene)
    assert perturbed[1].endswith("aspire_launch.py") and perturbed[3] == "--"
    written = json.loads((tmp_path / "scene.json").read_text(encoding="utf-8"))
    assert written["pose"]["offsets_m"]["akita_black_bowl_1_joint0"] == [0.05, 0.0]


def test_missing_launcher_is_a_clear_error(tmp_path):
    b = AspireBackend(AspireConfig(launcher=tmp_path / "nope.py"))
    with pytest.raises(FileNotFoundError, match="launcher"):
        b.command(tmp_path / "p.py", tmp_path, 51, {"pose": {}})


def test_read_success_run(tmp_path):
    write_run(tmp_path, success=True, calls=[OK_CALL])
    r = read_run_dir(tmp_path, wall_s=41.0)
    assert r.outcome is Outcome.SUCCESS and r.error is None
    assert r.video_path.endswith("agentview.mp4") and r.metrics["wall_s"] == 41.0


def test_read_failed_run_feeds_the_rule_diagnoser(tmp_path):
    write_run(tmp_path, calls=[OK_CALL, TIMEOUT_CALL], stdout="move stage: grasp")
    r = read_run_dir(tmp_path)
    assert r.outcome is Outcome.FAILURE and r.last_phase == "move_to_pose"
    fb = to_feedback(r)
    assert fb["termination_reason"] == "program_completed"
    assert fb["failed_calls"][0] == {
        "call_index": 4,
        "tool": "move_to_pose",
        "status": "timeout",
        "steps_executed": 260,
    }
    assert fb["final_gripper"]["position_robot_base"] == [0.5, 0.1, 0.2]
    assert "grasp" in fb["stdout_tail"]


def test_program_crash_is_an_error(tmp_path):
    write_run(tmp_path, program_ok=False, error={"type": "NameError"})
    r = read_run_dir(tmp_path)
    assert r.outcome is Outcome.ERROR and "NameError" in r.error


def test_no_outcome_and_wall_clock_are_errors(backend, monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "boom")
    )
    r = backend.run_program("x = 1", None, 0, 10.0)
    assert r.outcome is Outcome.ERROR and to_feedback(r)["termination_reason"] == "harness_error"

    def hang(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", hang)
    r = backend.run_program("x = 1", POSE, 0, 5.0)
    assert r.outcome is Outcome.ERROR
    assert to_feedback(r)["termination_reason"] == "wall_clock_timeout"


def test_run_program_logs_seed_split_and_scene(backend, monkeypatch):
    fake = FakeHarness(calls=[TIMEOUT_CALL])
    monkeypatch.setattr(subprocess, "run", fake)
    r = backend.run_program("result = 1", POSE, 7, 900.0)
    assert r.details["harness_seed"] == ACCEPTANCE_SEEDS[7] and r.details["split"] == "acceptance"
    assert r.details["scene"]["pose"]["offsets_m"]
    cmd = fake.commands[0]
    assert Path(cmd[cmd.index("--program") + 1]).read_text(encoding="utf-8") == "result = 1"


class SplitHarness(FakeHarness):
    """Nominal runs (cap-harness) and perturbed runs (the launcher) get different run dirs."""

    def __init__(self, nominal, perturbed):
        super().__init__()
        self.nominal, self.perturbed = nominal, perturbed

    def __call__(self, cmd, **kwargs):
        self.run_kwargs = self.perturbed if "aspire_launch.py" in " ".join(cmd) else self.nominal
        return super().__call__(cmd, **kwargs)


V0 = Policy("bowl_on_plate", 0, "put the bowl on the plate", "result = 1")


def test_adversary_attacks_through_cap_harness(backend, monkeypatch):
    monkeypatch.setattr(subprocess, "run", FakeHarness(calls=[OK_CALL, TIMEOUT_CALL]))
    adv = Adversary(AdversaryConfig(backend="cap_harness"), backend)
    report = adv.attack(V0)
    assert report.result.outcome is Outcome.FAILURE
    assert adv.replay(Policy("p", 0, "t", "x"), [None])[0].details["scene"] == {}


def test_a_call_that_also_fails_in_the_nominal_run_is_not_blamed(backend, monkeypatch):
    # Every rollout of the real v0 has a harmless move_to_pose timeout at approach_high; it was
    # blamed for every failure on the GPU. Here nominal and attack share it: not the cause.
    harness = SplitHarness(
        nominal={"success": True, "calls": [OK_CALL, TIMEOUT_CALL]},
        perturbed={"calls": [OK_CALL, TIMEOUT_CALL]},
    )
    monkeypatch.setattr(subprocess, "run", harness)
    adv = Adversary(AdversaryConfig(backend="cap_harness"), backend)
    report = adv.attack(V0)
    assert report.result.outcome is Outcome.FAILURE
    assert report.constraint.failure_signature.endswith(":program_completed:not_scored")
    assert any("also failing in the nominal run" in e for e in report.constraint.evidence)
    notes = adv.history.records[-1].notes["nominal"]
    assert notes == {"outcome": "success", "expected_failed_calls": ["move_to_pose:timeout"]}


def test_a_call_that_fails_only_under_the_perturbation_is_blamed(backend, monkeypatch):
    harness = SplitHarness(
        nominal={"success": True, "calls": [OK_CALL]},
        perturbed={"calls": [OK_CALL, TIMEOUT_CALL]},
    )
    monkeypatch.setattr(subprocess, "run", harness)
    adv = Adversary(AdversaryConfig(backend="cap_harness"), backend)
    report = adv.attack(V0)
    assert report.constraint.failure_signature.endswith(":move_to_pose:timeout")
    runs = len(harness.commands)
    adv.nominal_feedback(V0, 0)  # cached per version and seed: no second nominal run
    assert len(harness.commands) == runs


def test_the_model_diagnoser_sees_both_runs_printed_measurements(backend, monkeypatch):
    from ants.adversary.models import Effort, MockModel

    harness = SplitHarness(
        nominal={"success": True, "calls": [OK_CALL], "stdout": "plate height m: 0.021"},
        perturbed={"calls": [OK_CALL], "stdout": "plate height m: 0.157"},
    )
    monkeypatch.setattr(subprocess, "run", harness)
    model = MockModel()
    adv = Adversary(AdversaryConfig(backend="cap_harness"), backend, model=model)
    adv.attack(V0)
    prompts = [m[0][0].content for m in model.calls if m[1] is Effort.DELIBERATE]
    assert prompts and "plate height m: 0.157" in prompts[0] and "0.021" in prompts[0]
    assert "outcome: success" in prompts[0]


def test_the_adversary_token_budget_reaches_the_model(monkeypatch):
    import ants.adversary.adversary as adversary_module

    class Budgeted:
        token_budget = 100_000

    monkeypatch.setattr(adversary_module, "get_model", lambda spec: Budgeted())
    adv = Adversary.from_config(AdversaryConfig(model="muse-spark", token_budget=500_000))
    assert adv.model.token_budget == 500_000


def test_default_root_is_the_submodule_and_the_env_overrides_it(monkeypatch):
    from ants.adversary.rollout.aspire_backend import DEFAULT_ASPIRE_ROOT, REPO_ROOT

    monkeypatch.delenv("ANTS_ASPIRE_ROOT", raising=False)
    assert AspireConfig().root == DEFAULT_ASPIRE_ROOT == REPO_ROOT / "ASPIRE"
    monkeypatch.setenv("ANTS_ASPIRE_ROOT", "/opt/aspire")
    assert AspireConfig().root == Path("/opt/aspire")


def test_relative_root_is_resolved_because_the_harness_runs_with_cwd_root(tmp_path, monkeypatch):
    # `--aspire ASPIRE` from the repo root: with cwd=root, a relative cli path would point at
    # ASPIRE/ASPIRE/.venv-libero/bin/cap-harness (seen on the first GPU smoke run).
    monkeypatch.chdir(tmp_path)
    cfg = AspireConfig(root=Path("ASPIRE"))
    assert cfg.root == tmp_path.resolve() / "ASPIRE"
    assert cfg.cli.is_absolute() and cfg.python.is_absolute()
    assert cfg.cli == tmp_path.resolve() / "ASPIRE" / ".venv-libero" / "bin" / "cap-harness"
