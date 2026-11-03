"""Pre-flight check before a GPU run, so a long run cannot die at minute one.

    uv run python -m ants.orchestrator.preflight --aspire ASPIRE                  # checks only
    uv run python -m ants.orchestrator.preflight --aspire ASPIRE --muse-code --smoke

Checks: the ASPIRE checkout and its LIBERO venv (`cap-harness`), System 1's launcher
(`tools/aspire_launch.py`, needed for every perturbed attack), the ASPIRE services (SAM 3 and
PyRoki on ports 8114 / 8116, cuRobo on 8118 if used), the GPU (`nvidia-smi`), free disk for the
videos, `META_API_KEY` (only when a Muse model is used; never printed) and the `muse` CLI (only for
`--muse-code`).

`--smoke` then runs one nominal rollout of the bowl-on-plate v0 through `AspireBackend` (about
40 s) and checks that `outcome.json` has the fields the backend maps to an outcome:
`task_success`, `program_ok` and `termination_reason`. It costs GPU time, no tokens.

Exit code 0 when every required check passes; each line says what to fix otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ants.adversary.rollout import AspireConfig
from ants.adversary.rollout.aspire_backend import AspireBackend

SERVICE_PORTS = {"sam3": 8114, "pyroki": 8116, "curobo": 8118}
REQUIRED_SERVICES = ("sam3", "pyroki")
SERVICE_FIX = {
    "sam3": "start ASPIRE's scripts/supervise_services.sh --providers sam3,pyroki",
    "pyroki": "start ASPIRE's scripts/supervise_services.sh --providers sam3,pyroki",
    "curobo": "optional; only for cuRobo planning (dev/curobo/service_dev.py)",
}
OUTCOME_FIELDS = ("task_success", "program_ok", "termination_reason")
MIN_FREE_GB = 5.0
DEFAULT_POLICY = Path("examples/bowl_on_plate/policy.py")


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True

    def line(self) -> str:
        mark = "ok  " if self.ok else ("FAIL" if self.required else "warn")
        return f"[{mark}] {self.name}: {self.detail}"


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_aspire(cfg: AspireConfig) -> list[Check]:
    out = [
        Check(
            "ASPIRE checkout",
            cfg.root.is_dir(),
            str(cfg.root)
            if cfg.root.is_dir()
            else f"{cfg.root} missing: pass --aspire or set "
            "ANTS_ASPIRE_ROOT, or `git submodule update --init ASPIRE`",
        ),  # fmt: skip
        Check("LIBERO venv python", cfg.python.exists(), str(cfg.python)),
        Check("cap-harness CLI", cfg.cli.exists(), str(cfg.cli)),
        Check("LIBERO config", (cfg.root / ".libero").is_dir(), str(cfg.root / ".libero")),
        Check(
            "System 1 launcher",
            cfg.launcher.exists(),
            str(cfg.launcher)
            if cfg.launcher.exists()
            else f"{cfg.launcher} missing: perturbed attacks need tools/aspire_launch.py "
            "(on branch synthesizer)",
        ),  # fmt: skip
    ]
    return out


def check_services(ports: dict[str, int] = SERVICE_PORTS) -> list[Check]:
    return [
        Check(
            f"service {name} :{port}",
            _port_open(port),
            "listening"
            if _port_open(port)
            else "not listening: start ASPIRE's "
            "scripts/supervise_services.sh --providers sam3,pyroki",
            required=name in REQUIRED_SERVICES,
        )
        for name, port in ports.items()
    ]


def check_gpu() -> Check:
    smi = shutil.which("nvidia-smi")
    if smi is None:
        return Check("GPU", False, "nvidia-smi not found: no NVIDIA GPU on this machine")
    try:
        q = "--query-gpu=name,memory.used,memory.total,utilization.gpu"
        res = subprocess.run(
            [smi, q, "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Check("GPU", False, f"nvidia-smi failed: {exc}")
    rows = [r.split(", ") for r in res.stdout.strip().splitlines() if r.strip()]
    if res.returncode != 0 or not rows:
        return Check("GPU", False, f"nvidia-smi gave no GPU: {res.stderr.strip()[:200]}")
    name, used, total, util = (rows[0] + ["?"] * 4)[:4]
    return Check("GPU", True, f"{name}, {used}/{total} MiB used, {util}% busy")


def check_disk(path: Path, min_free_gb: float = MIN_FREE_GB) -> Check:
    path.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(path).free / 1e9
    return Check("free disk", free >= min_free_gb, f"{free:.1f} GB free at {path}")


def check_models(muse_spark: bool, muse_code: bool) -> list[Check]:
    out = []
    if muse_spark or muse_code:
        has_key = bool(os.environ.get("META_API_KEY")) or _env_file_has("META_API_KEY")
        out.append(
            Check("META_API_KEY", has_key, "set" if has_key else "missing from env and .env")
        )
    if muse_code:
        muse = shutil.which("muse")
        out.append(Check("muse CLI", muse is not None, muse or "not on PATH: install Muse Code"))
    return out


def _env_file_has(key: str, path: Path = Path(".env")) -> bool:
    if not path.exists():
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    return any(ln.strip().startswith(f"{key}=") and ln.split("=", 1)[1].strip() for ln in lines)


def smoke(cfg: AspireConfig, policy: Path = DEFAULT_POLICY, timeout_s: float = 600) -> Check:
    """One nominal rollout through the real backend; checks the outcome.json fields."""
    backend = AspireBackend(cfg)
    result = backend.run_program(policy.read_text(encoding="utf-8"), None, 0, timeout_s)
    run_dir = result.details.get("run_dir")
    if run_dir is None:
        return Check("smoke rollout", False, f"{result.outcome.value}: {result.error}")
    outcome = json.loads((Path(run_dir) / "outcome.json").read_text(encoding="utf-8"))
    missing = [f for f in OUTCOME_FIELDS if f not in outcome]
    fields = f"outcome.json lacks {missing}" if missing else "outcome fields present"
    detail = f"{result.outcome.value} in {result.duration_s:.0f} s, run {run_dir}; {fields}"
    return Check("smoke rollout", not missing and result.outcome.value != "error", detail)


def run_checks(
    cfg: AspireConfig, muse_spark: bool = False, muse_code: bool = False, do_smoke: bool = False
) -> list[Check]:
    checks = [*check_aspire(cfg), *check_services(), check_gpu(), check_disk(cfg.output_root)]
    checks += check_models(muse_spark, muse_code)
    if do_smoke:
        ready = all(c.ok for c in checks if c.required and c.name != "System 1 launcher")
        checks.append(
            smoke(cfg) if ready else Check("smoke rollout", False, "skipped: fix the FAILs first")
        )
    return checks


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--aspire", type=Path, default=None, help="ASPIRE checkout")
    ap.add_argument("--out", type=Path, default=Path("data/runs/preflight"))
    ap.add_argument("--muse-spark", action="store_true", help="the run uses --model muse-spark")
    ap.add_argument("--muse-code", action="store_true", help="the run uses --synthesizer muse-code")
    ap.add_argument("--smoke", action="store_true", help="also run one nominal rollout (~40 s)")
    args = ap.parse_args(argv)
    cfg = AspireConfig(**({"root": args.aspire} if args.aspire else {}), output_root=args.out)
    checks = run_checks(cfg, args.muse_spark, args.muse_code, args.smoke)
    for c in checks:
        print(c.line())
    failed = [c for c in checks if c.required and not c.ok]
    print(f"\n{'READY' if not failed else f'NOT READY: {len(failed)} check(s) failed'}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
