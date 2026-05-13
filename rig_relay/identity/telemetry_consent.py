"""Telemetry consent model for Rig Relay alpha onboarding.

Content-light consent records — no raw email, raw tokens, raw prompts,
raw code, or raw output.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum, auto

from pydantic import BaseModel, ConfigDict


class TelemetryConsentStatus(StrEnum):
    NOT_REQUESTED = auto()
    GRANTED = auto()
    DENIED = auto()
    REVOKED = auto()


class TelemetryConsentScope(StrEnum):
    # Basic telemetry scopes (opt-in by default)
    USAGE_METRICS = auto()
    CONTENT_LIGHT_BUNDLES = auto()
    CRASH_REPORTS = auto()
    COORDINATION_METRICS = auto()
    TOOL_REFINEMENT_METRICS = auto()
    # Commercial / dataset license scopes (opt-in only, never default)
    PROVIDER_MODEL_BENCHMARKING = auto()
    LOCAL_MODEL_BENCHMARKING = auto()
    COMMERCIAL_DATASET_LICENSE = auto()
    AGGREGATE_PUBLIC_REPORTING = auto()


TELEMETRY_CONSENT_SCHEMA_VERSION = "rig.relay.telemetry_consent.v1"
TELEMETRY_CONSENT_POLICY_VERSION = "alpha-usage-data-license-v1"


class TelemetryConsentRecord(BaseModel):
    """Consent record for telemetry data sharing.

    Content-light: no raw email, raw tokens, raw prompts, raw code, raw output.
    OAuth tokens remain in the token store — not in consent records.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = TELEMETRY_CONSENT_SCHEMA_VERSION
    consent_id: str = ""
    subject_hash: str = ""
    provider: str = ""
    status: TelemetryConsentStatus = TelemetryConsentStatus.NOT_REQUESTED
    scopes: list[TelemetryConsentScope] = []
    granted_at: str = ""
    revoked_at: str = ""
    expires_at: str = ""
    policy_version: str = TELEMETRY_CONSENT_POLICY_VERSION
    local_only: bool = True
    warnings: list[str] = []

    def model_dump_content_light(self) -> dict:
        """Dump content-light fields safe for audit/UI."""
        return self.model_dump(
            mode="json",
            include={
                "schema_version",
                "consent_id",
                "subject_hash",
                "provider",
                "status",
                "scopes",
                "granted_at",
                "revoked_at",
                "policy_version",
                "local_only",
                "warnings",
            },
        )


def create_consent_id() -> str:
    import uuid

    return f"cons_{uuid.uuid4().hex[:12]}"


def build_initial_consent() -> TelemetryConsentRecord:
    return TelemetryConsentRecord(
        consent_id=create_consent_id(),
        status=TelemetryConsentStatus.NOT_REQUESTED,
        scopes=[],
        granted_at="",
        revoked_at="",
    )


def grant_consent(
    subject_hash: str, provider: str, scopes: list[TelemetryConsentScope] | None = None
) -> TelemetryConsentRecord:
    now = datetime.now(UTC).isoformat()
    if scopes is None:
        scopes = [
            TelemetryConsentScope.USAGE_METRICS,
            TelemetryConsentScope.CONTENT_LIGHT_BUNDLES,
            TelemetryConsentScope.CRASH_REPORTS,
            TelemetryConsentScope.COORDINATION_METRICS,
            TelemetryConsentScope.TOOL_REFINEMENT_METRICS,
        ]
    return TelemetryConsentRecord(
        consent_id=create_consent_id(),
        subject_hash=subject_hash,
        provider=provider,
        status=TelemetryConsentStatus.GRANTED,
        scopes=scopes,
        granted_at=now,
        revoked_at="",
    )


def revoke_consent(existing: TelemetryConsentRecord) -> TelemetryConsentRecord:
    now = datetime.now(UTC).isoformat()
    existing.status = TelemetryConsentStatus.REVOKED
    existing.revoked_at = now
    existing.warnings = existing.warnings or []
    existing.warnings.append("Consent revoked by user")
    return existing


def has_commercial_dataset_license(record: TelemetryConsentRecord) -> bool:
    """Check if the consent record includes commercial dataset license scope.

    Commercial dataset licensing is a separate concept from privacy consent.
    This checks for the COMMERCIAL_DATASET_LICENSE scope specifically.
    The AGGREGATE_PUBLIC_REPORTING scope implies commercial licensing intent
    but is checked independently.
    """
    return TelemetryConsentScope.COMMERCIAL_DATASET_LICENSE in record.scopes


def active_consent_scopes(
    record: TelemetryConsentRecord,
) -> list[TelemetryConsentScope]:
    """Return the list of scopes that are currently active on a record.

    A scope is active only when:
    - The consent status is GRANTED (not REVOKED, DENIED, or NOT_REQUESTED)
    - The scope is present in the record's scopes list

    Revoked or denied records return an empty list even if scopes remain
    in the record's scopes field. The data is preserved for audit but
    no longer considered active.
    """
    if record.status != TelemetryConsentStatus.GRANTED:
        return []
    return list(record.scopes)


def has_active_commercial_dataset_license(record: TelemetryConsentRecord) -> bool:
    """Check if the commercial dataset license scope is currently active.

    Unlike has_commercial_dataset_license(), this checks both scope presence
    AND consent status. A revoked record with commercial_dataset_license in
    its scopes list returns False.
    """
    return TelemetryConsentScope.COMMERCIAL_DATASET_LICENSE in active_consent_scopes(
        record
    )


def observation_allowed_by_consent(
    record: TelemetryConsentRecord, observation_kind: str
) -> bool:
    """Check if a model observation is allowed by the current active consent.

    observation_kind must be one of:
    - 'provider'          — cloud provider model observations
    - 'local_model'       — local model observations
    - 'commercial_export' — export to commercial/aggregated datasets
    - 'public_aggregate'  — inclusion in public aggregate reports

    Returns True only if the consent status is GRANTED AND the required
    scopes are present and active.
    """
    active = active_consent_scopes(record)

    if observation_kind == "provider":
        return TelemetryConsentScope.PROVIDER_MODEL_BENCHMARKING in active
    elif observation_kind == "local_model":
        return TelemetryConsentScope.LOCAL_MODEL_BENCHMARKING in active
    elif observation_kind == "commercial_export":
        return TelemetryConsentScope.COMMERCIAL_DATASET_LICENSE in active
    elif observation_kind == "public_aggregate":
        return TelemetryConsentScope.AGGREGATE_PUBLIC_REPORTING in active
    else:
        msg = f"Unknown observation_kind: {observation_kind}"
        raise ValueError(msg)
