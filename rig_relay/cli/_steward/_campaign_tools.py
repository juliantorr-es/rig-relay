"""Campaign tool authority gateway.

Enforces allowlisted runtime capabilities during active campaign
execution. Denies writes outside active scope, protected paths,
and unknown capabilities.
"""

from __future__ import annotations

from pathlib import Path

from rig_relay.campaign_contract.models import CampaignManifest, MissionDefinition
from rig_relay.cli._steward._campaign_models import CampaignState


def _check_scope_and_protected(
    target_path: str, owned_scope: list[str], exclusions: list[str]
) -> str | None:
    """Check path is in owned scope and not in protected/excluded paths."""
    if target_path not in frozenset(owned_scope):
        return f"target '{target_path}' not in active mission owned_path_scope"

    prohibited = [
        ".rig/relay/campaigns/",
        "rig_relay/campaign_contract/",
        ".opencode/plugins/",
    ]
    for prefix in prohibited:
        if target_path.startswith(prefix):
            return f"target '{target_path}' is in a protected authority path"

    if "confidential_build_sink" in frozenset(exclusions):
        if target_path.startswith(".build/rig-relay/confidential/"):
            return f"target '{target_path}' is in confidential build sink"

    return None


def validate_campaign_tool_write(
    state: CampaignState,
    manifest: CampaignManifest,
    mission: MissionDefinition | None,
    target_path: str,
    repo_root: Path,
) -> str | None:
    """Validate a write operation within campaign authority.

    Returns None if the write is allowed.
    Returns a refusal reason string if denied.
    """
    if state.phase not in {"running", "resolver_active", "repair_active"}:
        return f"campaign not in active phase (current: {state.phase})"
    if mission is None:
        return "no active mission or repair context"

    resolved = (repo_root / target_path).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError:
        return f"target '{target_path}' is outside repository root"

    scope_err = _check_scope_and_protected(
        target_path, mission.owned_path_scope, list(manifest.absolute_exclusions)
    )
    return scope_err


def validate_campaign_tool_read(
    state: CampaignState,
    mission: MissionDefinition | None,
    target_path: str,
    repo_root: Path,
) -> str | None:
    """Validate a read operation within campaign authority.

    Returns None if the read is allowed.
    Returns a refusal reason string if denied.
    """
    if mission is None:
        return "no active mission context"

    resolved = (repo_root / target_path).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError:
        return f"target '{target_path}' is outside repository root"

    allowed_read = frozenset(mission.read_context_scope)
    if target_path not in allowed_read:
        return f"target '{target_path}' not in active mission read_context_scope"

    return None
