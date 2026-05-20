from __future__ import annotations

from enum import StrEnum, auto


class ReactionClass(StrEnum):
    PROJECTION_UPDATE = auto()
    EVIDENCE_APPEND = auto()
    LOCAL_DIAGNOSTIC = auto()
    SCHEDULING_HINT = auto()
    GATED_COMMAND_REQUIRED = auto()
    FORBIDDEN = auto()


_READ_SIDE_CLASS: dict[str, ReactionClass] = {
    "projection_update": ReactionClass.PROJECTION_UPDATE,
    "evidence_append": ReactionClass.EVIDENCE_APPEND,
    "local_diagnostic": ReactionClass.LOCAL_DIAGNOSTIC,
}

_GATED_COMMAND_PREFIXES = frozenset({"tool.", "github."})

_FORBIDDEN_ACTIONS: frozenset[str] = frozenset({
    "dismiss_alert",
    "create_pr",
    "create_issue",
    "merge_branch",
    "delete_branch",
    "push_remote",
    "deploy",
})


def classify_reaction(event_type: str, intended_action: str) -> ReactionClass:
    read_side = _READ_SIDE_CLASS.get(intended_action)
    if read_side is not None:
        return read_side

    if intended_action == "scheduling_hint" and event_type.startswith("resource."):
        return ReactionClass.SCHEDULING_HINT

    is_forbidden = intended_action in _FORBIDDEN_ACTIONS
    is_gated_domain = any(
        event_type.startswith(prefix) for prefix in _GATED_COMMAND_PREFIXES
    )

    if is_forbidden:
        return ReactionClass.FORBIDDEN

    if is_gated_domain:
        return ReactionClass.GATED_COMMAND_REQUIRED

    return ReactionClass.GATED_COMMAND_REQUIRED


__all__ = ["ReactionClass", "classify_reaction"]
