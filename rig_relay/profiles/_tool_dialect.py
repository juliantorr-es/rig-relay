"""Tool dialect adapter.

Adapts tool descriptions and results for different provider-harness
compatibility profiles. Never modifies factual content — only adjusts
format and adds authority-preserving metadata.
"""

from __future__ import annotations

from rig_relay.profiles.models import HarnessCompatibilityProfile, ToolDialectStrategy

_GOVERNANCE_HEADER = (
    "[Rig Relay: this is a governed tool result. Proposal ≠ execution.]"
)

_AUTHORITY_FORBIDDEN_PATTERNS = [
    "execute immediately",
    "direct execution",
    "bypass permission",
    "bypass authorization",
    "skip approval",
    "no receipt required",
    "omit evidence",
    "omit receipt",
    "publish directly",
    "claim publication",
    "reset workspace",
    "retire workspace",
    "delete workspace",
    "transmit secret",
    "transmit credential",
    "exfiltrate data",
    "send to external",
]


def adapt_tool_description(
    tool_name: str,
    tool_description: str,
    strategy: ToolDialectStrategy,
    profile_id: str,
) -> str:
    match strategy:
        case ToolDialectStrategy.RIG_NATIVE:
            return tool_description
        case ToolDialectStrategy.OPENAI_FUNCTION_CALLING:
            return (
                f"{tool_description}\n\n"
                "This tool operates under Rig Relay governance. "
                "All actions are receipt-backed."
            )
        case ToolDialectStrategy.ANTHROPIC_TOOL_USE:
            return (
                f"{tool_description}\n\n"
                "Note: When using this tool via Anthropic tool_use blocks, "
                "the tool returns structured content. Rig Relay governance "
                "still applies — all actions are receipt-backed."
            )
        case ToolDialectStrategy.MODEL_DRIVEN:
            return (
                f"{tool_description}\n\n"
                "Actual execution is governed by Rig Relay. "
                "The model determines tool format; Rig determines authority."
            )


def adapt_tool_result(
    tool_name: str, result: str, strategy: ToolDialectStrategy, profile_id: str
) -> str:
    match strategy:
        case ToolDialectStrategy.RIG_NATIVE:
            return f"{_GOVERNANCE_HEADER}\n{result}"
        case ToolDialectStrategy.OPENAI_FUNCTION_CALLING:
            header = _GOVERNANCE_HEADER
            if "codex" in profile_id.lower():
                header += (
                    " Citation format: use 【F:path†L1-L2】 when referencing "
                    "file locations."
                )
            return f"{header}\n{result}"
        case ToolDialectStrategy.ANTHROPIC_TOOL_USE:
            return f"{_GOVERNANCE_HEADER}\n{result}"
        case ToolDialectStrategy.MODEL_DRIVEN:
            return f"{_GOVERNANCE_HEADER}\n{result}"


def assert_tool_dialect_authority_preserved(
    adapted_description: str,
    original_description: str,
    profile: HarnessCompatibilityProfile,
) -> bool:
    combined = f"{adapted_description} {original_description}".lower()

    for pattern in _AUTHORITY_FORBIDDEN_PATTERNS:
        if pattern in combined:
            return False

    forbidden_keywords = [
        "grant mutation authority",
        "claim execution authority",
        "bypass permissions",
        "omit evidence",
        "claim publication",
        "claim workspace reset",
        "transmit secret",
    ]
    for kw in forbidden_keywords:
        if kw in combined:
            return False

    if (
        "publication" in adapted_description.lower()
        and "publication" not in original_description.lower()
    ):
        return False

    return True
