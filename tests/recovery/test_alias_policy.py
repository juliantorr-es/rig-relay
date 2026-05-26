"""Test explicit alias policy — deterministic, literal, no fuzzy matching."""

from __future__ import annotations

from rig_relay.recovery.alias_policy import (
    _ALIAS_MAP,
    _SHELL_METACHAR_RE,
    check_alias_shadows_canonical,
    resolve_alias,
    validate_alias_registry,
)


def test_resolve_hyphen_alias() -> None:
    assert resolve_alias("git-status") == "git_status"
    assert resolve_alias("read-file") == "read_file"
    assert resolve_alias("write-file") == "write_file"
    assert resolve_alias("search-replace") == "search_replace"


def test_resolve_underscore_not_changed() -> None:
    assert resolve_alias("git_status") is None


def test_resolve_unknown_returns_none() -> None:
    assert resolve_alias("getstatus") is None
    assert resolve_alias("readfiel") is None
    assert resolve_alias("gitty") is None


def test_resolve_empty_string_returns_none() -> None:
    assert resolve_alias("") is None


def test_no_substring_matching() -> None:
    assert resolve_alias("git") is None
    assert resolve_alias("read") is None
    assert resolve_alias("write") is None


def test_all_aliases_are_lowercase() -> None:
    for alias in _ALIAS_MAP:
        assert alias == alias.lower(), f"Alias '{alias}' is not lowercase"


def test_all_aliases_map_to_lowercase_canonical() -> None:
    for alias, canonical in _ALIAS_MAP.items():
        assert canonical == canonical.lower(), (
            f"Canonical '{canonical}' for alias '{alias}' is not lowercase"
        )


def test_validate_registry_rejects_unknown_canonical() -> None:
    refusal = validate_alias_registry({"git_status"})
    assert refusal is not None


def test_validate_registry_accepts_valid_alias_set() -> None:
    admitted = {
        "git_status",
        "git_diff",
        "git_log",
        "git_branch",
        "git_show",
        "git_ls_files",
        "read_file",
        "write_file",
        "search_replace",
        "prepare_checkpoint",
        "validation_suite",
        "get_context",
        "git_workspace_state",
        "ast_grep",
        "git_hub_tool",
        "git_hub_truth_tool",
        "behavior_patch",
        "ask_user_question",
        "exit_plan_mode",
        "web_fetch",
    }
    refusal = validate_alias_registry(admitted)
    assert refusal is None


def test_alias_shadow_detection_returns_none_for_clean_set() -> None:
    admitted = {"git_status", "read_file"}
    shadow = check_alias_shadows_canonical(admitted)
    assert shadow is None


def test_no_aliases_contain_shell_metacharacters() -> None:
    for alias in _ALIAS_MAP:
        assert not _SHELL_METACHAR_RE.search(alias), (
            f"Alias '{alias}' contains shell metacharacters"
        )
