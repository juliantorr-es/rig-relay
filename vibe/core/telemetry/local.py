from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
) -> None:
    """Write a telemetry event to the local JSONL sink."""
    path = get_observability_log_path(session_id)
    event = {
        "event_name": event_name.replace("vibe.", "rig.relay."),
        "session_id": session_id,
        "parent_session_id": parent_session_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def compute_fingerprint(content: str) -> str:
    """Return a SHA256 fingerprint of the provided content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
