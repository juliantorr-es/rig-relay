"""Replay engine — reconstructs session state from observability events.

Adapted from Rig's replay architecture (replay.py, runtime_replay.py) but
built for Rig Relay's session-centric domain.

The engine reads observability JSONL, builds typed ReplayEvents, frames them
by sequence/tool boundaries, and produces a ReplayResult with integrity
findings and a navigation cursor.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from rig_relay.replay.models import (
    ReplayConflictType,
    ReplayCursor,
    ReplayEvent,
    ReplayEventKind,
    ReplayFrame,
    ReplayIntegrityFinding,
    ReplayIntegritySeverity,
    ReplayResult,
    ReplayState,
)


def _compute_hash(*components: str) -> str:
    raw = "|".join(components)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _event_kind_from_event_name(event_name: str) -> ReplayEventKind:
    kind_map: dict[str, ReplayEventKind] = {
        "tool_receipt": ReplayEventKind.RECEIPT,
        "receipt": ReplayEventKind.RECEIPT,
        "tool_invocation": ReplayEventKind.TOOL_INVOCATION,
        "governance": ReplayEventKind.GOVERNANCE_DECISION,
        "decision": ReplayEventKind.GOVERNANCE_DECISION,
        "session": ReplayEventKind.SESSION_EVENT,
        "projection": ReplayEventKind.PROJECTION_UPDATE,
        "dirty": ReplayEventKind.DIRTY_SNAPSHOT,
        "snapshot": ReplayEventKind.DIRTY_SNAPSHOT,
    }
    for key, kind in kind_map.items():
        if key in event_name:
            return kind
    return ReplayEventKind.UNKNOWN


def _build_event_from_observability(
    line: str, sequence: int, session_id: str
) -> ReplayEvent | None:
    """Parse a single observability JSONL line into a ReplayEvent."""
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None

    event_id = data.get("event_id") or str(uuid4())
    event_name = data.get("event_name", "")
    created_at = data.get("created_at", "")
    kind = _event_kind_from_event_name(event_name)
    payload = data.get("payload", {}) or {}

    tool_name: str | None = None
    status: str | None = None
    error_kind: str | None = None
    refusal_reason: str | None = None
    duration_ms: float | None = None

    if isinstance(payload, dict):
        tool_name = payload.get("tool_name")
        receipt = payload.get("receipt")
        if isinstance(receipt, dict):
            receipt = payload["receipt"]
        elif isinstance(payload.get("receipt"), dict):
            receipt = payload["receipt"]
        else:
            receipt = None

        if isinstance(receipt, dict):
            status = receipt.get("status") or payload.get("status")
            error_kind = receipt.get("error_kind") or payload.get("error_kind")
            refusal_reason = receipt.get("refusal_reason") or payload.get("refusal_reason")
            duration_ms = receipt.get("duration_ms") or payload.get("duration_ms")
        else:
            status = payload.get("status")
            error_kind = payload.get("error_kind")
            refusal_reason = payload.get("refusal_reason")
            duration_ms = payload.get("duration_ms")

    payload_hash = _compute_hash(json.dumps(data, sort_keys=True))

    return ReplayEvent(
        event_id=event_id,
        sequence=sequence,
        event_kind=kind,
        event_name=event_name,
        session_id=session_id,
        created_at=created_at,
        tool_name=tool_name,
        status=status,
        error_kind=error_kind,
        refusal_reason=refusal_reason,
        duration_ms=duration_ms,
        payload_hash=payload_hash,
    )


def _frame_events(
    events: list[ReplayEvent],
) -> tuple[list[ReplayFrame], list[ReplayIntegrityFinding]]:
    """Group events into frames by tool boundaries and sequence gaps."""
    if not events:
        return [], []

    frames: list[ReplayFrame] = []
    findings: list[ReplayIntegrityFinding] = []
    sorted_events = sorted(events)

    current_group: list[ReplayEvent] = [sorted_events[0]]
    previous_hash: str | None = None

    for i in range(1, len(sorted_events)):
        prev = sorted_events[i - 1]
        curr = sorted_events[i]
        gap = curr.sequence - prev.sequence

        if gap > 1:
            findings.append(ReplayIntegrityFinding(
                finding_id=str(uuid4()),
                severity=ReplayIntegritySeverity.WARNING,
                message=f"Sequence gap between {prev.sequence} and {curr.sequence}",
                conflict_type=ReplayConflictType.SEQUENCE_GAP,
                event_ids=[prev.event_id, curr.event_id],
            ))

        # Frame boundary: tool change or sequence gap > 1
        if gap > 1 or (curr.tool_name and prev.tool_name and curr.tool_name != prev.tool_name):
            frame = _build_frame(current_group, len(frames), previous_hash)
            frames.append(frame)
            previous_hash = frame.frame_hash
            current_group = [curr]
        else:
            current_group.append(curr)

    if current_group:
        frame = _build_frame(current_group, len(frames), previous_hash, is_terminal=True)
        frames.append(frame)

    return frames, findings


def _build_frame(
    events: list[ReplayEvent], index: int, previous_hash: str | None,
    is_terminal: bool = False,
) -> ReplayFrame:
    event_ids = "".join(e.event_id for e in events)
    frame_hash = _compute_hash(str(index), event_ids, previous_hash or "")
    return ReplayFrame(
        frame_index=index,
        events=events,
        frame_hash=frame_hash,
        previous_frame_hash=previous_hash,
        is_terminal=is_terminal,
    )


def _check_duplicates(
    events: list[ReplayEvent],
) -> list[ReplayIntegrityFinding]:
    findings: list[ReplayIntegrityFinding] = []
    seen: set[str] = set()
    for event in events:
        if event.event_id in seen:
            findings.append(ReplayIntegrityFinding(
                finding_id=str(uuid4()),
                severity=ReplayIntegritySeverity.ERROR,
                message=f"Duplicate event: {event.event_id}",
                conflict_type=ReplayConflictType.DUPLICATE_SEQUENCE,
                event_ids=[event.event_id],
            ))
        seen.add(event.event_id)
    return findings


def _build_summary(
    result: ReplayResult,
) -> dict[str, Any]:
    tool_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for frame in result.frames:
        for event in frame.events:
            if event.tool_name:
                tool_counts[event.tool_name] = tool_counts.get(event.tool_name, 0) + 1
            if event.status:
                status_counts[event.status] = status_counts.get(event.status, 0) + 1

    error_count = sum(
        1 for f in result.findings
        if f.severity in {ReplayIntegritySeverity.ERROR, ReplayIntegritySeverity.CRITICAL}
    )

    return {
        "total_frames": len(result.frames),
        "total_events": result.total_events,
        "by_tool": dict(sorted(tool_counts.items())),
        "by_status": dict(sorted(status_counts.items())),
        "integrity_findings": len(result.findings),
        "integrity_errors": error_count,
        "all_passed": result.all_passed,
    }


def replay_session_from_observability(
    session_id: str,
    observability_path: Path,
) -> ReplayResult:
    """Replay a session from its local observability JSONL.

    Args:
        session_id: The session ID to replay.
        observability_path: Path to the observability JSONL file.

    Returns:
        A ReplayResult containing the frame chain, integrity findings,
        navigation cursor, and summary.
    """
    replay_id = str(uuid4())
    result = ReplayResult(
        replay_id=replay_id,
        session_id=session_id,
        state=ReplayState.PROCESSING,
    )

    if not observability_path.is_file():
        result.state = ReplayState.FAILED
        result.findings.append(ReplayIntegrityFinding(
            finding_id=str(uuid4()),
            severity=ReplayIntegritySeverity.ERROR,
            message=f"Observability file not found: {observability_path}",
        ))
        result.summary = _build_summary(result)
        return result

    events: list[ReplayEvent] = []
    sequence = 0

    with observability_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            event = _build_event_from_observability(line, sequence, session_id)
            if event is not None:
                events.append(event)
                sequence += 1

    if not events:
        result.state = ReplayState.COMPLETE
        result.total_events = 0
        result.summary = _build_summary(result)
        return result

    # Check for duplicates
    findings = _check_duplicates(events)

    # Frame events
    frames, frame_findings = _frame_events(events)
    findings.extend(frame_findings)

    result.frames = frames
    result.findings = findings
    result.total_events = len(events)
    result.state = ReplayState.COMPLETE
    result.cursor = ReplayCursor(
        current_frame_index=0,
        total_frames=len(frames),
        can_go_forward=len(frames) > 1,
    )
    result.summary = _build_summary(result)

    return result


def replay_session_from_receipt_index(  # noqa: PLR0914
    session_id: str,
    records: list,
) -> ReplayResult:
    """Replay a session from an existing receipt index (no file I/O).

    Args:
        session_id: The session ID to replay.
        records: List of ToolReceiptIndexRecord objects.

    Returns:
        A ReplayResult containing the frame chain, integrity findings,
        navigation cursor, and summary.
    """
    replay_id = str(uuid4())
    result = ReplayResult(
        replay_id=replay_id,
        session_id=session_id,
        state=ReplayState.PROCESSING,
    )

    events: list[ReplayEvent] = []
    for seq, record in enumerate(records):
        kind = _event_kind_from_event_name(getattr(record, "event_name", "tool_receipt"))
        tool_name = getattr(record, "tool_name", None)
        status = getattr(record, "status", None)
        error_kind = getattr(record, "error_kind", None)
        refusal_reason = getattr(record, "refusal_reason", None)
        duration_ms = getattr(record, "duration_ms", None)
        created_at = getattr(record, "captured_at", "")
        event_id = getattr(record, "event_id", str(uuid4()))

        payload = record.model_dump(mode="json") if hasattr(record, "model_dump") else {}
        payload_hash = _compute_hash(json.dumps(payload, sort_keys=True))

        events.append(ReplayEvent(
            event_id=event_id,
            sequence=seq,
            event_kind=kind,
            event_name="tool_invocation",
            session_id=session_id,
            created_at=created_at,
            tool_name=tool_name,
            status=status,
            error_kind=error_kind,
            refusal_reason=refusal_reason,
            duration_ms=duration_ms,
            payload_hash=payload_hash,
        ))

    findings = _check_duplicates(events)
    frames, frame_findings = _frame_events(events)
    findings.extend(frame_findings)

    result.frames = frames
    result.findings = findings
    result.total_events = len(events)
    result.state = ReplayState.COMPLETE
    result.cursor = ReplayCursor(
        current_frame_index=0,
        total_frames=len(frames),
        can_go_forward=len(frames) > 1,
    )
    result.summary = _build_summary(result)

    return result


__all__ = [
    "replay_session_from_observability",
    "replay_session_from_receipt_index",
]
