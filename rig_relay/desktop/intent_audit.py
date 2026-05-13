"""Rig Relay Desktop Intent Audit Trail.

Durable, content-light audit events and result artifacts for the Desktop
Intent API. Writes to .build/rig-relay/desktop/intents/.

All entries are content-light: no raw prompts, model outputs, source code,
stdout/stderr bodies, diffs, secrets, or raw private paths.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any
import uuid

from rig_relay.evidence.redaction import assert_remote_safe

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_INTENTS_DIR = REPO_ROOT / ".build" / "rig-relay" / "desktop" / "intents"

EVENT_NAMES = frozenset({
    "desktop.intent.received",
    "desktop.intent.completed",
    "desktop.intent.refused",
    "desktop.intent.failed",
})


def _intents_dir(build_root: Path | None = None) -> Path:
    root = build_root or DEFAULT_INTENTS_DIR
    return root


def _events_path(build_root: Path | None = None) -> Path:
    return _intents_dir(build_root) / "intent_events.jsonl"


def _results_dir(build_root: Path | None = None) -> Path:
    d = _intents_dir(build_root) / "intent_results"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sha256_json(data: dict[str, Any]) -> str:
    """Compute SHA256 of the JSON bytes of a dict (sorted keys for determinism)."""
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _write_event(event: dict[str, Any], build_root: Path | None = None) -> None:
    """Append an event to the JSONL event log."""
    path = _events_path(build_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True, default=str) + "\n")


def _write_result_artifact(
    result: dict[str, Any], build_root: Path | None = None
) -> None:
    """Write a result artifact as an atomic JSON file."""
    d = _results_dir(build_root)
    result = assert_remote_safe(result)
    intent_id = str(result.get("intent_id", "unknown"))
    path = d / f"{intent_id}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    try:
        tmp.rename(path)
    except FileNotFoundError:
        # Another process already wrote and renamed; that's fine.
        pass


def build_event(
    event_name: str, intent_id: str, intent_name: str, status: str, **extra: Any
) -> dict[str, Any]:
    """Build a content-light intent audit event dict.

    Args:
        event_name: One of desktop.intent.received/completed/refused/failed.
        intent_id: Matches the intent_id from the request.
        intent_name: Name of the intent.
        status: Final status of the intent execution.
        **extra: Optional fields (dry_run, authorization_required, result_kind,
            output_ref_count, projection_seq, result_sha256, warnings, build_root).

    Returns:
        Content-light event dict.
    """
    if event_name not in EVENT_NAMES:
        msg = f"Unknown event name: {event_name}. Allowed: {sorted(EVENT_NAMES)}"
        raise ValueError(msg)

    return {
        "schema_version": "rig.relay.desktop_intent_event.v1",
        "event_id": f"evt_{uuid.uuid4().hex[:12]}",
        "intent_id": intent_id,
        "intent_name": intent_name,
        "event_name": event_name,
        "status": status,
        "dry_run": extra.get("dry_run", True),
        "authorization_required": extra.get("authorization_required", False),
        "result_kind": extra.get("result_kind", "summary"),
        "output_ref_count": extra.get("output_ref_count", 0),
        "projection_seq": extra.get("projection_seq", 0),
        "result_sha256": extra.get("result_sha256", ""),
        "created_at": datetime.now(UTC).isoformat(),
        "authorization_receipt_sha256": extra.get("authorization_receipt_sha256", ""),
        "authorization_action": extra.get("authorization_action", ""),
        "authorization_status": extra.get("authorization_status", ""),
        "authorization_expires_at": extra.get("expires_at", ""),
        "authorization_method": extra.get("method", ""),
        "warnings": extra.get("warnings", []),
    }


def emit_received(request: dict[str, Any], build_root: Path | None = None) -> None:
    """Emit a received event for an intent request."""
    event = build_event(
        event_name="desktop.intent.received",
        intent_id=str(request.get("intent_id", "unknown")),
        intent_name=str(request.get("intent_name", "unknown")),
        status="received",
        dry_run=bool(request.get("dry_run", True)),
        projection_seq=int(request.get("projection_seq", 0)),
    )
    _write_event(event, build_root)


def emit_result(result: dict[str, Any], build_root: Path | None = None) -> str:
    """Emit a completed/refused/failed event and write result artifact.

    Args:
        result: The intent result dict.
        build_root: Override build root path.

    Returns:
        The SHA256 of the result artifact.
    """
    result_sha256 = _sha256_json(result)

    status = str(result.get("status", "unknown"))
    event_name_map: dict[str, str] = {
        "completed": "desktop.intent.completed",
        "refused": "desktop.intent.refused",
        "failed": "desktop.intent.failed",
    }
    event_name = event_name_map.get(status, "desktop.intent.completed")

    warnings = result.get("warnings")
    if warnings is None:
        warnings = []

    event = build_event(
        event_name=event_name,
        intent_id=str(result.get("intent_id", "unknown")),
        intent_name=str(result.get("intent_name", "unknown")),
        status=status,
        dry_run=bool(result.get("dry_run", True)),
        authorization_required=bool(result.get("authorization_required", False)),
        result_kind=str(result.get("result_kind", "summary")),
        output_ref_count=len(result.get("output_refs", [])),
        result_sha256=result_sha256,
        authorization_receipt_sha256=result.get("authorization_receipt_sha256", ""),
        authorization_action=result.get("authorization_action", ""),
        authorization_status=result.get("authorization_status", ""),
        expires_at=result.get("expires_at", ""),
        method=result.get("method", ""),
        warnings=warnings,
    )

    _write_event(event, build_root)
    # Strip raw receipt body from artifact before writing
    artifact_result = {k: v for k, v in result.items() if k != "authorization_receipt"}
    _write_result_artifact(artifact_result, build_root)
    return result_sha256


def count_events(build_root: Path | None = None) -> dict[str, int]:
    """Count events by event_name in the intent event log."""
    path = _events_path(build_root)
    if not path.is_file():
        return {}
    counts: dict[str, int] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                name = str(event.get("event_name", "unknown"))
                counts[name] = counts.get(name, 0) + 1
            except json.JSONDecodeError:
                continue
    return counts


def list_result_artifacts(build_root: Path | None = None) -> list[Path]:
    """List result artifact files."""
    d = _results_dir(build_root)
    return sorted(d.glob("*.json"))
