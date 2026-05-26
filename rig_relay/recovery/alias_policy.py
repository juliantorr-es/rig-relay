"""Explicit alias policy for deterministic tool-call recovery.

Conservative initial aliases: underscore/hyphen formatting variants only.
No fuzzy matching. No semantic synonyms. No substring guessing.
"""

from __future__ import annotations

import re

from rig_relay.recovery.models import RecoveryRefusal, RecoveryRefusalCode

_ALIAS_MAP: dict[str, str] = {
    "git-status": "git_status",
    "git-diff": "git_diff",
    "git-log": "git_log",
    "git-branch": "git_branch",
    "git-show": "git_show",
    "git-ls-files": "git_ls_files",
    "git-ls_files": "git_ls_files",
    "read-file": "read_file",
    "write-file": "write_file",
    "search-replace": "search_replace",
    "prepare-checkpoint": "prepare_checkpoint",
    "validation-suite": "validation_suite",
    "get-context": "get_context",
    "git-workspace-state": "git_workspace_state",
    "ast-grep": "ast_grep",
    "behavior-patch": "behavior_patch",
    "ask-user-question": "ask_user_question",
    "exit-plan-mode": "exit_plan_mode",
    "web-fetch": "web_fetch",
    "git_hub-tool": "git_hub_tool",
    "git-hub-tool": "git_hub_tool",
    "git-hub-truth-tool": "git_hub_truth_tool",
    "git_hub-truth-tool": "git_hub_truth_tool",
}

_PAYLOAD_KEY_ALIASES: dict[str, dict[str, str]] = {
    "checkpoint": {"msg": "message"},
    "search_replace": {"old_str": "old_string", "new_str": "new_string"},
}


def resolve_alias(candidate_name: str) -> str | None:
    """Resolve an explicit alias to a canonical tool name.

    Returns the canonical name if the candidate is a recognized alias,
    None otherwise. Case-insensitive matching for single-token aliases
    only (hyphenated variants must match exactly).
    """
    normalized = candidate_name.strip().lower()
    if normalized in _ALIAS_MAP:
        return _ALIAS_MAP[normalized]
    return None


def get_payload_key_alias(canonical_tool: str, candidate_key: str) -> str | None:
    """Resolve a payload key alias for a specific canonical tool.

    Returns the canonical key name if a mapping exists, None otherwise.
    Scoped to individual tool contracts — no cross-tool generalization.
    """
    tool_aliases = _PAYLOAD_KEY_ALIASES.get(canonical_tool, {})
    return tool_aliases.get(candidate_key)


def validate_alias_registry(admitted_names: set[str]) -> RecoveryRefusal | None:
    """Validate the alias registry against admitted tool names.

    Returns a refusal if any alias maps to an unknown tool
    or if any alias collides with a different canonical name.
    """
    for alias, canonical in _ALIAS_MAP.items():
        if canonical not in admitted_names:
            return RecoveryRefusal(
                refusal_code=RecoveryRefusalCode.CANONICAL_TOOL_NOT_ADMITTED,
                reason=f"Alias '{alias}' maps to unknown canonical tool '{canonical}'",
                candidate_count=0,
                manifest_digest="sha256:" + "0" * 64,
                original_emission_hash="sha256:" + "0" * 64,
            )
        if _SHELL_METACHAR_RE.search(alias):
            return RecoveryRefusal(
                refusal_code=RecoveryRefusalCode.FORBIDDEN_SHELL_SURFACE,
                reason=f"Alias '{alias}' contains shell metacharacters",
                candidate_count=0,
                manifest_digest="sha256:" + "0" * 64,
                original_emission_hash="sha256:" + "0" * 64,
            )
    return None


def check_alias_shadows_canonical(admitted_names: set[str]) -> str | None:
    """Check that no alias shadows a different canonical tool name.

    Returns the first shadowing alias found, or None.
    """
    for alias, canonical in _ALIAS_MAP.items():
        if alias in admitted_names and alias != canonical:
            return alias
    return None


_SHELL_METACHAR_RE = re.compile(r"[;&|`$(){}\[\]<>!\\'\"]")
