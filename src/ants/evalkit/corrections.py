"""Signature-keyed correction store: past gate-accepted repairs, retrieved by failure.

A correction is written only when the regression gate accepts a candidate that fixed
its triggering case. Retrieval keys on the failure signature alone (never the program
or prompt), so a repair found for one program can be offered for another; the
generator still writes a new program and the gate still judges it. Records are JSONL;
loading keeps the newest copy of each ``correction_id`` so counter updates are
append-only. Writers reject held-out records.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ants.contracts import Constraint


def _bucket(value: object) -> str:
    if isinstance(value, bool) or value is None:
        return "unknown"
    if isinstance(value, (int, float)):
        magnitude = abs(float(value))
        for bound in (0.0, 0.005, 0.02, 0.05):
            if magnitude <= bound:
                return f"<={bound:g}"
        return ">0.05"
    if isinstance(value, dict):
        parts = [f"{k}:{_bucket(v)}" for k, v in sorted(value.items())]
        return ",".join(parts) if parts else "unknown"
    if isinstance(value, list):
        return ",".join(_bucket(v) for v in value) if value else "unknown"
    return str(value)


@dataclass(frozen=True)
class FailureSignature:
    """Stable features of a failure; volatile detail (steps, wording, poses) is dropped."""

    primitive: str = "unknown"
    status: str = "unknown"
    termination: str = "unknown"
    deviation: str = "unknown"

    def key(self, level: int) -> str:
        if level <= 1:
            return self.status
        if level == 2:
            return f"{self.primitive}|{self.status}"
        return f"{self.primitive}|{self.status}|{self.deviation}|{self.termination}"

    def as_dict(self) -> dict[str, str]:
        return {
            "primitive": self.primitive,
            "status": self.status,
            "termination": self.termination,
            "deviation": self.deviation,
        }


def signature_from_trace(fb: dict) -> FailureSignature:
    """Trace signature of a failed rollout, from `adversary.rollout.feedback` output."""
    failed = fb.get("failed_calls") or []
    first = failed[0] if failed else {}
    return FailureSignature(
        primitive=str(first.get("tool") or "unknown"),
        status=str(first.get("status") or fb.get("termination_reason") or "unknown"),
        termination=str(fb.get("termination_reason") or "unknown"),
        deviation=_bucket(first.get("final_position_error_m")),
    )


def make_correction(
    constraint: Constraint,
    fb: dict,
    trigger_case_id: str,
    parent_id: str,
    repaired_id: str,
    repair_diff: str,
    gate: dict,
    epoch: int,
    split: str = "acceptance",
) -> dict:
    """Build the record written at gate acceptance for one diagnosed failure."""
    if split != "acceptance":
        raise ValueError("corrections may only be written from the acceptance split")
    sig = signature_from_trace(fb)
    correction_id = hashlib.sha256(
        f"{sig.key(3)}\n{constraint.rule}\n{repair_diff}".encode()
    ).hexdigest()[:12]
    return {
        "correction_id": correction_id,
        "signature": sig.as_dict(),
        "signature_keys": {"l1": sig.key(1), "l2": sig.key(2), "l3": sig.key(3)},
        "constraint_id": constraint.constraint_id,
        "failure_signature": constraint.failure_signature,
        "when_to_apply": constraint.when_to_apply,
        "rule": constraint.rule,
        "repair_diff": repair_diff,
        "trigger_case": trigger_case_id,
        "parent_policy": parent_id,
        "repaired_policy": repaired_id,
        "evidence": list(constraint.evidence),
        "gate": gate,
        "status": "admitted",
        "split": split,
        "help_count": 0,
        "hurt_count": 0,
        "retrieved_count": 0,
        "created_epoch": epoch,
    }


class CorrectionStore:
    """Append-only JSONL store; `load` folds updates by keeping the newest copy."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def append(self, record: dict) -> None:
        if record.get("split") != "acceptance":
            raise ValueError("corrections may only be written from the acceptance split")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        newest: dict[str, dict] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            newest[record.get("correction_id", "")] = record
        return [r for cid, r in newest.items() if cid]

    def bump(
        self,
        correction_id: str,
        *,
        help_delta: int = 0,
        hurt_delta: int = 0,
        retrieved_delta: int = 0,
    ) -> None:
        """Append an updated copy with adjusted counters (the audit trail keeps both)."""
        for record in self.load():
            if record["correction_id"] == correction_id:
                updated = dict(record)
                updated["help_count"] = int(record.get("help_count", 0)) + help_delta
                updated["hurt_count"] = int(record.get("hurt_count", 0)) + hurt_delta
                updated["retrieved_count"] = int(record.get("retrieved_count", 0)) + retrieved_delta
                self.append(updated)
                return


def retrieve_corrections(
    records: list[dict], fb: dict, k: int = 2
) -> tuple[list[dict], list[dict]]:
    """Corrections for this failure signature, best level first (L3, then L2, then L1).

    Returns ``(chosen, candidates)``; candidates carry level and score for logging and
    the viewer, including records that were filtered out or beyond the ``k`` cap.
    """
    sig = signature_from_trace(fb)
    candidates: list[dict] = []
    for record in records:
        keys = record.get("signature_keys") or {}
        level = next((lv for lv in (3, 2, 1) if keys.get(f"l{lv}") == sig.key(lv)), None)
        eligible = (
            record.get("status") in ("admitted", "verified")
            and record.get("split") == "acceptance"
            and level is not None
        )
        help_n, hurt_n = int(record.get("help_count", 0)), int(record.get("hurt_count", 0))
        # Wilson-style caution: one lucky help must not outrank a proven record.
        score = (level or 0) + (help_n - hurt_n) / (help_n + hurt_n + 2)
        candidates.append(
            {
                "correction_id": record.get("correction_id", ""),
                "level": level,
                "score": round(score, 3),
                "eligible": eligible,
                "status": record.get("status", ""),
                "rule": record.get("rule", ""),
                "help_count": help_n,
                "hurt_count": hurt_n,
            }
        )
    ranked = sorted(
        (c for c in candidates if c["eligible"]),
        key=lambda c: (-c["level"], -c["score"], c["correction_id"]),
    )
    by_id = {r["correction_id"]: r for r in records}
    chosen = [by_id[c["correction_id"]] for c in ranked[:k]]
    return chosen, sorted(candidates, key=lambda c: -(c["score"] or -1))
