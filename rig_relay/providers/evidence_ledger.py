"""Canonical append-only content-light provider invocation evidence ledger.

Lane C owns this persistence surface. It records every completed
provider invocation as a schema-validated content-light JSONL event.
Never stores prompts, completions, raw bodies, or credentials.

Writes to .build/rig-relay/providers/provider_evidence_events.v1.jsonl
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any
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


def _recompute_event_digest(loaded_event: dict) -> str:
    """Recompute the digest for a loaded event.

    Blanks the stored digest field before recomputation, matching the
    canonical computation rule used at persistence time (where event_digest
    is "" when _compute_event_digest is called).
    """
    event_copy = dict(loaded_event)
    event_copy["event_digest"] = ""
    return _compute_event_digest(event_copy)


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
    """Load all persisted provider evidence events. Read-only.

    Deprecated for authoritative consumption: this loader does not
    schema-validate events, recompute digests, or distinguish corrupt
    entries. Prefer load_verified_provider_events() for application-facing
    query, reporting, and diagnostics consumers.
    """
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


@dataclass
class VerifiedProviderEvent:
    """A single provider evidence event with read-side verification disposition."""

    event: dict[str, Any]
    event_id: str = ""
    event_digest: str = ""
    is_valid: bool = False
    is_corrupt: bool = False
    corruption_kind: str = ""
    corruption_detail: str = ""


@dataclass
class VerifiedLedgerResult:
    """Typed result of verified canonical provider evidence loading.

    Distinguishes valid admitted evidence from corrupt/untrusted entries.
    Content-light: no raw prompts, completions, provider payloads, or secrets.
    """

    events: list[VerifiedProviderEvent] = field(default_factory=list)
    total_lines: int = 0
    valid_events: list[dict[str, Any]] = field(default_factory=list)
    corrupt_events: list[VerifiedProviderEvent] = field(default_factory=list)
    malformed_json_count: int = 0
    schema_invalid_count: int = 0
    digest_mismatch_count: int = 0
    duplicate_event_id_count: int = 0
    duplicate_digest_count: int = 0
    corpus_integrity_verified: bool = False
    corruption_summary: list[str] = field(default_factory=list)


def _process_loaded_line(
    line: str,
    line_index: int,
    seen_ids: set[str],
    seen_digests: set[str],
    result: VerifiedLedgerResult,
) -> None:
    """Parse, validate, digest-recompute, and duplicate-check one ledger line."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError as e:
        result.malformed_json_count += 1
        result.corruption_summary.append(f"Line {line_index + 1}: malformed JSON ({e})")
        v = VerifiedProviderEvent(
            event={},
            is_corrupt=True,
            corruption_kind="malformed_json",
            corruption_detail=f"Line {line_index + 1}: {e}",
        )
        result.events.append(v)
        result.corrupt_events.append(v)
        return

    # Schema validation
    try:
        _validate_event_against_schema(event)
    except (SchemaValidationUnavailableError, ValueError) as e:
        result.schema_invalid_count += 1
        result.corruption_summary.append(
            f"Event {event.get('event_id', '?')}: schema invalid ({e})"
        )
        v = VerifiedProviderEvent(
            event=event,
            event_id=event.get("event_id", ""),
            event_digest=event.get("event_digest", ""),
            is_corrupt=True,
            corruption_kind="schema_invalid",
            corruption_detail=str(e),
        )
        result.events.append(v)
        result.corrupt_events.append(v)
        return

    # Digest recomputation
    stored_digest = event.get("event_digest", "")
    recomputed = _recompute_event_digest(event)
    if recomputed != stored_digest:
        result.digest_mismatch_count += 1
        result.corruption_summary.append(
            f"Event {event.get('event_id', '?')}: digest mismatch"
        )
        v = VerifiedProviderEvent(
            event=event,
            event_id=event.get("event_id", ""),
            event_digest=stored_digest,
            is_corrupt=True,
            corruption_kind="digest_mismatch",
            corruption_detail=f"Stored={stored_digest} Recomputed={recomputed}",
        )
        result.events.append(v)
        result.corrupt_events.append(v)
        return

    # Duplicate detection
    eid = event.get("event_id", "")
    dig = event.get("event_digest", "")
    dups: list[str] = []

    if eid in seen_ids:
        result.duplicate_event_id_count += 1
        dups.append("duplicate event_id")
    if dig in seen_digests:
        result.duplicate_digest_count += 1
        dups.append("duplicate digest")

    if dups:
        result.corruption_summary.append(f"Event {eid}: duplicate ({'; '.join(dups)})")
        v = VerifiedProviderEvent(
            event=event,
            event_id=eid,
            event_digest=dig,
            is_corrupt=True,
            corruption_kind="duplicate",
            corruption_detail="; ".join(dups),
        )
        result.events.append(v)
        result.corrupt_events.append(v)
        return

    seen_ids.add(eid)
    seen_digests.add(dig)
    result.events.append(
        VerifiedProviderEvent(
            event=event, event_id=eid, event_digest=dig, is_valid=True
        )
    )
    result.valid_events.append(event)


def load_verified_provider_events() -> VerifiedLedgerResult:
    """Load and verify every event from the canonical provider evidence ledger.

    Each line is JSON-parsed, schema-validated, and digest-recomputed.
    Malformed lines, schema-invalid events, digest mismatches, and
    duplicate identities are surfaced as corrupt rather than silently
    skipped. Read-only: never mutates the ledger.

    Returns a VerifiedLedgerResult with separate valid/corrupt event lists.
    """
    result = VerifiedLedgerResult()
    path = _ledger_path()
    if not path.exists():
        result.corpus_integrity_verified = True
        return result

    raw_lines = path.read_text("utf-8").splitlines()
    seen_event_ids: set[str] = set()
    seen_digests: set[str] = set()

    for i, line in enumerate(raw_lines):
        line = line.strip()
        if not line:
            continue
        result.total_lines += 1
        _process_loaded_line(line, i, seen_event_ids, seen_digests, result)

    result.corpus_integrity_verified = (
        len(result.corrupt_events) == 0 and result.total_lines > 0
    )
    return result


__all__ = [
    "LEDGER_DIR",
    "LEDGER_FILE",
    "SchemaValidationUnavailableError",
    "VerifiedLedgerResult",
    "VerifiedProviderEvent",
    "load_provider_events",
    "load_verified_provider_events",
    "persist_provider_event",
]
