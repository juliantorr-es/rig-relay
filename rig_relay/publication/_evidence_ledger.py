"""Append-only content-light JSONL evidence ledger for publication preview receipts.

Durable persistence with fcntl locking, schema validation, recursive
content-light enforcement, operation-id idempotency, and typed
corruption-communicating reconstruction.
"""

from __future__ import annotations

from datetime import UTC, datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re as _re
from typing import Any

from rig_relay.publication._models import LedgerReconstruction

LEDGER_DIR = Path(".build/rig-relay/publication")
LEDGER_FILE = "publication_preview_evidence.v1.jsonl"
EVENT_SCHEMA_VERSION = "rig.relay.publication_preview_event.v1"

_EVENT_SCHEMA_REL_PATH = (
    "docs/schemas/rig.relay.publication_preview_event.v1.schema.json"
)

_event_schema_cache: dict | None = None


def _resolve_schema_path() -> Path:
    p = Path(_EVENT_SCHEMA_REL_PATH)
    if p.exists():
        return p
    repo_root = Path(__file__).resolve().parent.parent.parent
    return repo_root / _EVENT_SCHEMA_REL_PATH


def _load_event_schema() -> dict:
    global _event_schema_cache
    if _event_schema_cache is not None:
        return _event_schema_cache
    loaded: dict = json.loads(_resolve_schema_path().read_text("utf-8"))
    _event_schema_cache = loaded
    return loaded


def _validate_event_against_schema(event: dict) -> None:
    try:
        import jsonschema
    except ImportError as e:
        raise RuntimeError(
            "Cannot validate publication preview events: jsonschema is not installed"
        ) from e

    try:
        schema = _load_event_schema()
    except FileNotFoundError as e:
        raise RuntimeError(
            "Cannot validate publication preview events: schema file not found"
        ) from e

    try:
        jsonschema.validate(event, schema)
    except jsonschema.ValidationError as e:
        raise ValueError(
            f"Publication preview event failed schema validation: {e.message}"
        ) from e


_FORBIDDEN_FIELD_NAMES: frozenset[str] = frozenset({
    "raw_prompt",
    "raw_completion",
    "raw_file_contents",
    "private_repo_contents",
    "access_token",
    "refresh_token",
    "api_key",
    "api_secret",
    "private_key",
    "oauth_code",
    "secret",
})

_FORBIDDEN_VALUE_PATTERNS: list[tuple[str, _re.Pattern[str]]] = [
    ("github_pat", _re.compile(r"ghp_[A-Za-z0-9]{36}")),
    ("github_oauth", _re.compile(r"gho_[A-Za-z0-9]{36}")),
    ("github_user", _re.compile(r"ghu_[A-Za-z0-9]{36}")),
    ("github_server", _re.compile(r"ghs_[A-Za-z0-9]{36}")),
    ("github_refresh", _re.compile(r"ghr_[A-Za-z0-9]{36}")),
    ("github_classic", _re.compile(r"github_pat_[A-Za-z0-9]{22,}")),
    ("openai_key", _re.compile(r"sk-(?:proj-)?[A-Za-z0-9]{32,}")),
    ("anthropic_key", _re.compile(r"sk-ant-[A-Za-z0-9]{32,}")),
    ("google_api", _re.compile(r"AIza[0-9A-Za-z\-_]{35}")),
    (
        "generic_api_key",
        _re.compile(r"(?:api[_-]?key|apikey)\s*[:=]\s*['\"]?[A-Za-z0-9\-_]{20,}"),
    ),
    ("bearer_token", _re.compile(r"Bearer\s+[A-Za-z0-9\-_\.\+/]{20,}")),
]

_RAW_PATH_PATTERN: _re.Pattern[str] = _re.compile(r"^(/[Uu]sers/|/[Hh]ome/|[A-Z]:\\)")


def _scan_recursive(data: Any, path: str) -> list[str]:
    """Recursively scan any value for forbidden content.

    Checks forbidden field names in dict keys, secret patterns
    in string values, and raw path patterns.
    """
    violations: list[str] = []

    if isinstance(data, dict):
        for key, value in data.items():
            current = f"{path}.{key}" if path else key
            if key.lower() in _FORBIDDEN_FIELD_NAMES:
                violations.append(f"forbidden_key:{current}")
            violations.extend(_scan_recursive(value, current))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            violations.extend(_scan_recursive(item, f"{path}[{i}]"))
    elif isinstance(data, str):
        for label, pattern in _FORBIDDEN_VALUE_PATTERNS:
            if pattern.search(data):
                violations.append(f"secret_pattern:{label} at {path}")
        if _RAW_PATH_PATTERN.search(data):
            violations.append(f"raw_path at {path}")

    return violations


def _assert_content_light(data: dict[str, Any]) -> None:
    violations = _scan_recursive(data, "")
    if violations:
        raise ValueError(f"Receipt contains forbidden content: {violations[:10]}")


class PublicationEvidenceLedger:
    """Append-only JSONL ledger for publication preview evidence events.

    - Schema-validated: every event validates against the event schema
      before append and after reconstruction.
    - Idempotent: same operation_id will not produce a duplicate row.
    - Recursively content-light: forbidden keys, secret patterns, and
      raw paths are rejected from anywhere in the event.
    - Typed reconstruction: corrupted rows are communicated via
      LedgerReconstruction, never silently dropped from authority.
    - Thread-safe and process-safe via fcntl locking.
    """

    def __init__(self, ledger_path: Path | None = None) -> None:
        if ledger_path is None:
            ledger_path = LEDGER_DIR / LEDGER_FILE
        self._path = ledger_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = ledger_path.with_suffix(ledger_path.suffix + ".lock")

    def append_event(self, operation_id: str, receipt_data: dict[str, Any]) -> str:
        """Persist a receipt as a schema-validated content-light event.

        Returns the event_digest for the recorded row.
        If an event with the same operation_id already exists,
        returns the existing event_digest (idempotent).
        """
        _assert_content_light(receipt_data)

        existing_digest = self._find_existing_by_operation_id(operation_id)
        if existing_digest is not None:
            return existing_digest

        event = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "operation_id": operation_id,
            "created_at": datetime.now(UTC).isoformat(),
            "receipt": receipt_data,
        }
        event_digest = _compute_event_digest(event)
        event["event_digest"] = event_digest

        _validate_event_against_schema(event)

        line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"

        with open(self._lock_path, "a") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                with open(self._path, "a") as f:
                    f.write(line)
                    f.flush()
                    os.fsync(f.fileno())
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)

        return event_digest

    def load_receipts(self, authoritative: bool = False) -> LedgerReconstruction:
        """Load all persisted events with integrity verification.

        When authoritative=True, any corruption prevents reconstruction
        (emits warnings and refuse to produce an apparently clean list).
        When authoritative=False (default), corrupt rows are reported
        but valid receipts may be returned alongside corruption metadata.

        Returns a LedgerReconstruction typed result. Consumers MUST
        inspect corruption_detected before treating receipts by
        authority.
        """
        if not self._path.exists():
            return LedgerReconstruction()

        receipts: list[dict[str, Any]] = []
        corrupt_lines: list[int] = []
        total = 0
        valid = 0

        with open(self._path) as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                total += 1

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    corrupt_lines.append(line_num)
                    continue

                try:
                    _validate_event_against_schema(event)
                    _verify_event_digest(event)
                    _assert_content_light(event.get("receipt", event))
                    receipts.append(event.get("receipt", event))
                    valid += 1
                except (ValueError, RuntimeError, KeyError):
                    corrupt_lines.append(line_num)
                    continue

        corrupt_count = len(corrupt_lines)
        corruption_detected = corrupt_count > 0

        warnings: list[str] = []
        if corruption_detected:
            warnings.append(
                f"Ledger {self._path}: {corrupt_count} corrupt/tampered/invalid "
                f"row(s) at lines {corrupt_lines[:10]}"
            )

        if authoritative and corruption_detected:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(
                "Authoritative reconstruction refused: %d corrupt rows in %s",
                corrupt_count,
                self._path,
            )
            return LedgerReconstruction(
                receipts=[],
                total_rows=total,
                valid_rows=0,
                corrupt_rows=corrupt_count,
                corrupt_lines=corrupt_lines,
                corruption_detected=True,
                reconstruction_warnings=[
                    f"Authoritative reconstruction refused: "
                    f"{corrupt_count} corrupt/tampered/invalid row(s) at lines "
                    f"{corrupt_lines[:10]}"
                ],
            )

        return LedgerReconstruction(
            receipts=receipts,
            total_rows=total,
            valid_rows=valid,
            corrupt_rows=corrupt_count,
            corrupt_lines=corrupt_lines,
            corruption_detected=corruption_detected,
            reconstruction_warnings=warnings,
        )

    def count_events(self) -> int:
        """Count persisted events (fast, no full parse)."""
        if not self._path.exists():
            return 0
        count = 0
        with open(self._path) as f:
            for line in f:
                if line.strip():
                    count += 1
        return count

    def _find_existing_by_operation_id(self, operation_id: str) -> str | None:
        """Find an existing event with the given operation_id.

        Returns the event_digest if found, None otherwise.
        Must be called under the fcntl lock for safety.
        """
        if not self._path.exists():
            return None

        target = f'"operation_id":"{operation_id}"'
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if target in line:
                    try:
                        event = json.loads(line)
                        _verify_event_digest(event)
                        return event.get("event_digest", "")
                    except (json.JSONDecodeError, ValueError, KeyError):
                        continue
        return None


def _verify_event_digest(event: dict[str, Any]) -> None:
    stored = event.get("event_digest")
    if stored is None:
        return
    # Preserve event_digest in the dict for schema validation;
    # compute over a copy that excludes it.
    data = {k: v for k, v in event.items() if k != "event_digest"}
    computed_digest = f"sha256:{hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}"
    if stored != computed_digest:
        raise ValueError(
            f"Event integrity failure: stored={stored}, computed={computed_digest}"
        )


def _compute_event_digest(event: dict[str, Any]) -> str:
    data = {k: v for k, v in event.items() if k != "event_digest"}
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"
