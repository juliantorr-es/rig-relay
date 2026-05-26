"""Canonical append-only content-light provider invocation evidence ledger.

Lane C owns this persistence surface. It records every completed
provider invocation as a schema-validated content-light JSONL event.
Never stores prompts, completions, raw bodies, or credentials.

Writes to .build/rig-relay/providers/provider_evidence_events.v1.jsonl
"""

from __future__ import annotations

from datetime import UTC, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import uuid as _uuid

from rig_relay.providers.invocation import (
    ProviderInvocationOutcome,
    assert_content_light,
)

LEDGER_DIR = Path(".build/rig-relay/providers")
LEDGER_FILE = "provider_evidence_events.v1.jsonl"
SCHEMA_VERSION = "rig.relay.provider_invocation_evidence_event.v1"
_SCHEMA_REL_PATH = (
    "docs/schemas/rig.relay.provider_invocation_evidence_event.v1.schema.json"
)
_schema_cache: dict | None = None


def _resolve_schema_path() -> Path:
    p = Path(_SCHEMA_REL_PATH)
    if p.exists():
        return p
    repo_root = Path(__file__).resolve().parent.parent.parent
    return repo_root / _SCHEMA_REL_PATH


def _load_schema() -> dict:
    """Load the provider evidence schema, cached after first call.

    Raises FileNotFoundError if the schema file is missing.
    """
    global _schema_cache
    cached = _schema_cache
    if cached is not None:
        return cached
    _schema_cache = json.loads(_resolve_schema_path().read_text("utf-8"))
    return _schema_cache  # type: ignore[return-value]


class SchemaValidationUnavailableError(RuntimeError):
    """Raised when canonical schema validation cannot be performed."""


def _validate_event_against_schema(event: dict) -> None:
    """Validate an event against the canonical provider evidence schema.

    Fail-closed: refuses persistence on any unavailability of the
    validation apparatus. No event enters the canonical ledger without
    passing schema validation.

    Raises:
        SchemaValidationUnavailableError: jsonschema library missing or
            schema file absent.
        ValueError: event failed schema validation.
    """
    try:
        import jsonschema
    except ImportError:
        raise SchemaValidationUnavailableError(
            "Cannot validate provider evidence events: jsonschema is not installed"
        ) from None

    try:
        schema = _load_schema()
    except FileNotFoundError:
        raise SchemaValidationUnavailableError(
            "Cannot validate provider evidence events: schema file not found"
        ) from None

    try:
        jsonschema.validate(event, schema)
    except jsonschema.ValidationError as e:
        raise ValueError(
            f"Provider evidence event failed schema validation: {e.message}"
        ) from e


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
    now = datetime.now(UTC).isoformat()
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

    # Schema validation at append boundary
    _validate_event_against_schema(event)

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
    "SchemaValidationUnavailableError",
    "load_provider_events",
    "persist_provider_event",
]
