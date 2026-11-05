"""Generation attempts of one run, live, for the console: why the model changed the code, the
program diff, the feedback sent back, and the rollout's keyframes.

Same files as `evalkit.report`, which only reads `record.json`, written when a sample ends. This
reads the event log and per-attempt files so attempts appear while generation is still running.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ants.evalkit.report import _why

MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
MAX_FRAMES = 60


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _frames(sample: Path, k: int, root: Path) -> list[dict]:
    frames: list[dict] = []
    for base in sorted((sample / f"debug_attempt{k}").glob("**/media/keyframes")):
        for d in sorted(p for p in base.iterdir() if p.is_dir())[:MAX_FRAMES]:
            img = d / "agentview.png"
            if img.is_file():
                rel = os.path.relpath(img.resolve(), root.resolve()).replace(os.sep, "/")
                frames.append({"label": d.name, "src": rel})
    return frames


def attempts(run_dir: Path | None) -> list[dict]:
    """One row per attempt seen so far, oldest first; empty when there is no generation yet."""
    if run_dir is None:
        return []
    gen = run_dir / "generation"
    rows: dict[tuple[str, int], dict] = {}
    try:
        lines = (gen / "events.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            e = json.loads(line)
            key = (e["arm"], int(e["attempt"]))
        except (ValueError, KeyError):
            continue
        row = rows.setdefault(key, {"arm": key[0], "attempt": key[1]})
        if e.get("kind") == "program":
            row.update(role=e.get("role"), tokens=e.get("tokens"), from_cache=e.get("from_cache"))
            row.update(cache_kind=e.get("cache_kind"), sample=e.get("sample"))
        elif e.get("kind") == "rollout":
            row.update(success=e.get("success"), reason=e.get("reason"), wall_s=e.get("wall_s"))
            row.update(seed=e.get("seed"), sample=e.get("sample"))
    out = []
    for (arm, k), row in sorted(rows.items()):
        if "sample" not in row:
            continue
        sample = gen / arm / f"sample{row['sample']}"
        reply = _text(sample / f"reply_attempt{k}.md")
        raw = _text(sample / f"feedback_attempt{k}.json")
        try:
            feedback = json.loads(raw) if raw else None
        except ValueError:
            feedback = None
        row.update(
            why=_why(reply),
            diff=_text(sample / f"diff_attempt{k}.diff") or "",
            feedback=feedback,
            frames=_frames(sample, k, run_dir),
        )
        out.append(row)
    return out


def media_path(run_dir: Path | None, rel: str) -> Path | None:
    """An image inside the run folder. Anything else (other types, `..`, symlink escapes): None."""
    if run_dir is None or Path(rel).suffix.lower() not in MEDIA:
        return None
    try:
        resolved = (run_dir / rel).resolve()
        resolved.relative_to(run_dir.resolve())
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None
