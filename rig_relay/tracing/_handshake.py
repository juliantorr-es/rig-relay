"""Rig Relay Trace Handshake — package-owned implementation.

Provides helpers to load, select, and format correlated handshake trace
events from a JSONL trace store.

Originally extracted from scripts/rig_relay_trace_handshake.py to close the
reverse-layering gap where production packages (bridge_server.py) imported
from scripts/.
"""

from __future__ import annotations

from collections.abc import Iterable
import json
from pathlib import Path


def load_events(path: Path) -> list[dict[str, object]]:
    """Load all JSON objects from a JSONL trace events file."""
    events: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def select_handshake_id(
    events: Iterable[dict[str, object]], handshake_id: str | None = None
) -> str | None:
    """Select a handshake_id from events.

    If handshake_id is provided, confirms it exists. Otherwise returns
    the latest handshake_id found.
    """
    if handshake_id:
        for event in events:
            attrs = event.get("attributes")
            if not isinstance(attrs, dict):
                continue
            if attrs.get("handshake_id") == handshake_id:
                return handshake_id
    latest: tuple[str, str] | None = None
    for event in events:
        attrs = event.get("attributes")
        if not isinstance(attrs, dict):
            continue
        current = attrs.get("handshake_id")
        if not isinstance(current, str) or not current:
            continue
        timestamp = str(event.get("timestamp", ""))
        if latest is None or timestamp >= latest[0]:
            latest = (timestamp, current)
    return latest[1] if latest else None


def _match_handshake(
    events: Iterable[dict[str, object]], handshake_id: str
) -> list[dict[str, object]]:
    matched: list[dict[str, object]] = []
    for event in events:
        attrs = event.get("attributes")
        if not isinstance(attrs, dict):
            continue
        if attrs.get("handshake_id") == handshake_id:
            matched.append(event)
    return matched


def format_handshake_trace(events: list[dict[str, object]], handshake_id: str) -> str:
    """Format a human-readable handshake trace from correlated events."""
    matched = _match_handshake(events, handshake_id)
    matched.sort(key=lambda event: str(event.get("timestamp", "")))
    lines = [f"Handshake trace: {handshake_id}", f"Events: {len(matched)}"]
    for event in matched:
        lines.append(
            " | ".join([
                str(event.get("timestamp", "")),
                str(event.get("name", "")),
                str(event.get("event_kind", "")),
                str(event.get("status", "")),
            ]).rstrip(" |")
        )
        attrs = event.get("attributes")
        if isinstance(attrs, dict):
            filtered = {
                k: v
                for k, v in attrs.items()
                if k
                in {
                    "handshake_id",
                    "transport.session_id",
                    "token_present",
                    "ws_scheme",
                    "frontend_scheme",
                    "transport_label",
                }
            }
            if filtered:
                lines.append(f"  attrs={json.dumps(filtered, sort_keys=True)}")
    return "\n".join(lines)


__all__ = ["format_handshake_trace", "load_events", "select_handshake_id"]
