from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vibe import __version__
from pydantic import BaseModel


class ContextAccounting(BaseModel):
    model: str
    call_type: str
    message_id: str | None
    total_messages: int
    total_chars: int
    estimated_tokens: int
    by_role: dict[str, int]
    largest_messages: list[dict[str, Any]]
    system_prompt_chars: int
    tool_result_chars: int
    user_message_chars: int
    assistant_message_chars: int
    stable_prefix_fingerprint: str
    dynamic_suffix_fingerprint: str


def get_observability_log_path(session_id: str) -> Path:
    """Return the path to the local observability JSONL log for a session."""
    base = Path(".rig") / "relay" / "sessions" / session_id
    base.mkdir(parents=True, exist_ok=True)
    return base / "observability.jsonl"


def log_local_event(
    session_id: str,
    event_name: str,
    payload: dict[str, Any],
    parent_session_id: str | None = None,
    receipt_candidate: bool = False,
) -> None:
    """Write a telemetry event to the local JSONL sink with a formal envelope."""
    path = get_observability_log_path(session_id)

    # 1. Determine sequence (simple line count)
    sequence = 0
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                sequence = sum(1 for _ in f)
        except Exception:
            sequence = 0

    # 2. Normalize event name (bridge legacy to rig.relay.*)
    normalized_name = event_name
    if normalized_name.startswith("vibe."):
        normalized_name = normalized_name.replace("vibe.", "rig.relay.")
    if not normalized_name.startswith("rig.relay."):
        normalized_name = f"rig.relay.{normalized_name}"

    # 3. Build the formal envelope
    event = {
        "schema_version": "rig.relay.observability.v1",
        "event_id": str(uuid.uuid4()),
        "session_id": session_id,
        "parent_session_id": parent_session_id,
        "sequence": sequence,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "event_name": normalized_name,
        "payload": payload,
        "producer": {
            "name": "rig-relay",
            "version": __version__,
        },
        "receipt_candidate": receipt_candidate,
    }

    # 4. Hash the event contents (excluding the hash itself)
    event_str = json.dumps(event, sort_keys=True)
    event["event_hash"] = hashlib.sha256(event_str.encode("utf-8")).hexdigest()

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def compute_fingerprint(content: str) -> str:
    """Return a SHA256 fingerprint of the provided content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
