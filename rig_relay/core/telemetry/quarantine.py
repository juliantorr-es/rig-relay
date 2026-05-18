from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

from rig_relay.core.telemetry.local import dump_canonical_json


def is_debug_packet(event_name: str) -> bool:
    return event_name.startswith(("debug.", "rig.relay.debug."))


def _quarantine_file_path(quarantine_root: Path, session_id: str) -> Path:
    return quarantine_root / session_id / "debug_quarantine.jsonl"


def _hash_packet(packet: dict) -> str:
    raw = dump_canonical_json(packet)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def write_debug_packet(packet: dict, quarantine_root: Path, session_id: str) -> Path:
    file_path = _quarantine_file_path(quarantine_root, session_id)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    new_line = dump_canonical_json(packet) + "\n"
    tmp = file_path.with_suffix(file_path.suffix + ".tmp")
    if file_path.exists():
        existing = file_path.read_text(encoding="utf-8")
    else:
        existing = ""
    tmp.write_text(existing + new_line, encoding="utf-8")
    tmp.rename(file_path)
    return file_path


def list_quarantined_packets(quarantine_root: Path, session_id: str) -> list[dict]:
    file_path = _quarantine_file_path(quarantine_root, session_id)
    if not file_path.exists():
        return []
    packets: list[dict] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            packets.append(json.loads(line))
    return packets


def get_quarantine_summary(quarantine_root: Path, session_id: str) -> dict:
    file_path = _quarantine_file_path(quarantine_root, session_id)
    if not file_path.exists():
        return {
            "session_id": session_id,
            "packet_count": 0,
            "total_bytes": 0,
            "quarantined_at": None,
            "file_path": str(file_path),
            "packet_hashes": [],
            "redaction_status": "n/a",
        }
    packets = list_quarantined_packets(quarantine_root, session_id)
    total_bytes = file_path.stat().st_size
    hashes = [_hash_packet(p) for p in packets]
    redacted_count = sum(1 for p in packets for v in p.values() if v == "[REDACTED]")
    return {
        "session_id": session_id,
        "packet_count": len(packets),
        "total_bytes": total_bytes,
        "quarantined_at": datetime.now(UTC).isoformat(),
        "file_path": str(file_path),
        "packet_hashes": hashes,
        "redacted_field_count": redacted_count,
        "redaction_status": "verified" if redacted_count == 0 else "present",
    }


def quarantine_debug_export_allowed(share_level: str) -> bool:
    return share_level == "debug_opt_in"
