"""Context correlation — compares tool call arguments against a ContextPacket.

This module is the "context-aware telemetry" layer. It extracts target paths
from common built-in tool arguments, normalizes them, and checks them against
the context packet's recommendations, collision warnings, dirty paths, and
do-not-touch lists.

Correlation is NOT policy. It never blocks tool execution. The output is a
ContextObservation record that can be logged, stored, or fed into analysis.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rig_relay.context.models import ContextPacket
from rig_relay.context.observation import ContextObservation

# Tool argument field names that may contain file paths
_PATH_FIELDS: set[str] = {
    "path",
    "paths",
    "file_path",
    "file",
    "target",
    "targets",
    "source",
    "destination",
    "src",
    "dst",
    "root",
}


def correlate_tool_call_with_context(
    context_packet: ContextPacket | None,
    tool_name: str,
    tool_args: dict[str, Any] | None,
    tool_status: str = "pending",
    blocked_by_policy: bool = False,
    mutation_class: str = "unknown",
    session_id: str | None = None,
    agent_id: str | None = None,
    tool_call_id: str | None = None,
) -> ContextObservation:
    """Correlate a tool call against a context packet and return an observation.

    This is a pure function — no side effects, no I/O. All missing or
    unknown fields produce safe defaults rather than errors.

    Args:
        context_packet: The context packet at time of tool call, or None.
        tool_name: Name of the tool that was called.
        tool_args: The tool's arguments dict.
        tool_status: Outcome status: pending, succeeded, failed, refused, skipped.
        blocked_by_policy: Whether the tool was blocked by policy.
        mutation_class: Tool mutation class string.
        session_id: Optional session identifier.
        agent_id: Optional agent identifier.
        tool_call_id: Optional tool call identifier.

    Returns:
        A ContextObservation with all correlation fields populated.
        `context_available` is False when no context packet is provided.
    """
    if context_packet is None:
        return ContextObservation(
            session_id=session_id,
            agent_id=agent_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            target_paths=[],
            mutation_class=mutation_class,
            context_available=False,
            matched_recommended_context=False,
            overlapped_active_work=False,
            touched_dirty_path=False,
            touched_soft_warning=False,
            touched_hard_denied_path=False,
            tool_status=tool_status,
            blocked_by_policy=blocked_by_policy,
        )

    # Extract target paths from tool args
    target_paths = _extract_target_paths(tool_args or {})

    # Normalize relative paths
    normalized = _normalize_paths(target_paths)

    # Correlation checks
    matched_recommended = _match_recommended_context(context_packet, normalized)
    overlapped_work = _overlap_active_work(context_packet, normalized)
    touched_dirty = _touched_dirty_paths(context_packet, normalized)
    touched_soft = _touched_soft_warnings(context_packet, normalized)
    touched_hard = _touched_hard_denied(context_packet, normalized)

    return ContextObservation(
        session_id=session_id,
        agent_id=agent_id,
        context_id=context_packet.context_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        target_paths=normalized,
        mutation_class=mutation_class,
        context_available=True,
        matched_recommended_context=matched_recommended,
        overlapped_active_work=overlapped_work,
        touched_dirty_path=touched_dirty,
        touched_soft_warning=touched_soft,
        touched_hard_denied_path=touched_hard,
        tool_status=tool_status,
        blocked_by_policy=blocked_by_policy,
    )


def _extract_target_paths(args: dict[str, Any]) -> list[str]:
    """Extract file path values from tool arguments.

    Scans the args dict for known path-like keys. Returns all string
    and list values found. Non-string values are skipped.
    """
    paths: list[str] = []
    for key, value in args.items():
        if key in _PATH_FIELDS:
            if isinstance(value, str):
                paths.append(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        paths.append(item)
    return paths


def _normalize_paths(paths: list[str]) -> list[str]:
    """Normalize paths to relative posix form.

    Strips leading ./ or /, converts backslashes, removes empty strings.
    If a path can't be made relative safely, it's kept as-is.
    """
    normalized: list[str] = []
    for p in paths:
        if not p or not p.strip():
            continue
        cleaned = Path(p).as_posix()
        # Remove leading ./  and /
        if cleaned.startswith("./"):
            cleaned = cleaned[2:]
        elif cleaned.startswith("/"):
            cleaned = cleaned.lstrip("/")
        if cleaned:
            normalized.append(cleaned)
    return normalized


def _match_recommended_context(packet: ContextPacket, paths: list[str]) -> bool:
    """Check if any target path matches recommended_context."""
    if not paths or not packet.recommended_context:
        return False
    recommended_set = {r.path for r in packet.recommended_context}
    for p in paths:
        for rec in recommended_set:
            if p == rec or rec.endswith(p) or p.endswith(rec):
                return True
    return False


def _overlap_active_work(packet: ContextPacket, paths: list[str]) -> bool:
    """Check if any target path overlaps active work lanes or collision warnings."""
    if not paths:
        return False

    # Check collision warnings
    warnings = packet.active_work.get("collision_warnings", [])
    for w in warnings:
        warned_path = w.get("path", "")
        if not warned_path:
            continue
        for p in paths:
            if p == warned_path or warned_path in p or p in warned_path:
                return True

    # Check claimed paths in active lanes
    lanes = packet.active_work.get("lanes", [])
    for lane in lanes:
        claimed = lane.get("claimed_paths", [])
        for cp in claimed:
            for p in paths:
                if p == cp or cp in p or p in cp:
                    return True

    return False


def _touched_dirty_paths(packet: ContextPacket, paths: list[str]) -> bool:
    """Check if any target path was dirty at context capture time.

    Compares paths against the dirty file list from git status.
    We don't have the full dirty file list in the packet currently,
    so we check the dirty_summary count and return False for exact
    path matching (the packet only stores counts, not individual paths).
    Future: store dirty file paths in the packet.

    For now, returns True if dirty count > 0 and paths exist.
    """
    if not paths:
        return False
    dirty_count = packet.repo.dirty_summary.get("modified", 0)
    return dirty_count > 0


def _touched_soft_warnings(packet: ContextPacket, paths: list[str]) -> bool:
    """Check if any target path appears in the soft_warnings section.

    Future: soft warnings are not yet stored in the packet model.
    Returns False until that field is added.
    """
    return False


def _touched_hard_denied(packet: ContextPacket, paths: list[str]) -> bool:
    """Check if any target path is in the do_not_touch section."""
    if not paths or not packet.do_not_touch:
        return False
    denied_set = {d.path for d in packet.do_not_touch}
    for p in paths:
        for denied in denied_set:
            if p == denied or denied in p or p in denied:
                return True
    return False


def emit_observation(observation: ContextObservation) -> None:
    """Emit a context observation as a structured log line.

    This is the only side-effect function in this module. It writes
    the observation as a JSON line to stdout for now (capturable by
    the process supervisor). Future: route through the telemetry
    pipeline.
    """
    import sys

    line = observation.model_dump_json(exclude_none=True)
    # Use stderr to avoid interfering with ACP/stdout protocol
    print(f"[rig:observation] {line}", file=sys.stderr, flush=True)
