"""Pre-flight: each missing piece is a FAIL with a fix; optional pieces only warn."""

import json
import socket

from ants.adversary.rollout import AspireConfig
from ants.orchestrator import preflight as pf


def fake_aspire(root):
    (root / ".venv-libero" / "bin").mkdir(parents=True)
    for exe in ("python", "cap-harness"):
        (root / ".venv-libero" / "bin" / exe).write_text("", encoding="utf-8")
    (root / ".libero").mkdir()
    launcher = root / "aspire_launch.py"
    launcher.write_text("", encoding="utf-8")
    return AspireConfig(root=root, launcher=launcher, output_root=root / "out")


def test_a_complete_checkout_passes_the_aspire_checks(tmp_path):
    assert all(c.ok for c in pf.check_aspire(fake_aspire(tmp_path)))


def test_a_missing_checkout_fails_with_a_fix(tmp_path):
    checks = pf.check_aspire(AspireConfig(root=tmp_path / "nope", launcher=tmp_path / "x.py"))
    failed = {c.name: c.detail for c in checks if not c.ok}
    assert "ASPIRE checkout" in failed and "submodule" in failed["ASPIRE checkout"]
    assert "aspire_launch.py" in failed["System 1 launcher"]


def test_services_are_probed_and_curobo_is_optional():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        checks = pf.check_services({"sam3": port, "curobo": 1})
    by = {c.name.split()[1]: c for c in checks}
    assert by["sam3"].ok and by["sam3"].required
    assert not by["curobo"].ok and not by["curobo"].required


def test_model_checks_only_when_a_model_is_used(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("META_API_KEY", raising=False)
    assert pf.check_models(False, False) == []
    key = pf.check_models(True, False)[0]
    assert key.name == "META_API_KEY" and not key.ok
    (tmp_path / ".env").write_text("META_API_KEY=secret\n", encoding="utf-8")
    assert pf.check_models(True, False)[0].ok
    assert "secret" not in pf.check_models(True, True)[0].line()


def test_smoke_checks_the_outcome_fields(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    (run / "outcome.json").write_text(json.dumps({"task_success": True}), encoding="utf-8")

    def fake_run_program(self, program, perturbation, seed, timeout_s):
        from ants.adversary.rollout.aspire_backend import read_run_dir

        return read_run_dir(run, wall_s=40.0)

    monkeypatch.setattr(pf.AspireBackend, "run_program", fake_run_program)
    check = pf.smoke(fake_aspire(tmp_path / "a"))
    assert not check.ok and "program_ok" in check.detail and "termination_reason" in check.detail


def test_main_reports_not_ready_without_a_checkout(tmp_path, capsys):
    assert pf.main(["--aspire", str(tmp_path / "nope"), "--out", str(tmp_path / "o")]) == 1
    assert "NOT READY" in capsys.readouterr().out
