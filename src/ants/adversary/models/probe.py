"""Find out how the Meta Model API selects Muse Spark's reasoning modes. Costs a few cents.

    uv run python -m ants.adversary.models.probe            # list models, try candidate settings
    uv run python -m ants.adversary.models.probe --dry-run  # show what would be sent

Sends one short question per candidate setting and prints whether the API accepted it, the
reasoning tokens it spent and the time it took. Put an accepted setting into
`EffortSetting.extra` in `meta.py`. Needs META_API_KEY in the environment or in `.env`.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from ants.adversary.models.meta import DEFAULT_MODEL, META_BASE_URL, load_dotenv

QUESTION = "A 0.4 kg bowl sits on a table. Name one way it could slip from a two-finger grasp."
CANDIDATES: list[tuple[str, dict]] = [
    ("baseline", {}),
    ("reasoning_effort=low", {"reasoning_effort": "low"}),
    ("reasoning_effort=medium", {"reasoning_effort": "medium"}),
    ("reasoning_effort=high", {"reasoning_effort": "high"}),
    ("reasoning.effort=high", {"reasoning": {"effort": "high"}}),
    ("mode=instant", {"mode": "instant"}),
    ("mode=thinking", {"mode": "thinking"}),
    ("mode=contemplating", {"mode": "contemplating"}),
]


def _request(url: str, key: str, body: dict | None) -> tuple[int, dict | str, float]:
    req = urllib.request.Request(
        url,
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8")), time.time() - t0
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:200], time.time() - t0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--base-url", default=META_BASE_URL)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    load_dotenv(Path(".env"))
    key = os.environ.get("META_API_KEY", "")
    if args.dry_run:
        for name, extra in CANDIDATES:
            print(f"{name:26s} {json.dumps(extra)}")
        return 0
    if not key:
        print("META_API_KEY is not set (environment or .env)")
        return 2

    status, models, _ = _request(f"{args.base_url}/models", key, None)
    if status == 200 and isinstance(models, dict):
        print("models:", ", ".join(m.get("id", "?") for m in models.get("data", [])))
    else:
        print(f"GET /models -> {status}")

    print(f"\n{'setting':26s} {'HTTP':>4s} {'reasoning tok':>13s} {'completion':>10s} {'s':>6s}")
    for name, extra in CANDIDATES:
        body = {
            "model": args.model,
            "messages": [{"role": "user", "content": QUESTION}],
            **extra,
        }
        status, data, secs = _request(f"{args.base_url}/chat/completions", key, body)
        if status == 200 and isinstance(data, dict):
            usage = data.get("usage") or {}
            reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", "?")
            print(
                f"{name:26s} {status:>4d} {reasoning!s:>13s} "
                f"{usage.get('completion_tokens', '?')!s:>10s} {secs:6.1f}"
            )
        else:
            print(f"{name:26s} {status:>4d}  rejected: {str(data)[:80]}")
    print("\nA setting that is accepted and changes the reasoning tokens selects a mode.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
