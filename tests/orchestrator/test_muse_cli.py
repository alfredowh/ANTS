"""run_muse against a fake `muse` executable: no real API call, no tokens spent."""

from __future__ import annotations

import json
import stat
import sys
import textwrap
from pathlib import Path

import pytest

from ants.orchestrator.muse_cli import MuseCliError, run_muse

TERMINAL_EVENT = {
    "payload_type": "run.terminal.completed",
    "payload": {"terminal": "completed", "text": "WHY: fixed it\n```python\nresult = {}\n```"},
}
USAGE_EVENT = {
    "payload_type": "run.usage",
    "payload": {
        "models": [
            {"input_tokens": 10, "output_tokens": 5, "reasoning_tokens": 3, "cached_tokens": 0}
        ]
    },
}


def _fake_muse(tmp_path: Path, script: str) -> str:
    """A fake `muse` executable. Windows cannot run a shebang script directly, so there it is a
    `.cmd` wrapper that runs the same script with this interpreter."""
    path = tmp_path / "fake_muse.py"
    path.write_text(f"#!/usr/bin/env python3\n{script}\n", encoding="utf-8")
    if sys.platform == "win32":
        shim = tmp_path / "fake_muse.cmd"
        shim.write_text(f'@"{sys.executable}" "{path}" %*\r\n', encoding="utf-8")
        return str(shim)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_run_muse_parses_terminal_and_usage(tmp_path):
    fake = _fake_muse(
        tmp_path,
        textwrap.dedent(f"""
            import sys
            print({json.dumps(json.dumps(TERMINAL_EVENT))})
            print({json.dumps(json.dumps(USAGE_EVENT))})
        """),
    )
    result = run_muse("do the thing", muse_bin=fake)
    assert "result = {}" in result.text
    assert result.input_tokens == 10
    assert result.output_tokens == 5
    assert result.reasoning_tokens == 3
    assert result.total_tokens == 15
    assert len(result.events) == 2


def test_run_muse_raises_on_nonzero_exit(tmp_path):
    fake = _fake_muse(tmp_path, "import sys\nsys.exit(1)\n")
    with pytest.raises(MuseCliError):
        run_muse("prompt", muse_bin=fake)


def test_run_muse_raises_when_no_terminal_event(tmp_path):
    fake = _fake_muse(tmp_path, "print('not json')\n")
    with pytest.raises(MuseCliError):
        run_muse("prompt", muse_bin=fake)


def test_run_muse_raises_when_not_completed(tmp_path):
    failed = {
        "payload_type": "run.terminal.completed",
        "payload": {"terminal": "failed", "text": ""},
    }
    fake = _fake_muse(tmp_path, f"print({json.dumps(json.dumps(failed))})\n")
    with pytest.raises(MuseCliError):
        run_muse("prompt", muse_bin=fake)


def test_run_muse_raises_on_timeout(tmp_path):
    fake = _fake_muse(tmp_path, "import time\ntime.sleep(5)\n")
    with pytest.raises(MuseCliError):
        run_muse("prompt", muse_bin=fake, timeout_s=0.2)
