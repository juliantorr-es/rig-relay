from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any

from vibe.core.telemetry.constants import EventName
from vibe.core.telemetry.local import dump_canonical_json
from vibe.core.telemetry.manifest import load_manifest
from vibe.core.telemetry.receipts import EvidenceReceipt, load_receipts, verify_receipt


@dataclass(slots=True)
class EvidenceValidationResult:
    evidence_root: Path
    session_id: str
    root_mode: str | None
    root_source: str | None
    passed_check_count: int = 0
    failed_checks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    event_count: int = 0
    referenced_file_count: int = 0
    unreferenced_evidence_file_count: int = 0
    malformed_event_count: int = 0
    receipt_count: int = 0
    receipt_chain_status: str = (
        "missing"  # "missing", "valid", "invalid", "legacy_missing"
    )
    final_receipt_sha256: str | None = None

    @property
    def status(self) -> str:
        if self.failed_checks:
            return "fail"
        if self.warnings:
            return "warn"
        return "pass"


def _sha256_prefix(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _is_safe_relative_path(path_value: str) -> bool:
    candidate = Path(path_value)
    return not candidate.is_absolute() and ".." not in candidate.parts


def _read_events(log_path: Path) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    events: list[dict[str, Any]] = []
    canonical_errors: list[str] = []
    parse_errors: list[str] = []
    lines = log_path.read_text(encoding="utf-8").splitlines()
    for line_no, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            parse_errors.append(f"line {line_no}: malformed JSON ({exc.msg})")
            continue
        if not isinstance(event, dict):
            parse_errors.append(f"line {line_no}: event must be a JSON object")
            continue
        if line != dump_canonical_json(event):
            canonical_errors.append(f"line {line_no}: non-canonical JSONL encoding")
        events.append(event)
    return events, parse_errors, canonical_errors


def _session_start_metadata(
    events: list[dict[str, Any]], result: EvidenceValidationResult
) -> None:
    started = next(
        (
            event
            for event in events
            if event.get("event_name") == EventName.SESSION_STARTED
        ),
        None,
    )
    if started is None:
        result.failed_checks.append("missing rig.relay.session.started event")
        return

    payload = started.get("payload")
    if not isinstance(payload, dict):
        result.failed_checks.append("session.started payload must be an object")
        return

    result.root_mode = payload.get("evidence_root_mode")
    result.root_source = payload.get("evidence_root_source")
    if result.root_mode is None or result.root_source is None:
        result.warnings.append("session.started missing evidence_root_mode/source")
    else:
        result.passed_check_count += 1


def _session_closed_warning(
    events: list[dict[str, Any]], result: EvidenceValidationResult
) -> None:
    if any(event.get("event_name") == EventName.SESSION_CLOSED for event in events):
        result.passed_check_count += 1
        return

    result.warnings.append("missing rig.relay.session.closed event")


def _collect_references(
    events: list[dict[str, Any]], session_root: Path, result: EvidenceValidationResult
) -> tuple[set[Path], dict[str, list[Path]]]:
    referenced_paths: set[Path] = set()
    parity_buckets: dict[str, list[Path]] = {
        str(EventName.ARTIFACT_WRITTEN): [],
        str(EventName.SHADOW_REQUEST_ASSEMBLED): [],
        str(EventName.CONTEXT_ASSEMBLY_REPORTED): [],
        str(EventName.CONTEXT_LAYOUT_PLANNED): [],
    }

    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, dict):
            result.failed_checks.append("event payload must be an object")
            continue

        evidence_relative_path = payload.get("evidence_relative_path")
        if evidence_relative_path is None:
            continue
        if not isinstance(evidence_relative_path, str):
            result.failed_checks.append("evidence_relative_path must be a string")
            continue
        if not _is_safe_relative_path(evidence_relative_path):
            result.failed_checks.append(
                f"unsafe evidence_relative_path: {evidence_relative_path}"
            )
            continue

        resolved = (session_root / evidence_relative_path).resolve()
        if not resolved.is_relative_to(session_root.resolve()):
            result.failed_checks.append(
                f"evidence_relative_path escapes session root: {evidence_relative_path}"
            )
            continue
        if not resolved.exists():
            result.failed_checks.append(
                f"referenced evidence file missing: {evidence_relative_path}"
            )
            continue

        referenced_paths.add(resolved)
        result.referenced_file_count += 1
        event_name = str(event.get("event_name"))
        if event_name in parity_buckets:
            parity_buckets[event_name].append(resolved)

        evidence_sha256 = payload.get("evidence_sha256")
        if evidence_sha256 is None:
            continue
        if not isinstance(evidence_sha256, str) or not evidence_sha256.startswith(
            "sha256:"
        ):
            result.failed_checks.append(
                f"malformed evidence_sha256 for {evidence_relative_path}"
            )
            continue
        if event_name == str(EventName.ARTIFACT_WRITTEN):
            try:
                artifact_data = json.loads(resolved.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                result.failed_checks.append(
                    f"artifact evidence unreadable for {evidence_relative_path}: {exc}"
                )
                continue
            expected_hash = artifact_data.get(
                "artifact_record_sha256"
            ) or _sha256_prefix(resolved)
        else:
            expected_hash = _sha256_prefix(resolved)

        if expected_hash != evidence_sha256:
            result.failed_checks.append(
                f"evidence hash mismatch for {evidence_relative_path}"
            )

    return referenced_paths, parity_buckets


def _check_file_to_event_parity(
    session_root: Path,
    event_by_name: dict[str, dict[str, Any]],
    result: EvidenceValidationResult,
) -> None:
    buckets = {
        str(EventName.ARTIFACT_WRITTEN): session_root / "artifacts" / "tool-results",
        str(EventName.SHADOW_REQUEST_ASSEMBLED): session_root / "context",
        str(EventName.CONTEXT_ASSEMBLY_REPORTED): session_root / "context",
        str(EventName.CONTEXT_LAYOUT_PLANNED): session_root / "context",
    }
    patterns = {
        str(EventName.ARTIFACT_WRITTEN): "*.json",
        str(EventName.SHADOW_REQUEST_ASSEMBLED): "shadow_request_*.json",
        str(EventName.CONTEXT_ASSEMBLY_REPORTED): "assembly_*.json",
        str(EventName.CONTEXT_LAYOUT_PLANNED): "layout_*.json",
    }

    for event_name, directory in buckets.items():
        if not directory.exists():
            continue
        files = list(directory.glob(patterns[event_name]))
        if not files:
            continue
        if event_name not in event_by_name:
            result.failed_checks.append(f"missing event for {event_name}")


def _collect_session_evidence_files(session_root: Path) -> list[Path]:
    files: list[Path] = []
    observability = session_root / "observability.jsonl"
    if observability.exists():
        files.append(observability)
    artifact_dir = session_root / "artifacts" / "tool-results"
    context_dir = session_root / "context"
    if artifact_dir.exists():
        files.extend(sorted(artifact_dir.glob("*.json")))
    if context_dir.exists():
        files.extend(sorted(context_dir.glob("assembly_*.json")))
        files.extend(sorted(context_dir.glob("layout_*.json")))
        files.extend(sorted(context_dir.glob("shadow_request_*.json")))
    return [path.resolve() for path in files]


def _collect_contract_evidence_files(session_root: Path) -> list[Path]:
    files: list[Path] = []
    artifact_dir = session_root / "artifacts" / "tool-results"
    context_dir = session_root / "context"
    if artifact_dir.exists():
        files.extend(sorted(artifact_dir.glob("*.json")))
    if context_dir.exists():
        files.extend(sorted(context_dir.glob("assembly_*.json")))
        files.extend(sorted(context_dir.glob("layout_*.json")))
        files.extend(sorted(context_dir.glob("shadow_request_*.json")))
    return [path.resolve() for path in files]


def _validate_manifest(
    session_root: Path, result: EvidenceValidationResult
) -> tuple[set[Path], bool]:
    try:
        manifest = load_manifest(session_root)
    except json.JSONDecodeError as exc:
        result.failed_checks.append(f"manifest is invalid JSON: {exc.msg}")
        return set(), True
    if manifest is None:
        result.warnings.append("manifest missing; using scan fallback")
        return set(), False

    manifest_path = session_root / "manifest.json"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    if manifest_text.rstrip("\n") != dump_canonical_json(manifest):
        result.failed_checks.append("manifest is not canonical JSON")
        return set(), True

    entries = manifest.get("entries")
    if not isinstance(entries, list):
        result.failed_checks.append("manifest entries must be a list")
        return set(), True

    manifest_paths: set[Path] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            result.failed_checks.append(f"manifest entry {index} must be an object")
            continue

        relative_path = entry.get("relative_path")
        sha256 = entry.get("sha256")
        if not isinstance(relative_path, str) or not _is_safe_relative_path(
            relative_path
        ):
            result.failed_checks.append(
                f"manifest entry {index} has unsafe relative_path"
            )
            continue
        if not isinstance(sha256, str) or not sha256.startswith("sha256:"):
            result.failed_checks.append(f"manifest entry {index} has malformed sha256")
            continue

        resolved = (session_root / relative_path).resolve()
        if not resolved.is_relative_to(session_root):
            result.failed_checks.append(
                f"manifest entry {index} escapes session root: {relative_path}"
            )
            continue
        if not resolved.exists():
            result.failed_checks.append(
                f"manifest entry missing evidence file: {relative_path}"
            )
            continue
        if _sha256_prefix(resolved) != sha256:
            result.failed_checks.append(
                f"manifest entry hash mismatch: {relative_path}"
            )
            continue

        manifest_paths.add(resolved)

    return manifest_paths, True


def _check_receipt_format(
    receipts_path: Path, result: EvidenceValidationResult
) -> None:
    """Verify that the receipts file uses canonical JSONL format."""
    receipt_lines = receipts_path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(receipt_lines):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            if line != dump_canonical_json(data):
                result.failed_checks.append(
                    f"receipt line {i + 1} is not canonical JSON"
                )
                result.receipt_chain_status = "invalid"
        except json.JSONDecodeError:
            result.failed_checks.append(f"receipt line {i + 1} is malformed JSON")
            result.receipt_chain_status = "invalid"


def _verify_receipt_artifact(
    session_root: Path,
    receipt: EvidenceReceipt,
    result: EvidenceValidationResult,
    index: int,
) -> bool:
    """Verify that the artifact referenced by a receipt exists and matches its hash."""
    if not _is_safe_relative_path(receipt.evidence_relative_path):
        result.failed_checks.append(
            f"receipt {index + 1} has unsafe relative path: {receipt.evidence_relative_path}"
        )
        return False

    resolved = (session_root / receipt.evidence_relative_path).resolve()
    if not resolved.is_relative_to(session_root.resolve()):
        result.failed_checks.append(
            f"receipt {index + 1} path escapes session root: {receipt.evidence_relative_path}"
        )
        return False

    if not resolved.exists():
        result.failed_checks.append(
            f"receipt {index + 1} referenced file missing: {receipt.evidence_relative_path}"
        )
        return False

    if receipt.event_name == str(EventName.ARTIFACT_WRITTEN):
        try:
            artifact_data = json.loads(resolved.read_text(encoding="utf-8"))
            actual_hash = artifact_data.get("artifact_record_sha256") or _sha256_prefix(
                resolved
            )
        except (OSError, json.JSONDecodeError):
            actual_hash = "ERROR"
    else:
        actual_hash = _sha256_prefix(resolved)

    if actual_hash != receipt.evidence_sha256:
        result.failed_checks.append(
            f"receipt {index + 1} evidence hash mismatch: {receipt.evidence_relative_path}"
        )
        return False

    return True


def _verify_receipt_event(
    events: list[dict[str, Any]],
    receipt: EvidenceReceipt,
    result: EvidenceValidationResult,
    index: int,
) -> bool:
    """Verify that the receipt correctly references an event in the observability log."""
    if receipt.event_index < 0 or receipt.event_index >= len(events):
        result.failed_checks.append(
            f"receipt {index + 1} event_index out of range: {receipt.event_index}"
        )
        return False

    event = events[receipt.event_index]
    if event.get("event_name") != receipt.event_name:
        result.failed_checks.append(
            f"receipt {index + 1} event_name mismatch: expected {event.get('event_name')}, got {receipt.event_name}"
        )
        return False

    # Check if event actually produced this file
    payload = event.get("payload", {})
    if payload.get("evidence_relative_path") != receipt.evidence_relative_path:
        result.failed_checks.append(
            f"receipt {index + 1} evidence_relative_path mismatch with event payload"
        )
        return False

    return True


def _validate_receipt_chain(
    session_root: Path, events: list[dict[str, Any]], result: EvidenceValidationResult
) -> None:
    receipts_path = session_root / "receipts.jsonl"
    if not receipts_path.is_file():
        # Check if this is a legacy session or partial session
        if any(event.get("event_name") == EventName.SESSION_CLOSED for event in events):
            # If closed but no receipts, it's missing (might be old)
            result.receipt_chain_status = "legacy_missing"
            result.warnings.append("receipts.jsonl missing for closed session")
        else:
            result.receipt_chain_status = "missing"
            result.warnings.append(
                "receipts.jsonl missing (session might be active/partial)"
            )
        return

    result.receipt_chain_status = "valid"
    _check_receipt_format(receipts_path, result)
    receipts = load_receipts(session_root)
    result.receipt_count = len(receipts)
    if not receipts:
        return

    previous_hash: str | None = None
    expected_sequence = 1
    receipt_event_indices: set[int] = set()

    for i, receipt in enumerate(receipts):
        if receipt.sequence != expected_sequence:
            result.failed_checks.append(
                f"receipt {i + 1} has out-of-order sequence: {receipt.sequence} (expected {expected_sequence})"
            )
            result.receipt_chain_status = "invalid"
        expected_sequence += 1

        if receipt.previous_receipt_sha256 != previous_hash:
            result.failed_checks.append(
                f"receipt {i + 1} has broken chain: previous_receipt_sha256 mismatch"
            )
            result.receipt_chain_status = "invalid"

        if not verify_receipt(receipt):
            result.failed_checks.append(f"receipt {i + 1} hash verification failed")
            result.receipt_chain_status = "invalid"

        if not _verify_receipt_artifact(session_root, receipt, result, i):
            result.receipt_chain_status = "invalid"

        if not _verify_receipt_event(events, receipt, result, i):
            result.receipt_chain_status = "invalid"

        receipt_event_indices.add(receipt.event_index)
        previous_hash = receipt.receipt_sha256

    result.final_receipt_sha256 = previous_hash

    # Check if all file-producing events have receipts
    kind_map = {
        "rig.relay.artifact.tool_output_written": "tool_result",
        "rig.relay.context.assembly_reported": "context_assembly_report",
        "rig.relay.context.layout_planned": "context_layout_plan",
        "rig.relay.context.shadow_request_assembled": "shadow_request_report",
    }
    for idx, event in enumerate(events):
        if event.get("event_name") in kind_map:
            if idx not in receipt_event_indices:
                result.failed_checks.append(
                    f"file-producing event at index {idx} ({event.get('event_name')}) is missing a receipt"
                )
                result.receipt_chain_status = "invalid"


def validate_evidence_session(
    evidence_root: Path, session_id: str
) -> EvidenceValidationResult:
    result = EvidenceValidationResult(
        evidence_root=evidence_root,
        session_id=session_id,
        root_mode=None,
        root_source=None,
    )
    session_root = (evidence_root / "sessions" / session_id).resolve()
    evidence_root = evidence_root.resolve()

    if not evidence_root.exists():
        result.failed_checks.append("evidence root does not exist")
        return result
    if not session_root.exists():
        result.failed_checks.append("session directory does not exist")
        return result

    log_path = session_root / "observability.jsonl"
    if not log_path.is_file():
        result.failed_checks.append("observability.jsonl missing")
        return result

    events, parse_errors, canonical_errors = _read_events(log_path)
    result.event_count = len(events)
    result.malformed_event_count = len(parse_errors)
    result.failed_checks.extend(parse_errors)
    result.failed_checks.extend(canonical_errors)

    _session_start_metadata(events, result)
    _session_closed_warning(events, result)
    event_by_name = {
        str(event.get("event_name")): event
        for event in events
        if isinstance(event.get("event_name"), str)
    }
    manifest_paths, manifest_present = _validate_manifest(session_root, result)
    referenced_paths, _ = _collect_references(events, session_root, result)
    _validate_receipt_chain(session_root, events, result)
    _check_file_to_event_parity(session_root, event_by_name, result)

    evidence_files = _collect_session_evidence_files(session_root)
    if manifest_present and set(evidence_files) != manifest_paths:
        result.failed_checks.append("manifest does not cover current evidence files")

    for path in _collect_contract_evidence_files(session_root):
        if path not in referenced_paths:
            result.unreferenced_evidence_file_count += 1
            result.failed_checks.append(
                f"unreferenced evidence file: {path.relative_to(session_root).as_posix()}"
            )

    if not result.failed_checks:
        result.passed_check_count += 1
    return result
