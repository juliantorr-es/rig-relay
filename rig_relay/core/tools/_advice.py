from __future__ import annotations

__all__ = [
    "_CHECKPOINT_ADVICE",
    "_SEARCH_REPLACE_ADVICE",
    "_WRITE_FILE_ADVICE",
    "suggested_next_action_for_error",
]

_SEARCH_REPLACE_ADVICE: dict[str, str] = {
    "expected_hash_mismatch": (
        "Re-read the file, set expected_before_sha256 to the current bytes, and retry."
    ),
    "dirty_file_protected": (
        "Re-read the file, set expected_before_sha256 to the current bytes, and retry."
    ),
    "path_reserved": "Wait for the other session to release the lease, then retry.",
    "old_text_not_found": "Re-read the file and update the SEARCH block to match it.",
    "multiple_matches_when_single_required": (
        "Set allow_multiple=true or narrow the SEARCH block to one match."
    ),
    "replacement_count_mismatch": (
        "Adjust expected_replacements to the actual replacement count."
    ),
    "content_too_large": "Shorten the SEARCH/REPLACE content and retry.",
    "empty_content": "Provide a non-empty SEARCH/REPLACE block and retry.",
    "parse_error": "Fix the SEARCH/REPLACE block format and retry.",
    "block_parse_failed": "Fix the SEARCH/REPLACE block format and retry.",
    "file_not_found": "Fix the target path and retry.",
    "path_refused": "Fix the target path and retry.",
    "unsafe_path": "Fix the target path and retry.",
    "path_is_directory": "Fix the target path and retry.",
    "binary_file": "Use a binary-safe editing path instead of search_replace.",
}

_WRITE_FILE_ADVICE: dict[str, str] = {
    "expected_hash_mismatch": (
        "Re-read the file, set expected_before_sha256 to the current bytes, and retry."
    ),
    "dirty_file_protected": (
        "Re-read the file, set expected_before_sha256 to the current bytes, and retry."
    ),
    "path_reserved": "Wait for the other session to release the lease, then retry.",
    "overwrite_required": "Set overwrite=True if you intend to replace the file.",
    "parent_missing": "Create the parent directory or choose an existing path.",
    "content_too_large": "Shorten the content or split the write into a smaller file.",
    "path_is_directory": "Choose a file path instead of a directory.",
}

_CHECKPOINT_ADVICE: dict[str, str] = {
    "unstaged_file_refused": "Stage the requested files, then retry checkpoint.",
    "path_reserved": "Wait for the other session to release the lease, then retry.",
    "empty_message": "Provide a non-empty checkpoint message and retry.",
}


def suggested_next_action_for_error(
    tool_name: str, error_kind: str | None
) -> str | None:
    """Look up recovery advice by tool name and error kind. Pure deterministic lookup."""
    if error_kind is None:
        return None
    match tool_name:
        case "search_replace":
            return _SEARCH_REPLACE_ADVICE.get(error_kind)
        case "write_file":
            return _WRITE_FILE_ADVICE.get(error_kind)
        case "checkpoint":
            return _CHECKPOINT_ADVICE.get(error_kind)
        case _:
            return None
