"""Refusal adapter — build schema-valid ACP refusal envelopes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import NoReturn

from rig_relay.acp.exceptions import RefusalError

_REFUSAL_SCHEMA_VERSION = "rig.relay.acp.refusal.v1"


def build_acp_refusal(
    refusal_code: str,
    reason: str,
    method: str,
    trace_id: str = "",
    session_id: str = "",
) -> dict:
    return {
        "schema_version": _REFUSAL_SCHEMA_VERSION,
        "trace_id": trace_id,
        "session_id": session_id,
        "method": method,
        "refusal_code": refusal_code,
        "reason": reason,
        "content_light": True,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def raise_acp_refusal(
    refusal_code: str,
    reason: str,
    method: str,
    trace_id: str = "",
    session_id: str = "",
) -> NoReturn:
    refusal = build_acp_refusal(
        refusal_code=refusal_code,
        reason=reason,
        method=method,
        trace_id=trace_id,
        session_id=session_id,
    )
    raise RefusalError(method, refusal_code, refusal)
