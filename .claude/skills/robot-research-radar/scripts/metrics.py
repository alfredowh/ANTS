"""Fetch popularity metrics for research works: citations and GitHub stars.

Citations come from Semantic Scholar (one source, so counts are comparable).
Stars, license and last push come from the GitHub API. Results are cached on
disk so repeated runs do not hit the rate limits again.

Usage (stdlib only):
    uv run python .claude/skills/robot-research-radar/scripts/metrics.py \
        --arxiv 2607.00272 2603.22435 --github NVlabs/ASPIRE capgym/cap-x
    uv run python .claude/skills/robot-research-radar/scripts/metrics.py \
        --title "Code as Policies: Language Model Programs for Embodied Control"
    uv run python .claude/skills/robot-research-radar/scripts/metrics.py --file items.json

`--file` takes a JSON list of {"arxiv": ..., "github": ..., "title": ...} objects
and prints the same list with a "metrics" field added.

Set S2_API_KEY or GITHUB_TOKEN in the environment for higher rate limits.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CACHE_PATH = Path.home() / ".cache" / "robot-research-radar" / "metrics.json"
CACHE_TTL_DAYS = 7
S2_FIELDS = "title,year,citationCount,venue,authors,externalIds,url"


def _today() -> str:
    return dt.date.today().isoformat()


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_cache(cache: dict) -> None:
    # Several processes may share the cache: merge with what is on disk, then
    # replace atomically so a concurrent reader never sees a half-written file.
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        merged = {**_load_cache(), **cache}
    except json.JSONDecodeError:
        merged = cache
    tmp = CACHE_PATH.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(merged, indent=1), encoding="utf-8")
    tmp.replace(CACHE_PATH)


def _fresh(entry: dict) -> bool:
    queried = dt.date.fromisoformat(entry["queried"])
    return (dt.date.today() - queried).days < CACHE_TTL_DAYS


def _get_json(
    url: str, headers: dict[str, str], retries: int = 6, body: dict | None = None
) -> dict | list | None:
    delay = 2.0
    data = json.dumps(body).encode("utf-8") if body is not None else None
    for _ in range(retries):
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "User-Agent": "robot-research-radar",
                "Content-Type": "application/json",
                **headers,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return None
            if err.code in (403, 429, 500, 502, 503):
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except urllib.error.URLError:
            time.sleep(delay)
            delay *= 2
    return {"error": "rate_limited_or_unreachable"}


def _s2_headers() -> dict[str, str]:
    return {"x-api-key": os.environ["S2_API_KEY"]} if os.environ.get("S2_API_KEY") else {}


def _s2_value(data: dict) -> dict:
    return {
        "citations": data.get("citationCount"),
        "s2_title": data.get("title"),
        "year": data.get("year"),
        "venue": data.get("venue") or None,
        "first_author": (data.get("authors") or [{}])[0].get("name"),
        "arxiv": (data.get("externalIds") or {}).get("ArXiv"),
        "s2_url": data.get("url"),
    }


def norm_arxiv(value: str) -> str:
    m = re.search(r"\d{4}\.\d{4,5}", value)
    return m.group(0) if m else value.strip()


def norm_repo(value: str) -> str:
    repo = re.sub(r"^https?://github\.com/", "", value.strip()).strip("/")
    return "/".join(repo.split("/")[:2])


def prefetch_arxiv(ids: list[str], cache: dict) -> set[str]:
    """Fill the cache for many arXiv ids with the batch endpoint (one request per 400 ids).

    Returns the ids the batch endpoint answered, found or not, so callers can skip
    slow one-by-one lookups for ids Semantic Scholar does not know.
    """
    answered: set[str] = set()
    todo = sorted({a for a in ids if not (f"s2:{a}" in cache and _fresh(cache[f"s2:{a}"]))})
    for i in range(0, len(todo), 400):
        chunk = todo[i : i + 400]
        url = f"https://api.semanticscholar.org/graph/v1/paper/batch?fields={S2_FIELDS}"
        data = _get_json(url, _s2_headers(), retries=8, body={"ids": [f"arXiv:{a}" for a in chunk]})
        if not isinstance(data, list):
            continue
        answered.update(chunk)
        for arxiv_id, paper in zip(chunk, data, strict=False):
            if paper and paper.get("citationCount") is not None:
                cache[f"s2:{arxiv_id}"] = {"queried": _today(), "value": _s2_value(paper)}
    return answered


def semantic_scholar(*, arxiv: str | None = None, title: str | None = None) -> dict:
    headers = _s2_headers()
    if arxiv:
        url = f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv}?fields={S2_FIELDS}"
        data = _get_json(url, headers)
    elif title:
        q = urllib.parse.quote(title)
        url = f"https://api.semanticscholar.org/graph/v1/paper/search/match?query={q}&fields={S2_FIELDS}"
        data = _get_json(url, headers)
        if data and "data" in data:
            data = data["data"][0] if data["data"] else None
    else:
        return {}
    if not data or "error" in data:
        return {"citations": None, "s2_error": (data or {}).get("error", "not_found")}
    return _s2_value(data)


def github(repo: str) -> dict:
    repo = repo.removeprefix("https://github.com/").strip("/")
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    data = _get_json(f"https://api.github.com/repos/{repo}", headers)
    if not data or "error" in data:
        return {"stars": None, "gh_error": (data or {}).get("error", "not_found")}
    return {
        "stars": data.get("stargazers_count"),
        "license": (data.get("license") or {}).get("spdx_id"),
        "pushed_at": (data.get("pushed_at") or "")[:10],
        "archived": data.get("archived"),
    }


def metrics_for(item: dict, cache: dict, answered: frozenset[str] = frozenset()) -> dict:
    out: dict = {}
    arxiv = norm_arxiv(str(item["arxiv"])) if item.get("arxiv") else None
    paper_key = f"s2:{arxiv or item.get('title')}"
    if arxiv or item.get("title"):
        if paper_key in cache and _fresh(cache[paper_key]):
            out.update(cache[paper_key]["value"])
        elif arxiv in answered:
            out.update({"citations": None, "s2_error": "not_found"})
        else:
            value = semantic_scholar(arxiv=arxiv, title=item.get("title"))
            if value.get("citations") is not None:
                cache[paper_key] = {"queried": _today(), "value": value}
            out.update(value)
            time.sleep(1.1)  # unauthenticated S2 allows about 1 request per second
    if item.get("github"):
        gh_key = f"gh:{norm_repo(item['github'])}"
        if gh_key in cache and _fresh(cache[gh_key]):
            out.update(cache[gh_key]["value"])
        else:
            value = github(norm_repo(item["github"]))
            if value.get("stars") is not None:
                cache[gh_key] = {"queried": _today(), "value": value}
            out.update(value)
    out["queried"] = _today()
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--arxiv", nargs="*", default=[])
    parser.add_argument("--github", nargs="*", default=[])
    parser.add_argument("--title", nargs="*", default=[])
    parser.add_argument("--file", type=Path)
    args = parser.parse_args(argv)

    items: list[dict] = []
    if args.file:
        loaded = json.loads(args.file.read_text(encoding="utf-8"))
        items = loaded["works"] if isinstance(loaded, dict) else loaded
    items += [{"arxiv": a} for a in args.arxiv]
    items += [{"title": t} for t in args.title]
    items += [{"github": g} for g in args.github]

    cache = _load_cache()
    try:
        ids = [norm_arxiv(str(i["arxiv"])) for i in items if i.get("arxiv")]
        answered = frozenset(prefetch_arxiv(ids, cache))
        for item in items:
            item["metrics"] = metrics_for(item, cache, answered)
    finally:
        _save_cache(cache)
    json.dump(items, sys.stdout, indent=1)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
