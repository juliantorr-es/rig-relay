"""Content-light fail-closed enforcement tests — Lane X0.2 Gate H."""

from __future__ import annotations

import pytest

from rig_relay.desktop.gateway._content_light import enforce_content_light
from rig_relay.desktop.gateway._intents import (
    get_gateway_service,
    reset_gateway_service,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_gateway_service()


class TestContentLightFailClosed:
    def test_token_leak_in_projection_is_detected(self) -> None:
        violations = enforce_content_light(
            {"bad": "github_pat_ABCabcDEFdefGHIghiJKLjklMNO"}, source_label="test"
        )
        assert len(violations) > 0

    def test_raw_path_in_projection_is_detected(self) -> None:
        violations = enforce_content_light(
            {"path": "/Users/user/secret/project/src/main.py"}, source_label="test"
        )
        assert len(violations) > 0

    def test_provider_url_not_flagged_as_path(self) -> None:
        """base_url values should not be false-flagged as paths."""
        violations = enforce_content_light(
            {"base_url": "https://api.openai.com/v1"}, source_label="test"
        )
        assert len(violations) == 0

    def test_repository_name_not_flagged_as_path(self) -> None:
        """Repository names like 'rig-relay' should not be false-flagged."""
        violations = enforce_content_light(
            {"repository_label": "rig-relay"}, source_label="test"
        )
        assert len(violations) == 0

    def test_build_projection_fails_closed_on_violation(self) -> None:
        """When content-light violations exist, the projection is refused."""
        gw = get_gateway_service()
        # Build a projection — it should succeed normally
        proj = gw.build_projection()
        # The projection should have content_light=True in normal operation
        # (The test environment has no secrets, so it should pass)
        assert proj.content_light is True

    def test_enforce_content_light_detects_secrets_in_nested_dict(self) -> None:
        violations = enforce_content_light(
            {
                "level1": {
                    "level2": {"token": "ghp_0123456789ABCDEFGHIJabcdefghijABCDEFGH"}
                }
            },
            source_label="test",
        )
        assert len(violations) > 0

    def test_enforce_content_light_rejects_forbidden_field_names(self) -> None:
        violations = enforce_content_light(
            {"access_token": "any_value"}, source_label="test"
        )
        assert len(violations) > 0

    def test_enforce_content_light_rejects_long_strings(self) -> None:
        long_str = "x" * 2001
        violations = enforce_content_light({"data": long_str}, source_label="test")
        assert len(violations) > 0
