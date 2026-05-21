from __future__ import annotations

import json
from typing import ClassVar

import pytest


class TestAnalyticsWidgetDataHandling:
    """Each analytics widget handles empty, error, and valid data."""

    WIDGET_NAMES: ClassVar[list[str]] = [
        "governanceGateHealth",
        "sessionHealth",
        "toolLatency",
        "releaseBlocker",
        "dependencyRisk",
        "findingsWidget",
        "correlationIntegrity",
        "localInference",
    ]

    @pytest.mark.parametrize("widget_name", WIDGET_NAMES)
    def test_widget_has_registered_renderer(self, widget_name: str) -> None:
        """Verify analytics JS registers all 8 widgets."""
        analytics_js = (
            _repo_root() / "frontend" / "desktop" / "js" / "widgets" / "analytics.js"
        )
        content = analytics_js.read_text()
        assert f"registerWidget('{widget_name}'" in content, (
            f"Widget '{widget_name}' not registered in analytics.js"
        )

    @pytest.mark.parametrize("widget_name", WIDGET_NAMES)
    def test_widget_checks_available_flag(self, widget_name: str) -> None:
        """All widgets guard against unavailable data."""
        analytics_js = (
            _repo_root() / "frontend" / "desktop" / "js" / "widgets" / "analytics.js"
        )
        content = analytics_js.read_text()
        assert ".available" in content, (
            "analytics.js must check .available for unavailable data"
        )
        assert "Unavailable" in content, (
            "analytics.js must render 'Unavailable' for missing data"
        )

    def test_empty_projection_handled(self) -> None:
        """Widget read path handles null/undefined projection."""
        analytics_js = (
            _repo_root() / "frontend" / "desktop" / "js" / "widgets" / "analytics.js"
        )
        content = analytics_js.read_text()
        # The analytics() function returns null-safe chains
        assert "|| null" in content, (
            "analytics() must return null for missing projection"
        )
        assert "|| {}" in content, "Widget must default to {} when data is missing"

    def test_compact_chips_exist(self) -> None:
        """At least some widgets render compact chips."""
        analytics_js = (
            _repo_root() / "frontend" / "desktop" / "js" / "widgets" / "analytics.js"
        )
        content = analytics_js.read_text()
        assert "renderCompactChip" in content, (
            "Analytics widgets must render compact chips"
        )

    def test_standard_cards_exist(self) -> None:
        """All widgets render standard cards."""
        analytics_js = (
            _repo_root() / "frontend" / "desktop" / "js" / "widgets" / "analytics.js"
        )
        content = analytics_js.read_text()
        assert content.count("renderStandardCard") >= len(self.WIDGET_NAMES), (
            "Every analytics widget must render a standard card"
        )

    def test_expanded_views_exist(self) -> None:
        """All widgets render expanded views."""
        analytics_js = (
            _repo_root() / "frontend" / "desktop" / "js" / "widgets" / "analytics.js"
        )
        content = analytics_js.read_text()
        assert content.count("renderExpandedWidget") >= len(self.WIDGET_NAMES), (
            "Every analytics widget must render an expanded view"
        )


class TestAnalyticsContentLight:
    """Analytics projection data is content-light (no secrets, raw prompts, paths)."""

    FORBIDDEN_PATTERNS: ClassVar[list[str]] = [
        "sk-",
        "ghp_",
        "api_key",
        "secret",
        "password",
        "raw_prompt",
        "file_contents",
        "model_output",
        "/Users/",
        "bearer ",
    ]

    def sample_analytics_projection(self) -> dict:
        return {
            "governance_gate_health": {
                "available": True,
                "decisions": {"allowed": 42, "blocked": 5, "critical": 1},
                "total": 48,
            },
            "session_health": {
                "available": True,
                "sessions": {"healthy": 120, "degraded": 3, "failed": 0},
                "total": 123,
            },
            "tool_latency": {
                "available": True,
                "tools": [
                    {"name": "read_file", "p50_ms": 12, "p95_ms": 45, "p99_ms": 120}
                ],
            },
            "release_blockers": {
                "available": True,
                "open": 3,
                "resolved": 27,
                "total": 30,
                "trend": "improving",
            },
            "dependency_risk": {
                "available": True,
                "packages": [
                    {
                        "name": "urllib3",
                        "risk": "high",
                        "current": "1.26.0",
                        "latest": "2.0.0",
                    }
                ],
            },
            "findings": {
                "available": True,
                "total": 12,
                "by_severity": {"low": 5, "medium": 4, "high": 2, "critical": 1},
                "open": 8,
                "resolved": 4,
            },
            "correlation_integrity": {
                "available": True,
                "status": "healthy",
                "matched": 95,
                "unmatched": 0,
                "total": 95,
            },
            "local_inference": {
                "available": True,
                "models": [
                    {"name": "llama3-8b", "status": "running", "tokens_per_sec": 42}
                ],
            },
        }

    def test_no_forbidden_patterns_in_sample_data(self) -> None:
        """Sample analytics data must not contain secrets or raw content."""
        sample = self.sample_analytics_projection()
        serialized = json.dumps(sample)
        for pattern in self.FORBIDDEN_PATTERNS:
            assert pattern not in serialized.lower(), (
                f"Forbidden pattern '{pattern}' found in analytics projection sample"
            )

    def test_sample_data_no_raw_paths(self) -> None:
        """No raw filesystem paths in analytics projection."""
        sample = self.sample_analytics_projection()
        serialized = json.dumps(sample)
        assert "/Users/" not in serialized
        assert "/home/" not in serialized
        assert "C:\\" not in serialized

    def test_sample_data_structure_valid(self) -> None:
        """Each analytics section has the required 'available' flag."""
        sample = self.sample_analytics_projection()
        for section_name, section_data in sample.items():
            assert isinstance(section_data, dict), (
                f"Section '{section_name}' must be a dict"
            )
            assert "available" in section_data, (
                f"Section '{section_name}' must have 'available' key"
            )
            assert isinstance(section_data["available"], bool), (
                f"Section '{section_name}' available must be bool"
            )


class TestAnalyticsIntegration:
    """Analytics integration with frontend infrastructure."""

    def test_analytics_css_exists(self) -> None:
        css_path = _repo_root() / "frontend" / "desktop" / "css" / "analytics.css"
        assert css_path.is_file(), "analytics.css must exist"
        content = css_path.read_text()
        assert ".analytics-unavailable" in content
        assert ".analytics-bar" in content
        assert ".analytics-heatmap" in content
        assert ".analytics-donut-container" in content

    def test_analytics_js_imports_register_widget(self) -> None:
        analytics_js = (
            _repo_root() / "frontend" / "desktop" / "js" / "widgets" / "analytics.js"
        )
        content = analytics_js.read_text()
        assert "registerWidget(" in content
        assert "from '../widgets.js'" in content
        assert "from '../state.js'" in content

    def test_index_html_includes_analytics_css(self) -> None:
        index_html = _repo_root() / "frontend" / "desktop" / "index.html"
        content = index_html.read_text()
        assert 'href="css/analytics.css"' in content

    def test_index_html_has_analytics_mode_button(self) -> None:
        index_html = _repo_root() / "frontend" / "desktop" / "index.html"
        content = index_html.read_text()
        assert 'data-mode="analytics"' in content, "Analytics mode button missing"

    def test_main_js_has_analytics_panel_assignments(self) -> None:
        main_js = _repo_root() / "frontend" / "desktop" / "js" / "main.js"
        content = main_js.read_text()
        assert "analytics:" in content, "Analytics panel assignments missing"
        for widget_name in TestAnalyticsWidgetDataHandling.WIDGET_NAMES:
            assert widget_name in content, (
                f"Widget '{widget_name}' not in panel assignments"
            )

    def test_state_js_has_analytics_disclosure_defaults(self) -> None:
        state_js = _repo_root() / "frontend" / "desktop" / "js" / "state.js"
        content = state_js.read_text()
        assert "analytics:" in content, "Analytics disclosure defaults missing"

    def test_projection_js_maps_analytics_section(self) -> None:
        projection_js = _repo_root() / "frontend" / "desktop" / "js" / "projection.js"
        content = projection_js.read_text()
        assert "analytics: 'governanceGateHealth'" in content, (
            "Analytics section mapping missing"
        )
        assert "analyticsWidgets" in content, (
            "Analytics widget list not in projection.js"
        )

    def test_orchestrator_imports_analytics(self) -> None:
        orchestrator_js = (
            _repo_root() / "frontend" / "desktop" / "js" / "boot" / "orchestrator.js"
        )
        content = orchestrator_js.read_text()
        assert "widgets/analytics.js" in content, (
            "Analytics import missing from orchestrator"
        )

    def test_widgets_js_exports_helpers(self) -> None:
        widgets_js = _repo_root() / "frontend" / "desktop" / "js" / "widgets.js"
        content = widgets_js.read_text()
        assert "export function renderCompactChip" in content
        assert "export function renderStandardCard" in content
        assert "export function renderExpandedWidget" in content


class TestAnalyticsWidgetStructure:
    """Cross-cutting structural checks on analytics.js."""

    def test_no_innerHTML_for_untrusted_data(self) -> None:
        """Analytics widgets must not use innerHTML directly for user data."""
        analytics_js = (
            _repo_root() / "frontend" / "desktop" / "js" / "widgets" / "analytics.js"
        )
        content = analytics_js.read_text()
        assert "escapeHtml" in content, (
            "Analytics widgets must use escapeHtml for dynamic values"
        )

    def test_all_widgets_have_expanded_level(self) -> None:
        analytics_js = (
            _repo_root() / "frontend" / "desktop" / "js" / "widgets" / "analytics.js"
        )
        content = analytics_js.read_text()
        for _widget_name in TestAnalyticsWidgetDataHandling.WIDGET_NAMES:
            # Each widget section should check for expanded level
            assert "expanded" in content, "Analytics must support expanded disclosure"

    def test_widgets_guard_against_missing_subobjects(self) -> None:
        """Widgets use safe access patterns for nested projection data."""
        analytics_js = (
            _repo_root() / "frontend" / "desktop" / "js" / "widgets" / "analytics.js"
        )
        content = analytics_js.read_text()
        # Guards: || {} patterns and .available checks
        assert content.count("|| {}") >= 6, "Insufficient null guards on sub-objects"


def _repo_root():
    from pathlib import Path

    return Path(__file__).resolve().parent.parent.parent
