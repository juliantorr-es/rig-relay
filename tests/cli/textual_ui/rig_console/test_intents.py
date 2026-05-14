"""Tests for DashboardActionResult — read-only action result model."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from vibe.cli.textual_ui.rig_console.intents import DashboardActionResult


class TestDashboardActionResult:
    """DashboardActionResult model tests."""

    def test_minimal_construction(self) -> None:
        result = DashboardActionResult(action_name="refresh")
        assert result.action_name == "refresh"
        assert result.status == "ok"
        assert result.message is None

    def test_full_construction(self) -> None:
        result = DashboardActionResult(
            action_name="validate", status="error", message="Not wired"
        )
        assert result.action_name == "validate"
        assert result.status == "error"
        assert result.message == "Not wired"

    def test_ok_convenience(self) -> None:
        result = DashboardActionResult.ok("refresh", "Done")
        assert result.action_name == "refresh"
        assert result.status == "ok"
        assert result.message == "Done"

    def test_ok_without_message(self) -> None:
        result = DashboardActionResult.ok("refresh")
        assert result.action_name == "refresh"
        assert result.status == "ok"
        assert result.message is None

    def test_info_convenience(self) -> None:
        result = DashboardActionResult.info("help", "Available actions")
        assert result.action_name == "help"
        assert result.status == "info"
        assert result.message == "Available actions"

    def test_error_convenience(self) -> None:
        result = DashboardActionResult.error("validate", "Not available")
        assert result.action_name == "validate"
        assert result.status == "error"
        assert result.message == "Not available"

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            DashboardActionResult.model_validate({
                "action_name": "test",
                "raw_output": "should_not_exist",
            })

    def test_no_raw_field_names(self) -> None:
        forbidden = ("stdout", "stderr", "output", "content", "diff", "snippet")
        for field_name in DashboardActionResult.model_fields:
            lower = field_name.lower()
            for prefix in forbidden:
                assert not lower.startswith(prefix), (
                    f"Field '{field_name}' starts with forbidden prefix '{prefix}'"
                )
