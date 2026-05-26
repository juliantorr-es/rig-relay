"""Canonical append-only content-light provider invocation evidence ledger.

Lane C owns this persistence surface. It records every completed
provider invocation as a schema-validated content-light JSONL event.
Never stores prompts, completions, raw bodies, or credentials.

Writes to .build/rig-relay/providers/provider_evidence_events.v1.jsonl
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path

from rig_relay.providers.invocation import (
    ProviderInvocationOutcome,
    assert_content_light,
)

LEDGER_DIR = Path(".build/rig-relay/providers")
LEDGER_FILE = "provider_evidence_events.v1.jsonl"
SCHEMA_VERSION = "rig.relay.provider_invocation_evidence_event.v1"


def _ledger_path() -> Path:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    return LEDGER_DIR / LEDGER_FILE


def _compute_event_digest(event: dict) -> str:
    canonical = json.dumps(event, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def persist_provider_event(
    outcome: ProviderInvocationOutcome,
    *,
    session_id: str = "",
    turn_id: str = "",
    correlation_id: str = "",
) -> str:
    """Persist a content-light provider invocation event to the canonical ledger.

    Returns the event_digest.
    """
    outcome_dict = outcome.to_dict()

    # Content-light guard
    violations = assert_content_light(outcome_dict)
    if violations:
        raise ValueError(f"Content-light violations in provider event: {violations}")

    event_id = _uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "created_at": now,
        "session_id": session_id,
        "turn_id": turn_id,
        "correlation_id": correlation_id,
        "outcome": outcome_dict,
        "event_digest": "",
        "content_light": True,
    }
    event["event_digest"] = _compute_event_digest(event)

    path = _ledger_path()
    line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"

    with open(str(path), "a") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    return event["event_digest"]


def load_provider_events() -> list[dict]:
    """Load all persisted provider evidence events. Read-only."""
    path = _ledger_path()
    if not path.exists():
        return []
    events: list[dict] = []
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


__all__ = [
    "LEDGER_DIR",
    "LEDGER_FILE",
    "load_provider_events",
    "persist_provider_event",
]
