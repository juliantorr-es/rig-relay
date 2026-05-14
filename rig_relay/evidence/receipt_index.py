"""Tool receipt evidence index — content-light query/replay surface.

Reads session observability JSONL, filters for `rig.relay.tool_receipt.captured`
events, and returns a list of structured, content-light index records.

All index records are content-light: no raw stdout, stderr, file contents,
diffs, snippets, old/new text, or replacement text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from vibe.core.telemetry.constants import EventName
from vibe.core.telemetry.local import get_observability_log_path

TOOL_RECEIPT_INDEX_SCHEMA_VERSION = "rig.relay.tool_receipt_index.v1"

# ── Forbidden field patterns ──────────────────────────────────────────

FORBIDDEN_RAW_FIELD_NAMES: tuple[str, ...] = (
    "stdout",
    "stderr",
    "output",
    "content",
    "diff",
    "snippet",
    "old",
    "new",
    "replacement_text",
    "file_contents",
    "old_text",
    "new_text",
)

# ── Index model ───────────────────────────────────────────────────────


class ToolReceiptIndexRecord(BaseModel):
    """Content-light indexed receipt record.

    Contains no raw tool output, file contents, diffs, snippets, or
    secrets — only metadata, hashes, byte counts, and structured
    error classification.

    Fields are populated from ``rig.relay.tool_receipt.captured`` events
    in the session's local observability JSONL.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = TOOL_RECEIPT_INDEX_SCHEMA_VERSION
    session_id: str
    event_name: str = EventName.TOOL_RECEIPT_CAPTURED
    event_id: str | None = None
    captured_at: str | None = None
    tool_name: str
    invocation_id: str | None = None
    status: str | None = None
    error_kind: str | None = None
    refusal_reason: str | None = None
    changed: bool | None = None
    path: str | None = None
    before_sha256: str | None = None
    after_sha256: str | None = None
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None
    stdout_bytes: int | None = None
    stderr_bytes: int | None = None
    duration_ms: float | None = None
    receipt_schema_version: str | None = None


# ── Summary model ─────────────────────────────────────────────────────


@dataclass
class ReceiptIndexSummary:
    """Compact summary of a receipt index."""

    total_events: int = 0
    by_tool: dict[str, int] = field(default_factory=dict)
    by_status: dict[str, int] = field(default_factory=dict)
    mutation_count: int = 0
    refusal_count: int = 0
    timeout_count: int = 0
    mutated_paths: dict[str, dict[str, str | None]] = field(default_factory=dict)
    tools_with_receipts: list[str] = field(default_factory=list)
    receipt_schema_versions: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_events": self.total_events,
            "by_tool": dict(sorted(self.by_tool.items())),
            "by_status": dict(sorted(self.by_status.items())),
            "mutation_count": self.mutation_count,
            "refusal_count": self.refusal_count,
            "timeout_count": self.timeout_count,
            "mutated_paths": dict(
                sorted(
                    {
                        p: {"before": v.get("before"), "after": v.get("after")}
                        for p, v in self.mutated_paths.items()
                    }.items()
                )
            ),
            "tools_with_receipts": sorted(self.tools_with_receipts),
            "receipt_schema_versions": sorted(self.receipt_schema_versions),
        }


# ── Index builder ─────────────────────────────────────────────────────


class ReceiptIndexBuildError(Exception):
    """Raised when a receipt event cannot be parsed."""

    def __init__(self, message: str, line: int | None = None) -> None:
        self.message = message
        self.line = line
        super().__init__(message)


def _resolve_observability_path(session_id_or_path: str | Path) -> Path:
    """Resolve a session identifier or exact path to an observability file."""
    p = Path(session_id_or_path)
    if p.is_file():
        return p
    if p.is_dir():
        maybe = p / "observability.jsonl"
        if maybe.is_file():
            return maybe
        return maybe
    # Treat as session_id
    return get_observability_log_path(str(session_id_or_path))


def _is_tool_receipt_event(event: dict[str, Any]) -> bool:
    """Return True if the event is a rig.relay.tool_receipt.captured event."""
    event_name = event.get("event_name", "")
    return event_name == EventName.TOOL_RECEIPT_CAPTURED


def _extract_tool_name(event: dict[str, Any]) -> str | None:
    payload = event.get("payload")
    if isinstance(payload, dict):
        return payload.get("tool_name")
    return None


def _extract_receipt(event: dict[str, Any]) -> dict[str, Any] | None:
    payload = event.get("payload")
    if isinstance(payload, dict):
        receipt = payload.get("receipt")
        if isinstance(receipt, dict):
            return receipt
    return None


# ruff: noqa: PLR0914  — _build_record_from_event extracts many fields


def _build_record_from_event(event: dict[str, Any]) -> ToolReceiptIndexRecord:
    """Build an index record from a single receipt-captured event.

    Args:
        event: A parsed observability event dict.

    Returns:
        A content-light ToolReceiptIndexRecord.

    Raises:
        ReceiptIndexBuildError: If the event is malformed.
    """
    session_id = event.get("session_id", "")
    if not session_id:
        msg = "Missing session_id in event envelope"
        raise ReceiptIndexBuildError(msg)

    tool_name = _extract_tool_name(event)
    if not tool_name:
        msg = "Missing tool_name in event payload"
        raise ReceiptIndexBuildError(msg)

    receipt = _extract_receipt(event)
    if receipt is None:
        msg = "Missing or non-dict receipt in event payload"
        raise ReceiptIndexBuildError(msg)

    status = receipt.get("status")
    error_kind = receipt.get("error_kind")
    refusal_reason = receipt.get("refusal_reason")
    duration_ms = receipt.get("duration_ms")

    # ── Tool-specific field extraction ──
    path: str | None = None
    changed: bool | None = None
    before_sha256: str | None = None
    after_sha256: str | None = None
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None
    stdout_bytes: int | None = None
    stderr_bytes: int | None = None

    if tool_name == "bash":
        stdout_bytes = receipt.get("stdout_bytes")
        stderr_bytes = receipt.get("stderr_bytes")
        stdout_sha256 = receipt.get("stdout_sha256")
        stderr_sha256 = receipt.get("stderr_sha256")
        changed = None  # bash does not mutate files by default

    elif tool_name == "search_replace":
        path = receipt.get("file")
        before_map = receipt.get("before_file_sha256", {})
        after_map = receipt.get("after_file_sha256", {})
        changed_files = receipt.get("changed_files", [])
        changed = bool(changed_files) if changed_files else None
        # Extract first file's hash for the primary path
        if path and path in before_map:
            before_sha256 = before_map[path]
        elif before_map:
            # Fall back to first entry
            before_sha256 = next(iter(before_map.values()), None)
        if path and path in after_map:
            after_sha256 = after_map[path]
        elif after_map:
            after_sha256 = next(iter(after_map.values()), None)

    elif tool_name == "validate":
        # Validate receipt is content-light per-check.
        # Top-level receipt has no stdout/stderr fields — they're
        # per-check in check_receipts[]. No file mutation.
        changed = None
        # stdout/stderr hashes and bytes are per-check, not at top level

    record = ToolReceiptIndexRecord(
        session_id=session_id,
        event_id=event.get("event_id"),
        captured_at=event.get("created_at"),
        tool_name=tool_name,
        status=status,
        error_kind=error_kind,
        refusal_reason=refusal_reason,
        changed=changed,
        path=str(Path(path).resolve()) if path else None,
        before_sha256=before_sha256,
        after_sha256=after_sha256,
        stdout_sha256=stdout_sha256,
        stderr_sha256=stderr_sha256,
        stdout_bytes=stdout_bytes,
        stderr_bytes=stderr_bytes,
        duration_ms=duration_ms,
    )

    return record


def build_receipt_index(
    session_id_or_path: str | Path,
) -> tuple[list[ToolReceiptIndexRecord], list[str]]:
    """Build a receipt index from a session's local observability JSONL.

    Args:
        session_id_or_path: Session ID string or path to observability
            JSONL file or session directory.

    Returns:
        (records, errors) where:
        - records is a list of successfully parsed ToolReceiptIndexRecord
        - errors is a list of human-readable error messages for events
          that could not be parsed.

    The builder:
    - filters only ``rig.relay.tool_receipt.captured`` events
    - tolerates unrelated event types silently
    - tolerates malformed unrelated events
    - fails safely on malformed receipt events, preserving error messages
    - never loads or exposes raw output content
    """
    obs_path = _resolve_observability_path(session_id_or_path)
    records: list[ToolReceiptIndexRecord] = []
    errors: list[str] = []

    if not obs_path.is_file():
        return records, [f"Observability file not found: {obs_path}"]

    with obs_path.open("r", encoding="utf-8") as f:
        for line_idx, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            # Parse event
            try:
                event = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"line {line_idx}: JSON decode error: {e}")
                continue

            # Filter for receipt-captured events only
            if not _is_tool_receipt_event(event):
                continue

            # Build record
            try:
                record = _build_record_from_event(event)
                records.append(record)
            except ReceiptIndexBuildError as e:
                err_msg = f"line {line_idx}: {e.message}"
                if e.line:
                    err_msg = f"line {e.line}: {e.message}"
                errors.append(err_msg)
            except Exception as e:
                errors.append(f"line {line_idx}: unexpected error building record: {e}")

    return records, errors


def summarize_receipt_index(
    records: list[ToolReceiptIndexRecord],
) -> ReceiptIndexSummary:
    """Summarize a receipt index with counts and aggregates.

    The summary is content-light: no raw output, file contents, or diffs.
    """
    summary = ReceiptIndexSummary(total_events=len(records))

    for record in records:
        # By tool
        summary.by_tool[record.tool_name] = summary.by_tool.get(record.tool_name, 0) + 1

        # By status
        st = record.status or "unknown"
        summary.by_status[st] = summary.by_status.get(st, 0) + 1

        # Mutation tracking (search_replace with changes)
        if record.tool_name == "search_replace" and record.changed and record.path:
            summary.mutation_count += 1
            summary.mutated_paths[record.path] = {
                "before": record.before_sha256,
                "after": record.after_sha256,
            }

        # Refusal count
        if record.status in {"refused"}:
            summary.refusal_count += 1

        # Timeout count (one check, avoid double-counting)
        if record.status == "timed_out" or (
            record.tool_name == "bash" and record.error_kind == "timeout"
        ):
            summary.timeout_count += 1

    summary.tools_with_receipts = list(summary.by_tool.keys())
    return summary


# ── Content-light validation ──────────────────────────────────────────


def validate_index_content_light(records: list[ToolReceiptIndexRecord]) -> list[str]:
    """Validate that indexed receipt records are content-light.

    Checks that no record exposes a field whose name matches a forbidden
    raw-content pattern.

    Returns a list of warning strings. An empty list means all records
    passed.
    """
    warnings: list[str] = []

    for idx, record in enumerate(records):
        dumped = record.model_dump(mode="json")
        _check_forbidden_in_dict(dumped, f"record[{idx}]", warnings)

    return warnings


def _check_forbidden_in_dict(
    data: dict[str, Any], path: str, warnings: list[str]
) -> None:
    for key, value in data.items():
        full_key = f"{path}.{key}"
        lower_key = key.lower()
        # Check for forbidden field names (but allow *_sha256 and *_hash)
        if lower_key.endswith("_sha256") or lower_key.endswith("_hash"):
            continue
        if lower_key in FORBIDDEN_RAW_FIELD_NAMES:
            warnings.append(f"{full_key}: field name '{key}' is forbidden")
        if isinstance(value, dict):
            _check_forbidden_in_dict(value, full_key, warnings)
