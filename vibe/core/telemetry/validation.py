from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any

from vibe.core.telemetry.constants import EventName
from vibe.core.telemetry.local import dump_canonical_json


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
        if _sha256_prefix(resolved) != evidence_sha256:
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


def _collect_evidence_files(session_root: Path) -> list[Path]:
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
    event_by_name = {
        str(event.get("event_name")): event
        for event in events
        if isinstance(event.get("event_name"), str)
    }
    referenced_paths, _ = _collect_references(events, session_root, result)
    _check_file_to_event_parity(session_root, event_by_name, result)

    for path in _collect_evidence_files(session_root):
        if path not in referenced_paths:
            result.unreferenced_evidence_file_count += 1
            result.failed_checks.append(
                f"unreferenced evidence file: {path.relative_to(session_root).as_posix()}"
            )

    if not result.failed_checks:
        result.passed_check_count += 1
    return result
