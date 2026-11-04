"""The Adversary side of ANTS Studio: Daniel's page, served for the console's current run.

`build.py` and `template.html` stay his: this module only calls `build()` and, when serving,
fills the inert `<!--ANTS_STUDIO_SWITCH-->` comment in his header with the Adversary | Synthesizer
switch and adds a light-theme mapping. A standalone `studio.html` still contains only the comment,
so it looks and behaves as it always did. Everything here is read-only over the run folder, apart
from `run.json`/`policy.py` written at run start, the same two files his own runners write.
"""

from __future__ import annotations

import html
import json
import threading
import time
from pathlib import Path

from ants.studio.build import TEMPLATE, build

SWITCH_MARKER = "<!--ANTS_STUDIO_SWITCH-->"
VIEWS_DIR = Path(__file__).parent / "views"
MEDIA_TYPES = {".mp4": "video/mp4", ".webm": "video/webm"}
_BUILD_LOCK = threading.Lock()


def write_run_meta(run_dir: Path, adv, policy, cfg) -> None:
    """Write `run.json` + `policy.py` in the shape `build.collect` reads (see orchestrator/run.py).

    Includes the nominal rollout his Replay compares every attack against: one extra rollout at
    run start, free on the mock backend, about 40 s on the real one. Logging never breaks the loop.
    """
    from ants.studio.run import nominal_events

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "policy.py").write_text(policy.code, encoding="utf-8")
    c = adv.config
    meta = {
        "name": run_dir.name,
        "kind": "loop",
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "task": policy.task,
        "policy": {"id": policy.policy_id, "version": policy.version, "path": "policy.py"},
        "backend": c.backend,
        "model": c.model,
        "attacks_planned": cfg.cycles,
        "config": {
            "categories": list(c.categories),
            "eta": c.eta,
            "severity_bound": cfg.rho,
            "rho": 0.8,
            "n_agents": c.n_agents if adv.model else 0,
            "stop_mode": c.stop_mode,
            "min_tests": c.min_tests,
            "tau": c.tau,
            "seed": c.seed,
            "rollout_timeout_s": c.rollout_timeout_s,
            "stall_window": cfg.stall_window,
            "synthesizer": "GenerateSynthesizer",
        },
    }
    try:
        meta["nominal"] = nominal_events(adv, policy, c.seed)
    except Exception as exc:  # noqa: BLE001 -- the Replay shows no nominal comparison instead
        meta["nominal"] = {"outcome": "error", "events": [], "error": str(exc)}
    (run_dir / "run.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")


def mark_finished(run_dir: Path) -> None:
    path = run_dir / "run.json"
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
        meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        path.write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
    except (OSError, ValueError):
        pass


def latest_run(runs_dir: Path | None) -> Path | None:
    """Newest run folder his page can render (it has `run.json`), or None."""
    if runs_dir is None or not runs_dir.is_dir():
        return None
    runs = [d for d in runs_dir.iterdir() if d.is_dir() and (d / "run.json").is_file()]
    return max(runs, key=lambda d: d.name, default=None)


def _built(run_dir: Path) -> Path:
    """`studio.html` for this run, rebuilt only when a log or the template is newer."""
    out = run_dir / "studio.html"
    with _BUILD_LOCK:
        sources = [
            run_dir / n for n in ("run.json", "attacks.jsonl", "loop.jsonl", "summary.json")
        ] + [TEMPLATE, *(run_dir / "policies").glob("*")]
        newest = max((p.stat().st_mtime for p in sources if p.exists()), default=0.0)
        if not out.exists() or out.stat().st_mtime < newest:
            try:
                build(run_dir)
            except (OSError, ValueError, KeyError) as exc:
                # a log line still being written: serve the last good page if there is one
                if not out.exists():
                    raise RuntimeError(str(exc)) from exc
    return out


SWITCH_HTML = """<div class="ants-switch" role="group" aria-label="View">\
<button type="button" data-view="adversary" aria-pressed="true">Adversary</button>\
<button type="button" data-view="synthesizer" aria-pressed="false">Synthesizer</button></div>\
<span class="ants-run" id="ants-run" hidden><span class="badge acc" id="ants-pill"></span>\
<button type="button" class="ants-stop" id="ants-stop" hidden \
title="Stop the whole run">Stop</button></span>"""


def inject(page_html: str) -> str:
    """His page plus the switch. Only the marker and two head/body insertions differ."""
    css = (VIEWS_DIR / "adversary_inject.css").read_text(encoding="utf-8")
    js = (VIEWS_DIR / "adversary_inject.js").read_text(encoding="utf-8")
    head, sep, rest = page_html.partition("</head>")
    out = f"{head}<style>\n{css}</style>\n{sep}" + rest.replace(SWITCH_MARKER, SWITCH_HTML, 1)
    body, sep, tail = out.rpartition("</body>")
    return f"{body}<script>\n{js}</script>\n{sep}{tail}"


def empty_page(message: str) -> str:
    """Same look and same switch when there is no run to show. His template needs data to render."""
    head, _, _ = TEMPLATE.read_text(encoding="utf-8").partition("</head>")
    return inject(
        f'{head}</head>\n<body>\n<header><span class="mono">ANTS Studio</span>{SWITCH_MARKER}'
        f'<div style="flex:1"></div></header>\n'
        f'<div class="ants-empty">{html.escape(message)}</div>\n</body>\n</html>\n'
    )


def page(run_dir: Path | None) -> str:
    if run_dir is None:
        return empty_page(
            "No Adversary run in this session yet. Start one from the Synthesizer view with "
            "/policy-dev; attacks, replay videos and versions appear here as they are logged."
        )
    try:
        return inject(_built(run_dir).read_text(encoding="utf-8"))
    except (OSError, RuntimeError, ValueError) as exc:
        return empty_page(f"This run cannot be rendered yet ({run_dir.name}): {exc}")


def media_path(run_dir: Path | None, rel: str) -> Path | None:
    """A video inside the run folder. Anything else (other types, `..`, symlink escapes): None."""
    if run_dir is None or Path(rel).suffix.lower() not in MEDIA_TYPES:
        return None
    try:
        resolved = (run_dir / rel).resolve()
        resolved.relative_to(run_dir.resolve())
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def media_type(path: Path) -> str:
    return MEDIA_TYPES[path.suffix.lower()]


def byte_range(header: str | None, size: int) -> tuple[int | None, int]:
    """(start, end) inclusive for a `Range: bytes=a-b` header; (None, 0) when unsatisfiable."""
    if not header:
        return (0, size - 1) if size else (None, 0)
    try:
        unit, _, spec = header.partition("=")
        first = spec.split(",")[0].strip()
        a, _, b = first.partition("-")
        if unit.strip() != "bytes":
            return None, 0
        if not a:  # suffix form: the last b bytes
            n = int(b)
            start, end = max(0, size - n), size - 1
        else:
            start = int(a)
            end = min(int(b), size - 1) if b else size - 1
    except ValueError:
        return None, 0
    return (start, end) if 0 <= start <= end else (None, 0)
