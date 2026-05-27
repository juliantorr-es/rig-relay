"""macOS release-operations application service (X4).

Governed entry point for packaging, signing, notarization, update,
recovery, and diagnostic operations at the native macOS boundary.
"""

from __future__ import annotations

from rig_relay.native._artifact_manifest import ArtifactManifestService
from rig_relay.native._diagnostics import DiagnosticExportService
from rig_relay.native._packaging import PackagingService
from rig_relay.native._recovery import RecoveryService
from rig_relay.native._release_operations import ReleaseOperationsService
from rig_relay.native._update import UpdateDeliveryService
from rig_relay.native.models import (
    AppPackageEvidence,
    AppPackageIdentity,
    ArtifactItem,
    ArtifactItemKind,
    ArtifactItemSignificance,
    CanonicalDistributionArtifactManifest,
    DiagnosticBundle,
    DiagnosticContentLightViolation,
    DiagnosticExportBlocked,
    NativeReleaseOperation,
    NotarizationEvidence,
    NotarizationStatus,
    RecoveryState,
    SigningEvidence,
    SigningIdentityStatus,
    UpdateEvidenceStatus,
    UpdateStatus,
)

__all__ = [
    "AppPackageEvidence",
    "AppPackageIdentity",
    "ArtifactItem",
    "ArtifactItemKind",
    "ArtifactItemSignificance",
    "ArtifactManifestService",
    "CanonicalDistributionArtifactManifest",
    "DiagnosticBundle",
    "DiagnosticContentLightViolation",
    "DiagnosticExportBlocked",
    "DiagnosticExportService",
    "NativeReleaseOperation",
    "NotarizationEvidence",
    "NotarizationStatus",
    "PackagingService",
    "RecoveryService",
    "RecoveryState",
    "ReleaseOperationsService",
    "SigningEvidence",
    "SigningIdentityStatus",
    "UpdateDeliveryService",
    "UpdateEvidenceStatus",
    "UpdateStatus",
]
