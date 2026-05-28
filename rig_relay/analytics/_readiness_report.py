"""X-Wave Readiness Report Projection — Lane Y0.1.

Consumes public provider boundaries and admitted evidence artifacts
to produce a typed X-Wave readiness report for the desktop cockpit.
"""

from __future__ import annotations

from datetime import UTC

from pydantic import BaseModel, ConfigDict, Field


class ProviderReadinessEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_lane: str = ""
    product_name: str = ""
    released_boundary: str = ""
    remote_sha: str | None = None
    consumer_readiness: str = (
        "unavailable"  # available, verification_pending, unavailable
    )
    desktop_consumption_state: str = "unavailable"  # available, pending, unavailable
    status: str = "unavailable"


class XWaveReadinessReportProjection(BaseModel):
    """Content-light X-Wave readiness report for desktop cockpit."""

    model_config = ConfigDict(extra="forbid")
    schema_version: str = "rig.relay.x_wave_readiness_report.v1"
    generated_at: str = ""

    # Provider readiness
    provider_summary: list[ProviderReadinessEntry] = Field(default_factory=list)

    # Delivery summary
    landed_and_visible: int = 0
    remote_not_consumed: int = 0
    cannot_confirm_remotely: int = 0

    # Integration gaps
    blocking_seams: list[str] = Field(default_factory=list)
    deferred_seams: list[str] = Field(default_factory=list)

    # Content-light
    content_light_guarantee: bool = True


def build_x_wave_readiness_report() -> XWaveReadinessReportProjection:
    """Build X-Wave readiness report from admitted evidence and remote truth."""
    from datetime import datetime

    providers: list[ProviderReadinessEntry] = []

    # X1 data plane status
    try:
        from rig_relay.data_plane.postgres._config import PostgresConnectionConfig
        from rig_relay.data_plane.postgres._store import (
            PostgresOperationalProjectionStore,
        )
        from rig_relay.data_plane.postgres._x0_projection import X0ProjectionSurface

        config = PostgresConnectionConfig()
        store = PostgresOperationalProjectionStore(config)
        x0 = X0ProjectionSurface(store)
        statuses = x0.get_projection_status()
        estate_status = statuses.get("repository_estate")
        x1_ready = estate_status is not None and estate_status.availability not in {
            "unavailable"
        }
        providers.append(
            ProviderReadinessEntry(
                provider_lane="X1",
                product_name="PostgreSQL Data Plane",
                released_boundary="X0ProjectionSurface",
                remote_sha="12344dd",  # x1.6 final checkpoint
                consumer_readiness="available" if x1_ready else "verification_pending",
                desktop_consumption_state="available",
                status="available" if x1_ready else "verification_pending",
            )
        )
    except Exception:
        providers.append(
            ProviderReadinessEntry(
                provider_lane="X1",
                product_name="PostgreSQL Data Plane",
                released_boundary="X0ProjectionSurface",
                remote_sha="12344dd",
                consumer_readiness="verification_pending",
                desktop_consumption_state="unavailable",
                status="verification_pending",
            )
        )

    # X2/OMLX status
    providers.append(
        ProviderReadinessEntry(
            provider_lane="X2",
            product_name="Local Inference Runtime",
            released_boundary="RiggedLocalRuntime (X2.4)",
            remote_sha="39a27157",
            consumer_readiness="verification_pending",
            desktop_consumption_state="unavailable",
            status="unavailable",
        )
    )

    # X3 publication status
    providers.append(
        ProviderReadinessEntry(
            provider_lane="X3",
            product_name="Publication Deployment",
            released_boundary="PublicationStatusContract (x3.5 published, x3.7 unpublished)",
            remote_sha="ec1954dc",
            consumer_readiness="verification_pending",
            desktop_consumption_state="unavailable",
            status="verification_pending",
        )
    )

    # X4 Safari companion status
    try:
        from rig_relay.native._safari_x0_contract import build_safari_native_projection

        safari = build_safari_native_projection()
        safari_ready = safari.safari_companion_state != "error"
        providers.append(
            ProviderReadinessEntry(
                provider_lane="X4",
                product_name="Safari Companion",
                released_boundary="SafariNativeProjection",
                remote_sha="3a57413",
                consumer_readiness="available"
                if safari_ready
                else "verification_pending",
                desktop_consumption_state="available",
                status="available" if safari_ready else "verification_pending",
            )
        )
    except Exception:
        providers.append(
            ProviderReadinessEntry(
                provider_lane="X4",
                product_name="Safari Companion",
                released_boundary="SafariNativeProjection",
                remote_sha="3a57413",
                consumer_readiness="verification_pending",
                desktop_consumption_state="unavailable",
                status="verification_pending",
            )
        )

    # Counts
    landed = sum(1 for p in providers if p.desktop_consumption_state == "available")
    remote_not_consumed = sum(
        1
        for p in providers
        if p.consumer_readiness == "available"
        and p.desktop_consumption_state == "unavailable"
    )
    cannot_confirm = sum(1 for p in providers if p.status == "verification_pending")

    return XWaveReadinessReportProjection(
        generated_at=datetime.now(UTC).isoformat(),
        provider_summary=providers,
        landed_and_visible=landed,
        remote_not_consumed=remote_not_consumed,
        cannot_confirm_remotely=cannot_confirm,
        blocking_seams=[],
        deferred_seams=[
            "X2 OMLX runtime not consumed by M0 inference service",
            "X3 build_publication_projection not on remote main",
        ],
    )


__all__ = [
    "ProviderReadinessEntry",
    "XWaveReadinessReportProjection",
    "build_x_wave_readiness_report",
]
