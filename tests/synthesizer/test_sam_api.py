import argparse
import json

import pytest

from ants.synthesizer.sam_api import (
    DEFAULT_SAM_MODEL,
    SAM_CHOICES,
    Sam31Client,
    add_sam_model_arg,
    boxes_to_mask,
    decode_mask_payload,
    normalize_sam_model,
    parse_output_text,
)

# Exact record grammar observed from the live sam-3.1 call on a LIBERO frame
# (agentview 800x512, prompt "bowl"); mask payload shortened, structure kept.
REAL_BOWL = (
    "<0f>0<|box;x1=437;y1=270;x2=525;y2=339;w=800;h=512|><|mask;x=0;y=0;data=70,89,~ABCDEF|>\\n"
)


def test_normalize():
    assert normalize_sam_model("sam3") == "sam3"
    assert normalize_sam_model("sam3.1") == "sam-3.1"
    assert normalize_sam_model("sam-3.1") == "sam-3.1"
    with pytest.raises(ValueError):
        normalize_sam_model("sam4")


def test_flag_defaults_to_sam3():
    p = argparse.ArgumentParser()
    add_sam_model_arg(p)
    assert p.parse_args([]).sam_model == "sam3"
    assert set(SAM_CHOICES) == {"sam3", "sam3.1"}
    assert DEFAULT_SAM_MODEL == "sam3"
    assert p.parse_args(["--sam-model", "sam3.1"]).sam_model == "sam3.1"


def test_parse_real_record_shape():
    recs = parse_output_text(REAL_BOWL)
    assert len(recs) == 1
    rec = recs[0]
    assert (rec["frame"], rec["object_id"]) == (0, 0)
    assert rec["box"] == {"x1": 437, "y1": 270, "x2": 525, "y2": 339, "w": 800, "h": 512}
    assert rec["masks"][0]["encoding"] == "lossless"
    assert (rec["masks"][0]["width"], rec["masks"][0]["height"]) == (70, 89)
    assert rec["confidence"] is None


def test_parse_multi_object_and_confidence():
    text = (
        "<0f>0<|box;x1=1;y1=2;x2=3;y2=4;w=10;h=10;c=0.94|>"
        "<|mask;x=1;y=2;data=2,2,!XYZ|>"
        "<0f>1<|box;x1=5;y1=5;x2=6;y2=6;w=10;h=10|>"
    )
    recs = parse_output_text(text)
    assert [r["object_id"] for r in recs] == [0, 1]
    assert recs[0]["confidence"] == pytest.approx(0.94)
    assert recs[0]["masks"][0]["encoding"] == "one_bit"
    assert recs[1]["masks"] == [] and recs[1]["confidence"] is None


def test_boxes_to_mask_inclusive_edges():
    grid = boxes_to_mask([{"box": {"x1": 1, "y1": 1, "x2": 2, "y2": 2}}], 4, 4)
    assert sum(sum(row) for row in grid) == 4  # 2x2: x2/y2 are inclusive
    assert grid[0][0] is False and grid[1][1] is True
    grid = boxes_to_mask([{"box": None}], 4, 4)
    assert sum(sum(row) for row in grid) == 0


def test_pixel_decoder_is_explicit_followup():
    with pytest.raises(NotImplementedError, match="mask_kind=.box"):
        decode_mask_payload("ABC", 2, 2, "lossless")


def test_client_uses_cache_without_network(tmp_path, monkeypatch):
    monkeypatch.delenv("META_API_KEY", raising=False)
    c = Sam31Client(tmp_path / "c", tmp_path / "l.jsonl")
    payload = {
        "status": "completed",
        "output": [{"content": [{"type": "output_text", "text": REAL_BOWL}]}],
    }
    (tmp_path / "c").mkdir()
    import hashlib

    key = hashlib.sha256(c.model.encode() + b"\x00" + b"arm" + b"\x00" + b"img").hexdigest()[:24]
    (tmp_path / "c" / f"{key}.json").write_text(json.dumps(payload), encoding="utf-8")
    out = c.segment_png(b"img", "arm", tag="t")
    assert out["from_cache"] is True and out["mask_kind"] == "box"
    assert out["records"][0]["box"]["x1"] == 437
    assert json.loads((tmp_path / "l.jsonl").read_text(encoding="utf-8"))["tag"] == "t"
