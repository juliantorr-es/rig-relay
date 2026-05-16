"""Golden-path trace event builder — constructs correlated trace events for the
desktop launch trace.

Every event carries the rig.trace_event.v1 envelope with correlation, authority,
redaction, and content-light payload. This is the release gate: if the golden path
trace is incomplete or contradictory, the app does not "work".
"""

from __future__ import annotations

from enum import StrEnum

from rig_relay.tracing.models import (
    RigTraceEvent,
    TraceEventKind,
    TraceStatus,
    new_span_id,
    new_trace_id,
)


class TraceAuthorityKind(StrEnum):
    user_prompt = "user_prompt"
    agents_md = "agents_md"
    mission_prompt = "mission_prompt"
    schema = "schema"
    validator = "validator"
    tool_result = "tool_result"
    frontend_runtime = "frontend_runtime"
    backend_runtime = "backend_runtime"
    desktop_bridge = "desktop_bridge"
    websocket_server = "websocket_server"
    projection_builder = "projection_builder"
    renderer = "renderer"
    hidden_harness_claim = "hidden_harness_claim"
    untrusted_document = "untrusted_document"
    unknown = "unknown"


def build_redaction(
    *,
    contains_secret: bool = False,
    secret_fields_redacted: list[str] | None = None,
    token_present: bool = False,
    token_value_included: bool = False,
) -> dict[str, object]:
    return {
        "contains_secret": contains_secret,
        "secret_fields_redacted": secret_fields_redacted or [],
        "token_present": token_present,
        "token_value_included": token_value_included,
    }


def build_authority(
    *,
    authority_kind: TraceAuthorityKind | str = TraceAuthorityKind.unknown,
    trusted: bool = True,
    source_path: str = "",
    source_hash: str = "",
    notes: str = "",
) -> dict[str, object]:
    result: dict[str, object] = {
        "authority_kind": authority_kind.value
        if isinstance(authority_kind, TraceAuthorityKind)
        else authority_kind,
        "trusted": trusted,
    }
    if source_path:
        result["source_path"] = source_path
    if source_hash:
        result["source_hash"] = source_hash
    if notes:
        result["notes"] = notes
    return result


def build_correlation(  # noqa: PLR0913
    *,
    handshake_id: str = "",
    session_id: str = "",
    connection_id: str = "",
    projection_id: str = "",
    intent_id: str = "",
    job_id: str = "",
    agent_id: str = "",
    worktree_id: str = "",
    receipt_id: str = "",
    commit_sha: str = "",
    frontend_url: str = "",
    websocket_url: str = "",
) -> dict[str, object]:
    result: dict[str, object] = {}
    if handshake_id:
        result["handshake_id"] = handshake_id
    if session_id:
        result["session_id"] = session_id
    if connection_id:
        result["connection_id"] = connection_id
    if projection_id:
        result["projection_id"] = projection_id
    if intent_id:
        result["intent_id"] = intent_id
    if job_id:
        result["job_id"] = job_id
    if agent_id:
        result["agent_id"] = agent_id
    if worktree_id:
        result["worktree_id"] = worktree_id
    if receipt_id:
        result["receipt_id"] = receipt_id
    if commit_sha:
        result["commit_sha"] = commit_sha
    if frontend_url:
        result["frontend_url"] = frontend_url
    if websocket_url:
        result["websocket_url"] = websocket_url
    return result


def build_golden_path_event(  # noqa: PLR0913
    *,
    event_type: str,
    trace_id: str | None = None,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    status: TraceStatus | None = None,
    handshake_id: str = "",
    correlation: dict[str, object] | None = None,
    authority: dict[str, object] | None = None,
    redaction: dict[str, object] | None = None,
    payload: dict[str, object] | None = None,
    commit_sha: str = "",
    host: str = "",
    port: int = 0,
    frontend_url: str = "",
    websocket_url: str = "",
    tls_enabled: bool | None = None,
    transport_label: str = "",
    token_present: bool = False,
    duration_ms: int | None = None,
    error_message: str | None = None,
    **extra: object,
) -> RigTraceEvent:
    corr = dict(correlation or {})
    corr = build_correlation(
        handshake_id=handshake_id or str(corr.get("handshake_id", "")),
        commit_sha=commit_sha or str(corr.get("commit_sha", "")),
        frontend_url=frontend_url or str(corr.get("frontend_url", "")),
        websocket_url=websocket_url or str(corr.get("websocket_url", "")),
    ) | {k: v for k, v in corr.items() if v}

    redact = dict(redaction or {})
    if "token_present" not in redact:
        redact["token_present"] = token_present
    if "token_value_included" not in redact:
        redact["token_value_included"] = False
    if "contains_secret" not in redact:
        redact["contains_secret"] = False
    if "secret_fields_redacted" not in redact:
        redact["secret_fields_redacted"] = []

    auth = dict(authority or {})
    if "authority_kind" not in auth:
        auth["authority_kind"] = TraceAuthorityKind.desktop_bridge.value
    if "trusted" not in auth:
        auth["trusted"] = True

    p = dict(payload or {})
    if host:
        p.setdefault("host", host)
    if port:
        p.setdefault("port", port)
    if frontend_url:
        p.setdefault("frontend_url", frontend_url)
    if websocket_url:
        p.setdefault("websocket_url", websocket_url)
    if tls_enabled is not None:
        p.setdefault("tls_enabled", tls_enabled)
    if transport_label:
        p.setdefault("transport_label", transport_label)
    if token_present is not None:
        p.setdefault("token_present", token_present)
    for k, v in extra.items():
        if v is not None:
            p[k] = v

    return RigTraceEvent(
        trace_id=trace_id or new_trace_id(),
        span_id=span_id or new_span_id(),
        parent_span_id=parent_span_id,
        event_kind=TraceEventKind.span_event,
        name=event_type,
        event_type=event_type,
        status=status,
        duration_ms=duration_ms,
        error_message=error_message,
        payload=p,
        correlation=corr,
        authority=auth,
        redaction=redact,
    )


__all__ = [
    "TraceAuthorityKind",
    "build_authority",
    "build_correlation",
    "build_golden_path_event",
    "build_redaction",
]
