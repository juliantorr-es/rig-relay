"""Models for native macOS release-operations application services (X4)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NativeReleaseOperation(StrEnum):
    BUILD_APP = "build_app"
    SIGN_APP = "sign_app"
    NOTARIZE_APP = "notarize_app"
    STAPLE_TICKET = "staple_ticket"
    VERIFY_SIGNATURE = "verify_signature"
    CHECK_UPDATE = "check_update"
    DOWNLOAD_UPDATE = "download_update"
    INSTALL_UPDATE = "install_update"
    ROLLBACK_UPDATE = "rollback_update"
    EXPORT_DIAGNOSTICS = "export_diagnostics"
    REGISTER_EXTENSION = "register_extension"
    RECOVERY_REPAIR = "recovery_repair"


class AppPackageIdentity(BaseModel):
    """Identity metadata for a built .app bundle."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="rig.relay.native.package_identity.v1")
    bundle_identifier: str
    bundle_name: str
    short_version: str
    build_version: str
    minimum_system_version: str
    executable_path: str
    bundle_path: str


class AppPackageEvidence(BaseModel):
    """Evidence artifact for an app package build."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="rig.relay.native.package_evidence.v1")
    identity: AppPackageIdentity
    build_config: str
    build_sha256: str
    timestamp: str
    entitlements_path: str | None = None
    entitlements_sha256: str | None = None
    resources_count: int = 0
    extension_embedded: bool = False
    extension_bundle_id: str | None = None
    signed: bool = False
    signing_identity: str | None = None
    notarized: bool = False
    notarization_ticket_stapled: bool = False
    warnings: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)


class SigningIdentityStatus(BaseModel):
    """Content-light signing identity discovery result."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="rig.relay.native.signing_status.v1")
    developer_id_available: bool = False
    developer_id_count: int = 0
    apple_development_available: bool = False
    mac_distribution_available: bool = False
    identities: list[str] = Field(default_factory=list)
    has_notary_profile: bool = False
    has_keychain_access: bool = True
    warnings: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)


class SigningEvidence(BaseModel):
    """Evidence of a code-signing operation (hash-only, content-light)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="rig.relay.native.signing_evidence.v1")
    identity_used: str
    identity_type: str
    hardened_runtime: bool = True
    timestamp_included: bool = True
    entitlements_sha256: str
    bundle_sha256_after: str
    signed_at: str
    status: str = "signed"
    warnings: list[str] = Field(default_factory=list)


class NotarizationStatus(StrEnum):
    NOT_SUBMITTED = "not_submitted"
    IN_PROGRESS = "in_progress"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    STAPLED = "stapled"
    FAILED = "failed"


class NotarizationEvidence(BaseModel):
    """Content-light notarization submission evidence."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="rig.relay.native.notarization_evidence.v1")
    submission_id: str | None = None
    status: NotarizationStatus = NotarizationStatus.NOT_SUBMITTED
    bundle_sha256: str
    submitted_at: str | None = None
    completed_at: str | None = None
    ticket_stapled: bool = False
    log_url: str | None = None
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class UpdateStatus(StrEnum):
    UP_TO_DATE = "up_to_date"
    UPDATE_AVAILABLE = "update_available"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    READY_TO_INSTALL = "ready_to_install"
    INSTALLING = "installing"
    INSTALLED = "installed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class UpdateEvidenceStatus(BaseModel):
    """Content-light update evidence (no raw binaries)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="rig.relay.native.update_evidence.v1")
    current_version: str
    latest_version: str | None = None
    update_available: bool = False
    status: UpdateStatus = UpdateStatus.UP_TO_DATE
    feed_url: str | None = None
    download_sha256: str | None = None
    ed_signature_verified: bool = False
    last_check_at: str | None = None
    installed_at: str | None = None
    rolled_back_at: str | None = None
    rollback_version: str | None = None
    warnings: list[str] = Field(default_factory=list)


class RecoveryState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    NEEDS_REPAIR = "needs_repair"
    REPAIRING = "repairing"
    REPAIRED = "repaired"
    UNRECOVERABLE = "unrecoverable"


class RecoveryEvidence(BaseModel):
    """Content-light recovery state evidence."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="rig.relay.native.recovery_evidence.v1")
    state: RecoveryState = RecoveryState.HEALTHY
    affected_components: list[str] = Field(default_factory=list)
    recovery_actions_taken: list[str] = Field(default_factory=list)
    recovery_successful: bool = False
    requires_manual_intervention: bool = False
    db_migration_status: str | None = None
    frontend_bundle_status: str | None = None
    extension_binding_status: str | None = None
    bridge_connection_status: str | None = None
    warnings: list[str] = Field(default_factory=list)


class DiagnosticContentLightViolation(BaseModel):
    """A content-light violation found in diagnostic data."""

    model_config = ConfigDict(extra="forbid")

    field_name: str
    reason: str
    redacted_value: str = "[REDACTED]"


class DiagnosticBundle(BaseModel):
    """Content-light diagnostic export for support and user review."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="rig.relay.native.diagnostic_export.v1")
    export_id: str
    exported_at: str
    app_identity: AppPackageIdentity
    signing_status: SigningIdentityStatus | None = None
    notarization_status: NotarizationEvidence | None = None
    update_status: UpdateEvidenceStatus | None = None
    recovery_state: RecoveryEvidence | None = None
    extension_available: bool = False
    extension_connection_state: str = "unknown"
    native_bridge_healthy: bool = True
    frontend_resources_present: bool = True
    health_checks: list[dict[str, Any]] = Field(default_factory=list)
    content_light_violations: list[DiagnosticContentLightViolation] = Field(
        default_factory=list
    )
    content_policy: str = "content_light"
    redacted: bool = False
    warnings: list[str] = Field(default_factory=list)
    blocking: list[str] = Field(default_factory=list)
