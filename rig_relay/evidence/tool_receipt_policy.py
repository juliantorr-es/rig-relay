"""Tool receipt content-light policy validator.

Validates that emitted ``rig.relay.tool_receipt.captured`` event payloads
remain content-light. Detects forbidden raw-content fields, suspicious
value shapes, and nested leaks. Read-only — does not mutate files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ── Forbidden field names (exact match, not substring) ─────────────────

_FORBIDDEN_RECEIPT_FIELDS: frozenset[str] = frozenset({
    "stdout",
    "stderr",
    "output",
    "raw_output",
    "raw_stdout",
    "raw_stderr",
    "content",
    "file_content",
    "file_contents",
    "diff",
    "patch",
    "snippet",
    "context",
    "old",
    "new",
    "replacement",
    "replacement_text",
    "command_output",
})

# Allowed hash/count metadata that contain "stdout"/"stderr" substrings
# but are legitimate content-light fields.
_ALLOWED_METADATA_FIELDS: frozenset[str] = frozenset({
    "stdout_sha256",
    "stderr_sha256",
    "stdout_bytes",
    "stderr_bytes",
    "stdout_truncated",
    "stderr_truncated",
    "before_sha256",
    "after_sha256",
    "before_bytes",
    "after_bytes",
    "before_truncated",
    "after_truncated",
})


# ── Finding model ─────────────────────────────────────────────────────


class ReceiptPolicyFinding:
    """A single policy violation or observation from receipt validation."""

    __slots__ = ("line", "field_path", "message", "severity")

    def __init__(
        self, line: int | None, field_path: str, message: str, severity: str = "error"
    ) -> None:
        self.line = line
        self.field_path = field_path
        self.message = message
        self.severity = severity

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "field_path": self.field_path,
            "message": self.message,
            "severity": self.severity,
        }
        if self.line is not None:
            d["line"] = self.line
        return d

    def __repr__(self) -> str:
        return (
            f"ReceiptPolicyFinding(line={self.line}, "
            f"path={self.field_path!r}, {self.severity}: {self.message})"
        )


# ── Key-based validation ──────────────────────────────────────────────


def _check_forbidden_keys(
    receipt: dict[str, Any],
    *,
    path: str = "receipt",
    findings: list[ReceiptPolicyFinding],
    line: int | None = None,
) -> None:
    """Check a receipt dict for exact forbidden field names.

    Recursively walks nested dicts. Skips fields in ``_ALLOWED_METADATA_FIELDS``.
    """
    for key, value in receipt.items():
        full_path = f"{path}.{key}"

        # Skip allowed metadata fields even if they match a forbidden prefix
        if key in _ALLOWED_METADATA_FIELDS:
            continue

        if key in _FORBIDDEN_RECEIPT_FIELDS:
            findings.append(
                ReceiptPolicyFinding(
                    line=line,
                    field_path=full_path,
                    message=f"Forbidden field '{key}' present in receipt",
                )
            )
            continue

        # Recurse into nested dicts
        if isinstance(value, dict):
            _check_forbidden_keys(value, path=full_path, findings=findings, line=line)


# ── Value-shape heuristics ─────────────────────────────────────────────


# Strings longer than this that look like raw output are flagged
_RAW_VALUE_THRESHOLD = 256

# Strings with more than this many newlines are flagged as possible raw content
_EXCESSIVE_NEWLINES = 10

# Unified diff markers
_DIFF_START_PATTERNS = ("--- ", "+++ ", "@@ ", "diff --git ")


def _check_value_shape(
    receipt: dict[str, Any],
    *,
    path: str = "receipt",
    findings: list[ReceiptPolicyFinding],
    line: int | None = None,
) -> None:
    """Check receipt values for suspicious shapes indicative of raw output.

    Flags:
    - String values exceeding a length threshold
    - Strings containing unified diff markers
    - Strings with excessive newlines
    """
    for key, value in receipt.items():
        full_path = f"{path}.{key}"

        if not isinstance(value, str):
            if isinstance(value, dict):
                _check_value_shape(value, path=full_path, findings=findings, line=line)
            continue

        # Check length
        if len(value) > _RAW_VALUE_THRESHOLD:
            findings.append(
                ReceiptPolicyFinding(
                    line=line,
                    field_path=full_path,
                    message=(
                        f"String value exceeds {_RAW_VALUE_THRESHOLD} bytes "
                        f"({len(value)} bytes), possible raw content leak"
                    ),
                    severity="warn",
                )
            )

        # Check for unified diff markers
        newlines = value.count("\n")
        if newlines > 0:
            for pattern in _DIFF_START_PATTERNS:
                if pattern in value:
                    findings.append(
                        ReceiptPolicyFinding(
                            line=line,
                            field_path=full_path,
                            message=(
                                f"String contains unified diff marker '{pattern}', "
                                "possible raw diff leakage"
                            ),
                        )
                    )
                    break

            # Excessive newlines (more than 10)
            if newlines > _EXCESSIVE_NEWLINES:
                findings.append(
                    ReceiptPolicyFinding(
                        line=line,
                        field_path=full_path,
                        message=(
                            f"String contains {newlines} newlines, "
                            "possible raw content leak"
                        ),
                        severity="warn",
                    )
                )


# ── Top-level receipt validation ──────────────────────────────────────


def validate_receipt_payload(
    payload: dict[str, Any], *, line: int | None = None
) -> list[ReceiptPolicyFinding]:
    """Validate a single receipt payload dict.

    Checks:
    1. Payload has ``tool_name`` and ``receipt`` keys.
    2. Forbidden field names are not present.
    3. Value shapes are suspicious-free.

    Returns a (possibly empty) list of findings.
    """
    findings: list[ReceiptPolicyFinding] = []

    receipt = payload.get("receipt")
    if not isinstance(receipt, dict):
        findings.append(
            ReceiptPolicyFinding(
                line=line,
                field_path="payload.receipt",
                message="Missing or non-dict 'receipt' in payload",
            )
        )
        return findings

    _check_forbidden_keys(receipt, findings=findings, line=line)
    _check_value_shape(receipt, findings=findings, line=line)

    return findings


# ── Event-level validation ────────────────────────────────────────────


def validate_event(
    event: dict[str, Any], *, line: int | None = None
) -> list[ReceiptPolicyFinding]:
    """Validate a single parsed JSONL event for receipt policy.

    Ignores non-receipt events. Returns (possibly empty) findings list.
    """
    findings: list[ReceiptPolicyFinding] = []

    event_name = event.get("event_name") or event.get("event")

    if event_name != "rig.relay.tool_receipt.captured":
        return findings  # ignore unrelated events

    payload = event.get("payload")
    if not isinstance(payload, dict):
        findings.append(
            ReceiptPolicyFinding(
                line=line,
                field_path="event.payload",
                message="Malformed tool receipt event: missing or non-dict payload",
            )
        )
        return findings

    findings.extend(validate_receipt_payload(payload, line=line))
    return findings


# ── File-level validation ─────────────────────────────────────────────


def validate_file(file_path: Path) -> list[ReceiptPolicyFinding]:
    """Scan an observability JSONL file for receipt policy violations.

    Unrelated events are silently ignored. Malformed lines produce findings.
    Returns a list of findings (empty if clean).
    """
    findings: list[ReceiptPolicyFinding] = []
    raw = file_path.read_text(encoding="utf-8")

    for i, line_text in enumerate(raw.strip().split("\n")):
        if not line_text.strip():
            continue
        try:
            event = json.loads(line_text)
        except json.JSONDecodeError as e:
            findings.append(
                ReceiptPolicyFinding(
                    line=i + 1, field_path="<line>", message=f"Malformed JSON: {e}"
                )
            )
            continue

        if not isinstance(event, dict):
            findings.append(
                ReceiptPolicyFinding(
                    line=i + 1,
                    field_path="<line>",
                    message="JSON value is not an object",
                )
            )
            continue

        findings.extend(validate_event(event, line=i + 1))

    return findings
