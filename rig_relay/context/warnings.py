"""Context assembler warnings — safe, content-light, structured.

Warning codes are stable enum-ish strings. Detail fields carry only
content-light information: no raw paths, no secrets, no raw exception messages.
"""

from __future__ import annotations

from typing import Any


class ContextWarningCode:
    REPO_SCAN_FAILED = "repo_scan_failed"
    WORK_MAP_FAILED = "work_map_failed"
    FINDINGS_SUMMARY_FAILED = "findings_summary_failed"
    RECEIPT_SCAN_FAILED = "receipt_scan_failed"
    REPO_INDEX_UNAVAILABLE = "repo_index_unavailable"
    REPO_INDEX_QUERY_FAILED = "repo_index_query_failed"
    COMPRESSION_FAILED = "compression_failed"
    NO_CANDIDATES_DISCOVERED = "no_candidates_discovered"
    UNTRUSTED_CONTEXT_BOUNDARY = "untrusted_context_boundary"
    PLANNER_SAFE_FIND_FAILED = "planner_safe_find_failed"
    SYMBOL_DIGEST_FAILED = "symbol_digest_failed"
    SYMBOL_MANIFEST_FAILED = "symbol_manifest_failed"
    COLLISION_DEGRADED = "collision_degraded"
    HANDOFF_DEGRADED = "handoff_degraded"


def build_warning(
    code: str,
    detail: str = "",
    source: str | None = None,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    """Build a content-light warning dict.

    Never includes raw paths, secrets, or raw exception messages.
    Detail text is truncated to 200 characters.
    """
    w: dict[str, Any] = {"code": code}
    if detail:
        w["detail"] = str(detail)[:200]
    if source:
        w["source"] = source
    if candidate_id:
        w["candidate_id"] = candidate_id
    return w


def exception_class_name(exc: Exception) -> str:
    """Return the exception class name only — no message, no traceback."""
    return type(exc).__name__


__all__ = ["ContextWarningCode", "build_warning", "exception_class_name"]
