"""Merge research-radar JSON sources into documents for the radar artifact's database.

Usage (stdlib only):
    uv run python .claude/skills/robot-research-radar/scripts/radar.py build \
        --in labs_industry.json labs_universities.json workspace_works.json blocks.json \
        --out <dir>
    uv run python .claude/skills/robot-research-radar/scripts/radar.py pending --dump <dir>

`build` dedupes works (by arXiv id, then GitHub repo, then normalised title),
merges their labs and fields, ranks labs, and writes:
    <dir>/orgs/<id>.json, <dir>/works/<id>.json   one file per database document
    <dir>/batches.json                            lists of <=50 ArtifactData batch writes
    <dir>/summary.json                            counts and the lab ranking
Inputs are {"orgs": [...], "works": [...]} objects or bare lists of works.

`pending` reads an ArtifactData export (`list` with `out_dir`) and prints the
works whose status is "draft" or "queued", i.e. the ones a sync must verify.

Lab score (documented so the ranking is reproducible):
    sum over the lab's works of  ln(1 + citations) + 0.5 * ln(1 + stars)
                                 (each GitHub repo counted once per lab)
                                 + 1.0 if year >= 2025
Labs are ranked by score, highest first, across all types.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
from difflib import SequenceMatcher
from pathlib import Path

WORK_FIELDS = (
    "title",
    "short_name",
    "org_ids",
    "orgs_display",
    "year",
    "venue",
    "arxiv",
    "url",
    "github",
    "citations",
    "stars",
    "metrics_date",
    "solves",
    "limitation",
    "outlook",
    "ants_blocks",
    "ants_fit_score",
    "ants_fit_reason",
    "gpu_note",
    "tier",
    "workspace_ref",
    "review",
    "unverified",
    "unverified_fields",
    "note",
)
BATCH_SIZE = 50
# Fields whose being unverified makes the whole entry a draft (a guessed limitation does not).
CORE_FIELDS = {"title", "arxiv", "github"}
# Block numbers used by the module radar (module-radar.md (dev note, not in repo)).
BLOCK_NUMBERS = {
    1: "human-video-to-robot",
    2: "perception",
    3: "perception",
    4: "demo-to-spec",
    5: "policy-synthesis",
    6: "primitives-grasp-motion",
    7: "policy-synthesis",
    8: "verification",
    9: "memory-skills",
    10: "simulation",
    11: "escalation",
}
# Lab name variants seen in sources, mapped to one org id.
ORG_ALIASES = {
    "deepmind": "gdm",
    "google": "gdm",
    "google-research": "gdm",
    "google-deepmind": "gdm",
    "google-deepmind-robotics": "gdm",
    "uc-berkeley": "berkeley",
    "stanford-university": "stanford",
    "mit-csail": "mit",
    "massachusetts-institute-of-technology": "mit",
    "carnegie-mellon-university": "cmu",
    "university-of-washington": "uw",
    "ut-austin": "utaustin",
    "university-of-texas-at-austin": "utaustin",
    "meta-fair": "meta",
    "fair": "meta",
    "nvidia-research": "nvidia",
    "national-university-of-singapore": "nus",
    "imperial-college-london": "imperial",
    "tsinghua-university": "tsinghua",
    "peking-university": "pku",
    "university-of-illinois-urbana-champaign": "uiuc",
    "university-of-michigan": "umich",
    "university-of-pennsylvania": "upenn",
    "georgia-tech": "gatech",
    "toyota-research-institute": "tri",
    "hugging-face": "hf",
    "huggingface": "hf",
    "physical-intelligence": "pi",
    "shanghai-ai-lab": "shai",
    "shanghai-ai-laboratory": "shai",
    "eth-zurich": "eth",
    "tu-darmstadt": "tudarmstadt",
}
# Labs that listed works credit but the crawl did not profile: (name, type).
STUB_ORGS = {
    "agentai": ("AgentAI Co., Ltd.", "company"),
    "beihang": ("Beihang University", "university"),
    "bit": ("Beijing Institute of Technology", "university"),
    "caltech": ("Caltech", "university"),
    "cuhk": ("Chinese University of Hong Kong", "university"),
    "fudan": ("Fudan University", "university"),
    "hello-robot": ("Hello Robot", "company"),
    "hust": ("Huazhong University of Science and Technology", "university"),
    "idea": ("IDEA Research", "institute"),
    "lehigh": ("Lehigh University", "university"),
    "machenta": ("Machenta", "company"),
    "metric-ai-lab": ("Metric AI Lab", "company"),
    "mondragon": ("Mondragon University", "university"),
    "nist": ("NIST", "institute"),
    "northeastern": ("Northeastern University", "university"),
    "oxford": ("University of Oxford", "university"),
    "polimi": ("Politecnico di Milano", "university"),
    "szu": ("Shenzhen University", "university"),
    "tiktok": ("TikTok", "company"),
    "toronto": ("University of Toronto", "university"),
    "umass": ("UMass Amherst", "university"),
    "umich": ("University of Michigan", "university"),
    "x-square-robot": ("X Square Robot", "company"),
}


def slug(text: str) -> str:
    s = re.sub(r"https?://", "", str(text).lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:80] or "item"


def org_id(name: str) -> str:
    sid = slug(name)
    return ORG_ALIASES.get(sid, sid)


def resolve_display_orgs(works: list[dict], orgs: list[dict]) -> None:
    """Give works that only name their labs ("orgs_display") org ids that exist."""
    by_name = {slug(o["name"]): o["id"] for o in orgs} | {o["id"]: o["id"] for o in orgs}
    for w in works:
        if w["org_ids"]:
            continue
        ids = []
        for name in w.get("orgs_display") or []:
            clean = re.sub(r"\(.*?\)", "", name).strip()
            sid = org_id(clean)
            hit = by_name.get(sid) or by_name.get(slug(clean))
            if not hit:  # "NVIDIA GEAR" -> nvidia, "Stanford IRIS" -> stanford
                hit = next((v for k, v in by_name.items() if sid.startswith(k + "-")), None)
            if hit:
                ids.append(hit)
        w["org_ids"] = list(dict.fromkeys(ids))


def norm_title(title: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (title or "").lower())[:60]


def norm_github(gh: str | None) -> str | None:
    if not gh:
        return None
    gh = re.sub(r"^https?://github\.com/", "", gh.strip()).strip("/")
    return "/".join(gh.split("/")[:2]) or None


def norm_arxiv(ax: str | None) -> str | None:
    if not ax:
        return None
    m = re.search(r"(\d{4}\.\d{4,5})", str(ax))
    return m.group(1) if m else None


def load_sources(paths: list[Path]) -> tuple[list[dict], list[dict]]:
    orgs, works = [], []
    for p in paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            works += data
        else:
            orgs += data.get("orgs", [])
            works += data.get("works", [])
    return orgs, works


def titles_match(s2_title: str, title: str, short_name: str | None) -> bool:
    words = lambda t: {x for x in re.findall(r"[a-z0-9]+", t.lower()) if len(x) > 2}  # noqa: E731
    a, b = words(s2_title), words(title)
    if a and b and len(a & b) / min(len(a), len(b)) >= 0.5:
        return True
    short = norm_title(short_name)
    if short and len(short) >= 3 and short in norm_title(s2_title):
        return True
    return SequenceMatcher(None, norm_title(s2_title), norm_title(title)).ratio() >= 0.6


def flatten_metrics(w: dict) -> dict:
    """Prefer fresh metrics over values carried in the source, and check the arXiv id.

    If Semantic Scholar's title for the given arXiv id does not match the work's title,
    the id is probably wrong: its citations are dropped and the entry becomes a draft.
    """
    m = w.pop("metrics", None) or {}
    s2_title = m.get("s2_title") or w.get("s2_title")
    if s2_title and w.get("title") and not titles_match(s2_title, w["title"], w.get("short_name")):
        w["unverified"] = True
        w["unverified_fields"] = list({*(w.get("unverified_fields") or []), "arxiv"})
        w["note"] = f"Semantic Scholar title for this arXiv id: {s2_title}"
        m.pop("citations", None)
        w["citations"] = None
    for src, dst in (("citations", "citations"), ("stars", "stars"), ("queried", "metrics_date")):
        if m.get(src) is not None:
            w[dst] = m[src]
    return w


def merge_into(base: dict, extra: dict) -> None:
    for key in WORK_FIELDS:
        val = extra.get(key)
        if val in (None, "", []):
            continue
        if key in ("org_ids", "orgs_display", "ants_blocks"):
            base[key] = list(dict.fromkeys((base.get(key) or []) + list(val)))
        elif key in ("citations", "stars", "ants_fit_score"):
            base[key] = max(base.get(key) or 0, val) if base.get(key) is not None else val
        elif key == "workspace_ref" and base.get(key) and val not in base[key]:
            base[key] = f"{base[key]}; {val}"
        elif base.get(key) in (None, "", []):
            base[key] = val


def dedupe_works(works: list[dict]) -> list[dict]:
    merged: list[dict] = []
    index: dict[str, dict] = {}
    for raw in works:
        w = flatten_metrics(dict(raw))
        w["ants_blocks"] = [
            BLOCK_NUMBERS.get(b, b) if isinstance(b, int) else b
            for b in (w.get("ants_blocks") or [])
        ]
        if w.get("orgs") and not w.get("org_ids"):
            w["orgs_display"] = list(w["orgs"])
        w["arxiv"] = norm_arxiv(w.get("arxiv"))
        w["github"] = norm_github(w.get("github"))
        keys = [
            k
            for k in (
                f"ax:{w['arxiv']}" if w["arxiv"] else None,
                f"gh:{w['github'].lower()}" if w["github"] else None,
                f"t:{norm_title(w.get('title'))}" if w.get("title") else None,
            )
            if k
        ]
        hit = next((index[k] for k in keys if k in index), None)
        if hit is None:
            hit = {k: None for k in WORK_FIELDS}
            merged.append(hit)
        merge_into(hit, w)
        for k in keys:
            index[k] = hit
    for w in merged:
        w["id"] = slug(w["arxiv"] or w["github"] or w["short_name"] or w["title"])
        fields = set(w.get("unverified_fields") or [])
        core_unverified = w.get("unverified") and (not fields or fields & CORE_FIELDS)
        w["status"] = "draft" if core_unverified else "verified"
        w["source"] = "seed-crawl"
        w["org_ids"] = list(dict.fromkeys(org_id(o) for o in (w.get("org_ids") or [])))
    seen: dict[str, int] = {}
    for w in merged:  # distinct ids even when two short names collide
        n = seen.get(w["id"], 0)
        seen[w["id"]] = n + 1
        if n:
            w["id"] = f"{w['id']}-{n + 1}"
    return merged


def merge_orgs(orgs: list[dict], works: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for o in orgs:
        oid = org_id(o.get("id") or o["name"])
        cur = by_id.setdefault(oid, {"id": oid})
        for k, v in o.items():
            if k != "id" and v not in (None, "", []) and cur.get(k) in (None, "", []):
                cur[k] = v
    for o in by_id.values():
        score = 0.0
        repos: set[str] = set()  # a repo shared by several works (openpi, lerobot) counts once
        for w in works:
            if o["id"] in (w.get("org_ids") or []):
                score += math.log1p(w.get("citations") or 0)
                if w.get("github") and w["github"].lower() not in repos:
                    repos.add(w["github"].lower())
                    score += 0.5 * math.log1p(w.get("stars") or 0)
                score += 1.0 if (w.get("year") or 0) >= 2025 else 0.0
        o["score"] = round(score, 2)
        o.setdefault("groups", [])
        o["source"] = "seed-crawl"
    ranked = sorted(by_id.values(), key=lambda o: -o["score"])
    for i, o in enumerate(ranked, 1):
        o["rank"] = i
    return ranked


def build(args: argparse.Namespace) -> None:
    orgs, works = load_sources(args.inputs)
    works = dedupe_works(works)
    orgs = merge_orgs(orgs, works)
    resolve_display_orgs(works, orgs)
    orgs = merge_orgs(
        [{k: v for k, v in o.items() if k not in ("score", "rank")} for o in orgs], works
    )
    known = {o["id"] for o in orgs}
    stubs = [
        {
            "id": sid,
            "name": name,
            "type": typ,
            "stub": True,
            "why_ranked": "Credited on a listed work; not profiled by the crawl.",
        }
        for sid, (name, typ) in STUB_ORGS.items()
        if sid not in known and any(sid in w["org_ids"] for w in works)
    ]
    if stubs:
        base = [{k: v for k, v in o.items() if k not in ("score", "rank")} for o in orgs]
        orgs = merge_orgs(base + stubs, works)
        known = {o["id"] for o in orgs}
    out: Path = args.out
    for sub in ("orgs", "works"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    writes = []
    for coll, docs in (("orgs", orgs), ("works", works)):
        for d in docs:
            doc = {k: v for k, v in d.items() if k != "id" and v is not None}
            path = (out / coll / f"{d['id']}.json").resolve()
            path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
            writes.append(
                {"op": "set", "collection": coll, "doc_id": d["id"], "file_path": str(path)}
            )
    batches = [writes[i : i + BATCH_SIZE] for i in range(0, len(writes), BATCH_SIZE)]
    (out / "batches.json").write_text(json.dumps(batches, indent=1), encoding="utf-8")
    orphans = sorted({o for w in works for o in w["org_ids"] if o not in known})
    summary = {
        "built": dt.date.today().isoformat(),
        "orgs": len(orgs),
        "works": len(works),
        "batches": len(batches),
        "ranking": [(o["rank"], o["id"], o["score"]) for o in orgs],
        "org_ids_without_org_entry": orphans,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k != "ranking"}
            | {"top10": summary["ranking"][:10]},
            indent=1,
        )
    )


def pending(args: argparse.Namespace) -> None:
    rows = []
    for p in sorted(Path(args.dump).rglob("*.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        data = doc.get("data", doc)
        if data.get("status") in ("draft", "queued"):
            rows.append(
                {
                    "doc_id": p.stem,
                    "version": doc.get("version"),
                    "url": data.get("url"),
                    "title": data.get("title"),
                    "status": data.get("status"),
                }
            )
    print(json.dumps(rows, indent=1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--in", dest="inputs", nargs="+", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("pending")
    p.add_argument("--dump", type=Path, required=True)
    args = parser.parse_args(argv)
    {"build": build, "pending": pending}[args.cmd](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
