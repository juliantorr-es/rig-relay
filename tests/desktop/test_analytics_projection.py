from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from rig_relay.analytics import HAS_DUCKD
from rig_relay.desktop.analytics_projection import (
    ALL_WIDGET_IDS,
    build_analytics_projection,
)


def test_build_analytics_projection_produces_valid_envelope() -> None:
    result = build_analytics_projection()

    assert isinstance(result, dict)
    assert result["schema_version"] == "rig.relay.analytics_projection.v1"
    assert "generated_at" in result
    assert "widgets" in result
    assert isinstance(result["widgets"], list)
    assert len(result["widgets"]) == 8

    for widget in result["widgets"]:
        assert "widget_id" in widget
        assert "refresh_interval_s" in widget
        assert "data" in widget
        assert widget["widget_id"] in ALL_WIDGET_IDS


def test_build_analytics_projection_with_specific_widgets() -> None:
    result = build_analytics_projection(
        widgets=["governance_gate_health", "correlation_integrity"]
    )

    assert len(result["widgets"]) == 2
    widget_ids = [w["widget_id"] for w in result["widgets"]]
    assert "governance_gate_health" in widget_ids
    assert "correlation_integrity" in widget_ids


def test_build_analytics_projection_handles_unknown_widget() -> None:
    result = build_analytics_projection(widgets=["nonexistent_widget"])

    assert len(result["widgets"]) == 1
    widget = result["widgets"][0]
    assert widget["widget_id"] == "nonexistent_widget"
    assert widget.get("error") is not None


def test_build_analytics_projection_handles_duckdb_missing(monkeypatch) -> None:
    import rig_relay.desktop.analytics_projection as ap_mod

    monkeypatch.setattr(ap_mod, "HAS_DUCKD", False)

    result = build_analytics_projection()
    assert result["engine_available"] is False
    for widget in result["widgets"]:
        assert widget.get("error") is not None


def test_build_analytics_projection_engine_failure(monkeypatch) -> None:
    import rig_relay.desktop.analytics_projection as ap_mod

    mock_engine = MagicMock()
    mock_engine.side_effect = RuntimeError("Test engine failure")

    monkeypatch.setattr(ap_mod, "HAS_DUCKD", True)
    monkeypatch.setattr(ap_mod, "AnalyticsEngine", mock_engine)

    result = build_analytics_projection()
    assert result["engine_available"] is False
    for widget in result["widgets"]:
        assert widget.get("error") is not None


def test_build_analytics_projection_content_light_no_raw_content() -> None:
    result = build_analytics_projection()

    serialized = json.dumps(result, sort_keys=True)

    forbidden_terms = [
        "api_key",
        "secret",
        "password",
        "private_key",
        "access_token",
        "raw_prompt",
    ]
    for term in forbidden_terms:
        assert term not in serialized.lower(), f"Forbidden term found: {term}"


def test_build_analytics_projection_includes_refresh_intervals() -> None:
    from rig_relay.analytics.views import WIDGET_REFRESH_INTERVALS

    result = build_analytics_projection()

    for widget in result["widgets"]:
        expected_interval = WIDGET_REFRESH_INTERVALS.get(widget["widget_id"], 120)
        assert widget["refresh_interval_s"] == expected_interval


def test_build_analytics_projection_individual_widget_resilience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rig_relay.desktop.analytics_projection as ap_mod

    original = dict(ap_mod._VIEW_FUNCTIONS)
    try:

        def _failing_view(engine):
            raise ValueError("Simulated view failure")

        # Patch one view to fail, others should still work
        patched = dict(ap_mod._VIEW_FUNCTIONS)
        patched["governance_gate_health"] = _failing_view
        monkeypatch.setattr(ap_mod, "_VIEW_FUNCTIONS", patched)

        result = build_analytics_projection()
        widgets_by_id = {w["widget_id"]: w for w in result["widgets"]}

        assert widgets_by_id["governance_gate_health"].get("error") is not None
        assert widgets_by_id["governance_gate_health"]["data"] == []

        non_failing = widgets_by_id["correlation_integrity"]
        assert isinstance(non_failing["data"], list)
    finally:
        ap_mod._VIEW_FUNCTIONS = original


def test_build_analytics_projection_close_called() -> None:
    mock_engine = MagicMock()
    mock_engine.con = MagicMock()

    with (
        patch(
            "rig_relay.desktop.analytics_projection.AnalyticsEngine",
            return_value=mock_engine,
        ),
        patch("rig_relay.desktop.analytics_projection.HAS_DUCKD", True),
    ):
        build_analytics_projection()

    mock_engine.close.assert_called_once()


def test_all_widget_ids_match_views() -> None:
    from rig_relay.desktop.analytics_projection import _VIEW_FUNCTIONS

    assert sorted(ALL_WIDGET_IDS) == sorted(_VIEW_FUNCTIONS.keys())


@pytest.mark.skipif(not HAS_DUCKD, reason="DuckDB not available")
def test_analytics_projection_schema_validates() -> None:
    result = build_analytics_projection()

    assert result["schema_version"] == "rig.relay.analytics_projection.v1"
    assert isinstance(result["generated_at"], str) and len(result["generated_at"]) > 0
    assert isinstance(result["widgets"], list)
    assert isinstance(result["engine_available"], bool)

    widget_ids = [w["widget_id"] for w in result["widgets"]]
    for wid in ALL_WIDGET_IDS:
        assert wid in widget_ids, f"Missing widget: {wid}"
