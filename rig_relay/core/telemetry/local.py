from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any
import uuid

from pydantic import BaseModel

from rig_relay import __version__


class ContextAccounting(BaseModel):
    model: str
    call_type: str
    message_id: str | None
    total_messages: int
    total_chars: int
    estimated_tokens: int
    by_role: dict[str, int]
    largest_messages: list[dict[str, Any]]
    system_prompt_chars: int
    tool_result_chars: int
    user_message_chars: int
    assistant_message_chars: int
    stable_prefix_fingerprint: str
    dynamic_suffix_fingerprint: str


from rig_relay.core.paths._vibe_home import SESSIONS_ROOT

_telemetry_enabled: bool = True
_degradation_marker_written: set[str] = set()
DEGRADATION_MARKER_FILENAME = "telemetry_degradation.json"


def set_telemetry_enabled(enabled: bool) -> None:
    global _telemetry_enabled
    _telemetry_enabled = enabled


def is_telemetry_enabled() -> bool:
    env_value = os.environ.get("RIG_TELEMETRY_ENABLED", "").strip().lower()
    if env_value in {"0", "false", "no", "off"}:
        return False
    if env_value in {"1", "true", "yes", "on"}:
        return True
    return _telemetry_enabled


def dump_canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def get_observability_log_path(session_id: str) -> Path:
    """Return the path to the local observability JSONL log for a session."""
    base = SESSIONS_ROOT.path / session_id
    base.mkdir(parents=True, exist_ok=True)
    return base / "observability.jsonl"


def get_degradation_marker_path(session_id: str) -> Path:
    base = SESSIONS_ROOT.path / session_id
    base.mkdir(parents=True, exist_ok=True)
    return base / DEGRADATION_MARKER_FILENAME


def write_degradation_marker(session_id: str) -> Path | None:
    from rig_relay.core.telemetry.types import TelemetryMode

    path = get_degradation_marker_path(session_id)
    if session_id in _degradation_marker_written:
        return path
    marker = {
        "schema_version": "rig.relay.telemetry_degradation.v1",
        "session_id": session_id,
        "degradation_mode": TelemetryMode.DISABLED_BY_USER.value,
        "degradation_reason": "Telemetry disabled — harness operating in reduced-adaptation mode",
        "generated_at": datetime.now(UTC).isoformat(),
        "runtime_correlation_preserved": True,
        "persisted_observability_correlation_disabled": True,
        "cross_session_trace_reconstruction_degraded": True,
        "telemetry_reason": "user_opt_out",
        "preserved_capabilities": [
            "core_harness_execution",
            "local_static_validation",
            "frontend_basic_operation",
            "runtime_correlation_identity",
        ],
        "degraded_capabilities": [
            "adaptive_diagnostics",
            "ux_optimization",
            "agent_tool_optimization",
            "ralph_refinement",
            "orchestrator_adaptation",
            "subagent_behavior_refinement",
            "persisted_observability_correlation",
            "cross_session_trace_reconstruction",
        ],
        "disabled_capabilities": ["telemetry_bundle_export", "debug_packet_export"],
        "export_allowed": False,
        "debug_quarantine_enabled": True,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(dump_canonical_json(marker) + "\n", encoding="utf-8")
    tmp.rename(path)
    _degradation_marker_written.add(session_id)
    return path


def read_degradation_marker(session_id: str) -> dict[str, Any] | None:
    path = get_degradation_marker_path(session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def log_local_event(
    session_id: str,
    event_name: str,
    payload: dict[str, Any],
    parent_session_id: str | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    receipt_candidate: bool = False,
) -> None:
    """Write a telemetry event to the local JSONL sink with a formal envelope."""
    if not is_telemetry_enabled():
        write_degradation_marker(session_id)
        return

    path = get_observability_log_path(session_id)

    # 1. Determine sequence (simple line count)
    # NOTE: This is not concurrency-safe and will need locking for parallel writers.
    sequence = 0
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                sequence = sum(1 for _ in f)
        except Exception:
            sequence = 0

    # 2. Normalize event name (bridge legacy to rig.relay.*)
    normalized_name = event_name
    if normalized_name.startswith("vibe."):
        normalized_name = normalized_name.replace("vibe.", "rig.relay.")
    if not normalized_name.startswith("rig.relay."):
        normalized_name = f"rig.relay.{normalized_name}"

    # 2a. Route debug packets to quarantine — before building the formal envelope
    from rig_relay.core.telemetry.quarantine import is_debug_packet, write_debug_packet

    if is_debug_packet(normalized_name):
        from rig_relay import __version__ as _version

        packet = {
            "schema_version": "rig.relay.debug_quarantine.v1",
            "event_id": str(uuid.uuid4()),
            "session_id": session_id,
            "parent_session_id": parent_session_id,
            "created_at": datetime.now(UTC).isoformat(),
            "event_name": normalized_name,
            "payload": payload,
            "producer": {"name": "rig-relay", "version": _version},
            "receipt_candidate": receipt_candidate,
        }
        write_debug_packet(packet, SESSIONS_ROOT.path, session_id)
        return

    # 3. Build the formal envelope
    event = {
        "schema_version": "rig.relay.observability.v1",
        "event_id": str(uuid.uuid4()),
        "session_id": session_id,
        "parent_session_id": parent_session_id,
        "correlation_id": correlation_id or "",
        "causation_id": causation_id or "",
        "sequence": sequence,
        "created_at": datetime.now(UTC).isoformat(),
        "event_name": normalized_name,
        "payload": payload,
        "producer": {"name": "rig-relay", "version": __version__},
        "receipt_candidate": receipt_candidate,
    }

    # 4. Hash the event contents (excluding the hash itself)
    # We use a deterministic compact JSON representation for the hash.
    event_str = dump_canonical_json(event)
    event["event_hash"] = (
        f"sha256:{hashlib.sha256(event_str.encode('utf-8')).hexdigest()}"
    )

    with path.open("a", encoding="utf-8") as f:
        f.write(dump_canonical_json(event) + "\n")


def compute_fingerprint(content: str) -> str:
    """Return a SHA256 fingerprint of the provided content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
