from __future__ import annotations

from typing import Any

from rig_relay.core.tools.builtins.validate_profiles import list_profiles

_BLOCKER_ADVICE: dict[str, str] = {
    "test_failure": "Fix the failing tests, then rerun the same validate profile.",
    "lint_failure": "Fix the lint violations, then rerun the profile on the affected files.",
    "typecheck_failure": "Fix the type errors, then rerun the Python validation profile.",
    "schema_failure": "Fix the schema or generated artifact, then rerun schema validation.",
    "governance_failure": (
        "Review the validation policy requirements, then rerun with the needed permissions."
    ),
    "dirty_workspace": "Clean or scope the dirty paths, then rerun the profile.",
    "timeout": "Rerun with narrower path scope or a longer timeout.",
    "missing_dependency": "Install the missing dependency or run `uv sync`, then retry.",
    "validation_already_running": "Wait for the current validation run to finish, then retry.",
    "blocked_duplicate": "Wait for the current validation run to finish, then retry.",
    "unknown_failure": "Review the failing check output and rerun the profile.",
}

_REFUSAL_ADVICE: dict[str, str] = {
    "tool_refusal": "Choose one of the known validate profiles and retry.",
    "unsafe_paths": "Re-run with paths inside the workspace root.",
    "dirty_workspace": "Clean or scope the dirty paths, then rerun the profile.",
    "validation_already_running": "Wait for the current validation run to finish, then retry.",
}


def suggested_next_action(result: Any) -> str | None:
    refusal_reason = str(getattr(result, "refusal_reason", "") or "").lower()
    error_kind = getattr(result, "error_kind", None)
    raw_status = getattr(result, "status", None)
    status = raw_status.value if hasattr(raw_status, "value") else raw_status
    blocker_summary = getattr(result, "blocker_summary", None) or {}
    suggestion: str | None = None

    if status != "passed" and error_kind in _REFUSAL_ADVICE:
        if error_kind == "tool_refusal" and "unknown profile" in refusal_reason:
            profiles = ", ".join(list_profiles())
            suggestion = f"Choose one of: {profiles}."
        else:
            suggestion = _REFUSAL_ADVICE[error_kind]
    elif isinstance(blocker_summary, dict) and blocker_summary:
        priority = (
            "test_failure",
            "lint_failure",
            "typecheck_failure",
            "schema_failure",
            "governance_failure",
            "dirty_workspace",
            "timeout",
            "missing_dependency",
            "blocked_duplicate",
            "unknown_failure",
        )
        for blocker in priority:
            if blocker in blocker_summary:
                suggestion = _BLOCKER_ADVICE[blocker]
                break

    if suggestion is None and status in {"failed", "blocked", "timed_out", "refused"}:
        if "unknown profile" in refusal_reason:
            profiles = ", ".join(list_profiles())
            suggestion = f"Choose one of: {profiles}."
        else:
            suggestion = (
                "Review the validation result and rerun with a narrower profile or "
                "fixed inputs."
            )

    return suggestion


def retryable(result: Any) -> bool | None:
    raw_status = getattr(result, "status", None)
    status = raw_status.value if hasattr(raw_status, "value") else raw_status
    if status in {"passed", "skipped"}:
        return None
    if status in {"failed", "blocked", "timed_out", "refused"}:
        return True
    return None


__all__ = ["retryable", "suggested_next_action"]
