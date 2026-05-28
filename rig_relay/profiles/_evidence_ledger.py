"""Canonical append-only content-light Y3 profile evidence ledger.

Records profile resolution, capability evidence, and context envelope
assembly events as schema-validated content-light JSONL events.
Never stores prompts, completions, raw bodies, or credentials.

Writes to .build/rig-relay/profiles/y3_profile_evidence_events.v1.jsonl
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum, auto
import fcntl
import hashlib
import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.core.logger import logger

LEDGER_DIR_NAME = ".build/rig-relay/profiles"
LEDGER_FILE_NAME = "y3_profile_evidence_events.v1.jsonl"
SCHEMA_VERSION = "rig.relay.y3_profile_event.v1"


def _ledger_dir() -> Path:
    return Path.cwd() / LEDGER_DIR_NAME


def _ledger_path() -> Path:
    p = _ledger_dir()
    p.mkdir(parents=True, exist_ok=True)
    return p / LEDGER_FILE_NAME


class Y3ProfileEventKind(StrEnum):
    PROFILE_REGISTERED = auto()
    PROFILE_DEPRECATED = auto()
    PROFILE_SUPERSEDED = auto()
    CAPABILITY_EVIDENCE_OBSERVED = auto()
    CAPABILITY_EVIDENCE_DECLARED = auto()
    CAPABILITY_EVIDENCE_RESOLVED = auto()
    PROFILE_RESOLUTION_ATTEMPTED = auto()
    PROFILE_SELECTED = auto()
    PROFILE_REFUSED = auto()
    USER_OVERRIDE_SELECTED = auto()
    CONTEXT_ENVELOPE_ASSEMBLED = auto()
    SESSION_RESOLUTION_EMITTED = auto()
    PROFILE_EVALUATION_OBSERVATION_EMITTED = auto()


class Y3ProfileEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.y3_profile_event.v1"
    event_id: str
    event_kind: Y3ProfileEventKind
    session_id: str = ""
    task_id: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    provider: str = ""
    model_id: str = ""
    profile_id: str = ""
    profile_digest: str = ""
    task_role: str = ""
    resolution_outcome: str = ""
    capability_evidence_digest: str = ""
    context_envelope_digest: str = ""
    governance_admission_digest: str = ""
    session_receipt_digest: str = ""
    evaluation_digest: str = ""
    warnings: list[str] = Field(default_factory=list)
    content_light: bool = True
    event_digest: str = ""

    def compute_digest(self) -> str:
        data = self.model_dump(exclude={"event_digest"})
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def persist_y3_event(
    event: Y3ProfileEvent, store_root: str | Path | None = None
) -> str:
    """Append a Y3 event to the canonical evidence ledger. Returns event digest."""
    if event.event_digest:
        event = event.model_copy(update={"event_digest": ""})
    digest = event.compute_digest()
    event = event.model_copy(update={"event_digest": digest})

    if store_root is None:
        ledger_path = _ledger_path()
    else:
        root = Path(store_root)
        root.mkdir(parents=True, exist_ok=True)
        ledger_path = root / LEDGER_FILE_NAME

    line = event.model_dump_json() + "\n"

    with open(str(ledger_path), "a") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    return digest


def load_y3_events(store_root: str | Path | None = None) -> list[Y3ProfileEvent]:
    """Load all events from ledger. Returns list (may be empty)."""
    if store_root is None:
        ledger_path = _ledger_path()
    else:
        root = Path(store_root)
        ledger_path = root / LEDGER_FILE_NAME

    if not ledger_path.exists():
        return []

    events: list[Y3ProfileEvent] = []
    for line in ledger_path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(Y3ProfileEvent.model_validate_json(line))
        except Exception:
            logger.warning(
                "Failed to parse Y3 event line from ledger path=%s", ledger_path
            )
            continue
    return events


def verify_y3_ledger_integrity(
    store_root: str | Path | None = None,
) -> tuple[bool, list[dict]]:
    """Verify all events: parse JSON, check required fields, recompute digests.

    Returns (ok, [corrupt_event_info, ...]).
    """
    if store_root is None:
        ledger_path = _ledger_path()
    else:
        root = Path(store_root)
        ledger_path = root / LEDGER_FILE_NAME

    if not ledger_path.exists():
        return True, []

    corrupt: list[dict] = []
    for line_idx, line in enumerate(
        ledger_path.read_text("utf-8").splitlines(), start=1
    ):
        line = line.strip()
        if not line:
            continue

        try:
            event = Y3ProfileEvent.model_validate_json(line)
        except Exception as e:
            corrupt.append({"line": line_idx, "error": f"parse failure: {e}"})
            continue

        stored_digest = event.event_digest
        recomputed = event.compute_digest()
        if stored_digest != recomputed:
            corrupt.append({
                "line": line_idx,
                "event_id": event.event_id,
                "error": f"digest mismatch: stored={stored_digest} recomputed={recomputed}",
            })

    ok = len(corrupt) == 0
    return ok, corrupt
