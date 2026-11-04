"""Live process-flow panel: the blocks file stays truthful and the panel is wired in."""

import json
from pathlib import Path

from ants.studio.console_server import STATIC_FILES, _assemble_shell

ROOT = Path(__file__).resolve().parents[2]
DATA = json.loads((ROOT / "docs" / "studio" / "process-flow-blocks.json").read_text("utf-8"))
BLOCKS = {b["id"]: b for b in DATA["blocks"]}


def test_every_pipeline_stage_has_a_top_level_block():
    assert set(DATA["stages"]) == {
        "video",
        "extract",
        "demospec",
        "prompt",
        "generate",
        "nominal",
        "review",
        "attack",
        "diagnose",
        "rewrite",
        "gate",
        "deploy",
    }
    for stage in DATA["stages"]:
        assert BLOCKS[stage]["stage"] == stage and "pos" in BLOCKS[stage]


def test_hierarchy_and_edges_are_consistent():
    seen: dict[str, str] = {}
    for b in DATA["blocks"]:
        for child in b["children"]:
            assert child in BLOCKS, child
            assert child not in seen, f"{child} has two parents"
            seen[child] = b["id"]
    assert len({(b["pos"]["col"], b["pos"]["row"]) for b in DATA["blocks"] if "pos" in b}) == sum(
        "pos" in b for b in DATA["blocks"]
    )
    for e in DATA["edges"]:
        assert "pos" in BLOCKS[e["from"]] and "pos" in BLOCKS[e["to"]]


def test_planned_blocks_can_never_light_up():
    planned = [b for b in DATA["blocks"] if b["status"] == "planned"]
    assert planned
    for b in planned:
        assert "stage" not in b and not b.get("inherit") and b["live"]["signal"] == "static"


def test_attack_inner_steps_are_grouped_not_sequential():
    for child in BLOCKS["attack"]["children"]:
        assert BLOCKS[child]["inherit"] is True
        assert BLOCKS[child]["live"]["signal"] == "grouped"
        assert "stage" not in BLOCKS[child]


def test_code_and_doc_references_exist():
    for b in DATA["blocks"]:
        for ref in b["code"] + b["docs"]:
            if ref.startswith("hurobo/"):  # a submodule, not always checked out
                continue
            assert (ROOT / ref).exists(), f"{b['id']}: {ref}"


def test_no_production_view_exists():
    js = STATIC_FILES["flow.js"].read_text("utf-8")
    assert "production" not in json.dumps(DATA).lower().replace("there is no production view", "")
    assert "production" not in js.lower()


def test_panel_is_mounted_above_the_feed_and_served():
    page = _assemble_shell()
    assert page.index('id="flow-panel"') < page.index('id="turns"')
    assert "/static/flow.js" in page and "/static/flow.css" in page
    for name in ("flow.js", "flow.css", "flow_blocks.json"):
        assert STATIC_FILES[name].exists()
