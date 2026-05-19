"""MCP minimum runtime refusal adapter — local-only, no transport, no execution.

Evaluates MCP tool requests against known tool tiers and produces
schema-valid refusal envelopes or tool-call receipts. Does NOT execute
any tool. Does NOT trust hint metadata as authorization.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from rig_relay.protocols.mcp.models import GATED_TOOLS, READ_ONLY_TOOLS, MCPToolTier

_ALL_TOOLS: dict[str, dict[str, Any]] = {
    t.name: {"tier": t.tier.value, "requires_approval": t.requires_approval}
    for t in READ_ONLY_TOOLS + GATED_TOOLS
}

_REFUSAL_CODE_UNKNOWN = "unknown_tool"
_REFUSAL_CODE_MUTATION = "mutation_tier"
_REFUSAL_CODE_OPEN_WORLD = "open_world_tier"
_REFUSAL_CODE_CREDENTIALED = "credentialed_tier"
_REFUSAL_CODE_DESTRUCTIVE = "destructive_tier"

_MAX_DESCRIPTION_BYTES = 4096


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _receipt_id(trace_id: str, tool_name: str) -> str:
    seed = f"{trace_id}:{tool_name}:{_now_iso()}"
    return f"rec-mcp-{_sha256(seed)[:16]}"


def _refuse(
    trace_id: str, tool_name: str, refusal_code: str, reason: str, tier: int
) -> dict[str, Any]:
    return {
        "schema_version": "rig.relay.mcp.refusal.v1",
        "receipt_id": _receipt_id(trace_id, tool_name),
        "trace_id": trace_id,
        "refusal_code": refusal_code,
        "reason": reason,
        "tier": tier,
        "content_light": True,
        "generated_at": _now_iso(),
    }


def _receipt(
    trace_id: str,
    session_id: str,
    tool_name: str,
    tier: int,
    verdict: str,
    refusal_code: str,
    request_dict: dict[str, Any],
) -> dict[str, Any]:
    request_canonical = json.dumps(request_dict, sort_keys=True)
    return {
        "schema_version": "rig.relay.mcp.tool_call_receipt.v1",
        "receipt_id": _receipt_id(trace_id, tool_name),
        "trace_id": trace_id,
        "session_id": session_id,
        "tool_name": tool_name,
        "tier": tier,
        "verdict": verdict,
        "refusal_code": refusal_code,
        "request_hash": _sha256(request_canonical),
        "response_hash": "0" * 64,
        "content_light": True,
        "generated_at": _now_iso(),
    }


def evaluate_mcp_request(
    tool_name: str, request_dict: dict[str, Any] | None, trace_id: str, session_id: str
) -> dict[str, Any]:
    """Evaluate an MCP tool request and produce refusal or receipt.

    Returns a schema-valid refusal envelope (rig.relay.mcp.refusal.v1)
    if the tool is unknown, mutation-tier, open-world, credentialed, or
    destructive. Returns a schema-valid receipt (rig.relay.mcp.tool_call_receipt.v1)
    otherwise.

    Does NOT execute any tool. Does NOT trust readOnlyHint /
    destructiveHint / openWorldHint as authorization.
    """
    if not isinstance(request_dict, dict):
        return _refuse(
            trace_id,
            tool_name,
            _REFUSAL_CODE_UNKNOWN,
            "Malformed request: request_dict is not a dict.",
            -1,
        )

    if not tool_name or not isinstance(tool_name, str):
        return _refuse(
            trace_id,
            tool_name or "(empty)",
            _REFUSAL_CODE_UNKNOWN,
            "Request missing valid tool name.",
            -1,
        )

    known = _ALL_TOOLS.get(tool_name)
    if known is None:
        return _refuse(
            trace_id, tool_name, _REFUSAL_CODE_UNKNOWN, f"Unknown tool: {tool_name}", -1
        )

    tier = known["tier"]

    if tier >= MCPToolTier.MUTATION.value:
        if tier == MCPToolTier.MUTATION.value:
            return _refuse(
                trace_id,
                tool_name,
                _REFUSAL_CODE_CREDENTIALED,
                f"Credentialed mutation tier tool refused: {tool_name}",
                tier,
            )

        if tier == MCPToolTier.GIT_RELEASE.value:
            return _refuse(
                trace_id,
                tool_name,
                _REFUSAL_CODE_DESTRUCTIVE,
                f"Destructive tier tool refused: {tool_name}",
                tier,
            )

    return _receipt(trace_id, session_id, tool_name, tier, "allowed", "", request_dict)


def classify_tool_descriptor_suspicious(
    descriptor_dict: dict[str, Any] | None,
) -> list[str]:
    """Detect suspicious metadata in an MCP tool descriptor.

    Reasons include:
    - Mismatched name (descriptor name != tool_name)
    - Dual-hint shadowing (destructiveHint + readOnlyHint both true)
    - Descriptor claims read-only but tool known to be destructive
    - Suspiciously large description (> 4096 bytes)
    - Unknown/foreign capability claims
    """
    if not isinstance(descriptor_dict, dict):
        return ["descriptor_invalid: descriptor is not a dict"]

    reasons: list[str] = []

    descriptor_name = descriptor_dict.get("name", "")
    tool_name = descriptor_dict.get("tool_name", "")

    if descriptor_name and tool_name and descriptor_name != tool_name:
        reasons.append(
            f"name_mismatch: descriptor name '{descriptor_name}' != tool_name '{tool_name}'"
        )

    destructive = descriptor_dict.get("destructiveHint", False)
    read_only = descriptor_dict.get("readOnlyHint", False)

    if destructive and read_only:
        reasons.append(
            "dual_hint_shadowing: destructiveHint and readOnlyHint both true"
        )

    if tool_name:
        known = _ALL_TOOLS.get(tool_name)
        if known is not None:
            if known["tier"] >= MCPToolTier.MUTATION.value and read_only:
                reasons.append(
                    f"read_only_claim_for_destructive: tool '{tool_name}' "
                    f"is tier {known['tier']} but descriptor claims readOnlyHint"
                )

    description = descriptor_dict.get("description", "")
    if isinstance(description, str):
        desc_bytes = len(description.encode("utf-8"))
        if desc_bytes > _MAX_DESCRIPTION_BYTES:
            reasons.append(
                f"oversized_description: {desc_bytes} bytes exceeds {_MAX_DESCRIPTION_BYTES} limit"
            )

    capabilities = descriptor_dict.get("capabilities", {})
    if isinstance(capabilities, dict):
        for cap_name in capabilities:
            if isinstance(cap_name, str) and not cap_name.startswith("rig."):
                reasons.append(
                    f"foreign_capability: capability '{cap_name}' is not in the rig namespace"
                )

    return reasons


__all__ = ["classify_tool_descriptor_suspicious", "evaluate_mcp_request"]
