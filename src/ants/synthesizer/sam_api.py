"""SAM model selection: SAM 3 (in-harness) or SAM 3.1 (Meta Model API).

Default is ``sam3``, which is exactly today's behavior: segmentation runs inside
ASPIRE's harness (``segment_text``, ``localize_object``, planner ``curobo-sam3``).
``sam3.1`` routes segmentation through the Meta Model API model ``sam-3.1``
(``POST {base_url}/responses``) wherever ANTS owns the call site — currently the
cuRobo planner masking in ``tools/aspire_launch.py`` (mode ``curobo-sam31``).

Programs that run inside ASPIRE's program sandbox cannot reach the network (the
sandbox allowlists only ``import math``), so in-sandbox ``segment_text`` stays on
SAM 3 until ASPIRE gains its own 3.1 provider. The requested model is still
recorded in run metadata so cached ``sam-3.1`` responses can be re-decoded later
without spending again.

Wire shape (measured against the live API): the request is
``{"model": "sam-3.1", "input": [{"role": "user", "content": [
{"type": "input_text", "text": prompt},
{"type": "input_image", "image_url": "data:image/png;base64,..."}]}]}``.
Each answer is one ``output_text`` string of records like
``<0f>0<|box;x1=437;y1=270;x2=525;y2=339;w=800;h=512|><|mask;x=0;y=0;data=70,89,~...|>``.
Box edges are inclusive (``x2 == right - 1`` of the half-open box). Mask payloads
are the API's base85 + arithmetic-coded rasters (``~`` lossless, ``!`` one-bit);
pixel decoding is a named follow-up (port ``@meta-sam/parser``), so this module
rasterizes record boxes and labels such masks ``mask_kind="box"``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from ants.synthesizer.llm import META_BASE_URL

SAM_CHOICES = ("sam3", "sam3.1")
DEFAULT_SAM_MODEL = "sam3"
SAM31_MODEL_ID = "sam-3.1"
SAM31_API_KEY_ENV = "META_API_KEY"

_BOX_RE = re.compile(r"<\|box;([^|]*)\|>")
_MASK_RE = re.compile(r"<\|mask;([^|]*)\|>")
_RECORD_RE = re.compile(r"<(\d+)f>(\d+)((?:<\|(?:box|mask);[^|]*\|>)*)")
_FIELDS_RE = re.compile(r"([a-z0-9_]+)=([^;]*)")


def normalize_sam_model(value: str) -> str:
    """Canonical model id: ``sam3`` stays, ``sam3.1``/``sam-3.1`` become ``sam-3.1``."""
    v = value.strip().lower()
    if v == "sam3":
        return "sam3"
    if v in ("sam3.1", "sam-3.1"):
        return "sam-3.1"
    raise ValueError(f"unknown SAM model {value!r} (expected one of {SAM_CHOICES})")


def add_sam_model_arg(parser) -> None:  # argparse.ArgumentParser without the import
    """Add the shared ``--sam-model`` flag (default ``sam3``, today's behavior)."""
    parser.add_argument(
        "--sam-model", default=DEFAULT_SAM_MODEL, choices=list(SAM_CHOICES),
        help="sam3: segmentation inside ASPIRE (default, unchanged); "
        "sam3.1: Meta Model API model sam-3.1 wherever ANTS owns the call site",
    )  # fmt: skip


def _fields(token: str) -> dict:
    out = {}
    for m in _FIELDS_RE.finditer(token):
        out[m.group(1)] = m.group(2)
    return out


def _num(token: dict, key: str) -> int:
    return int(float(token[key]))


def parse_output_text(text: str) -> list[dict]:
    """Parse one ``sam-3.1`` output_text into records (box + optional mask tokens).

    Returns ``[{"frame": int, "object_id": int, "box": {...} | None,
    "masks": [{"x": int, "y": int, "width": int, "height": int,
    "encoding": "lossless" | "one_bit", "payload": str}], "confidence": float | None}]``.
    Box ``x2``/``y2`` are inclusive pixel edges; ``right = x2 + 1``.
    """
    records = []
    for m in _RECORD_RE.finditer(text):
        frame, obj, tokens = int(m.group(1)), int(m.group(2)), m.group(3)
        box, masks, conf = None, [], None
        bm = _BOX_RE.search(tokens)
        if bm:
            f = _fields(bm.group(1))
            box = {
                "x1": _num(f, "x1"), "y1": _num(f, "y1"),
                "x2": _num(f, "x2"), "y2": _num(f, "y2"),
                "w": _num(f, "w"), "h": _num(f, "h"),
            }  # fmt: skip
            if "c" in f:
                conf = float(f["c"])
        for mm in _MASK_RE.finditer(tokens):
            f = _fields(mm.group(1))
            data = f.get("data", "")
            width, height, payload, encoding = 0, 0, data, "lossless"
            parts = data.split(",", 2)
            if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                width, height = int(parts[0]), int(parts[1])
                rest = parts[2]
                if rest[:1] == "!":
                    encoding = "one_bit"
                else:
                    encoding = "lossless"
                payload = rest[1:] if rest[:1] in ("~", "!") else rest
            masks.append({
                "x": _num(f, "x") if "x" in f else 0,
                "y": _num(f, "y") if "y" in f else 0,
                "width": width, "height": height,
                "encoding": encoding, "payload": payload,
            })  # fmt: skip
            if "c" in f and conf is None:
                conf = float(f["c"])
        records.append({
            "frame": frame, "object_id": obj, "box": box, "masks": masks,
            "confidence": conf,
        })  # fmt: skip
    return records


def boxes_to_mask(records: list[dict], height: int, width: int) -> list[list[bool]]:
    """Union of record boxes as a row-major bool grid (box approximation of masks).

    Pixel decoding of ``mask.payload`` is a follow-up (port of ``@meta-sam/parser``);
    until then callers use this and must record ``mask_kind="box"`` next to results.
    """
    grid = [[False] * width for _ in range(height)]
    for rec in records:
        box = rec.get("box")
        if not box:
            continue
        x1 = max(0, box["x1"])
        y1 = max(0, box["y1"])
        x2 = min(width - 1, box["x2"])  # x2/y2 are inclusive edges
        y2 = min(height - 1, box["y2"])
        for y in range(y1, y2 + 1):
            row = grid[y]
            for x in range(x1, x2 + 1):
                row[x] = True
    return grid


def decode_mask_payload(payload: str, width: int, height: int, encoding: str):
    """Pixel-decode one mask payload. Not implemented yet (needs network to fetch code)."""
    raise NotImplementedError(
        "pixel decoding of sam-3.1 mask payloads needs a port of the MIT-licensed "
        "@meta-sam/parser mask codec (base85 + arithmetic coding); offline snapshots "
        f"cannot fetch it (encoding={encoding}, raster={width}x{height}). "
        "Use boxes_to_mask() with mask_kind='box' until then; raw output_text is "
        "cached so re-decoding later costs nothing."
    )


@dataclass
class Sam31Client:
    """Thin ``sam-3.1`` client on the Meta Model API Responses endpoint.

    Responses are cached on disk by (model, prompt, image sha256) and logged to a
    JSONL ledger. Only uncached calls hit the network.
    """

    cache_dir: Path
    ledger: Path
    model: str = SAM31_MODEL_ID
    base_url: str = META_BASE_URL
    api_key_env: str = SAM31_API_KEY_ENV
    timeout_s: float = 300.0
    _calls: int = field(default=0, repr=False)

    def segment_png(self, png_bytes: bytes, prompt: str, tag: str = "") -> dict:
        """Segment one PNG image for ``prompt``; returns ``{"records", "raw", ...}``."""
        key = hashlib.sha256(
            self.model.encode() + b"\x00" + prompt.encode() + b"\x00" + png_bytes
        ).hexdigest()[:24]
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            from_cache = True
        else:
            data = self._post(png_bytes, prompt)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
            from_cache = False
            self._calls += 1
        text = _output_text(data)
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "model": self.model,
                "tag": tag, "cache_key": key, "from_cache": from_cache,
                "prompt": prompt,
                "image_sha256": hashlib.sha256(png_bytes).hexdigest(),
                "images_processed": ((data.get("usage") or {}).get("images_processed")),
            }) + "\n")  # fmt: skip
        return {
            "records": parse_output_text(text),
            "raw": text,
            "from_cache": from_cache,
            "mask_kind": "box",
        }

    def _post(self, png_bytes: bytes, prompt: str) -> dict:
        body = json.dumps(
            {
                "model": self.model,
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            {
                                "type": "input_image",
                                "image_url": "data:image/png;base64,"
                                + base64.b64encode(png_bytes).decode("ascii"),
                            },
                        ],
                    }
                ],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/responses", data=body,
            headers={"Authorization": f"Bearer {os.environ[self.api_key_env]}",
                     "Content-Type": "application/json"},
        )  # fmt: skip
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))


def _output_text(data: dict) -> str:
    if data.get("status") not in (None, "completed"):
        raise RuntimeError(f"sam-3.1 response not completed: {data.get('status')!r}")
    texts = []
    for item in data.get("output") or []:
        for part in item.get("content") or []:
            if part.get("type") == "output_text" and part.get("text"):
                texts.append(part["text"])
    if not texts:
        raise RuntimeError(f"sam-3.1 response has no output_text: {str(data)[:300]}")
    return "".join(texts)
