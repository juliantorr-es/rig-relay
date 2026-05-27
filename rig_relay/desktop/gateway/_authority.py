"""Gateway evidence authority model — Lane S2.

Defines the typed authority classification for every service consumed by
the DeveloperStudioGateway. Each service projection carries an explicit
authority state derived from canonical evidence availability, freshness,
and integrity rather than from hardcoded labels.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.desktop.gateway._models import TrustState


class ServiceAuthority(StrEnum):
    """Evidence-backed authority classification for a consumed service.

    These states are derived from canonical evidence, not from
    hardcoded labels or fixture narratives.
    """

    CANONICAL_LIVE = "canonical_live"
    """Live service with fresh, verified evidence from its canonical store."""

    CANONICAL_DEGRADED = "canonical_degraded"
    """Live service but evidence is stale, incomplete, or partially unavailable."""

    CONTROLLED_BOUNDARY = "controlled_boundary"
    """Service is live but exercised through a controlled (non-production) boundary."""

    FIXTURE_DEFERRED = "fixture_deferred"
    """Service is unavailable; typed fixture is used as a stand-in."""

    MISSING = "missing"
    """Service is completely unavailable — no evidence, no fixture."""

    STALE = "stale"
    """Canonical evidence exists but is older than the acceptable freshness window."""

    CORRUPT = "corrupt"
    """Evidence exists but is malformed, fails schema validation, or has inconsistent hashes."""

    CONTRADICTORY = "contradictory"
    """Multiple evidence sources disagree; authority cannot be resolved."""

    UNAUTHORIZED = "unauthorized"
    """Evidence would require authorization that is not available."""

    def to_trust_state(self) -> TrustState:
        """Map authority to the frontend-safe TrustState."""
        _MAP: dict[ServiceAuthority, TrustState] = {
            ServiceAuthority.CANONICAL_LIVE: TrustState.TRUSTED_LIVE,
            ServiceAuthority.CANONICAL_DEGRADED: TrustState.TRUSTED_LIVE,
            ServiceAuthority.CONTROLLED_BOUNDARY: TrustState.CONTROLLED_BOUNDARY,
            ServiceAuthority.FIXTURE_DEFERRED: TrustState.FIXTURE,
            ServiceAuthority.MISSING: TrustState.DEFERRED,
            ServiceAuthority.STALE: TrustState.DEFERRED,
            ServiceAuthority.CORRUPT: TrustState.CORRUPT,
            ServiceAuthority.CONTRADICTORY: TrustState.REFUSED,
            ServiceAuthority.UNAUTHORIZED: TrustState.REFUSED,
        }
        return _MAP[self]

    @property
    def is_evidence_backed(self) -> bool:
        """True when the authority comes from canonical evidence (not fixture)."""
        return self in {
            ServiceAuthority.CANONICAL_LIVE,
            ServiceAuthority.CANONICAL_DEGRADED,
            ServiceAuthority.CONTROLLED_BOUNDARY,
        }

    @property
    def is_degraded(self) -> bool:
        """True when the authority is degraded, blocked, or untrusted."""
        return self in {
            ServiceAuthority.MISSING,
            ServiceAuthority.STALE,
            ServiceAuthority.CORRUPT,
            ServiceAuthority.CONTRADICTORY,
            ServiceAuthority.UNAUTHORIZED,
            ServiceAuthority.FIXTURE_DEFERRED,
        }


class AuthorityEvidence(BaseModel):
    """Lightweight evidence anchor for a service authority claim.

    Content-light: hashes and timestamps only. Never contains raw data.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(description="Service name: j0_workspace, k0_operator, etc.")
    authority: ServiceAuthority
    evidence_sha256: str = Field(
        default="", description="SHA256 of the evidence source"
    )
    evidence_path_digest: str = Field(
        default="", description="SHA256 digest of the evidence file path"
    )
    freshness_at: str = Field(
        default="", description="ISO 8601 timestamp of the evidence's last update"
    )
    checked_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 timestamp of this authority check",
    )
    degradation_reason: str = Field(
        default="", description="If degraded: why (stale, corrupt, missing, etc.)"
    )


class GatewayAuthorityReport(BaseModel):
    """Aggregate authority report for all four consumed services.

    Each service is classified with an evidence-backed ServiceAuthority
    derived from canonical stores, not from hardcoded labels.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.gateway_authority_report.v1", frozen=True
    )
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    j0_workspace: AuthorityEvidence
    k0_operator: AuthorityEvidence
    l0_context: AuthorityEvidence
    m0_inference: AuthorityEvidence

    @property
    def all_evidence_backed(self) -> bool:
        return all(
            e.authority.is_evidence_backed
            for e in [
                self.j0_workspace,
                self.k0_operator,
                self.l0_context,
                self.m0_inference,
            ]
        )

    @property
    def degraded_services(self) -> list[str]:
        return [
            e.kind
            for e in [
                self.j0_workspace,
                self.k0_operator,
                self.l0_context,
                self.m0_inference,
            ]
            if e.authority.is_degraded
        ]


__all__ = ["AuthorityEvidence", "GatewayAuthorityReport", "ServiceAuthority"]
