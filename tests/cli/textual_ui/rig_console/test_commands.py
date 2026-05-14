"""Tests for the Rig Console command palette provider."""

from __future__ import annotations

from unittest.mock import Mock

from textual.app import SystemCommand

from vibe.cli.textual_ui.rig_console.actions import SAFE_ACTIONS
from vibe.cli.textual_ui.rig_console.commands import build_rig_console_commands


def test_command_provider_exposes_expected_commands() -> None:
    screen = Mock()
    commands = list(build_rig_console_commands(screen))

    assert all(isinstance(command, SystemCommand) for command in commands)
    assert [command[0] for command in commands] == [
        action.title for action in SAFE_ACTIONS
    ]


def test_command_provider_callbacks_dispatch_safe_action() -> None:
    screen = Mock()
    command = next(
        command
        for command in build_rig_console_commands(screen)
        if command[0] == "Refresh"
    )

    command[2]()

    screen.run_safe_action.assert_called_once()
    assert screen.run_safe_action.call_args.args[0].name == "refresh"


def test_command_provider_refresh_entry_triggers_refresh_action() -> None:
    screen = Mock()
    command = next(
        command
        for command in build_rig_console_commands(screen)
        if command[0] == "Refresh"
    )

    command[2]()

    assert screen.run_safe_action.call_args.args[0].callback_name == "action_refresh"


def test_no_forbidden_raw_field_names_in_command_metadata() -> None:
    forbidden = (
        "stdout",
        "stderr",
        "content",
        "file_contents",
        "chunk_text",
        "old_text",
        "new_text",
        "diff",
        "patch",
        "prompt",
        "secret",
        "argv",
        "snippet",
    )
    for action in SAFE_ACTIONS:
        for value in (
            action.name,
            action.title,
            action.description,
            action.callback_name,
        ):
            lower = value.lower()
            for prefix in forbidden:
                assert prefix not in lower
