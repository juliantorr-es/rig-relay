from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from vibe.core.telemetry.local import dump_canonical_json

_RECEIPTS_FILENAME = "receipts.jsonl"
_RECEIPT_SCHEMA_VERSION = "rig.relay.evidence.receipt.v1"


@dataclass(frozen=True, slots=True)
class EvidenceReceipt:
    schema_version: str
    sequence: int
    session_id: str
    event_index: int
    event_name: str
    evidence_kind: str
    evidence_relative_path: str
    evidence_sha256: str
    previous_receipt_sha256: str | None
    receipt_payload_sha256: str
    receipt_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "session_id": self.session_id,
            "event_index": self.event_index,
            "event_name": self.event_name,
            "evidence_kind": self.evidence_kind,
            "evidence_relative_path": self.evidence_relative_path,
            "evidence_sha256": self.evidence_sha256,
            "previous_receipt_sha256": self.previous_receipt_sha256,
            "receipt_payload_sha256": self.receipt_payload_sha256,
            "receipt_sha256": self.receipt_sha256,
        }


def _sha256_prefix(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def build_receipt_payload(
    *,
    sequence: int,
    session_id: str,
    event_index: int,
    event_name: str,
    evidence_kind: str,
    evidence_relative_path: str,
    evidence_sha256: str,
    previous_receipt_sha256: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": _RECEIPT_SCHEMA_VERSION,
        "sequence": sequence,
        "session_id": session_id,
        "event_index": event_index,
        "event_name": event_name,
        "evidence_kind": evidence_kind,
        "evidence_relative_path": evidence_relative_path,
        "evidence_sha256": evidence_sha256,
        "previous_receipt_sha256": previous_receipt_sha256,
    }


def compute_receipt_hashes(payload: dict[str, Any]) -> tuple[str, str]:
    # 1. receipt_payload_sha256: hash of the canonical receipt payload without receipt_sha256.
    # Here, payload doesn't have receipt_payload_sha256 either.
    payload_bytes = dump_canonical_json(payload).encode("utf-8")
    payload_hash = _sha256_prefix(payload_bytes)

    # 2. receipt_sha256: hash of the canonical receipt payload including receipt_payload_sha256 but excluding receipt_sha256.
    full_payload = {**payload, "receipt_payload_sha256": payload_hash}
    full_payload_bytes = dump_canonical_json(full_payload).encode("utf-8")
    receipt_hash = _sha256_prefix(full_payload_bytes)

    return payload_hash, receipt_hash


def create_receipt(
    *,
    sequence: int,
    session_id: str,
    event_index: int,
    event_name: str,
    evidence_kind: str,
    evidence_relative_path: str,
    evidence_sha256: str,
    previous_receipt_sha256: str | None,
) -> EvidenceReceipt:
    payload = build_receipt_payload(
        sequence=sequence,
        session_id=session_id,
        event_index=event_index,
        event_name=event_name,
        evidence_kind=evidence_kind,
        evidence_relative_path=evidence_relative_path,
        evidence_sha256=evidence_sha256,
        previous_receipt_sha256=previous_receipt_sha256,
    )
    payload_hash, receipt_hash = compute_receipt_hashes(payload)
    return EvidenceReceipt(
        **payload, receipt_payload_sha256=payload_hash, receipt_sha256=receipt_hash
    )


def verify_receipt(receipt: EvidenceReceipt) -> bool:
    payload = build_receipt_payload(
        sequence=receipt.sequence,
        session_id=receipt.session_id,
        event_index=receipt.event_index,
        event_name=receipt.event_name,
        evidence_kind=receipt.evidence_kind,
        evidence_relative_path=receipt.evidence_relative_path,
        evidence_sha256=receipt.evidence_sha256,
        previous_receipt_sha256=receipt.previous_receipt_sha256,
    )
    payload_hash, receipt_hash = compute_receipt_hashes(payload)
    return (
        receipt.receipt_payload_sha256 == payload_hash
        and receipt.receipt_sha256 == receipt_hash
    )


def build_session_receipts(
    session_root: Path, session_id: str
) -> list[EvidenceReceipt]:
    session_root = session_root.resolve()
    log_path = session_root / "observability.jsonl"
    if not log_path.is_file():
        return []

    lines = log_path.read_text(encoding="utf-8").splitlines()
    events: list[dict[str, Any]] = []
    for line in lines:
        if line.strip():
            events.append(json.loads(line))

    receipts: list[EvidenceReceipt] = []
    previous_hash: str | None = None
    sequence = 1

    # Map event names to evidence kinds
    kind_map = {
        "rig.relay.artifact.tool_output_written": "tool_result",
        "rig.relay.context.assembly_reported": "context_assembly_report",
        "rig.relay.context.layout_planned": "context_layout_plan",
        "rig.relay.context.shadow_request_assembled": "shadow_request_report",
    }

    for index, event in enumerate(events):
        event_name = event.get("event_name")
        if event_name not in kind_map:
            continue

        payload = event.get("payload", {})
        rel_path = payload.get("evidence_relative_path")
        ev_sha256 = payload.get("evidence_sha256")

        if not rel_path or not ev_sha256:
            continue

        receipt = create_receipt(
            sequence=sequence,
            session_id=session_id,
            event_index=index,
            event_name=event_name,
            evidence_kind=kind_map[event_name],
            evidence_relative_path=rel_path,
            evidence_sha256=ev_sha256,
            previous_receipt_sha256=previous_hash,
        )
        receipts.append(receipt)
        previous_hash = receipt.receipt_sha256
        sequence += 1

    return receipts


def write_session_receipts(session_root: Path, session_id: str) -> Path:
    session_root = session_root.resolve()
    receipts = build_session_receipts(session_root, session_id)
    receipts_path = session_root / _RECEIPTS_FILENAME

    lines = [dump_canonical_json(r.to_dict()) for r in receipts]
    temp_path = receipts_path.with_suffix(".jsonl.tmp")
    temp_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    temp_path.replace(receipts_path)
    return receipts_path


def load_receipts(session_root: Path) -> list[EvidenceReceipt]:
    receipts_path = session_root / _RECEIPTS_FILENAME
    if not receipts_path.is_file():
        return []

    lines = receipts_path.read_text(encoding="utf-8").splitlines()
    receipts: list[EvidenceReceipt] = []
    for line in lines:
        if not line.strip():
            continue
        data = json.loads(line)
        receipts.append(EvidenceReceipt(**data))
    return receipts
