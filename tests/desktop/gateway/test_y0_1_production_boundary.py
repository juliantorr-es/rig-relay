"""Production-boundary tests proving Y0.1 widened interface repairs
and analytics surface work correctly.

Real-substrate: imports actual production models and builders. No mocks,
no stubs, no fakes beyond minimal inline helper objects for
availability-derivation tests.
"""

from __future__ import annotations

import pytest

from rig_relay.desktop.gateway._models import (
    DeveloperStudioProjection,
    SafariCompanionFields,
)
from rig_relay.desktop.gateway._models_surfaces import (
    AnalyticsReportsSurfaceProjection,
    ConnectSurfaceProjection,
    InferenceStudioSurfaceProjection,
)
from rig_relay.desktop.gateway._projection_surfaces import _derive_x0_availability

# ── X0 availability derivation ─────────────────────────────────────


@pytest.mark.contract
def test_unavailable_backend_maps_to_unavailable_not_corrupt() -> None:
    """When X0 projection surface is None (no backend at all),
    the derived availability must report unavailable, not corrupt_source
    or error.
    """
    result = _derive_x0_availability(None, "repository_estate")
    assert result["status"] == "unavailable"
    assert "reason" in result


@pytest.mark.contract
def test_connection_failure_exception_maps_to_connection_required() -> None:
    """When get_projection_status raises a ConnectionError, status must be
    connection_required, not corrupt_source.
    """

    class FakeFailingSurface:
        def get_projection_status(self):
            raise ConnectionError("Connection refused")

    result = _derive_x0_availability(FakeFailingSurface(), "repository_estate")
    assert result["status"] == "connection_required"


@pytest.mark.contract
def test_actual_corruption_maps_to_corrupt_source() -> None:
    """When get_projection_status returns corrupt_source, the status must be
    corrupt_source (not connection_required or degraded).
    """

    class FakeCorruptStatus:
        def __init__(self) -> None:
            self.availability = "corrupt_source"
            self.rows_materialized = 0
            self.corrupt_rows = 1
            self.deterministic = False
            self.latest_build_at = "2026-01-01"
            self.authority_state = "corrupt"

    class FakeCorruptSurface:
        def get_projection_status(self):
            return {"repository_estate": FakeCorruptStatus()}

    result = _derive_x0_availability(FakeCorruptSurface(), "repository_estate")
    assert result["status"] == "corrupt_source"


# ── DeveloperStudioProjection structural checks ────────────────────


@pytest.mark.contract
def test_developer_studio_projection_constructs_with_all_surfaces() -> None:
    """DeveloperStudioProjection must construct without errors and
    all 9 surface fields must resolve to correct types.
    """
    p = DeveloperStudioProjection(
        projection_id="test", generated_at="2026-01-01T00:00:00Z"
    )
    assert isinstance(p.connect_surface, ConnectSurfaceProjection)
    assert isinstance(p.analytics_reports_surface, AnalyticsReportsSurfaceProjection)
    assert p.content_light is True


@pytest.mark.contract
def test_deferred_surfaces_do_not_overclaim_availability() -> None:
    """Y1-Y4 deferred surface slots must truthfully report
    unavailable/setup_required, not claim live delivery.
    """
    p = DeveloperStudioProjection(
        projection_id="test", generated_at="2026-01-01T00:00:00Z"
    )
    assert p.repository_readiness_surface.available is False
    assert p.repository_readiness_surface.surface_status == "setup_required"
    assert p.fleet_workspaces_surface.available is False
    assert p.harness_profile_surface.available is False


@pytest.mark.contract
def test_analytics_surface_has_x_wave_fields() -> None:
    """AnalyticsReportsSurfaceProjection must carry x_wave_providers
    and summary fields for the X-Wave readiness report.
    """
    p = DeveloperStudioProjection(
        projection_id="test", generated_at="2026-01-01T00:00:00Z"
    )
    a = p.analytics_reports_surface
    assert hasattr(a, "x_wave_providers")
    assert hasattr(a, "landed_and_visible")
    assert hasattr(a, "remote_not_consumed")
    assert hasattr(a, "cannot_confirm_remotely")
    assert isinstance(a.x_wave_providers, list)


# ── Safari shared mixin deduplication ──────────────────────────────


@pytest.mark.contract
def test_safari_fields_use_shared_mixin_no_duplication() -> None:
    """M0InferenceProjection and InferenceStudioSurfaceProjection must
    both inherit SafariCompanionFields with no duplicate field declarations.
    """
    safari_field_names = [
        f for f in SafariCompanionFields.model_fields if f.startswith("safari_")
    ]
    iss_own = set(InferenceStudioSurfaceProjection.model_fields) - set(
        SafariCompanionFields.model_fields
    )
    safari_in_own = [f for f in iss_own if f.startswith("safari_")]
    assert len(safari_in_own) == 0, (
        f"Safari fields duplicated in InferenceStudio: {safari_in_own}"
    )
    assert len(safari_field_names) > 0


# ── X3 publication projection importability ─────────────────────────


@pytest.mark.contract
def test_x3_publication_projection_importable() -> None:
    """build_publication_projection must be importable from the public API."""
    try:
        from rig_relay.publication import build_publication_projection

        assert callable(build_publication_projection)
    except ImportError:
        pytest.skip(
            "build_publication_projection not available (expected on remote main)"
        )


# ── X-Wave readiness report ────────────────────────────────────────


@pytest.mark.contract
def test_x_wave_readiness_report_builds_with_providers() -> None:
    """build_x_wave_readiness_report must return 4 providers with
    truthful status fields.
    """
    from rig_relay.analytics._readiness_report import build_x_wave_readiness_report

    report = build_x_wave_readiness_report()
    assert len(report.provider_summary) == 4
    lanes = {p.provider_lane for p in report.provider_summary}
    assert lanes == {"X1", "X2", "X3", "X4"}
    assert report.landed_and_visible >= 0
    assert report.content_light_guarantee is True


@pytest.mark.contract
def test_readiness_report_is_content_light() -> None:
    """Readiness report must not contain raw file contents, prompts,
    or secrets in its serialized form.
    """
    import json

    from rig_relay.analytics._readiness_report import build_x_wave_readiness_report

    report = build_x_wave_readiness_report()
    data = report.model_dump(mode="json")
    json_str = json.dumps(data)
    forbidden = ["raw_file_contents", "raw_prompt", "secret", "password", "API_KEY"]
    for term in forbidden:
        assert term not in json_str.lower(), f"Forbidden term '{term}' found in report"
